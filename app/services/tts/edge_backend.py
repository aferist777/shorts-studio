"""Edge TTS. Free, decent Russian voices, and — the reason it is the default —
it hands back word boundaries during synthesis, so subtitles need no Whisper pass.
"""

import asyncio
import json
from pathlib import Path

from app.paths import CACHE_DIR
from app.services.ffmpeg_tools import probe_duration

VOICE_CACHE = CACHE_DIR / "edge_voices.json"
TICKS_PER_SECOND = 10_000_000  # edge reports offsets in 100-nanosecond ticks

_memo = None


def _load_all_voices() -> list:
    """Full catalogue, cached on disk — it is a network call and rarely changes."""
    global _memo
    if _memo is not None:
        return _memo
    if VOICE_CACHE.exists():
        try:
            _memo = json.loads(VOICE_CACHE.read_text(encoding="utf-8"))
            return _memo
        except Exception:
            pass

    import edge_tts

    voices = asyncio.run(edge_tts.list_voices())
    _memo = [
        {"id": v["ShortName"], "locale": v["Locale"], "gender": v.get("Gender", "")}
        for v in voices
    ]
    VOICE_CACHE.write_text(json.dumps(_memo, ensure_ascii=False), encoding="utf-8")
    return _memo


def list_voices(locale_prefix: str) -> list:
    """Voices for one language, plus every Multilingual voice.

    Some locales ship only two native voices (ru-RU is one of them) and they are
    the older, flatter-sounding ones — the Multilingual voices read the same
    language far better, so they belong in every list.
    """
    prefix = locale_prefix.lower()
    out = []
    for v in _load_all_voices():
        multilingual = "Multilingual" in v["id"]
        if not multilingual and not v["locale"].lower().startswith(prefix):
            continue
        # "ru-RU-DmitryNeural" -> "Dmitry"
        name = v["id"].split("-")[-1].replace("MultilingualNeural", "").replace("Neural", "")
        gender = v["gender"][:1]
        label = (f"{name} · multilingual · {gender}" if multilingual
                 else f"{name} · {v['locale']} · {gender}").strip(" ·")
        out.append({"id": v["id"], "label": label, "gender": v["gender"],
                    "multilingual": multilingual})
    # native voices first, multilingual after
    return sorted(out, key=lambda v: (v["multilingual"], v["label"]))


async def _stream(text: str, voice: str, rate: str):
    import edge_tts

    # the default boundary is SentenceBoundary — word-level is the whole point here
    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            start = chunk["offset"] / TICKS_PER_SECOND
            words.append({
                "w": chunk["text"],
                "start": round(start, 3),
                "end": round(start + chunk["duration"] / TICKS_PER_SECOND, 3),
            })
    return bytes(audio), words


def synthesize(text: str, voice: str, rate: str, out_path: str, ffmpeg_path: str = "") -> dict:
    audio, words = asyncio.run(_stream(text, voice, rate))
    if not audio:
        raise RuntimeError("Edge TTS returned no audio — check the voice and the connection.")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(audio)

    duration = probe_duration(out_path, ffmpeg_path)
    if not duration and words:
        duration = words[-1]["end"]  # no ffmpeg — the last word is a close enough floor
    return {"path": out_path, "duration": round(duration, 3), "words": words}
