"""Shared data models for the video difference analyzer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SegmentResult:
    """Represents a contiguous block of frames that differ significantly."""

    start_frame: int
    end_frame: int
    max_difference: float
    screenshot_path: Path

    @property
    def duration_frames(self) -> int:
        return self.end_frame - self.start_frame + 1


@dataclass
class AnalysisMetadata:
    """Metadata about the analyzed videos."""

    fps: float
    total_frames: int
    video_a: Path
    video_b: Path
