"""Karaoke subtitles as an ASS file, built from the per-word TTS timings.

One dialogue event per word: the whole line stays on screen and only the active
word changes colour. That is what makes the result look like a modern short
rather than a caption track.
"""

from app.models_data import Scene

DEFAULT_STYLE = {
    "font": "Arial",
    "size": 78,
    "primary": "#FFFFFF",
    "highlight": "#8B7CF6",
    "outline": 5,
    "margin_v": 320,
    "words_per_line": 4,
    "uppercase": True,
}

# a pause longer than this starts a new subtitle line even mid-chunk
LINE_BREAK_GAP = 0.7
# four long Russian words overflow 1080px at the default size; break on width too
MAX_LINE_CHARS = 24


def _ass_colour(hex_rgb: str) -> str:
    """#RRGGBB -> &HAABBGGRR (ASS stores blue first, alpha 00 = opaque)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "").replace("}", "")


def _chunk(words: list, per_line: int, max_chars: int = MAX_LINE_CHARS) -> list:
    """Split one scene's words into subtitle lines.

    Breaks on word count, on a long pause, and on rendered width — the last one
    matters because `words_per_line` alone lets a run of long words overflow the
    frame and get clipped at both edges.
    """
    lines, current = [], []
    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            width = sum(len(w["w"]) + 1 for w in current) + len(word["w"])
            if len(current) >= per_line or gap > LINE_BREAK_GAP or width > max_chars:
                lines.append(current)
                current = []
        current.append(word)
    if current:
        lines.append(current)
    return lines


def build_ass(scenes: list, style: dict = None) -> str:
    """`scenes` are Scene objects (or dicts) carrying `words` and `duration`."""
    s = {**DEFAULT_STYLE, **(style or {})}
    primary = _ass_colour(s["primary"])
    highlight = _ass_colour(s["highlight"])

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{s['font']},{s['size']},{primary},{primary},&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,{s['outline']},2,2,70,70,{s['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    offset = 0.0
    for scene in scenes:
        words = scene["words"] if isinstance(scene, dict) else scene.words
        duration = scene["duration"] if isinstance(scene, dict) else scene.duration

        for line in _chunk([w for w in words if w.get("w", "").strip()], s["words_per_line"]):
            for i, word in enumerate(line):
                start = offset + word["start"]
                # run each word up to the next one so the line never blinks
                end = offset + (line[i + 1]["start"] if i + 1 < len(line) else word["end"])
                if end <= start:
                    continue
                parts = []
                for j, other in enumerate(line):
                    text = _escape(other["w"])
                    if s["uppercase"]:
                        text = text.upper()
                    colour = highlight if j == i else primary
                    parts.append(f"{{\\c{colour}&}}{text}")
                events.append(
                    f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Main,,0,0,0,,{' '.join(parts)}"
                )
        offset += duration

    return header + "\n".join(events) + "\n"


def total_words(scenes: list) -> int:
    return sum(len(s.words if isinstance(s, Scene) else s.get("words", [])) for s in scenes)
