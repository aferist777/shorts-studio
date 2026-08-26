"""Narrators — how a script is written, as opposed to the voice that reads it.

A narrator is built from real writing by one author: the samples go to a model,
which describes the voice behaviourally, and that description drives the hook,
script and cleaning prompts.

The neutral narrator is built in and carries the anti-machine rules. A narrator
made from real writing replaces those rules rather than stacking on top — a
profile already states what its author never does.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.paths import CACHE_DIR, DATA_DIR
from app.services import prompts

PATH = DATA_DIR / "narrators.json"
AUDIO_DIR = CACHE_DIR / "narrator_audio"

NEUTRAL = {"id": "neutral", "name": "Neutral", "builtin": True}
MIN_SAMPLE_WORDS = 500   # below this the analysis comes back generic and useless


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- store -----------------------------------------------------------------

def load() -> list:
    if not PATH.exists():
        return []
    try:
        return json.loads(PATH.read_text(encoding="utf-8")).get("narrators", [])
    except Exception:
        return []


def save(items: list):
    PATH.write_text(json.dumps({"narrators": items}, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def get(narrator_id: str) -> dict:
    if not narrator_id or narrator_id == "neutral":
        return dict(NEUTRAL)
    return next((n for n in load() if n["id"] == narrator_id), dict(NEUTRAL))


def put(item: dict):
    items = [n for n in load() if n["id"] != item["id"]]
    items.insert(0, {**item, "updated_at": _now()})
    save(items)


def delete(narrator_id: str):
    save([n for n in load() if n["id"] != narrator_id])


def choices() -> list:
    """-> [(id, name)] with the built-in first."""
    return [("neutral", "Neutral")] + [(n["id"], n["name"]) for n in load()]


def style_block(narrator_id: str) -> str:
    narrator = get(narrator_id)
    profile = narrator.get("profile")
    return prompts.render_profile(profile) if profile else prompts.NEUTRAL_BLOCK


# ---- samples ---------------------------------------------------------------

def word_count(samples: list) -> int:
    return sum(len(s.get("text", "").split()) for s in samples)


def transcribe_link(url: str, settings: dict, cookies: str = "", progress=None) -> dict:
    """Turn a video link into a writing sample.

    Deliberately separate from the ideas base: that store is raw material for
    videos, and a narrator's reference texts have no business in it.
    """
    from app.services.ideas import stt, youtube

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio = compact = ""
    try:
        if progress:
            progress("Reading the video page")
        info = youtube.fetch_info(url, cookies)

        if progress:
            progress("Downloading audio")
        audio = youtube.download_audio(info["url"], str(AUDIO_DIR), cookies, progress)

        compact = str(AUDIO_DIR / f"{info['video_id']}.mp3")
        stt.compress(audio, compact, info.get("duration", 0),
                     settings.get("ffmpeg_path", ""), progress)

        result = stt.transcribe(
            compact, settings.get("stt_model", stt.DEFAULT_MODEL), progress)
        text = " ".join(cue["text"] for cue in result["cues"])
        return {"kind": "link", "label": info["title"], "url": info["url"], "text": text}

    finally:
        for leftover in (audio, compact):
            if leftover:
                Path(leftover).unlink(missing_ok=True)


def transcribe_file(path: str, settings: dict, progress=None) -> dict:
    """Turn a video or audio file on disk into a writing sample.

    The route that does not depend on YouTube's mood. The chosen file is only
    read: what goes to the model is a compressed copy in the cache, and that
    copy is removed afterwards whatever happens.

    ffmpeg needs no help picking the audio out of a video container — asking it
    for mp3 makes it ignore the video stream on its own.
    """
    from app.services.ideas import stt

    source = Path(path)
    if not source.exists():
        raise RuntimeError("That file is gone.")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    compact = str(AUDIO_DIR / f"{source.stem[:60]}.mp3")
    try:
        if progress:
            progress("Reading the file")
        ffmpeg = settings.get("ffmpeg_path", "")
        duration = stt.probe_duration(str(source), ffmpeg)

        stt.compress(str(source), compact, duration, ffmpeg, progress)

        result = stt.transcribe(
            compact, settings.get("stt_model", stt.DEFAULT_MODEL), progress)
        text = " ".join(cue["text"] for cue in result["cues"])
        return {"kind": "file", "label": source.name, "path": str(source),
                "text": text}

    finally:
        Path(compact).unlink(missing_ok=True)
