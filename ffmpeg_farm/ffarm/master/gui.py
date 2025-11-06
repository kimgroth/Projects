"""
Tkinter GUI for the master node.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from sqlmodel import select

from ..config import APP_NAME, GUI_REFRESH_INTERVAL_MS
from ..db import session_scope
from ..discovery import WorkerDiscovery
from ..jobs import delete_succeeded_jobs, enqueue_folder, reset_failed_jobs
from ..models import Job, Worker, WorkerStatus
from ..state import state as master_state
from ..workers import list_workers, resume_worker, stop_worker
from ..worker import WorkerClient
from .server import MasterServer

log = logging.getLogger(__name__)


class MasterGUI:
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port
        self.server = MasterServer(host=self.host, port=self.port)
        self.discovery = WorkerDiscovery()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.run_local_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")

        self.jobs_tree = None
        self.workers_tree = None
        self.local_worker: WorkerClient | None = None
        self.local_worker_thread: threading.Thread | None = None

        self._build_layout()

    def _build_layout(self):
        control_frame = ttk.Frame(self.root, padding=10)
        control_frame.pack(fill=tk.X)

        choose_button = ttk.Button(control_frame, text="Choose Folder & Enqueue", command=self.choose_folder)
        choose_button.pack(side=tk.LEFT)

        local_check = ttk.Checkbutton(
            control_frame,
            text="Run locally",
            variable=self.run_local_var,
            command=self.toggle_local_worker,
        )
        local_check.pack(side=tk.LEFT, padx=10)

        pause_button = ttk.Button(control_frame, text="Pause", command=self.pause_queue)
        pause_button.pack(side=tk.LEFT, padx=5)

        resume_button = ttk.Button(control_frame, text="Resume", command=self.resume_queue)
        resume_button.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(control_frame, textvariable=self.status_var)
        self.status_label.pack(side=tk.LEFT, padx=10)

        workers_frame = ttk.Labelframe(self.root, text="Workers", padding=10)
        workers_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.workers_tree = ttk.Treeview(
            workers_frame,
            columns=("name", "status", "job", "accept_leases", "last_seen"),
            show="headings",
            height=6,
        )
        for col, heading in [
            ("name", "Name"),
            ("status", "Status"),
            ("job", "Job"),
            ("accept_leases", "Leasing"),
            ("last_seen", "Last Seen"),
        ]:
            self.workers_tree.heading(col, text=heading)
            self.workers_tree.column(col, stretch=True, width=100)
        self.workers_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        worker_button_frame = ttk.Frame(workers_frame)
        worker_button_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)

        soft_button = ttk.Button(worker_button_frame, text="Soft Stop", command=self.soft_stop_worker)
        soft_button.pack(fill=tk.X, pady=2)
        hard_button = ttk.Button(worker_button_frame, text="Hard Stop", command=self.hard_stop_worker)
        hard_button.pack(fill=tk.X, pady=2)
        resume_button = ttk.Button(worker_button_frame, text="Resume", command=self.resume_worker)
        resume_button.pack(fill=tk.X, pady=2)

        jobs_frame = ttk.Labelframe(self.root, text="Jobs", padding=10)
        jobs_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.jobs_tree = ttk.Treeview(
            jobs_frame,
            columns=("input", "state", "progress", "worker", "attempts"),
            show="headings",
            height=10,
        )
        for col, heading, width in [
            ("input", "Input", 280),
            ("state", "State", 80),
            ("progress", "Progress", 80),
            ("worker", "Worker", 120),
            ("attempts", "Attempts", 70),
        ]:
            self.jobs_tree.heading(col, text=heading)
            self.jobs_tree.column(col, stretch=True, width=width)
        self.jobs_tree.pack(fill=tk.BOTH, expand=True)

        jobs_button_frame = ttk.Frame(jobs_frame)
        jobs_button_frame.pack(fill=tk.X, pady=(10, 0))

        retry_button = ttk.Button(jobs_button_frame, text="Retry Failed", command=self.retry_failed)
        retry_button.pack(side=tk.LEFT)

        clear_button = ttk.Button(jobs_button_frame, text="Clear Succeeded", command=self.clear_succeeded)
        clear_button.pack(side=tk.LEFT, padx=5)

    def start(self):
        self.server.start()
        self.discovery.start()
        self.refresh()
        self.root.mainloop()

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        try:
            added, skipped = enqueue_folder(Path(folder))
            self.status_var.set(f"Enqueued {added} jobs (skipped {skipped})")
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to enqueue jobs")
            messagebox.showerror("Error", f"Unable to enqueue jobs:\n{exc}")

    def refresh(self):
        self._refresh_workers()
        self._refresh_jobs()
        self.root.after(GUI_REFRESH_INTERVAL_MS, self.refresh)

    def pause_queue(self):
        master_state.set_paused(True)
        self.status_var.set("Queue paused")

    def resume_queue(self):
        master_state.set_paused(False)
        self.status_var.set("Queue resumed")

    def _refresh_workers(self):
        for item in self.workers_tree.get_children():
            self.workers_tree.delete(item)
        for worker in list_workers():
            job_display = worker.running_job_id or "-"
            self.workers_tree.insert(
                "",
                tk.END,
                iid=worker.id,
                values=(
                    worker.name,
                    worker.status,
                    job_display,
                    "Yes" if worker.accept_leases else "No",
                    worker.last_seen.isoformat() if worker.last_seen else "-",
                ),
            )

    def _refresh_jobs(self):
        for item in self.jobs_tree.get_children():
            self.jobs_tree.delete(item)
        with session_scope() as session:
            jobs = session.exec(select(Job).order_by(Job.created_at)).all()
        for job in jobs:
            self.jobs_tree.insert(
                "",
                tk.END,
                iid=str(job.id),
                values=(
                    Path(job.input_path).name,
                    job.state,
                    f"{job.progress * 100:.1f}%",
                    job.worker_id or "-",
                    job.attempts,
                ),
            )

    def soft_stop_worker(self):
        worker_id = self._selected_worker_id()
        if not worker_id:
            messagebox.showinfo("Workers", "Select a worker first.")
            return
        stop_worker(worker_id, force=False)

    def hard_stop_worker(self):
        worker_id = self._selected_worker_id()
        if not worker_id:
            messagebox.showinfo("Workers", "Select a worker first.")
            return
        stop_worker(worker_id, force=True)

    def resume_worker(self):
        worker_id = self._selected_worker_id()
        if not worker_id:
            messagebox.showinfo("Workers", "Select a worker first.")
            return
        resume_worker(worker_id)

    def retry_failed(self):
        count = reset_failed_jobs()
        self.status_var.set(f"Queued {count} failed jobs for retry")

    def clear_succeeded(self):
        count = delete_succeeded_jobs()
        self.status_var.set(f"Cleared {count} succeeded jobs")

    def _selected_worker_id(self) -> str | None:
        selection = self.workers_tree.selection()
        if not selection:
            return None
        return selection[0]

    def toggle_local_worker(self):
        if self.run_local_var.get():
            if self.local_worker_thread and self.local_worker_thread.is_alive():
                return
            self.local_worker = WorkerClient(
                f"http://127.0.0.1:{self.port}",
                name="Master Local Worker",
                advertise=False,
            )
            self.local_worker_thread = threading.Thread(target=self.local_worker.run, daemon=True)
            self.local_worker_thread.start()
            self.status_var.set("Local worker running")
        else:
            if self.local_worker:
                self.local_worker.stop()
            if self.local_worker_thread:
                self.local_worker_thread.join(timeout=1.0)
            self.status_var.set("Local worker stopped")

    def on_close(self):
        if self.local_worker:
            self.local_worker.stop()
        if self.local_worker_thread:
            self.local_worker_thread.join(timeout=1.0)
        self.discovery.stop()
        self.server.stop()
        self.root.destroy()
