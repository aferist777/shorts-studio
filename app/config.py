"""API keys (OS credential store) + plain app settings (JSON).

Keys never touch repo files. Model Manager is checked as a fallback so keys
already entered there don't have to be typed again.
"""

import json
import os
from pathlib import Path

from app.paths import DATA_DIR

try:
    import keyring
except Exception:  # pragma: no cover
    keyring = None

KEYRING_SERVICE = "ShortsStudio"
FALLBACK_SERVICES = ["ModelManager"]

# providers the Settings dialog exposes
PROVIDERS = [
    ("anthropic", "Anthropic — Claude (script writing)"),
    ("openrouter", "OpenRouter — any model, one key"),
    ("openai", "OpenAI"),
    ("pexels", "Pexels — stock footage"),
    ("pixabay", "Pixabay — stock footage"),
    ("elevenlabs", "ElevenLabs — premium voices"),
]

SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULTS = {
    "llm_provider": "anthropic",
    "llm_model": "claude-opus-5",
    "llm_effort": "medium",
    "language": "Russian",
    "paragraphs": 5,
    "tone": "Conversational",
    "tts_engine": "edge",
    "tts_voice": "ru-RU-DmitryNeural",
    "tts_rate": "+0%",
    "footage_sources": ["pexels", "pixabay"],
    "local_folder": "",
    "sub_font": "Arial",
    "sub_size": 78,
    "sub_highlight": "#8B7CF6",
    "sub_words_per_line": 4,
    "sub_uppercase": True,
    "sub_margin_v": 320,
    "bgm_path": "",
    "bgm_volume": 12,
    "stt_model": "x-ai/grok-stt-1.0",
    "cookies_path": "",
    "ffmpeg_path": "",
}


def get_key(provider: str) -> str:
    if keyring is not None:
        for service in [KEYRING_SERVICE, *FALLBACK_SERVICES]:
            try:
                v = keyring.get_password(service, f"apikey:{provider}")
                if v:
                    return v
            except Exception:
                pass
    return (
        os.environ.get(f"{provider.upper()}_API_KEY", "")
        or os.environ.get(f"{provider.upper()}_KEY", "")
    )


def set_key(provider: str, value: str):
    if keyring is None:
        return
    try:
        keyring.set_password(KEYRING_SERVICE, f"apikey:{provider}", value or "")
    except Exception:
        pass


# first-run fallbacks, tried in order — whichever provider already has a key wins
_FIRST_RUN_ORDER = [
    ("anthropic", "claude-opus-5"),
    ("openrouter", "google/gemini-3.5-flash"),
    ("openai", "gpt-5.5"),
]


def load_settings() -> dict:
    s = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
            return s
        except Exception:
            pass
    for provider, model in _FIRST_RUN_ORDER:
        if get_key(provider):
            s["llm_provider"], s["llm_model"] = provider, model
            break
    return s


def save_settings(s: dict):
    SETTINGS_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
