"""Source video: fetched once, cut into per-project fragments, then dropped.

The full download is a working file. What survives is one slice per project,
inside that project's own folder, so deleting the project takes its footage
with it and nothing is left orphaned or shared.

Cutting copies the streams instead of re-encoding. Measured on a 1080p source
with keyframes every four seconds: 0.3 s against 28.7 s, and the fragment came
out 0.7 s long. The overshoot is always lead-in at the front — never missing
material — and is bounded by the source's keyframe spacing. Harmless for
fragments that exist to be mined for stills; if frame-accuracy ever matters,
the same call re-encodes at roughly a hundred times the cost.
"""

import subprocess
import sys
from pathlib import Path

from app.paths import MEDIA_DIR, find_ffmpeg, project_dir
from app.services.ideas import youtube

# 1080p is the ceiling: enough to lift a painting or a map out of a frame, and
# a quarter the weight of the same video in mp4 at that height
SOURCE_FORMAT = ("bestvideo[height<=1080]+bestaudio/best[height<=1080]/best")

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def source_path(video_id: str) -> str:
    """The working copy on disk, whatever container it came in, or ""."""
    hit = sorted(MEDIA_DIR.glob(f"{video_id}.*"))
    return str(hit[0]) if hit else ""


def download_source(url: str, video_id: str, cookies: str = "", progress=None) -> str:
    """Fetch the whole video once. Returns the path it landed at."""
    existing = source_path(video_id)
    if existing:
        if progress:
            progress("Using the video already on disk")
        return existing

    import yt_dlp

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def hook(status):
        if not progress:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            if not total:
                progress(f"Downloading · {done / 1e6:.0f} MB so far")
                return
            # what is left is the number worth watching — a percentage tells you
            # nothing about whether to wait or go and do something else
            speed = status.get("speed") or 0
            left = f" · {(total - done) / max(speed, 1):.0f}s left" if speed else ""
            progress(f"Downloading · {done / 1e6:.0f} of {total / 1e6:.0f} MB · "
                     f"{(total - done) / 1e6:.0f} MB to go{left}")
        elif status.get("status") == "finished":
            progress("Joining video and audio")

    opts = {**youtube._options(cookies), "skip_download": False,
            "format": SOURCE_FORMAT,
            "outtmpl": str(MEDIA_DIR / "%(id)s.%(ext)s"),
            "progress_hooks": [hook]}

    def call():
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        return source_path(video_id)

    path = youtube._with_retries(call, progress)
    if not path:
        raise RuntimeError("The download finished but left no file behind.")
    return path


def extract_audio(source: str, out_path: str, ffmpeg_path: str = "",
                  progress=None) -> str:
    """Pull the sound out of a local video — no second trip to YouTube."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("No ffmpeg found. Set its location in Settings.")
    if progress:
        progress("Taking the audio out of the video")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", source,
         "-vn", "-acodec", "copy", out_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW, timeout=1800,
    )
    if result.returncode != 0 or not Path(out_path).exists():
        # stream copy fails when the container cannot hold that codec; re-encode
        result = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", source,
             "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", out_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW, timeout=1800,
        )
        if result.returncode != 0 or not Path(out_path).exists():
            raise RuntimeError("Could not take the audio out:\n"
                               + (result.stderr or "")[-400:])
    return out_path


def cut(source: str, start: float, end: float, out_path: str,
        ffmpeg_path: str = "") -> str:
    """One slice, stream-copied. `-ss` before `-i` so the seek is instant."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("No ffmpeg found. Set its location in Settings.")

    duration = max(0.0, float(end) - float(start))
    if duration <= 0:
        raise RuntimeError("That topic has no length to cut.")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{float(start):.3f}", "-i", source, "-t", f"{duration:.3f}",
         "-c", "copy", "-avoid_negative_ts", "make_zero", out_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW, timeout=1800,
    )
    if result.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError("Could not cut the fragment:\n"
                           + (result.stderr or "")[-400:])
    return out_path


def cut_for_projects(source: str, projects: list, ffmpeg_path: str = "",
                     progress=None) -> list:
    """Give every project its own slice. -> [(project, path_or_empty, error)]"""
    ext = Path(source).suffix or ".mp4"
    results = []
    for i, project in enumerate(projects, 1):
        if progress:
            progress(f"Cutting fragment {i}/{len(projects)}")
        target = project_dir(project.id) / f"fragment{ext}"
        try:
            path = cut(source, project.source_start, project.source_end,
                       str(target), ffmpeg_path)
            results.append((project, path, ""))
        except Exception as e:
            results.append((project, "", str(e)[:200]))
    return results


def drop_source(video_id: str):
    """The working copy has done its job once every fragment is cut."""
    for leftover in MEDIA_DIR.glob(f"{video_id}.*"):
        leftover.unlink(missing_ok=True)


def build(projects: list, settings: dict, local_file: str = "",
          progress=None) -> list:
    """Get the source — downloaded, or handed over — and slice it up.

    -> [(project, path_or_empty, error)]
    """
    video_id = next((p.source_video_id for p in projects if p.source_video_id), "")
    url = next((p.source_url for p in projects if p.source_url), "")

    if not local_file and video_id:
        # a video analysed off the disk keeps its path; no reason to ask twice
        from app.services import ideas
        saved = ideas.get_entry(video_id).get("local_path", "")
        if saved and Path(saved).exists():
            local_file = saved

    if local_file:
        source = local_file
    elif url:
        source = download_source(url, video_id, settings.get("cookies_path", ""),
                                 progress)
    else:
        raise RuntimeError("These projects carry no video link to fetch.")

    try:
        return cut_for_projects(source, projects, settings.get("ffmpeg_path", ""),
                                progress)
    finally:
        # a file the user picked is theirs and stays put; our own copy does not
        if not local_file and video_id:
            drop_source(video_id)
