"""Finding the seams in a project's fragment, so it can be broken into b-roll.

The fragment is one continuous slice of somebody else's edit, which means it
already has cuts in it — between a painting and a map, between archive footage
and the presenter. Those seams are where it wants to come apart, and ffmpeg can
find them without anyone being asked to watch the whole thing.

Measured on a clip with four known cuts: a threshold of 0.25 found all four and
invented none. The markers it produces are a starting point, not a verdict —
they exist to be dragged.
"""

import re
import subprocess
import sys
from pathlib import Path

from app.paths import find_ffmpeg

SCENE_THRESHOLD = 0.25
MIN_SEGMENT = 0.8          # anything shorter is a transition frame, not a shot
STRIP_HEIGHT = 54          # the filmstrip under the timeline

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def _run(args: list, timeout: int = 1800) -> subprocess.CompletedProcess:
    # utf-8 explicitly: a Cyrillic path makes Windows decode ffmpeg as cp1252
    # and the reader thread dies mid-way
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW, timeout=timeout)


def detect_cuts(video: str, ffmpeg_path: str = "", progress=None) -> list:
    """Seconds at which the picture changes."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("No ffmpeg found. Set its location in Settings.")
    if progress:
        progress("Looking for cuts")

    result = _run([ffmpeg, "-hide_banner", "-i", video,
                   "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
                   "-f", "null", "-"])
    found = sorted({round(float(m), 2) for m in _PTS_RE.findall(result.stderr or "")})
    return [t for t in found if t > MIN_SEGMENT]


def grab_frame(video: str, at: float, dest: str, ffmpeg_path: str = "") -> str:
    """One full-size frame, for keeping.

    Scrubbing the preview is done by the player, which costs nothing; this is
    only for the still the user decides to save, so it is worth the full
    resolution and the wait.
    """
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("No ffmpeg found. Set its location in Settings.")
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    result = _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", f"{max(0.0, at):.3f}", "-i", video, "-frames:v", "1",
                   "-q:v", "2", dest], timeout=120)
    if result.returncode != 0 or not Path(dest).exists():
        raise RuntimeError("Could not read that frame:\n"
                           + (result.stderr or "")[-300:])
    return dest


THUMB_H = 64


def thumb(video: str, at: float, dest: str, ffmpeg_path: str = "") -> str:
    """A small poster frame for a shelf card. Failure is not worth an error —
    a card without a picture is still a card."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        return ""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    result = _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-ss", f"{max(0.0, at):.3f}", "-i", video, "-frames:v", "1",
                   "-vf", f"scale=-2:{THUMB_H}", "-q:v", "6", dest], timeout=60)
    return dest if result.returncode == 0 and Path(dest).exists() else ""


def segments(cuts: list, duration: float) -> list:
    """Cut points -> [(start, end)] covering the whole fragment."""
    edges = [0.0] + [c for c in cuts if 0 < c < duration] + [float(duration)]
    out = []
    for start, end in zip(edges, edges[1:]):
        if end - start >= MIN_SEGMENT:
            out.append((round(start, 2), round(end, 2)))
    return out
