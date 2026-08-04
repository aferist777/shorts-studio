"""Pixabay video search.

Pixabay has no orientation filter for videos, so portrait selection happens
client-side on the reported dimensions.
"""

import httpx

from app.config import get_key

SEARCH_URL = "https://pixabay.com/api/videos/"
TIMEOUT = 60.0
SIZE_ORDER = ["small", "medium", "large", "tiny"]  # small is already 1080-wide


def search(term: str, per_page: int = 8) -> list:
    key = get_key("pixabay")
    if not key:
        raise RuntimeError("No Pixabay API key. Add one in Settings.")

    r = httpx.get(
        SEARCH_URL,
        params={"key": key, "q": term, "per_page": max(3, per_page), "safesearch": "true"},
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Pixabay error {r.status_code}: {r.text[:200]}")

    out = []
    for hit in r.json().get("hits", []):
        if hit.get("isLowQuality"):
            continue
        variant = _best_variant(hit.get("videos") or {})
        if not variant:
            continue
        out.append({
            "source": "pixabay",
            "id": str(hit["id"]),
            "term": term,
            "thumb_url": variant.get("thumbnail", ""),
            "video_url": variant["url"],
            "width": variant.get("width", 0),
            "height": variant.get("height", 0),
            "duration": float(hit.get("duration") or 0),
            "credit": hit.get("user", ""),
        })
    return out


def _best_variant(variants: dict) -> dict:
    """Prefer portrait, but keep landscape as fallback material.

    Pixabay's video library is mostly 16:9. Dropping all of it left the source
    contributing almost nothing, so landscape clips stay in and get centre-cropped
    at render time — `rank()` still sorts them below anything already vertical.
    """
    usable = {name: v for name, v in variants.items() if v.get("url")}
    if not usable:
        return {}
    portrait = {n: v for n, v in usable.items()
                if (v.get("height") or 0) > (v.get("width") or 0)}
    pool = portrait or usable
    short_edge = (lambda v: min(v.get("width") or 0, v.get("height") or 0))

    for name in SIZE_ORDER:
        v = pool.get(name)
        if v and short_edge(v) >= 1080:
            return v
    return max(pool.values(), key=short_edge)
