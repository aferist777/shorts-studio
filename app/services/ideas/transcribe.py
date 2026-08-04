"""Whisper fallback for videos that ship no subtitles.

Never runs on its own — the dialog asks first, because the first run downloads
a model and the transcription itself takes minutes, not seconds.
"""

from pathlib import Path

from app.paths import CACHE_DIR

MODEL_DIR = CACHE_DIR / "whisper"
MODEL_SIZES = ["tiny", "base", "small", "medium"]


def transcribe(audio_path: str, model_size: str = "small", language: str = "",
               duration: float = 0.0, progress=None) -> list:
    """-> [{'start', 'end', 'text'}], the same shape subtitles come back in."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "The `faster-whisper` package is missing — run: pip install faster-whisper"
        ) from e

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(f"Loading the {model_size} model")

    # int8 on CPU is the only combination that finishes in reasonable time here
    model = WhisperModel(model_size, device="cpu", compute_type="int8",
                         download_root=str(MODEL_DIR))

    segments, info = model.transcribe(
        audio_path, language=language or None, vad_filter=True, beam_size=1)
    total = duration or getattr(info, "duration", 0) or 0

    cues = []
    for segment in segments:   # this generator is what actually drives the work
        text = " ".join(segment.text.split())
        if text:
            cues.append({"start": round(segment.start, 2),
                         "end": round(segment.end, 2), "text": text})
        if progress and total:
            progress(f"Transcribing · {min(100, int(segment.end * 100 / total))}%")

    if not cues:
        raise RuntimeError("Whisper produced nothing — the audio may be silent.")
    return cues


def audio_cache_dir() -> Path:
    path = CACHE_DIR / "audio"
    path.mkdir(parents=True, exist_ok=True)
    return path
