"""One rule for every picture the interface shows: a small copy, never the original.

A drawn frame is a 3 MB png, 768x1376, and showing it in a strip 57 pixels tall
costs 4.2 MB of memory and about 70 ms — nineteen scenes of them froze the
window for four seconds. Nothing on screen is larger than a few hundred pixels,
so nothing on screen needs more than this.

The ceiling is on bytes rather than on dimensions because that is the promise
worth keeping: a thumbnail is never a file worth waiting for.
"""

import hashlib
import os
import threading
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader

from app.paths import CACHE_DIR

MINI_DIR = CACHE_DIR / "mini"

HEIGHT = 320                 # covers every place one is shown, at any zoom
MAX_BYTES = 25 * 1024
# tried in order until one fits; the last is used whatever it weighs
QUALITIES = [85, 75, 65, 55]
FLOOR_HEIGHT = 200           # if even the worst quality will not fit, shrink

READABLE = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def key_for(path: Path) -> str:
    """Same file, same thumbnail; redrawn file, new one.

    Size and mtime rather than contents: hashing three megabytes to decide
    whether to spend fifty milliseconds is a poor trade.
    """
    stat = path.stat()
    stamp = f"{path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}"
    return hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:20]


def _read_scaled(path: Path, height: int) -> QImage:
    """Decode straight to the size wanted where the format allows it."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.height() > height:
        width = max(1, round(size.width() * height / size.height()))
        reader.setScaledSize(QSize(width, height))
    image = reader.read()
    if image.isNull():
        return image
    if image.height() > height:      # a format that ignored the request
        image = image.scaledToHeight(height, Qt.SmoothTransformation)
    return image


def _write_under_ceiling(image: QImage, dest: Path) -> bool:
    """Save as jpeg, giving up quality until it fits. -> whether anything was written.

    Written aside and moved into place: the background pass and a scene being
    opened by hand can want the same thumbnail at the same moment, and a reader
    must never catch a half-written file and cache it as good.
    """
    tmp = dest.with_name(f"{dest.stem}.{os.getpid()}-{threading.get_ident()}.part")
    try:
        for height in (image.height(), FLOOR_HEIGHT):
            small = image if height == image.height() else image.scaledToHeight(
                height, Qt.SmoothTransformation)
            for quality in QUALITIES:
                if not small.save(str(tmp), "JPEG", quality):
                    return False
                if tmp.stat().st_size <= MAX_BYTES:
                    os.replace(tmp, dest)
                    return True
        if tmp.exists():          # kept at its smallest, even if still over
            os.replace(tmp, dest)
            return True
        return False
    finally:
        tmp.unlink(missing_ok=True)


def thumb_for(path: str) -> str:
    """A small copy of `path`, made once and kept. -> its path, or "" .

    Returns the original only when it cannot be read as an image at all, which
    keeps callers free of "is this a picture" checks.
    """
    if not path:
        return ""
    source = Path(path)
    if not source.is_file() or source.suffix.lower() not in READABLE:
        return ""

    MINI_DIR.mkdir(parents=True, exist_ok=True)
    dest = MINI_DIR / f"{key_for(source)}.jpg"
    if dest.exists():
        return str(dest)

    image = _read_scaled(source, HEIGHT)
    if image.isNull():
        return ""
    if not _write_under_ceiling(image, dest):
        dest.unlink(missing_ok=True)
        return ""
    return str(dest)


def missing(paths: list) -> list:
    """Which of these have no thumbnail yet. Reads no pixels — a stat each."""
    out = []
    for path in paths:
        source = Path(path) if path else None
        if not source or not source.is_file():
            continue
        if source.suffix.lower() not in READABLE:
            continue
        if not (MINI_DIR / f"{key_for(source)}.jpg").exists():
            out.append(str(source))
    return out


def build(paths: list, progress=None) -> int:
    """Make the ones that are missing. Belongs on a worker thread."""
    done = 0
    for i, path in enumerate(paths):
        if progress and i % 5 == 0:
            progress(f"Preparing thumbnails · {i + 1} of {len(paths)}")
        if thumb_for(path):
            done += 1
    return done


def small(path: str) -> str:
    """What to hand a QPixmap: the thumbnail, or the original if none can be made.

    Every place that shows a picture goes through here rather than storing the
    thumbnail's path, so a project written before any of this existed is shown
    the same way as one written today.
    """
    return thumb_for(path) or path
