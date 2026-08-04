"""YouTube ingest — metadata and subtitles through yt-dlp.

Only the subtitle track is fetched here. The video itself stays on YouTube
until a later phase actually needs a fragment.
"""

import re

import httpx

TIMEOUT = 120.0
# [музыка], [applause] and friends are recognition markers, not speech
_MARKER_RE = re.compile(r"\[[^\]]{1,40}\]")
_VTT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")


def _options(cookies: str = "") -> dict:
    opts = {"skip_download": True, "quiet": True, "no_warnings": True}
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def fetch_info(url: str, cookies: str = "") -> dict:
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("The `yt-dlp` package is missing — run: pip install yt-dlp") from e

    try:
        with yt_dlp.YoutubeDL(_options(cookies)) as ydl:
            raw = ydl.extract_info(url, download=False)
    except Exception as e:
        raise RuntimeError(f"Could not read that link: {str(e)[:200]}") from e

    if raw.get("_type") == "playlist":
        raise RuntimeError("That link is a playlist. Give me a single video.")

    return {
        "video_id": raw.get("id", ""),
        "url": raw.get("webpage_url") or url,
        "title": raw.get("title", "Untitled"),
        "channel": raw.get("uploader") or raw.get("channel") or "",
        "duration": float(raw.get("duration") or 0),
        "description": (raw.get("description") or "")[:4000],
        "language": (raw.get("language") or "").split("-")[0],
        "subtitles": raw.get("subtitles") or {},
        "automatic_captions": raw.get("automatic_captions") or {},
    }


def pick_track(info: dict) -> dict:
    """Best available subtitle track, or {} when the video has none.

    Manual beats automatic, and the original-language auto track beats the
    machine-translated one — YouTube exposes both and `ru` may well be a
    translation of an English original.
    """
    lang = info.get("language") or "en"
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    candidates = [
        (manual, lang, "subtitles"),
        (manual, "en", "subtitles"),
        (auto, f"{lang}-orig", "auto-captions"),
        (auto, lang, "auto-captions"),
        (auto, "en-orig", "auto-captions"),
        (auto, "en", "auto-captions"),
    ]
    if manual:
        first = sorted(manual.keys())[0]
        candidates.insert(2, (manual, first, "subtitles"))

    for pool, key, kind in candidates:
        formats = pool.get(key)
        if not formats:
            continue
        for ext in ("json3", "vtt"):
            match = next((f for f in formats if f.get("ext") == ext and f.get("url")), None)
            if match:
                return {"url": match["url"], "ext": ext, "language": key, "kind": kind}
    return {}


def fetch_cues(track: dict) -> list:
    """-> [{'start', 'end', 'text'}] in seconds."""
    response = httpx.get(track["url"], timeout=TIMEOUT, follow_redirects=True)
    if response.status_code >= 400:
        raise RuntimeError(f"Subtitle download failed ({response.status_code}).")
    if track["ext"] == "json3":
        return _parse_json3(response.json())
    return _parse_vtt(response.text)


def _clean(text: str) -> str:
    return " ".join(_MARKER_RE.sub(" ", text).split())


def _parse_json3(data: dict) -> list:
    cues = []
    for event in data.get("events", []):
        text = _clean("".join(s.get("utf8", "") for s in (event.get("segs") or [])))
        if not text:
            continue
        start = event.get("tStartMs", 0) / 1000
        cues.append({
            "start": round(start, 2),
            "end": round(start + event.get("dDurationMs", 0) / 1000, 2),
            "text": text,
        })
    return cues


def _parse_vtt(body: str) -> list:
    cues, pending = [], None
    for line in body.splitlines():
        stamp = _VTT_TIME_RE.search(line)
        if stamp:
            h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in stamp.groups())
            pending = {
                "start": h1 * 3600 + m1 * 60 + s1 + ms1 / 1000,
                "end": h2 * 3600 + m2 * 60 + s2 + ms2 / 1000,
                "parts": [],
            }
            cues.append(pending)
        elif pending is not None and line.strip():
            pending["parts"].append(line)

    out = []
    for cue in cues:
        text = _clean(re.sub(r"<[^>]+>", " ", " ".join(cue["parts"])))
        if text:
            out.append({"start": round(cue["start"], 2), "end": round(cue["end"], 2),
                        "text": text})
    return out


def download_audio(url: str, out_dir: str, cookies: str = "", progress=None) -> str:
    """Audio-only grab, used solely to feed Whisper when there are no subtitles."""
    import yt_dlp
    from pathlib import Path

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    template = str(Path(out_dir) / "%(id)s.%(ext)s")

    def hook(status):
        if progress and status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            if total:
                progress(f"Downloading audio · {done * 100 // total}%")

    opts = {**_options(cookies), "skip_download": False, "format": "bestaudio/best",
            "outtmpl": template, "progress_hooks": [hook]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        raw = ydl.extract_info(url, download=True)
    return ydl.prepare_filename(raw)
