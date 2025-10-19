#!/usr/bin/env python3

from __future__ import annotations

import argparse
import selectors
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable, List

VIDEO_EXTENSIONS = {
    ".3g2",
    ".3gp",
    ".amv",
    ".asf",
    ".avi",
    ".drc",
    ".flv",
    ".m2v",
    ".m4v",
    ".mkv",
    ".mod",
    ".mov",
    ".mp4",
    ".mpe",
    ".mpeg",
    ".mpg",
    ".mpv",
    ".mxf",
    ".ogm",
    ".ogv",
    ".qt",
    ".rm",
    ".rmvb",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create ProRes proxy encodes of every video in SOURCE and place them in DEST."
        )
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Directory to search for source videos (recursively).",
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="Directory that will receive the proxy conversions.",
    )
    parser.add_argument(
        "--font-file",
        type=Path,
        default=None,
        help=(
            "Optional path to a font file for drawtext. "
            "If not supplied, ffmpeg will use its default font configuration."
        ),
    )
    return parser.parse_args()


def validate_paths(source: Path, destination: Path) -> None:
    if not source.exists():
        sys.exit(f"Source path does not exist: {source}")
    if not source.is_dir():
        sys.exit(f"Source path must be a directory: {source}")
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.exit(f"Could not create destination directory {destination}: {exc}")

    source_resolved = source.resolve()
    destination_resolved = destination.resolve()
    if source_resolved == destination_resolved:
        sys.exit("Destination directory must be different from the source directory.")
    try:
        is_dest_inside_source = destination_resolved.is_relative_to(source_resolved)
    except AttributeError:
        # Fall back for Python < 3.9
        try:
            destination_resolved.relative_to(source_resolved)
            is_dest_inside_source = True
        except ValueError:
            is_dest_inside_source = False
    if is_dest_inside_source:
        sys.exit("Destination directory must not be nested inside the source directory.")


def discover_videos(source: Path) -> List[Path]:
    files: List[Path] = []
    for candidate in source.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in VIDEO_EXTENSIONS:
            files.append(candidate)
    files.sort()
    return files


def describe_files(files: Iterable[Path], source: Path) -> None:
    counts = Counter(p.suffix.lower() for p in files)
    if not counts:
        print("No video files found.")
        return

    print("Video files discovered by extension:")
    for extension, count in sorted(counts.items()):
        label = extension if extension else "[no extension]"
        print(f"  {label}: {count}")
    print(f"Total files: {sum(counts.values())}")

    warn_name_conflicts(files)

    actions = {
        "s": "start conversion",
        "l": "list files",
        "q": "quit",
    }
    files_listed = False
    while True:
        print("Choose an action:")
        for key, desc in actions.items():
            print(f"  [{key}] {desc}")
        choice = input("> ").strip().lower()
        if choice == "s":
            return
        if choice == "l":
            list_files(files, source)
            files_listed = True
            continue
        if choice == "q":
            sys.exit(0)
        print("Unrecognized option, please choose again.")
        if not files_listed:
            print("Hint: type 'l' to list every file that will be processed.")


def list_files(files: Iterable[Path], source: Path) -> None:
    print("Files queued for conversion:")
    for path in files:
        try:
            rel_path = path.relative_to(source)
        except ValueError:
            rel_path = path
        print(f"  {rel_path}")


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        return
    sys.exit(
        "ffmpeg is required but was not found in PATH. "
        "Install ffmpeg and rerun the script."
    )


def probe_duration(path: Path) -> float | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    output = result.stdout.strip()
    if not output:
        return None
    try:
        return float(output)
    except ValueError:
        return None


def parse_timecode(value: str) -> float | None:
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def build_video_filter(font_file: Path | None) -> str:
    drawtext = [
        "drawtext=text='proxy'",
        "fontcolor=white@0.5",
        "fontsize=36",
        "x=16",
        "y=h-th-16",
    ]
    if font_file is not None:
        drawtext.append(f"fontfile='{font_file}'")

    filters = [
        "scale=1024:1024:force_original_aspect_ratio=decrease:force_divisible_by=2",
        ":".join(drawtext),
    ]
    return ",".join(filters)


def warn_name_conflicts(files: Iterable[Path]) -> None:
    proxy_names = Counter(f"{path.stem}_Proxy.mov" for path in files)
    conflicts = {name: count for name, count in proxy_names.items() if count > 1}
    if not conflicts:
        print("All proxy filenames will be unique.")
        return

    total_conflicts = sum(conflicts.values())
    print(
        f"Warning: {total_conflicts} source files map to "
        f"{len(conflicts)} proxy filename(s)."
    )
    for name, count in sorted(conflicts.items()):
        print(f"  {name}: {count} source files")


