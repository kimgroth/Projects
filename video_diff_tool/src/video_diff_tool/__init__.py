"""Video difference analysis toolkit."""

__all__ = ["analyze_videos", "generate_report"]

from .cli import analyze_videos
from .report import generate_report
