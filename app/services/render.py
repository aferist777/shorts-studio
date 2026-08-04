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
           progress=None, progress_pct=None) -> dict:
    """`scenes` are dicts with clip_path, audio_path, duration and words."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("No ffmpeg found. Set its location in Settings.")

    missing_clip = [i + 1 for i, s in enumerate(scenes) if not s.get("clip_path")]
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

    # ---- pass 1: one normalised silent segment per scene --------------------
    segments = []
    for i, scene in enumerate(scenes):
        name = f"seg_{i + 1:02d}.mp4"
        if progress:
            progress(f"Fitting clip {i + 1} of {len(scenes)}")
        _run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(Path(scene["clip_path"]).resolve()),
            "-t", f"{float(scene['duration']):.3f}",
            "-vf", FIT, "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-g", str(FPS * 2),
            name,
        ], cwd=str(work))
        segments.append(name)
        if progress_pct:
            progress_pct(int(55 * (i + 1) / len(scenes)))

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
