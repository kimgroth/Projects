"""
Worker client that communicates with the master and executes FFmpeg jobs.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from zeroconf import ServiceInfo, Zeroconf

from ..config import SERVICE_TYPE, WORKER_POLL_INTERVAL
from ..models import CompletionReport, LeaseResponse, WorkerStatus
from ..profiles import build_profile_command

log = logging.getLogger(__name__)


PROGRESS_PATTERN = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
FFPROBE_ARGS = [
    "-v",
    "error",
    "-show_entries",
    "format=duration",
    "-of",
    "default=noprint_wrappers=1:nokey=1",
]


def _seconds_from_match(match: re.Match[str]) -> float:
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _get_default_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


@dataclass
class ActiveJob:
    job_id: int
    input_path: str
    output_path: str
    profile: str
    ffmpeg_args: list[str]


class WorkerClient:
    def __init__(
        self,
        master_url: str,
        *,
        worker_id: Optional[str] = None,
        name: Optional[str] = None,
        advertise: bool = True,
    ):
        self.master_url = master_url.rstrip("/")
        self.worker_id = worker_id or str(uuid.uuid4())
        self.name = name or f"Worker-{socket.gethostname()}"
        self.advertise = advertise
        self.client = httpx.Client(base_url=self.master_url, timeout=15.0)
        self._stop_event = threading.Event()
        self._force_stop_event = threading.Event()
        self._current_job: Optional[ActiveJob] = None
        self._last_lease_response: Optional[LeaseResponse] = None
        self._zeroconf: Optional[Zeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._lock = threading.Lock()
        self._last_stdout: deque[str] = deque(maxlen=50)
        self._last_stderr: deque[str] = deque(maxlen=50)
        self._status = WorkerStatus.ONLINE
        self._accept_leases = True
        self._heartbeat_interval = 10.0
        self._ffmpeg_bin = self._resolve_tool("FFARM_FFMPEG", "ffmpeg")
        self._ffprobe_bin = self._resolve_tool("FFARM_FFPROBE", "ffprobe")

    def run(self):
        try:
            if self.advertise:
                self._start_advertising()
            self._loop()
        finally:
            self._cleanup()

    def stop(self):
        self._stop_event.set()
        self._force_stop_event.set()

    def _loop(self):
        next_heartbeat = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            if now >= next_heartbeat:
                self._send_heartbeat()
                next_heartbeat = now + self._heartbeat_interval
            if self._current_job is None and self._accept_leases and not self._force_stop_event.is_set():
                lease = self._request_job()
                if lease:
                    self._execute_job(lease)
                    next_heartbeat = 0.0  # trigger immediate heartbeat
                    continue
            time.sleep(WORKER_POLL_INTERVAL)

    def _request_job(self) -> Optional[ActiveJob]:
        try:
            response = self.client.post(
                "/api/v1/jobs/lease",
                json={
                    "worker_id": self.worker_id,
                    "name": self.name,
                    "base_url": "",  # reserved for future use
                },
            )
        except httpx.RequestError as exc:
            log.error("Lease request failed: %s", exc)
            return None

        if response.status_code != 200:
            log.error("Lease request returned %s", response.status_code)
            return None

        payload = LeaseResponse.parse_obj(response.json())
        self._last_lease_response = payload
        if payload.action == "force_stop":
            self._status = WorkerStatus.FORCE_STOPPING
            self._force_stop_event.set()
            return None
        if payload.action == "stop":
            self._status = WorkerStatus.STOPPING
            self._accept_leases = False
            return None
        if not payload.job_id:
            self._accept_leases = payload.accept_leases
            return None
        self._accept_leases = payload.accept_leases
        return ActiveJob(
            job_id=payload.job_id,
            input_path=payload.input_path,
            output_path=payload.output_path,
            profile=payload.profile,
            ffmpeg_args=payload.ffmpeg_args,
        )

    def _send_heartbeat(self):
        payload = {
            "worker_id": self.worker_id,
            "name": self.name,
            "base_url": "",
            "running_job_id": self._current_job.job_id if self._current_job else None,
            "status": self._status,
        }
        try:
            response = self.client.post("/api/v1/workers/heartbeat", json=payload)
            response.raise_for_status()
            data = response.json()
            self._accept_leases = data.get("accept_leases", True)
            status = data.get("status", WorkerStatus.ONLINE)
            if status == WorkerStatus.FORCE_STOPPING:
                self._status = WorkerStatus.FORCE_STOPPING
                self._force_stop_event.set()
            elif status == WorkerStatus.STOPPING:
                self._status = WorkerStatus.STOPPING
                self._accept_leases = False
            else:
                if self._current_job is None:
                    self._status = WorkerStatus.ONLINE
        except httpx.RequestError as exc:
            log.error("Heartbeat failed: %s", exc)

    def _execute_job(self, job: ActiveJob):
        self._current_job = job
        self._status = WorkerStatus.ONLINE
        self._last_stdout.clear()
        self._last_stderr.clear()
        duration = self._probe_duration(job.input_path)
        progress = 0.0

        ffmpeg_bin = self._ffmpeg_bin or self._resolve_tool("FFARM_FFMPEG", "ffmpeg")
        if not ffmpeg_bin:
            log.error("FFmpeg executable not found; set FFARM_FFMPEG or add ffmpeg to PATH")
            self._send_completion(job.job_id, False, return_code=-1)
            self._current_job = None
            return

        ffmpeg_args = [ffmpeg_bin] + list(job.ffmpeg_args)
        Path(job.output_path).parent.mkdir(parents=True, exist_ok=True)
        log.info("Starting job %s", job.job_id)

        try:
            process = subprocess.Popen(
                ffmpeg_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            log.exception("FFmpeg executable not found")
            self._send_completion(job.job_id, False, return_code=-1)
            self._current_job = None
            return
        except OSError:
            log.exception("Failed to start FFmpeg")
            self._send_completion(job.job_id, False, return_code=-1)
            self._current_job = None
            return

        stdout_thread = threading.Thread(
            target=self._stream_reader,
            args=(process.stdout, self._last_stdout, True),
            daemon=True,
        )
        stdout_thread.start()
        self._send_progress(job.job_id, progress)

        try:
            if process.stderr:
                for line in iter(process.stderr.readline, ""):
                    if self._force_stop_event.is_set():
                        process.terminate()
                        break
                    line = line.rstrip()
                    if not line:
                        continue
                    self._last_stderr.append(line)
                    match = PROGRESS_PATTERN.search(line)
                    if match and duration:
                        seconds = _seconds_from_match(match)
                        progress = min(0.99, seconds / duration)
                    self._send_progress(job.job_id, progress)
        finally:
            if process.stderr:
                process.stderr.close()

        return_code = process.wait()
        success = return_code == 0 and not self._force_stop_event.is_set()
        if self._force_stop_event.is_set() and return_code != 0:
            success = False
            self._status = WorkerStatus.FORCE_STOPPING
        self._send_completion(job.job_id, success, return_code)
        self._current_job = None
        self._force_stop_event.clear()
        self._status = WorkerStatus.STOPPED if not self._accept_leases else WorkerStatus.ONLINE
        log.info("Job %s finished with code %s", job.job_id, return_code)

    def _send_progress(self, job_id: int, progress: float):
        payload = {
            "worker_id": self.worker_id,
            "progress": progress,
            "stderr_tail": "\n".join(list(self._last_stderr)[-10:]) if self._last_stderr else None,
            "stdout_tail": "\n".join(list(self._last_stdout)[-10:]) if self._last_stdout else None,
        }
        try:
            self.client.post(f"/api/v1/jobs/{job_id}/progress", json=payload)
        except httpx.RequestError:
            log.exception("Failed to send progress update")

    def _send_completion(self, job_id: int, success: bool, return_code: int):
        payload = {
            "worker_id": self.worker_id,
            "success": success,
            "return_code": return_code,
            "stderr_tail": "\n".join(self._last_stderr),
            "stdout_tail": "\n".join(self._last_stdout),
            "error_message": None if success else "FFmpeg failed",
        }
        try:
            self.client.post(f"/api/v1/jobs/{job_id}/complete", json=payload)
        except httpx.RequestError:
            log.exception("Failed to send completion report")

    def _stream_reader(self, stream, target: deque[str], close: bool):
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                line = line.rstrip()
                if not line:
                    continue
                target.append(line)
        finally:
            if close:
                stream.close()

    def _probe_duration(self, input_path: str) -> Optional[float]:
        ffprobe_bin = self._ffprobe_bin or self._resolve_tool("FFARM_FFPROBE", "ffprobe")
        if not ffprobe_bin:
            log.warning("FFprobe executable not found; duration tracking disabled")
            return None
        cmd = [ffprobe_bin] + FFPROBE_ARGS + [input_path]
        try:
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            duration_str = result.stdout.strip()
            if duration_str:
                return float(duration_str)
        except (subprocess.CalledProcessError, ValueError):
            log.warning("Failed to determine duration for %s", input_path)
        return None

    def _start_advertising(self):
        self._zeroconf = Zeroconf()
        ip = _get_default_ip()
        info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=f"{self.worker_id}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=0,
            properties={
                b"id": self.worker_id.encode(),
                b"name": self.name.encode(),
                b"base_url": b"",
            },
        )
        self._service_info = info
        self._zeroconf.register_service(info)

    def _cleanup(self):
        if self.client:
            self.client.close()
        if self._zeroconf and self._service_info:
            try:
                self._zeroconf.unregister_service(self._service_info)
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._zeroconf.close()

    @staticmethod
    def _resolve_tool(env_var: str, executable: str) -> Optional[str]:
        override = os.environ.get(env_var)
        if override:
            if os.path.isabs(override) and os.access(override, os.X_OK):
                return override
            resolved = shutil.which(override)
            if resolved:
                return resolved
            log.warning("%s=%s is not executable", env_var, override)
        resolved = shutil.which(executable)
        if not resolved:
            log.warning("Executable '%s' not found on PATH", executable)
        return resolved