def convert_file(
    source_file: Path,
    source_root: Path,
    destination_root: Path,
    filter_chain: str,
    index: int,
    total: int,
    progress: ProgressDisplay,
) -> tuple[str, str]:
    relative = source_file.relative_to(source_root)
    proxy_name = f"{relative.stem}_Proxy.mov"
    output_path = destination_root / proxy_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    display_label = f"[{index}/{total}] {relative} -> {output_path.name}"

    if output_path.exists():
        skip_message = f"{display_label} | already exists, skipping"
        progress.log(skip_message)
        progress.finish_file(source_file, skip_message)
        return "skipped", f"Skipped existing proxy for {relative}"

    progress.log(display_label)
    progress.start_file(source_file, display_label)

    duration = progress.duration_for(source_file)

    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
        "-i",
        str(source_file),
        "-vf",
        filter_chain,
        "-c:v",
        "prores_ks",
        "-profile:v",
        "proxy",
        "-pix_fmt",
        "yuv422p10le",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )

    progress_block: dict[str, str] = {}
    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "progress")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "log")

    def handle_progress(block: dict[str, str]) -> None:
        progress_flag = block.get("progress")
        speed = block.get("speed")
        fraction: float | None = None
        if duration:
            if "out_time_ms" in block:
                try:
                    processed_seconds = float(block["out_time_ms"]) / 1_000_000.0
                except ValueError:
                    processed_seconds = None
                else:
                    fraction = processed_seconds / duration
            elif "out_time_us" in block:
                try:
                    processed_seconds = float(block["out_time_us"]) / 1_000_000.0
                except ValueError:
                    processed_seconds = None
                else:
                    fraction = processed_seconds / duration
            elif "out_time" in block:
                parsed = parse_timecode(block["out_time"])
                if parsed is not None and duration:
                    fraction = parsed / duration
        if fraction is not None:
            progress.update_partial(source_file, fraction, speed)
        elif progress_flag == "continue":
            # Ensure the display still updates for very small files.
            progress.render()

    while selector.get_map() or process.poll() is None:
        events = selector.select(timeout=0.1)
        if not events:
            if process.poll() is not None and not selector.get_map():
                break
            continue
        for key, _ in events:
            stream = key.fileobj
            if stream is None:
                continue
            line = stream.readline()
            if not line:
                selector.unregister(stream)
                continue
            text_line = line.rstrip("\r\n")
            if key.data == "progress":
                if "=" not in text_line:
                    continue
                key_name, _, value = text_line.partition("=")
                progress_block[key_name] = value
                if key_name == "progress":
                    handle_progress(progress_block)
                    progress_block = {}
            else:
                if text_line:
                    progress.log(text_line)

    selector.close()
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()

    return_code = process.wait()
    if return_code == 0:
        success_message = f"{display_label} | done"
        progress.finish_file(source_file, success_message)
        return "success", f"Converted {relative} -> {output_path.name}"

    error_message = f"{display_label} | failed (exit code {return_code})"
    progress.log(error_message)
    progress.finish_file(source_file, error_message, failed=True)
    return "failed", f"Failed to convert {relative}"


