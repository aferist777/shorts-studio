"""ElevenLabs. Better delivery than Edge, but paid — and its timings arrive
per character, so they get folded back into words here.

The `with-timestamps` endpoint is used rather than plain TTS specifically so the
karaoke subtitles keep working when the engine is switched.
"""

import base64
from pathlib import Path

import httpx

from app.config import get_key
from app.services.ffmpeg_tools import probe_duration

BASE_URL = "https://api.elevenlabs.io/v1"
MODEL_ID = "eleven_multilingual_v2"  # widest timestamp support
TIMEOUT = 180.0


def _headers() -> dict:
    key = get_key("elevenlabs")
    if not key:
        raise RuntimeError("No ElevenLabs API key. Add one in Settings, or use Edge TTS.")
    return {"xi-api-key": key}


def list_voices() -> list:
    r = httpx.get(f"{BASE_URL}/voices", headers=_headers(), timeout=60.0)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text[:200]}")
    out = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        detail = " · ".join(x for x in (labels.get("gender"), labels.get("accent")) if x)
        out.append({
            "id": v["voice_id"],
            "label": f"{v['name']} · {detail}" if detail else v["name"],
            "gender": labels.get("gender", ""),
        })
    return sorted(out, key=lambda v: v["label"])


def _words_from_alignment(alignment: dict) -> list:
    """Character-level timings -> word-level, splitting on whitespace."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not (len(chars) == len(starts) == len(ends)):
        return []

    words, buffer, start = [], "", None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if buffer:
                words.append({"w": buffer, "start": round(start, 3), "end": round(prev_end, 3)})
                buffer, start = "", None
            continue
        if not buffer:
            start = s
        buffer += ch
        prev_end = e
    if buffer:
        words.append({"w": buffer, "start": round(start, 3), "end": round(prev_end, 3)})
    return words


def synthesize(text: str, voice_id: str, out_path: str, ffmpeg_path: str = "") -> dict:
    r = httpx.post(
        f"{BASE_URL}/text-to-speech/{voice_id}/with-timestamps",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"text": text, "model_id": MODEL_ID},
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text[:200]}")

    body = r.json()
    audio_b64 = body.get("audio_base64")
    if not audio_b64:
        raise RuntimeError("ElevenLabs returned no audio.")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(base64.b64decode(audio_b64))

    words = _words_from_alignment(body.get("alignment") or {})
    duration = probe_duration(out_path, ffmpeg_path)
    if not duration and words:
        duration = words[-1]["end"]
    return {"path": out_path, "duration": round(duration, 3), "words": words}
