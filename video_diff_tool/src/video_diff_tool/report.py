"""PDF report generation for video difference analysis."""

from __future__ import annotations

from pathlib import Path
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import AnalysisMetadata, SegmentResult
from .utils import format_timecode


def _scale_image(image: Image, max_width: float, max_height: float) -> Image:
    """Scale an image to fit within the specified bounds while preserving aspect ratio."""

    width, height = image.drawWidth, image.drawHeight
    width_ratio = max_width / width if width > 0 else 1.0
    height_ratio = max_height / height if height > 0 else 1.0
    ratio = min(width_ratio, height_ratio, 1.0)
    image.drawWidth = width * ratio
    image.drawHeight = height * ratio
    return image


def _build_summary_table(metadata: AnalysisMetadata, threshold: float, min_segment_length: int, frame_stride: int) -> Table:
    """Create a summary table describing the analysis parameters."""

    data = [
        ["Video A", str(metadata.video_a)],
        ["Video B", str(metadata.video_b)],
        ["Frame rate", f"{metadata.fps:.3f} fps"],
        ["Compared frames", metadata.total_frames],
        ["Difference threshold", f"{threshold:.3f} (1 - SSIM)"],
        ["Minimum segment length", f"{min_segment_length} frames"],
        ["Frame stride", f"{frame_stride}"],
    ]

    table = Table(data, colWidths=[140, 360])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.lightgrey]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]
        )
    )
    return table


def _build_segments_table(segments: List[SegmentResult], metadata: AnalysisMetadata) -> Table:
    """Create the detailed table of differing segments."""

    header = ["#", "Start", "End", "Duration (s)", "Max Δ", "Peak frame"]
    data: List[List[object]] = [header]

    for idx, segment in enumerate(segments, start=1):
        start_tc = format_timecode(segment.start_frame, metadata.fps)
        end_tc = format_timecode(segment.end_frame, metadata.fps)
        duration_seconds = segment.duration_frames / metadata.fps
        diff_value = f"{segment.max_difference:.3f}"

        img = Image(str(segment.screenshot_path))
        img = _scale_image(img, max_width=2.6 * inch, max_height=1.6 * inch)

        row = [
            idx,
            start_tc,
            end_tc,
            f"{duration_seconds:.2f}",
            diff_value,
            img,
        ]
        data.append(row)

    col_widths = [30, 90, 90, 80, 70, 200]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ("TEXTCOLOR", (0, 0), (-2, 0), colors.white),
                ("TEXTCOLOR", (-1, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (0, 1), (-2, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FB")]),
            ]
        )
    )
    return table


def generate_report(
    segments: List[SegmentResult],
    metadata: AnalysisMetadata,
    *,
    output_path: Path,
    threshold: float,
    min_segment_length: int,
    frame_stride: int,
) -> None:
    """Generate a PDF report summarizing the analysis."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(str(output_path), pagesize=letter, title="Video Difference Report")
    styles = getSampleStyleSheet()
    title_style: ParagraphStyle = styles["Title"]
    body_style: ParagraphStyle = styles["BodyText"]

    elements: List[object] = []
    elements.append(Paragraph("Video Difference Report", title_style))
    elements.append(Spacer(1, 0.2 * inch))

    intro_text = (
        "This report compares two video sources and highlights segments where the "
        "content diverges beyond the configured structural dissimilarity threshold."
    )
    elements.append(Paragraph(intro_text, body_style))
    elements.append(Spacer(1, 0.2 * inch))

    elements.append(_build_summary_table(metadata, threshold, min_segment_length, frame_stride))
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph("Detected Segments", styles["Heading2"]))
    elements.append(Spacer(1, 0.15 * inch))
    elements.append(_build_segments_table(segments, metadata))

    doc.build(elements)
