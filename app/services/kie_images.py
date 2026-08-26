"""Image generation through kie.ai.

createTask, then poll recordInfo until it is done. Two quirks that cost time to
rediscover: references are accepted only as public URLs, so a local file has to
be hosted first, and the result CDN answers a default user agent with a 403.
"""

import base64
import hashlib
import json
import threading
import time
from pathlib import Path

import httpx

from app.config import get_key
from app.paths import DATA_DIR

JOBS = "https://api.kie.ai/api/v1/jobs"
IMGBB = "https://api.imgbb.com/1/upload"
CACHE = DATA_DIR / "imgbb_cache.json"
HOSTED_FOR = 30 * 24 * 3600
TIMEOUT = 90.0
POLL_SECONDS = 3.0
GIVE_UP_AFTER = 420.0


# One entry per model the user picks, not one per direction. kie exposes
# gpt-image-2 as two separate endpoints, but choosing between "with a reference"
# and "without" is not a decision anybody wants to make twice — the app knows
# which it needs from whether a reference was handed to it.
#   key -> (label, text-to-image id, image-to-image id, the field taking a shape)
MODELS = {
    "nano-banana-2": ("Nano Banana 2 — fastest",
                      "nano-banana-2", "nano-banana-2", "aspect_ratio"),
    "gpt-image-2": ("GPT Image 2",
                    "gpt-image-2-text-to-image", "gpt-image-2-image-to-image",
                    "aspect_ratio"),
}
DEFAULT_MODEL = "nano-banana-2"

ASPECTS = ["9:16", "16:9", "1:1", "4:5", "3:2"]
RESOLUTIONS = ["1K", "2K", "4K"]

# What one picture costs, as kie.ai bills it: credits and the dollars they came
# to. Quoted here rather than fetched — it is three numbers per model, and a
# price that silently changed under a running job would be worse than a stale
# one written down.
PRICES = {
    "nano-banana-2": {"1K": (8, 0.04), "2K": (12, 0.06), "4K": (18, 0.09)},
    "gpt-image-2": {"1K": (6, 0.03), "2K": (10, 0.05), "4K": (16, 0.08)},
}


def model_choices() -> list:
    return [(key, spec[0]) for key, spec in MODELS.items()]


def price_of(model_key: str, resolution: str) -> tuple:
    """-> (credits, dollars) for one picture, or (0, 0.0) if unpriced."""
    return PRICES.get(model_key, {}).get(resolution, (0, 0.0))


def generate_to(dest: str, model_key: str, prompt: str, aspect: str = "9:16",
                resolution: str = "1K", reference: str = "",
                reference_url: str = "", label: str = "", progress=None) -> dict:
    """Draw it and put it where it belongs. -> {'path', 'url'}

    The destination travels with the request so the task id can be written down
    against it. A picture asked for and then lost track of is still drawn and
    still charged; this is what makes it findable afterwards.
    """
    url = generate(model_key, prompt, aspect, resolution, reference,
                   reference_url, progress, dest=dest, label=label)
    path = download(url, dest)
    forget_task_for(dest)
    return {"path": path, "url": url}


def forget_task_for(dest: str):
    with _PENDING_LOCK:
        jobs = [j for j in pending() if j.get("dest") != dest]
        _write_pending(jobs)


def generate(model_key: str, prompt: str, aspect: str = "9:16",
             resolution: str = "1K", reference: str = "",
             reference_url: str = "", progress=None, dest: str = "",
             label: str = "") -> str:
    """One picture, with or without something to follow. -> the result URL.

    `reference_url` is for a batch: the sample is hosted once by the caller and
    every picture reuses the link, instead of each racing to upload the same
    file.
    """
    label, t2i, i2i, shape_field = MODELS.get(model_key, MODELS[DEFAULT_MODEL])
    payload = {"prompt": prompt, shape_field: aspect,
               "resolution": resolution, "output_format": "png"}

    link = reference_url
    if not link and reference:
        if progress:
            progress("Hosting the reference")
        link = host(reference)

    if link:
        payload["image_input"] = [link]
        return run(i2i, payload, progress, dest, label)
    return run(t2i, payload, progress, dest, label)


def _headers() -> dict:
    key = get_key("kie")
    if not key:
        raise RuntimeError("No kie.ai API key. Add one in Settings.")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


# ---- hosting a reference ----------------------------------------------------

def host(path: str) -> str:
    """A local file as a public URL, reusing a live upload of the same bytes."""
    key = get_key("imgbb")
    if not key:
        raise RuntimeError("No imgbb key — kie.ai cannot read local files without one.")

    raw = Path(path).read_bytes()
    digest = hashlib.sha1(raw).hexdigest()
    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    hit = cache.get(digest)
    if hit and hit.get("until", 0) > time.time():
        return hit["url"]

    response = httpx.post(IMGBB, timeout=TIMEOUT,
                          data={"key": key, "expiration": str(HOSTED_FOR),
                                "image": base64.b64encode(raw).decode("ascii")})
    if response.status_code >= 400:
        raise RuntimeError(f"imgbb refused the upload ({response.status_code}).")
    url = (response.json().get("data") or {}).get("url")
    if not url:
        raise RuntimeError("imgbb returned no URL.")

    cache[digest] = {"url": url, "until": time.time() + HOSTED_FOR - 3600}
    CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return url