class ProgressDisplay:
    def __init__(self, files: Iterable[Path]) -> None:
        file_list = list(files)
        self.total_files = len(file_list)
        self.file_sizes = {path: self._file_size(path) for path in file_list}
        self.total_bytes = sum(self.file_sizes.values())
        self.file_durations: dict[Path, float | None] = {}
        self.completed_files = 0
        self.completed_bytes = 0.0
        self.partial_bytes = 0.0
        self.failed_files: list[Path] = []
        self.start_time = time.monotonic()
        self.bar_width = 70
        self.stream = sys.stdout
        self.active_file: Path | None = None
        self.active_label = ""
        self.latest_speed: str | None = None
        self.last_render_lines = 0
        self.last_status_message = ""

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def duration_for(self, path: Path) -> float | None:
        if path not in self.file_durations:
            self.file_durations[path] = probe_duration(path)
        return self.file_durations[path]

    def _move_cursor_to_progress(self) -> None:
        if self.last_render_lines:
            self.stream.write(f"\x1b[{self.last_render_lines}F")

    def _clear_from_cursor(self) -> None:
        self.stream.write("\x1b[J")

    def log(self, message: str) -> None:
        self._move_cursor_to_progress()
        self._clear_from_cursor()
        self.stream.write(f"{message}\n")
        self.stream.flush()
        self.last_render_lines = 0
        self.render(self.last_status_message)

    def start_file(self, path: Path, label: str) -> None:
        self.active_file = path
        self.active_label = label
        self.partial_bytes = 0.0
        self.latest_speed = None
        self.render(f"{label} | starting")

    def update_partial(
        self,
        path: Path,
        fraction: float,
        speed: str | None = None,
    ) -> None:
        if path != self.active_file:
            return
        fraction = max(0.0, min(fraction, 1.0))
        self.partial_bytes = fraction * self.file_sizes.get(path, 0)
        self.latest_speed = speed or None
        status = self.active_label
        percent_text = f"{fraction * 100:5.1f}%"
        if speed:
            status = f"{status} | {percent_text} | {speed}"
        else:
            status = f"{status} | {percent_text}"
        self.render(status)

    def finish_file(self, path: Path, message: str, failed: bool = False) -> None:
        if failed:
            self.failed_files.append(path)
        self.completed_files += 1
        self.completed_bytes += self.file_sizes.get(path, 0)
        self.partial_bytes = 0.0
        self.active_file = None
        self.active_label = ""
        self.latest_speed = None
        self.render(message)

    def _eta_seconds(self) -> float:
        total_processed = self.completed_bytes + self.partial_bytes
        if self.total_bytes == 0 or total_processed <= 0:
            return float("inf")
        elapsed = time.monotonic() - self.start_time
        if elapsed <= 0:
            return float("inf")
        remaining_bytes = max(self.total_bytes - total_processed, 0.0)
        if remaining_bytes == 0:
            return 0.0
        bytes_per_second = total_processed / elapsed
        if bytes_per_second <= 0:
            return float("inf")
        return remaining_bytes / bytes_per_second

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds == float("inf"):
            return "Estimating..."
        if seconds <= 0:
            return "0s"
        total_seconds = int(round(seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}h")
        if minutes or hours:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
        return " ".join(parts)

    def render(self, status_message: str | None = None) -> None:
        if status_message is not None:
            self.last_status_message = status_message
        self._move_cursor_to_progress()
        self._clear_from_cursor()

        total_processed = self.completed_bytes + self.partial_bytes
        percent = total_processed / self.total_bytes if self.total_bytes else 0.0
        percent = max(0.0, min(percent, 1.0))
        filled = int(round(percent * self.bar_width))
        filled = min(max(filled, 0), self.bar_width)
        bar = "#" * filled + "-" * (self.bar_width - filled)
        files_remaining = max(self.total_files - self.completed_files, 0)
        eta_display = self._format_duration(self._eta_seconds())

        lines = [
            f"Files Done: {self.completed_files}/{self.total_files}  Remaining: {files_remaining}",
        ]
        if self.last_status_message:
            lines.append(f"Current: {self.last_status_message}")
        if self.latest_speed:
            lines.append(f"Speed: {self.latest_speed}")
        lines.append(f"[{bar}] {percent * 100:6.2f}%")
        lines.append(f"Est. Time Remaining: {eta_display}")
        if self.failed_files:
            lines.append(f"Failures: {len(self.failed_files)}")

        inner_width = max(len(line) for line in lines) if lines else self.bar_width
        inner_width = max(inner_width, self.bar_width + 12)
        border = "=" * (inner_width + 4)
        block_lines = [border] + [f"|| {line.ljust(inner_width)} ||" for line in lines] + [
            border
        ]
        block = "\n".join(block_lines)
        self.stream.write(f"{block}\n")
        self.stream.flush()
        self.last_render_lines = len(block_lines) + 1

    def finalize(self) -> None:
        message = "Conversion run complete."
        if self.failed_files:
            message += f" {len(self.failed_files)} file(s) failed."
        self.render(message)


def process_files(
    files: Iterable[Path],
    source_root: Path,
    destination_root: Path,
    filter_chain: str,
) -> None:
    file_list = list(files)
    progress = ProgressDisplay(file_list)
    total = len(file_list)
    if total == 0:
        return

    progress.render("Starting conversions")

    for index, path in enumerate(file_list, start=1):
        convert_file(
            path,
            source_root,
            destination_root,
            filter_chain,
            index,
            total,
            progress,
        )

    progress.finalize()
    if progress.failed_files:
        progress.log("The following files failed during conversion:")
        for failed in progress.failed_files:
            progress.log(f"  {failed}")
    progress.render(progress.last_status_message)


def main() -> None:
    args = parse_args()
    source = args.source.expanduser()
    destination = args.destination.expanduser()
    font_file = args.font_file
    if font_file is not None:
        font_file = font_file.expanduser()
        if not font_file.exists():
            sys.exit(f"Font file not found: {font_file}")

    ensure_ffmpeg()
    validate_paths(source, destination)

    files = discover_videos(source)
    if not files:
        print("No matching video files to process. Exiting.")
        return

    describe_files(files, source)
    filter_chain = build_video_filter(font_file)
    process_files(files, source, destination, filter_chain)


if __name__ == "__main__":
    main()
