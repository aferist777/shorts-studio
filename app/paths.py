"""Filesystem layout + ffmpeg discovery.

ffmpeg is not on PATH on this machine, but ffmpeg-static ships one inside the
sibling Node projects. Look there before giving up, and let Settings override.
"""

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"
CACHE_DIR = DATA_DIR / "cache"

for _d in (DATA_DIR, PROJECTS_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    d = PROJECTS_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# checked in order; first hit wins
_FFMPEG_CANDIDATES = [
    ROOT.parent / "ugc-cg-v1.0" / "node_modules" / "ffmpeg-static" / "ffmpeg.exe",
    ROOT.parent / "recursive-loop-studio" / "node_modules" / "ffmpeg-static" / "ffmpeg.exe",
    Path("C:/ffmpeg/bin/ffmpeg.exe"),
]


def find_ffmpeg(override: str = "") -> str:
    """Absolute path to an ffmpeg binary, or "" if none was found."""
    if override and Path(override).is_file():
        return override
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    env = os.environ.get("FFMPEG_PATH", "")
    if env and Path(env).is_file():
        return env
    for c in _FFMPEG_CANDIDATES:
        if c.is_file():
            return str(c)
    return ""


def find_ffprobe(override: str = "") -> str:
    """ffprobe usually sits next to ffmpeg — but ffmpeg-static ships only ffmpeg."""
    if override and Path(override).is_file():
        return override
    on_path = shutil.which("ffprobe")
    if on_path:
        return on_path
    ff = find_ffmpeg()
    if ff:
        sibling = Path(ff).with_name("ffprobe.exe")
        if sibling.is_file():
            return str(sibling)
    return ""
