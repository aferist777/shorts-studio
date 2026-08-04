"""Pexels video search."""

import httpx

from app.config import get_key

SEARCH_URL = "https://api.pexels.com/videos/search"
TIMEOUT = 60.0


def search(term: str, per_page: int = 8) -> list:
    key = get_key("pexels")
    if not key:
        raise RuntimeError("No Pexels API key. Add one in Settings.")

    r = httpx.get(
        SEARCH_URL,
        params={"query": term, "orientation": "portrait", "per_page": per_page},
        headers={"Authorization": key},
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Pexels error {r.status_code}: {r.text[:200]}")

    out = []
    for video in r.json().get("videos", []):
        best = _best_file(video.get("video_files", []))
        if not best:
            continue
        out.append({
            "source": "pexels",
            "id": str(video["id"]),
            "term": term,
            "thumb_url": video.get("image", ""),
            "video_url": best["link"],
            "width": best.get("width") or video.get("width", 0),
            "height": best.get("height") or video.get("height", 0),
            "duration": float(video.get("duration") or 0),
            "credit": (video.get("user") or {}).get("name", ""),
        })
    return out


def _best_file(files: list) -> dict:
    """Smallest mp4 that still covers 1080 on the short edge — bigger is just
    bandwidth we throw away when scaling to 1080×1920."""
    mp4 = [f for f in files if f.get("file_type") == "video/mp4" and f.get("link")]
    if not mp4:
        return {}
    tall = [f for f in mp4 if (f.get("height") or 0) >= (f.get("width") or 0)] or mp4
    covering = [f for f in tall if (f.get("width") or 0) >= 1080]
    if covering:
        return min(covering, key=lambda f: f["width"])
    return max(tall, key=lambda f: f.get("width") or 0)
