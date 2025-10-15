"""Utility helpers for the video difference analyzer."""

from __future__ import annotations

import math


def format_timecode(frame_index: int, fps: float) -> str:
    """Format a frame index as a HH:MM:SS:FF timecode."""

    if fps <= 0:
        raise ValueError("Frames per second must be positive to format timecodes.")

    total_seconds = frame_index / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    frame = int(round((total_seconds - math.floor(total_seconds)) * fps))
    if frame >= fps:
        seconds += 1
        frame = 0
    if seconds >= 60:
        minutes += 1
        seconds = 0
    if minutes >= 60:
        hours += 1
        minutes = 0
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame:02d}"
