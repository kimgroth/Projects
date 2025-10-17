#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
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
) -> None:
    relative = source_file.relative_to(source_root)
    proxy_name = f"{relative.stem}_Proxy.mov"
    output_path = destination_root / proxy_name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        print(f"[{index}/{total}] Skipping (already exists): {output_path.name}")
        return

    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
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

    print(
        f"[{index}/{total}] {relative} -> {output_path.name}"
    )
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed for {source_file}: {exc}", file=sys.stderr)


def process_files(
    files: Iterable[Path],
    source_root: Path,
    destination_root: Path,
    filter_chain: str,
) -> None:
    file_list = list(files)
    total = len(file_list)
    for index, path in enumerate(file_list, start=1):
        convert_file(path, source_root, destination_root, filter_chain, index, total)


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
