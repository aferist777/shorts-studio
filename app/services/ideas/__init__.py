"""The ideas base — analysed videos and the topics found inside them.

Global, not per-project: one long video is expected to spawn several shorts,
and you should be able to come back months later and mine the topics you
skipped the first time.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.paths import CACHE_DIR, DATA_DIR
from app.services.ideas import topics as topics_module
from app.services.ideas import transcribe as transcribe_module
from app.services.ideas import youtube

INDEX_PATH = DATA_DIR / "ideas.json"
TRANSCRIPT_DIR = CACHE_DIR / "transcripts"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- store -----------------------------------------------------------------

def load_index() -> list:
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8")).get("videos", [])
    except Exception:
        return []


def save_index(videos: list):
    INDEX_PATH.write_text(json.dumps({"videos": videos}, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def get_entry(video_id: str) -> dict:
    return next((v for v in load_index() if v.get("video_id") == video_id), {})


def put_entry(entry: dict):
    videos = [v for v in load_index() if v.get("video_id") != entry["video_id"]]
    videos.insert(0, entry)
    save_index(videos)


def mark_used(video_id: str, topic_index: int, project_id: str):
    videos = load_index()
    for video in videos:
        if video.get("video_id") != video_id:
            continue
        if 0 <= topic_index < len(video.get("topics", [])):
            video["topics"][topic_index]["used_by"] = project_id
    save_index(videos)


def cache_cues(video_id: str, cues: list):
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    (TRANSCRIPT_DIR / f"{video_id}.json").write_text(
        json.dumps(cues, ensure_ascii=False), encoding="utf-8")


def cached_cues(video_id: str) -> list:
    path = TRANSCRIPT_DIR / f"{video_id}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


# ---- pipeline --------------------------------------------------------------

def prepare(url: str, cookies: str = "", progress=None) -> dict:
    """Metadata plus a transcript if one can be had without transcribing.

    Returns {'info', 'cues', 'source', 'entry'}. Empty `cues` means the video
    has no subtitles and the caller has to decide about Whisper.
    """
    if progress:
        progress("Reading the video page")
    info = youtube.fetch_info(url, cookies)

    entry = get_entry(info["video_id"])
    cues = cached_cues(info["video_id"])
    if cues:
        if progress:
            progress("Using the cached transcript")
        return {"info": info, "cues": cues,
                "source": entry.get("source", "cache"), "entry": entry}

    if progress:
        progress("Looking for subtitles")
    track = youtube.pick_track(info)
    if not track:
        return {"info": info, "cues": [], "source": "", "entry": entry}

    if progress:
        progress(f"Downloading {track['kind']} ({track['language']})")
    cues = youtube.fetch_cues(track)
    if cues:
        cache_cues(info["video_id"], cues)
    return {"info": info, "cues": cues, "source": track["kind"], "entry": entry}


def transcribe_video(info: dict, model_size: str = "small", cookies: str = "",
                     progress=None) -> list:
    audio = youtube.download_audio(info["url"], str(transcribe_module.audio_cache_dir()),
                                   cookies, progress)
    cues = transcribe_module.transcribe(
        audio, model_size, info.get("language", ""), info.get("duration", 0), progress)
    cache_cues(info["video_id"], cues)
    Path(audio).unlink(missing_ok=True)   # the transcript is what we wanted
    return cues


def find_topics(info: dict, cues: list, settings: dict, source: str = "",
                progress=None) -> dict:
    result = topics_module.extract(info, cues, settings, progress)
    entry = {
        "video_id": info["video_id"],
        "url": info["url"],
        "title": info["title"],
        "channel": info["channel"],
        "duration": info["duration"],
        "source": source or "subtitles",
        "analysed_at": _now(),
        "video_summary": result["video_summary"],
        "topics": result["topics"],
    }
    put_entry(entry)
    return entry


def analyse(url: str, settings: dict, cookies: str = "", progress=None) -> dict:
    """Whole pipeline in one call, for the subtitle path. Raises if none exist."""
    prepared = prepare(url, cookies, progress)
    if not prepared["cues"]:
        raise RuntimeError("This video has no subtitles.")
    return find_topics(prepared["info"], prepared["cues"], settings,
                       prepared["source"], progress)