# ---- what is still owed ------------------------------------------------------
# A job lives on kie's side, not ours. If the app goes away between asking for a
# picture and being handed it, the picture is still drawn and still paid for —
# and without the task id written down, nobody can ever collect it. So the id
# goes to disk the moment it exists and is struck off once the file has landed.

PENDING = DATA_DIR / "pending_kie.json"
FORGET_AFTER = 3 * 24 * 3600     # kie will not still be holding it after this
_PENDING_LOCK = threading.Lock()


def pending() -> list:
    if not PENDING.exists():
        return []
    try:
        return json.loads(PENDING.read_text(encoding="utf-8")).get("jobs", [])
    except Exception:
        return []


def _write_pending(jobs: list):
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2),
                       encoding="utf-8")


def remember(task: str, model: str, dest: str, label: str = ""):
    with _PENDING_LOCK:
        jobs = [j for j in pending() if j.get("task") != task]
        jobs.append({"task": task, "model": model, "dest": dest,
                     "label": label, "asked": time.time()})
        _write_pending(jobs)


def forget_task(task: str):
    with _PENDING_LOCK:
        jobs = [j for j in pending() if j.get("task") != task]
        _write_pending(jobs)


def _peek(task: str) -> tuple:
    """One look, no waiting. -> (state, url)"""
    try:
        poll = httpx.get(f"{JOBS}/recordInfo", params={"taskId": task},
                         headers={"Authorization": _headers()["Authorization"]},
                         timeout=TIMEOUT)
        data = poll.json().get("data") or {}
    except Exception:
        return "unknown", ""
    state = data.get("state") or "working"
    if state != "success":
        return state, ""
    urls = json.loads(data.get("resultJson") or "{}").get("resultUrls") or []
    return ("success", urls[0]) if urls else ("fail", "")


def collect(progress=None) -> dict:
    """Pick up what finished while the app was not running.

    -> {'got': [labels], 'waiting': n, 'lost': n}
    """
    jobs = pending()
    if not jobs:
        return {"got": [], "waiting": 0, "lost": 0}

    got, still, lost = [], [], 0
    for job in jobs:
        if time.time() - job.get("asked", 0) > FORGET_AFTER:
            lost += 1
            continue
        if progress:
            progress(f"Asking about {job.get('label') or job['task'][:8]}")
        state, url = _peek(job["task"])
        if state == "success" and url:
            try:
                download(url, job["dest"])
                got.append(job.get("label") or Path(job["dest"]).name)
            except Exception:
                still.append(job)      # drawn but not fetched; try again next time
        elif state in ("fail", "failed"):
            lost += 1
        else:
            still.append(job)
    with _PENDING_LOCK:
        _write_pending(still)
    return {"got": got, "waiting": len(still), "lost": lost}


# ---- generation -------------------------------------------------------------

def run(model: str, payload: dict, progress=None, dest: str = "",
        label: str = "") -> str:
    """createTask then poll. -> the result image URL."""
    if progress:
        progress(f"Sending to {model}")
    response = httpx.post(f"{JOBS}/createTask", json={"model": model, "input": payload},
                          headers=_headers(), timeout=TIMEOUT)
    body = response.json()
    task = (body.get("data") or {}).get("taskId")
    if not task:
        raise RuntimeError(f"kie.ai refused the job: {str(body.get('msg') or body)[:200]}")
    if dest:
        remember(task, model, dest, label)

    started = time.time()
    while time.time() - started < GIVE_UP_AFTER:
        time.sleep(POLL_SECONDS)
        poll = httpx.get(f"{JOBS}/recordInfo", params={"taskId": task},
                         headers={"Authorization": _headers()["Authorization"]},
                         timeout=TIMEOUT)
        data = poll.json().get("data") or {}
        state = data.get("state")
        if progress:
            progress(f"{state or 'working'} · {int(time.time() - started)}s")
        if state == "success":
            urls = json.loads(data.get("resultJson") or "{}").get("resultUrls") or []
            if not urls:
                forget_task(task)
                raise RuntimeError("kie.ai finished but returned no image.")
            return urls[0]
        if state in ("fail", "failed"):
            forget_task(task)
            raise RuntimeError(str(data.get("failMsg") or "generation failed")[:200])
    # left on the books on purpose: it is still being drawn, and the next start
    # of the app will ask after it
    raise TimeoutError("kie.ai is still working after seven minutes — giving up.")


def alive(url: str) -> bool:
    """Is this link still worth handing to the model?

    Asked rather than inferred from a failed job: kie answers a dead reference
    with the same shape of error as a dozen other things, and re-uploading
    eleven megabytes on every misread error is worse than one HEAD request.
    """
    if not url:
        return False
    try:
        # the result CDN 403s a default user agent, same as on download
        response = httpx.head(url, timeout=15.0, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0"})
        return response.status_code < 400
    except Exception:
        return False


def forget(paths: list) -> int:
    """Drop these files from the hosting cache. -> how many were dropped."""
    if not CACHE.exists():
        return 0
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return 0
    gone = 0
    for path in paths:
        try:
            digest = hashlib.sha1(Path(path).read_bytes()).hexdigest()
        except Exception:
            continue
        if cache.pop(digest, None) is not None:
            gone += 1
    if gone:
        CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return gone


def download(url: str, dest: str) -> str:
    # the result CDN 403s a default user agent
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    response = httpx.get(url, timeout=TIMEOUT, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
    if response.status_code >= 400:
        raise RuntimeError(f"Could not fetch the result ({response.status_code}).")
    Path(dest).write_bytes(response.content)
    return dest
