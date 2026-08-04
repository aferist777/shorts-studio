"""Thin wrappers over the ffmpeg binary.

ffmpeg-static ships ffmpeg but no ffprobe, so duration is read back off
ffmpeg's own progress output rather than probed.
"""

import re
import subprocess
import sys
from pathlib import Path

from app.paths import find_ffmpeg

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

# keep console windows from flashing on every call
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _run(args: list, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_NO_WINDOW,
    )


def extract_thumbnail(video_path: str, out_path: str, at: float = 1.0,
                      height: int = 320, ffmpeg_path: str = "") -> str:
    """Grab one frame as a JPEG. Returns "" if ffmpeg isn't available."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        return ""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    result = _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", str(at), "-i", video_path, "-frames:v", "1",
        "-vf", f"scale=-2:{height}", out_path,
    ], timeout=60)
    return out_path if result.returncode == 0 and Path(out_path).exists() else ""


def probe_duration(path: str, ffmpeg_path: str = "") -> float:
    """Seconds of media in `path`, or 0.0 if ffmpeg isn't available."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        return 0.0
    result = _run([ffmpeg, "-hide_banner", "-i", path, "-f", "null", "-"], timeout=120)
    matches = _TIME_RE.findall(result.stderr or "")
    if not matches:
        return 0.0
    hours, minutes, seconds = matches[-1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
