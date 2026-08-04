"""Your own clips. Thumbnails come from ffmpeg rather than a CDN."""

import hashlib
from pathlib import Path

from app.paths import CACHE_DIR
from app.services.ffmpeg_tools import extract_thumbnail, probe_duration

EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
MAX_FILES = 60  # a folder scan probes every file with ffmpeg; keep it bounded
THUMB_DIR = CACHE_DIR / "thumbs"


def scan(folder: str, ffmpeg_path: str = "", progress=None) -> list:
    root = Path(folder)
    if not root.is_dir():
        raise RuntimeError(f"Not a folder: {folder}")

    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in EXTENSIONS)
    if not files:
        raise RuntimeError("No video files in that folder.")
    dropped = max(0, len(files) - MAX_FILES)
    files = files[:MAX_FILES]

    out = []
    for i, path in enumerate(files):
        if progress:
            progress(f"Reading {i + 1} of {len(files)}")
        key = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
        thumb = THUMB_DIR / f"local_{key}.jpg"
        if not thumb.exists():
            extract_thumbnail(str(path), str(thumb), ffmpeg_path=ffmpeg_path)
        out.append({
            "source": "local",
            "id": key,
            "term": path.stem,
            "thumb_url": "",
            "thumb_path": str(thumb) if thumb.exists() else "",
            "video_url": str(path),
            "width": 0,
            "height": 0,
            "duration": probe_duration(str(path), ffmpeg_path),
            "credit": path.name,
        })
    if dropped and progress:
        progress(f"Read {len(files)} files, skipped {dropped} over the limit")
    return out
