"""Assemble the final 1080×1920 video with direct ffmpeg calls.

Three passes: normalise each clip to one silent segment, then mux the concatenated
video against the concatenated narration while libass burns the subtitles in.
Going through explicit segments is what keeps the concat demuxer happy — it
refuses inputs whose codec, size or frame rate differ.
"""

import re
import subprocess
import sys
from pathlib import Path

from app.paths import find_ffmpeg
from app.services import subtitles

WIDTH, HEIGHT, FPS = 1080, 1920, 30
_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# scale up, then centre-crop — this is what lets landscape stock footage be used
FIT = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
       f"crop={WIDTH}:{HEIGHT},fps={FPS},setsar=1")

STILLS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
# A frame held motionless for three seconds reads as a stall rather than a
# choice. 12% of travel over its whole turn is below the threshold where
# anyone notices the movement itself.
KEN_BURNS_ZOOM = 1.12

# what a still can do while it is on screen; the ids are what settings store
MOTIONS = [
    ("none", "Hold still"),
    ("zoom_in", "Push in"),
    ("zoom_out", "Pull out"),
    ("pan_left", "Pan left"),
    ("pan_right", "Pan right"),
    ("pan_up", "Pan up"),
    ("pan_down", "Pan down"),
    ("varied", "Vary it"),
]
_CYCLE = ["zoom_in", "pan_right", "zoom_out", "pan_left", "zoom_in", "pan_up"]

# A true cross-dissolve needs neighbouring shots to overlap, which shortens the
# timeline and pulls the picture away from the voice — fixable, but it also
# wants every segment in one filter graph, and a nineteen-scene project has
# dozens. A dip happens inside a segment that already exists: nothing moves,
# nothing costs more.
TRANSITIONS = [
    ("none", "Straight cut"),
    ("black", "Dip to black"),
    ("white", "Dip to white"),
]


def _is_still(path: str) -> bool:
    return Path(path).suffix.lower() in STILLS


def _motion_for(motion: str, index: int) -> str:
    if motion == "varied":
        return _CYCLE[index % len(_CYCLE)]
    return motion or "zoom_in"


def _still_filter(seconds: float, motion: str = "zoom_in", index: int = 0) -> str:
    """How a saved frame behaves for the seconds it is on screen."""
    frames = max(2, int(round(seconds * FPS)))
    kind = _motion_for(motion, index)
    # the input is padded well past output size first, so there is room to move
    # inside it without ever showing an edge
    base = (f"scale={WIDTH * 2}:{HEIGHT * 2}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH * 2}:{HEIGHT * 2}")

    if kind == "none":
        return f"{base},scale={WIDTH}:{HEIGHT},fps={FPS},setsar=1"

    step = (KEN_BURNS_ZOOM - 1.0) / frames
    if kind == "zoom_in":
        z = f"min(zoom+{step:.6f},{KEN_BURNS_ZOOM})"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif kind == "zoom_out":
        # zoompan has no way to start zoomed in, so the expression counts down
        z = f"max({KEN_BURNS_ZOOM}-on*{step:.6f},1.0)"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    else:
        # a pan holds a constant crop and walks it across the padded frame
        z = f"{KEN_BURNS_ZOOM}"
        travel = f"(iw-iw/zoom)"
        travel_y = f"(ih-ih/zoom)"
        moves = {
            "pan_left": (f"{travel}*(1-on/{frames})", "ih/2-(ih/zoom/2)"),
            "pan_right": (f"{travel}*on/{frames}", "ih/2-(ih/zoom/2)"),
            "pan_up": ("iw/2-(iw/zoom/2)", f"{travel_y}*(1-on/{frames})"),
            "pan_down": ("iw/2-(iw/zoom/2)", f"{travel_y}*on/{frames}"),
        }
        x, y = moves.get(kind, ("iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"))

    return (f"{base},zoompan=z='{z}':d={frames}:x='{x}':y='{y}'"
            f":s={WIDTH}x{HEIGHT}:fps={FPS},setsar=1")


def _dip(seconds: float, kind: str, length: float) -> str:
    """Fade in and out of a shot, so cuts land softly."""
    if kind not in ("black", "white") or length <= 0:
        return ""
    # never eat more than a third of a shot at each end, or a short piece is
    # nothing but the fade
    span = min(length, seconds / 3)
    colour = ":c=white" if kind == "white" else ""
    return (f",fade=t=in:st=0:d={span:.3f}{colour}"
            f",fade=t=out:st={max(0.0, seconds - span):.3f}:d={span:.3f}{colour}")


def shots_of(scene: dict) -> list:
    """Every visual a scene shows, in order. -> [{'path', 'duration'}]

    A scene used to hold one clip stretched over the whole line; it now holds a
    list that shares the same seconds between them. Projects written before
    that still arrive with a single `clip_path`, and are read as a list of one.
    """
    visuals = scene.get("visuals") or []
    length = float(scene.get("duration") or 0)
    kept = [v for v in visuals if v.get("path")]
    if not kept:
        return [{"path": scene.get("clip_path", ""), "duration": length}]

    # trust the scene's own length over the stored shares: re-voicing a line
    # changes the total and the parts have to follow it, not the other way round
    each = length / len(kept)
    return [{"path": v["path"], "duration": each} for v in kept]


