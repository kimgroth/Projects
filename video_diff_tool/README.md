# Video Difference Tool

Compare two video files, identify segments with meaningful visual differences, and export
results to a PDF report that includes a spreadsheet-style table and representative
screenshots.

## Features

- Frame-by-frame comparison using the Structural Similarity Index (SSIM)
- Adjustable difference threshold, minimum segment length, and frame stride
- Automatic extraction of the most divergent frame for each segment
- PDF report containing timecodes, durations, difference metrics, and screenshots
- Cross-platform Python implementation compatible with Linux, macOS, and Windows

## Requirements

- Python 3.9 or newer
- FFmpeg-compatible video files readable by OpenCV

Install dependencies with:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use `.venv\\Scripts\\activate`
pip install -r requirements.txt
```

## Usage

```bash
python -m video_diff_tool.cli <video_a> <video_b> \
    --threshold 0.20 \
    --min-segment-length 8 \
    --frame-stride 1 \
    --output diff_report.pdf
```

### Key arguments

- `--threshold`: Minimum dissimilarity (1 - SSIM) required to flag a frame. Higher values
  reduce noise and report only large differences.
- `--min-segment-length`: Minimum consecutive differing frames required before a segment is
  reported. Increase this to ignore very short blips.
- `--frame-stride`: Process every Nth frame to trade accuracy for faster execution.
- `--workdir`: Optional directory for intermediate screenshots. Defaults to the output
  directory.

The generated PDF includes a summary of parameters followed by a table that lists each
segment with its start and end timecodes (HH:MM:SS:FF), duration, maximum difference score,
and the combined screenshot showing both videos and the heatmap of the detected difference.

## Notes

- The tool assumes both videos have comparable durations and frame rates. When frame rates
  differ, the FPS from the first readable source is used for timecode calculations.
- Screenshots are stored in `video_diff_screenshots` within the working directory, making it
  easy to review or reuse the images separately.
- Depending on codec support, you may need to install additional codecs or FFmpeg builds on
  your operating system so OpenCV can decode the input files.
