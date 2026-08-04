"""Run a blocking callable off the GUI thread.

Every generation step goes through this so the window never freezes and the
progress/lock state has something to hang off.
"""

import inspect
import traceback

from PySide6.QtCore import QObject, QThread, Signal

# every thread still in flight, so shutdown can wait them out
_LIVE = []


class Task(QObject):
    done = Signal(object)      # result
    failed = Signal(str)       # message
    progress = Signal(str)     # step label, for multi-item jobs
    progress_pct = Signal(int)  # 0-100, for jobs that can measure themselves

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            # a job that wants to narrate its steps declares these parameters
            params = inspect.signature(self._fn).parameters
            if "progress" in params:
                self._kwargs.setdefault("progress", self.progress.emit)
            if "progress_pct" in params:
                self._kwargs.setdefault("progress_pct", self.progress_pct.emit)
            self.done.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e) or e.__class__.__name__)


def run_async(parent, fn, on_done, on_failed, *args,
              on_progress=None, on_progress_pct=None, **kwargs) -> QThread:
    """Start `fn` on a worker thread. Keeps refs alive on `parent` so the
    thread isn't garbage-collected mid-flight."""
    thread = QThread(parent)
    task = Task(fn, *args, **kwargs)
    task.moveToThread(thread)
    # signal connections do not own the task; without this ref Python collects it
    # the moment run_async returns and the job silently never runs
    thread._task = task

    thread.started.connect(task.run)
    task.done.connect(on_done)
    task.failed.connect(on_failed)
    if on_progress is not None:
        task.progress.connect(on_progress)
    if on_progress_pct is not None:
        task.progress_pct.connect(on_progress_pct)
    task.done.connect(thread.quit)
    task.failed.connect(thread.quit)
    thread.finished.connect(task.deleteLater)
    thread.finished.connect(thread.deleteLater)

    if not hasattr(parent, "_live_threads"):
        parent._live_threads = []
    parent._live_threads.append(thread)
    _LIVE.append(thread)

    def _forget():
        for bucket in (parent._live_threads, _LIVE):
            if thread in bucket:
                bucket.remove(thread)

    thread.finished.connect(_forget)
    thread.start()
    return thread


def shutdown_all(timeout_ms: int = 8000):
    """Let in-flight jobs finish before the process goes away.

    A QThread destroyed while still running aborts the process, so quitting
    mid-generation used to take the whole app down with it.
    """
    for thread in list(_LIVE):
        try:
            if thread.isRunning():
                thread.quit()
                thread.wait(timeout_ms)
        except RuntimeError:
            pass  # already deleted on the C++ side
    _LIVE.clear()
