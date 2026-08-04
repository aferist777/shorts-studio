"""Speech synthesis — Edge (free, word timings included) and ElevenLabs.

Both backends return the same shape:
    {"path": str, "duration": float, "words": [{"w": str, "start": float, "end": float}]}

The word list is what makes karaoke subtitles free in the render step, so a
backend that cannot produce it is not worth having.
"""

from app.services.tts import edge_backend, eleven_backend

ENGINES = {"edge": "Edge TTS (free)", "elevenlabs": "ElevenLabs"}

# project language -> BCP-47 prefix used to filter the voice list
LOCALE_PREFIX = {
    "Russian": "ru", "English": "en", "Spanish": "es",
    "German": "de", "French": "fr", "Portuguese": "pt",
}

# Edge applies these natively and returns word timings already at the new tempo,
# so faster delivery costs nothing in subtitle accuracy — no ffmpeg atempo needed.
RATES = ["-25%", "-15%", "+0%", "+15%", "+25%", "+35%", "+50%", "+60%"]

# short sample used by the Preview button, per language
SAMPLES = {
    "ru": "Так звучит этот голос. Проверьте темп и интонацию.",
    "en": "This is how the voice sounds. Check the pace and tone.",
    "es": "Así suena esta voz. Comprueba el ritmo y el tono.",
    "de": "So klingt diese Stimme. Prüfe Tempo und Tonfall.",
    "fr": "Voici le son de cette voix. Vérifiez le rythme et le ton.",
    "pt": "É assim que esta voz soa. Verifique o ritmo e o tom.",
}


def sample_text(language: str) -> str:
    return SAMPLES.get(LOCALE_PREFIX.get(language, "en"), SAMPLES["en"])


def list_voices(engine: str, language: str) -> list:
    """-> [{"id", "label", "gender"}], filtered to the project language."""
    prefix = LOCALE_PREFIX.get(language, "en")
    if engine == "elevenlabs":
        return eleven_backend.list_voices()
    return edge_backend.list_voices(prefix)


def synthesize(engine: str, text: str, voice: str, rate: str, out_path: str,
               ffmpeg_path: str = "") -> dict:
    if engine == "elevenlabs":
        return eleven_backend.synthesize(text, voice, out_path, ffmpeg_path)
    return edge_backend.synthesize(text, voice, rate, out_path, ffmpeg_path)
