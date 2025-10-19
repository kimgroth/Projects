"""Command line interface for the video difference analyzer."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from time import monotonic

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from .models import AnalysisMetadata, SegmentResult
from .report import generate_report
from .utils import format_timecode


DEFAULT_THRESHOLD = 0.15
DEFAULT_MIN_SEGMENT_LENGTH = 6
DEFAULT_FRAME_STRIDE = 1


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds into H:MM:SS or MM:SS."""

    if not math.isfinite(seconds) or seconds < 0:
        return "--:--"
    seconds_int = int(round(seconds))
    hours, remainder = divmod(seconds_int, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Compare two video files, detect differing shots, and export a PDF "
            "report containing timecodes and representative screenshots."
        )
    )
    parser.add_argument("video_a", type=Path, help="Path to the first video file.")
    parser.add_argument("video_b", type=Path, help="Path to the second video file.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=(
            "Minimum structural difference (1 - SSIM) required to flag a frame as "
            "part of a differing segment. Values closer to 0 mean similar frames; "
            "closer to 1 mean very different."
        ),
    )
    parser.add_argument(
        "--min-segment-length",
        type=int,
        default=DEFAULT_MIN_SEGMENT_LENGTH,
        help=(
            "Minimum number of consecutive differing frames required before a "
            "segment is reported."
        ),
    )
    parser.add_argument(
        "--frame-stride",
        type=int,
        default=DEFAULT_FRAME_STRIDE,
        help=(
            "Process every Nth frame. Use values greater than 1 to speed up "
            "analysis at the cost of precision."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("video_difference_report.pdf"),
        help="Path to the output PDF report.",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Optional working directory for intermediate screenshots.",
    )
    return parser.parse_args(argv)


def _ensure_matching_dimensions(frame_a: np.ndarray, frame_b: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Resize frames to ensure they have matching dimensions."""

    if frame_a.shape == frame_b.shape:
        return frame_a, frame_b

    height, width = frame_a.shape[:2]
    resized_b = cv2.resize(frame_b, (width, height), interpolation=cv2.INTER_AREA)
    return frame_a, resized_b


def _label_frame(frame: np.ndarray, label: str) -> np.ndarray:
    """Draw a semi-transparent label on the top-left corner of a frame."""

    overlay = frame.copy()
    alpha = 0.7
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(frame.shape[1] / 1920, 0.5)
    thickness = max(int(2 * scale), 1)
    text_size, _ = cv2.getTextSize(label, font, scale, thickness)
    text_width, text_height = text_size
    padding = int(10 * scale)

    cv2.rectangle(
        overlay,
        (0, 0),
        (text_width + 2 * padding, text_height + 2 * padding),
        (0, 0, 0),
        -1,
    )
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    cv2.putText(
        frame,
        label,
        (padding, text_height + padding // 2),
        font,
        scale,
        (255, 255, 255),
        thickness,
        lineType=cv2.LINE_AA,
    )
    return frame


def _write_combined_screenshot(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    difference_map: np.ndarray,
    output_path: Path,
    labels: Tuple[str, str],
) -> None:
    """Create a combined screenshot showing both frames and the difference heatmap."""

    labeled_a = _label_frame(frame_a.copy(), labels[0])
    labeled_b = _label_frame(frame_b.copy(), labels[1])

    heatmap = cv2.normalize(difference_map, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    heatmap_color = cv2.applyColorMap(heatmap, cv2.COLORMAP_INFERNO)
    heatmap_color = _label_frame(heatmap_color, "Difference")

    combined = np.hstack([labeled_a, labeled_b, heatmap_color])
    cv2.imwrite(str(output_path), combined)


def analyze_videos(
    video_a: Path,
    video_b: Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_segment_length: int = DEFAULT_MIN_SEGMENT_LENGTH,
    frame_stride: int = DEFAULT_FRAME_STRIDE,
    workdir: Optional[Path] = None,
) -> Tuple[List[SegmentResult], AnalysisMetadata]:
    """Analyze two videos and return differing segments and metadata."""

    if frame_stride < 1:
        raise ValueError("frame_stride must be greater than or equal to 1")
    if min_segment_length < 1:
        raise ValueError("min_segment_length must be greater than or equal to 1")

    cap_a = cv2.VideoCapture(str(video_a))
    cap_b = cv2.VideoCapture(str(video_b))

    if not cap_a.isOpened():
        raise FileNotFoundError(f"Unable to open video: {video_a}")
    if not cap_b.isOpened():
        raise FileNotFoundError(f"Unable to open video: {video_b}")

    fps_a = cap_a.get(cv2.CAP_PROP_FPS) or 0.0
    fps_b = cap_b.get(cv2.CAP_PROP_FPS) or 0.0
    fps = fps_a if fps_a > 0 else fps_b
    if fps <= 0 and fps_b > 0:
        fps = fps_b
    if fps <= 0:
        raise RuntimeError("Unable to determine FPS from the provided videos.")

    total_frames_a = int(cap_a.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    total_frames_b = int(cap_b.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    total_frames = min(total_frames_a, total_frames_b)

    workdir = Path(workdir) if workdir else Path(".")
    screenshots_dir = workdir / "video_diff_screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    segments: List[SegmentResult] = []
    current_start: Optional[int] = None
    current_max_diff = -1.0
    current_best_frames: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None
    frame_index = 0
    start_time = monotonic()
    last_report_time = start_time
    progress_reported = False

    def report_progress(current_frame: int, *, final: bool = False) -> None:
        nonlocal last_report_time, progress_reported

        now = monotonic()
        if not final and now - last_report_time < 5 and current_frame < total_frames:
            return

        elapsed = max(now - start_time, 1e-9)
        processed = max(0, min(current_frame, total_frames if total_frames > 0 else current_frame))

        if total_frames > 0:
            percent = (processed / total_frames) * 100
            fps_processed = processed / elapsed if elapsed > 0 else 0.0
            remaining_frames = max(total_frames - processed, 0)
            eta_seconds = remaining_frames / fps_processed if fps_processed > 0 else float("inf")
            message = (
                f"Processed {processed}/{total_frames} frames "
                f"({percent:5.1f}%) | ETA {_format_duration(eta_seconds)}"
            )
        else:
            message = f"Processed {processed} frames | elapsed {_format_duration(elapsed)}"

        if final:
            print(message + " " * 20)
        else:
            print(message, end="\r", flush=True)

        last_report_time = now
        progress_reported = True

    try:
        while True:
            ret_a, frame_a = cap_a.read()
            ret_b, frame_b = cap_b.read()

            if not ret_a or not ret_b:
                break

            if frame_index % frame_stride != 0:
                frame_index += 1
                report_progress(frame_index)
                continue

            frame_a, frame_b = _ensure_matching_dimensions(frame_a, frame_b)
            gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
            gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)

            score, diff_map = structural_similarity(gray_a, gray_b, full=True)
            difference = 1.0 - float(score)

            if difference >= threshold:
                if current_start is None:
                    current_start = frame_index
                    current_max_diff = difference
                    current_best_frames = (frame_a.copy(), frame_b.copy(), diff_map)
                else:
                    if difference > current_max_diff and current_best_frames is not None:
                        current_max_diff = difference
                        current_best_frames = (frame_a.copy(), frame_b.copy(), diff_map)
            else:
                if current_start is not None and current_best_frames is not None:
                    end_frame = frame_index - 1
                    if end_frame - current_start + 1 >= min_segment_length:
                        screenshot_file = screenshots_dir / f"segment_{len(segments)+1:03d}.png"
                        frame_a_best, frame_b_best, diff_best = current_best_frames
                        _write_combined_screenshot(
                            frame_a_best,
                            frame_b_best,
                            diff_best,
                            screenshot_file,
                            (video_a.name, video_b.name),
                        )
                        segments.append(
                            SegmentResult(
                                start_frame=current_start,
                                end_frame=end_frame,
                                max_difference=current_max_diff,
                                screenshot_path=screenshot_file,
                            )
                        )
                current_start = None
                current_max_diff = -1.0
                current_best_frames = None

            frame_index += 1
            report_progress(frame_index)

        if current_start is not None and current_best_frames is not None:
            end_frame = frame_index - 1
            if end_frame - current_start + 1 >= min_segment_length:
                screenshot_file = screenshots_dir / f"segment_{len(segments)+1:03d}.png"
                frame_a_best, frame_b_best, diff_best = current_best_frames
                _write_combined_screenshot(
                    frame_a_best,
                    frame_b_best,
                    diff_best,
                    screenshot_file,
                    (video_a.name, video_b.name),
                )
                segments.append(
                    SegmentResult(
                        start_frame=current_start,
                        end_frame=end_frame,
                        max_difference=current_max_diff,
                        screenshot_path=screenshot_file,
                    )
                )
    finally:
        cap_a.release()
        cap_b.release()
        report_progress(frame_index, final=True)
        if progress_reported:
            print()  # Ensure subsequent output starts on a new line.

    metadata = AnalysisMetadata(
        fps=fps,
        total_frames=total_frames,
        video_a=Path(video_a),
        video_b=Path(video_b),
    )
    return segments, metadata


def main(argv: Optional[Iterable[str]] = None) -> None:
    """Entry point for CLI execution."""

    args = parse_args(argv)
    segments, metadata = analyze_videos(
        args.video_a,
        args.video_b,
        threshold=args.threshold,
        min_segment_length=args.min_segment_length,
        frame_stride=args.frame_stride,
        workdir=args.workdir or args.output.parent,
    )

    if not segments:
        print("No differing segments were detected with the current parameters.")
        return

    generate_report(
        segments,
        metadata,
        output_path=args.output,
        threshold=args.threshold,
        min_segment_length=args.min_segment_length,
        frame_stride=args.frame_stride,
    )
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
