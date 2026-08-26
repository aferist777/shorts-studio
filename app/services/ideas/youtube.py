"""YouTube ingest — metadata and subtitles through yt-dlp.

Only the subtitle track is fetched here. The video itself stays on YouTube
until a later phase actually needs a fragment.
"""

import re
import time
from pathlib import Path

import httpx

TIMEOUT = 120.0

# Retrying helps far less than the first measurement suggested: one link went
# through once in thirteen attempts, while another was served every single
# time. So the refusal is mostly decided per video, and a retry only catches
# the rare flake. Kept short on purpose — a long retry loop would just make the
# dead end slower without making it any less dead. The file route is the answer.
BOT_CHECK_TRIES = 3
BOT_CHECK_PAUSE = 2.0
_BOT_CHECK_RE = re.compile(r"sign in to confirm you.{0,3}re not a bot", re.I)
# the interface looks for this to offer the file route instead of the raw error
BOT_CHECK_MARK = "would not serve this video"

# [музыка], [applause] and friends are recognition markers, not speech
_MARKER_RE = re.compile(r"\[[^\]]{1,40}\]")


class BotCheck(RuntimeError):
    """YouTube asked for a login instead of serving the video.

    Its own message is a wall of text about cookie flags and links to a wiki,
    which is useless to someone standing in front of a dialog — hence a
    separate type carrying a sentence that says what to do next.
    """


def _with_retries(call, progress=None):
    """Run a yt-dlp call, retrying while YouTube throws its random refusal."""
    for attempt in range(1, BOT_CHECK_TRIES + 1):
        try:
            return call()
        except Exception as e:
            if not _BOT_CHECK_RE.search(str(e)):
                raise
            if attempt == BOT_CHECK_TRIES:
                raise BotCheck(
                    f"YouTube {BOT_CHECK_MARK} to the app — it asked for a "
                    f"login on all {BOT_CHECK_TRIES} attempts. Download the "
                    "video yourself and add it with “From a file…” instead."
                ) from e
            if progress:
                progress(f"YouTube refused — retrying {attempt}/{BOT_CHECK_TRIES - 1}")
            time.sleep(BOT_CHECK_PAUSE)
_VTT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")


def _options(cookies: str = "") -> dict:
    # noprogress: yt-dlp writes its own progress bar to stdout otherwise
    opts = {"skip_download": True, "quiet": True, "no_warnings": True, "noprogress": True}
    if cookies:
        opts["cookiefile"] = cookies

    # Best video and best audio arrive as separate streams and yt-dlp joins them
    # with ffmpeg — which it looks for on PATH, where this machine has none. It
    # has to be told where ours lives or the download dies at the join with
    # "you have requested merging of multiple formats but ffmpeg is not installed".
    from app.paths import find_ffmpeg
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = str(Path(ffmpeg).parent)
    return opts


def fetch_info(url: str, cookies: str = "", progress=None) -> dict:
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("The `yt-dlp` package is missing — run: pip install yt-dlp") from e

    def call():
        with yt_dlp.YoutubeDL(_options(cookies)) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        raw = _with_retries(call, progress)
    except BotCheck:
        raise
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


def pick_manual_track(info: dict) -> dict:
    """A human-made subtitle track, or {} if the video only has generated ones.

    Automatic captions are deliberately ignored. They mangle exactly the words
    that carry the content — on a video about David and Goliath they never once
    produced "Голиаф" — so speech-to-text is the primary path and this is only
    the fallback for videos that ship real subtitles.
    """
    lang = info.get("language") or "en"
    manual = info.get("subtitles") or {}
    if not manual:
        return {}

    order = [lang, "en", *sorted(manual.keys())]
    for key in order:
        formats = manual.get(key)
        if not formats:
            continue
        for ext in ("json3", "vtt"):
            match = next((f for f in formats if f.get("ext") == ext and f.get("url")), None)
            if match:
                return {"url": match["url"], "ext": ext, "language": key,
                        "kind": "subtitles"}
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

    def call():
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(raw)

    return _with_retries(call, progress)