def _run(args: list, cwd: str, total: float = 0.0, on_pct=None,
         base: int = 0, span: int = 0) -> None:
    process = subprocess.Popen(
        args, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
    )
    tail = []
    for line in process.stderr:
        tail.append(line)
        del tail[:-25]
        if not (on_pct and total):
            continue
        match = _TIME_RE.search(line)
        if match:
            h, m, s = match.groups()
            done = int(h) * 3600 + int(m) * 60 + float(s)
            on_pct(base + int(span * min(1.0, done / total)))
    process.wait()
    if process.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + "".join(tail[-12:]).strip())


def _quote_concat(name: str) -> str:
    return f"file '{name}'"


def render(scenes: list, out_path: str, work_dir: str, style: dict,
           bgm_path: str = "", bgm_volume: float = 0.12, ffmpeg_path: str = "",
           motion: str = "zoom_in", transition: str = "none",
           transition_len: float = 0.25,
           progress=None, progress_pct=None) -> dict:
    """`scenes` are dicts with visuals, audio_path, duration and words.

    `motion` is how a still behaves on screen and `transition` how each shot
    enters and leaves — both apply to every shot in the video, which is what
    keeps a project looking like one piece.
    """
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("No ffmpeg found. Set its location in Settings.")

    missing_clip = [i + 1 for i, s in enumerate(scenes)
                    if not any(v.get("path") for v in shots_of(s))]
    missing_audio = [i + 1 for i, s in enumerate(scenes) if not s.get("audio_path")]
    if missing_clip:
        raise RuntimeError(f"No footage on scene(s): {', '.join(map(str, missing_clip))}")
    if missing_audio:
        raise RuntimeError(f"No voice-over on scene(s): {', '.join(map(str, missing_audio))}")

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    total = sum(float(s["duration"]) for s in scenes) or 1.0

    if progress:
        progress("Writing subtitles")
    (work / "subs.ass").write_text(subtitles.build_ass(scenes, style), encoding="utf-8")

    # ---- pass 1: one normalised silent segment per shot ---------------------
    # A scene can hold several shots taking turns, so the segment list is
    # longer than the scene list. Their durations still add up to the scene's
    # own length, which is what keeps picture and narration in step.
    plan = [(i, shot) for i, scene in enumerate(scenes) for shot in shots_of(scene)]
    segments = []
    for n, (scene_index, shot) in enumerate(plan):
        name = f"seg_{n + 1:03d}.mp4"
        seconds = float(shot["duration"])
        source = str(Path(shot["path"]).resolve())
        if progress:
            progress(f"Fitting shot {n + 1} of {len(plan)} "
                     f"(scene {scene_index + 1})")

        if _is_still(source):
            head = ["-loop", "1", "-i", source]
            chain = _still_filter(seconds, motion, n)
        else:
            # a clip shorter than its slot repeats rather than freezing
            head = ["-stream_loop", "-1", "-i", source]
            chain = FIT
        chain += _dip(seconds, transition, transition_len)

        _run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            *head, "-t", f"{seconds:.3f}", "-vf", chain, "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-g", str(FPS * 2),
            name,
        ], cwd=str(work))
        segments.append(name)
        if progress_pct:
            progress_pct(int(55 * (n + 1) / len(plan)))

    (work / "video.txt").write_text(
        "\n".join(_quote_concat(n) for n in segments) + "\n", encoding="utf-8")
    (work / "audio.txt").write_text(
        "\n".join(_quote_concat(str(Path(s["audio_path"]).resolve()).replace("\\", "/"))
                  for s in scenes) + "\n", encoding="utf-8")

    # ---- pass 2: burn subtitles, attach narration, mix music ----------------
    if progress:
        progress("Burning subtitles and mixing audio")

    args = [ffmpeg, "-y", "-hide_banner",
            "-f", "concat", "-safe", "0", "-i", "video.txt",
            "-f", "concat", "-safe", "0", "-i", "audio.txt"]

    # the ass filter's path parsing chokes on "C:\..." — cwd is work_dir, so a
    # bare filename sidesteps the escaping entirely
    chain = "[0:v]ass=subs.ass[v]"
    if bgm_path and Path(bgm_path).exists():
        args += ["-stream_loop", "-1", "-i", str(Path(bgm_path).resolve())]
        # normalize=0 or amix halves the narration to make room for the music
        chain += (f";[2:a]volume={bgm_volume:.3f}[bg]"
                  f";[1:a][bg]amix=inputs=2:duration=first:normalize=0[a]")
        audio_map = "[a]"
    else:
        audio_map = "1:a"

    args += ["-filter_complex", chain, "-map", "[v]", "-map", audio_map,
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-r", str(FPS),
             # Edge TTS lands at 24 kHz mono; lift it to what platforms expect
             "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
             "-movflags", "+faststart",
             "-shortest", str(Path(out_path).resolve())]

    _run(args, cwd=str(work), total=total, on_pct=progress_pct, base=55, span=45)

    if progress_pct:
        progress_pct(100)
    return {
        "path": str(Path(out_path).resolve()),
        "duration": total,
        "scenes": len(scenes),
        "words": subtitles.total_words(scenes),
    }
