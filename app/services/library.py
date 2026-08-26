"""Cross-project view: what is finished, what is ready to render, what is still a draft.

The per-project steps only ever see one project; this is the layer that answers
"what have I actually made" and drives batch rendering.
"""

import hashlib
from datetime import datetime
from pathlib import Path

from app.paths import CACHE_DIR, project_dir
from app.services import render
from app.services.ffmpeg_tools import extract_thumbnail

POSTER_DIR = CACHE_DIR / "posters"

DRAFT, READY, RENDERED = "draft", "ready", "rendered"
STATE_LABELS = {DRAFT: "Draft", READY: "Ready", RENDERED: "Rendered"}


def render_path(project_id: str) -> Path:
    return project_dir(project_id) / "render.mp4"


def poster_for(video_path: str) -> str:
    """First frame of a render, cached and invalidated when the file changes."""
    if not video_path or not Path(video_path).exists():
        return ""
    key = hashlib.sha1(str(video_path).encode("utf-8")).hexdigest()[:16]
    poster = POSTER_DIR / f"{key}.jpg"
    stamp = Path(video_path).stat().st_mtime
    if poster.exists() and poster.stat().st_mtime >= stamp:
        return str(poster)
    return extract_thumbnail(video_path, str(poster), at=0.5, height=640)


# the four things that have to happen to a project, each worth the same. Four
# equal steps mean the only possible answers are 0, 25, 50, 75 and 100 — which
# is what lets the project list filter on named percentages instead of ranges.
STAGES = [0, 25, 50, 75, 100]


def progress_pct(project) -> int:
    """How far along a project is, as one number."""
    scenes = project.scenes
    if not scenes:
        return 0
    done = 1
    if all(s.audio_path for s in scenes):
        done += 1
    if all(s.shots for s in scenes):
        done += 1
    if render_path(project.id).exists():
        done += 1
    return done * 25


def project_state(project) -> str:
    if render_path(project.id).exists():
        return RENDERED
    scenes = project.scenes
    if scenes and all(s.audio_path and s.shots for s in scenes):
        return READY
    return DRAFT


def summarize(project) -> dict:
    """One row's worth of facts about a project."""
    video = render_path(project.id)
    has_render = video.exists()
    return {
        "id": project.id,
        "title": project.title or "Untitled",
        "state": project_state(project),
        "scenes": len(project.scenes),
        "duration": sum(s.duration for s in project.scenes),
        "video": str(video) if has_render else "",
        "size_mb": video.stat().st_size / 1e6 if has_render else 0.0,
        "made_at": (datetime.fromtimestamp(video.stat().st_mtime).strftime("%d %b, %H:%M")
                    if has_render else ""),
        "poster": poster_for(str(video)) if has_render else "",
    }


def render_batch(jobs: list, progress=None, progress_pct=None) -> list:
    """Render several projects one after another.

    Sequential on purpose: two libx264 encodes in parallel finish no sooner and
    make the machine unusable while they run.
    """
    results = []
    total = len(jobs) or 1

    for i, job in enumerate(jobs):
        if progress:
            progress(f"{job['title']} · {i + 1} of {total}")

        def inner(pct, index=i):
            if progress_pct:
                progress_pct(int((index * 100 + pct) / total))

        try:
            result = render.render(
                job["scenes"], job["out"], job["work"], job["style"],
                job.get("bgm_path", ""), job.get("bgm_volume", 0.12),
                job.get("ffmpeg_path", ""),
                progress=None, progress_pct=inner,
            )
            results.append({"id": job["id"], "title": job["title"], "ok": True,
                            "path": result["path"], "duration": result["duration"]})
        except Exception as e:
            # one bad project must not abandon the rest of the queue
            results.append({"id": job["id"], "title": job["title"], "ok": False,
                            "error": str(e)})

    if progress_pct:
        progress_pct(100)
    return results
