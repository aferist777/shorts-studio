"""Finding and fetching the clips that go under the narration.

A candidate is a plain dict:
    {source, id, term, thumb_url, video_url, width, height, duration, credit}
Local candidates carry `thumb_path` instead of `thumb_url`.
"""

import hashlib
import shutil
from pathlib import Path

import httpx

from app.paths import CACHE_DIR
from app.services.footage import local, pexels, pixabay

SOURCES = {"pexels": "Pexels", "pixabay": "Pixabay"}
THUMB_DIR = CACHE_DIR / "thumbs"
TIMEOUT = 120.0

TARGET_W, TARGET_H = 1080, 1920


def search(terms: list, sources: list, min_duration: float = 0.0,
           per_term: int = 6, progress=None) -> list:
    """Search every term against every source and merge the results.

    Searching per term rather than on one joined query is what gives the picker
    visual variety — a single query tends to return one look repeated.
    """
    found, seen = [], set()
    backends = {"pexels": pexels.search, "pixabay": pixabay.search}
    errors = []

    for term in [t for t in terms if t.strip()]:
        for source in sources:
            backend = backends.get(source)
            if not backend:
                continue
            if progress:
                progress(f"{SOURCES.get(source, source)} · {term}")
            try:
                results = backend(term, per_page=per_term)
            except Exception as e:
                errors.append(str(e))
                continue
            for candidate in results:
                key = (candidate["source"], candidate["id"])
                if key in seen:
                    continue
                seen.add(key)
                found.append(candidate)

    if not found and errors:
        raise RuntimeError(errors[0])
    return rank(found, min_duration)


def rank(candidates: list, min_duration: float = 0.0) -> list:
    """Long enough first, then portrait, then closest to 1080×1920."""
    def score(c):
        long_enough = 0 if (not min_duration or c["duration"] >= min_duration) else 1
        w, h = c.get("width") or 0, c.get("height") or 0
        portrait = 0 if h > w else 1
        # distance from the target frame, normalised so 4K doesn't beat 1080p
        fit = abs((w or TARGET_W) - TARGET_W) / TARGET_W
        return (long_enough, portrait, fit)

    return sorted(candidates, key=score)


def _cache_name(candidate: dict, suffix: str) -> str:
    raw = f"{candidate['source']}:{candidate['id']}".encode("utf-8")
    return f"{candidate['source']}_{hashlib.sha1(raw).hexdigest()[:16]}{suffix}"


def thumbnail(candidate: dict) -> str:
    """Local path to this candidate's thumbnail, downloading it once."""
    if candidate.get("thumb_path"):
        return candidate["thumb_path"]
    url = candidate.get("thumb_url")
    if not url:
        return ""
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    path = THUMB_DIR / _cache_name(candidate, ".jpg")
    if path.exists():
        return str(path)
    try:
        r = httpx.get(url, timeout=60.0, follow_redirects=True)
        if r.status_code >= 400:
            return ""
        path.write_bytes(r.content)
    except Exception:
        return ""
    return str(path)


def download(candidate: dict, dest_path: str, progress=None) -> str:
    """Fetch the clip itself. Local candidates are copied, not re-downloaded."""
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if candidate["source"] == "local":
        source_path = Path(candidate["video_url"])
        if source_path.resolve() != dest.resolve():
            shutil.copy2(source_path, dest)
        return str(dest)

    if progress:
        progress(f"Downloading {candidate['source']} clip")
    with httpx.stream("GET", candidate["video_url"], timeout=TIMEOUT,
                      follow_redirects=True) as r:
        if r.status_code >= 400:
            raise RuntimeError(f"Download failed ({r.status_code}) for {candidate['source']}")
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=1 << 16):
                f.write(chunk)

    if dest.stat().st_size < 1024:
        dest.unlink(missing_ok=True)
        raise RuntimeError("Downloaded clip was empty.")
    return str(dest)
