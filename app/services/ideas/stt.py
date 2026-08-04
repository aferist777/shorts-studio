"""Speech-to-text through OpenRouter's audio endpoint.

This is the primary transcript source. YouTube's automatic captions are not
used at all: on a fifty-minute video about David and Goliath they spelled
"Голиаф" zero times and "Тель-Дан" zero times, which is exactly the material a
script needs. The paid pass costs about eight cents an hour of audio and runs
two hundred times faster than real time.
"""

import subprocess
import sys
from pathlib import Path

import httpx

from app.config import get_key
from app.paths import find_ffmpeg

ENDPOINT = "https://openrouter.ai/api/v1/audio/transcriptions"
DEFAULT_MODEL = "x-ai/grok-stt-1.0"
TIMEOUT = 1800.0

# The endpoint rejects uploads over 25 MB. Splitting the audio would mean
# stitching two timelines back together, so instead the bitrate is chosen to
# make the whole thing fit — one file, one set of timings.
SIZE_LIMIT_MB = 25.0
SIZE_BUDGET_MB = 23.5      # leave room for the container and multipart overhead
# mp3 only encodes a fixed ladder; asking for 13 kbps gets rounded *up* to 16
# and blows the budget, so the rung is chosen here rather than by ffmpeg
MP3_BITRATES = (8, 16, 24, 32, 40, 48)

# a cue ends on punctuation, on a pause, or when it simply runs long — the
# opening minutes of a long file come back with no punctuation at all, so the
# time and gap rules are what actually carry the split there
MAX_CUE_SECONDS = 8.0
GAP_SECONDS = 0.9

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def pick_bitrate(duration_seconds: float) -> int:
    """Highest mp3 rung that still fits the upload budget, in kbps.

    Anything up to about an hour and a quarter keeps the full 48 kbps; longer
    videos trade audio quality for staying in one piece. Speech survives this
    far better than the timings would survive being split and re-joined.
    """
    if duration_seconds <= 0:
        return MP3_BITRATES[-1]
    budget = SIZE_BUDGET_MB * 8 * 1024 / duration_seconds
    affordable = [rung for rung in MP3_BITRATES if rung <= budget]
    return affordable[-1] if affordable else MP3_BITRATES[0]


def pick_sample_rate(kbps: int) -> int:
    """At the bottom of the ladder 8 kHz sounds better than 16 — fewer bands
    to spend the same handful of bits on."""
    return 8000 if kbps <= 16 else 16000


def compress(audio_path: str, out_path: str, duration: float = 0.0,
             ffmpeg_path: str = "", progress=None) -> str:
    """Mono 16 kHz mp3, bitrate scaled so the file clears the upload limit."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("No ffmpeg found. Set its location in Settings.")

    kbps = pick_bitrate(duration)
    rate = pick_sample_rate(kbps)
    if progress:
        progress(f"Re-encoding audio at {kbps} kbps")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", audio_path,
         "-ac", "1", "-ar", str(rate), "-b:a", f"{kbps}k", out_path],
        capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=1800,
    )
    if result.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError("Could not re-encode the audio:\n" + (result.stderr or "")[-400:])

    size_mb = Path(out_path).stat().st_size / 1e6
    if size_mb > SIZE_LIMIT_MB:
        raise RuntimeError(
            f"Even at {kbps} kbps this audio is {size_mb:.0f} MB, over the "
            f"{SIZE_LIMIT_MB:.0f} MB upload limit. The video is too long to "
            "transcribe in one piece."
        )
    return out_path


def cues_from_words(words: list) -> list:
    """Word timings -> [{'start', 'end', 'text'}] split on sentences and pauses."""
    cues, current = [], None
    for word in words:
        text = str(word.get("word", "")).strip()
        if not text:
            continue
        start, end = float(word.get("start", 0)), float(word.get("end", 0))

        if current is None:
            current = {"start": start, "end": end, "parts": [text]}
            continue

        too_long = end - current["start"] > MAX_CUE_SECONDS
        paused = start - current["end"] > GAP_SECONDS
        if too_long or paused:
            cues.append(current)
            current = {"start": start, "end": end, "parts": [text]}
            continue

        current["parts"].append(text)
        current["end"] = end
        if text.endswith((".", "!", "?")):
            cues.append(current)
            current = None

    if current:
        cues.append(current)
    return [{"start": round(c["start"], 2), "end": round(c["end"], 2),
             "text": " ".join(c["parts"])} for c in cues]


def transcribe(audio_path: str, model: str = DEFAULT_MODEL, progress=None) -> dict:
    """-> {'cues', 'seconds', 'cost'}"""
    key = get_key("openrouter")
    if not key:
        raise RuntimeError("No OpenRouter API key. Add one in Settings.")

    size_mb = Path(audio_path).stat().st_size / 1e6
    if progress:
        progress(f"Transcribing {size_mb:.0f} MB")

    response = httpx.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {key}"},
        files={"file": (Path(audio_path).name, Path(audio_path).read_bytes(), "audio/mpeg")},
        data={"model": model, "response_format": "verbose_json",
              "timestamp_granularities[]": "word"},
        timeout=TIMEOUT,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Transcription failed ({response.status_code}): "
                           f"{response.text[:300]}")

    body = response.json()
    words = body.get("words") or []
    if not words:
        raise RuntimeError("The transcription came back without word timings.")

    usage = body.get("usage") or {}
    return {
        "cues": cues_from_words(words),
        "seconds": float(usage.get("seconds") or body.get("duration") or 0),
        "cost": float(usage.get("cost") or 0),
    }
