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
    # one finished piece of a multi-item job, handed over the moment it exists
    # rather than at the end — a job that dies halfway keeps what it managed
    item = Signal(object)

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
            if "on_item" in params:
                self._kwargs.setdefault("on_item", self.item.emit)
            self.done.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e) or e.__class__.__name__)


def _must_be_bound(name: str, callback):
    """Qt needs a receiver object to know which thread to deliver a signal to.

    A bound method of a QObject has one. A lambda and a functools.partial do
    not, so Qt calls them where the signal was emitted — on the worker thread —
    and everything they touch in the window is then touched from the wrong
    thread. That looks like "QObject: setParent Cannot set parent, new parent
    is in a different thread" repeated once per widget, and then a hang.

    It is a quiet trap: the code reads fine and works until the callback
    happens to touch the interface. Refusing it here costs one line at the call
    site — whatever the lambda was closing over goes into the job's result
    instead — and saves an evening of looking for it.
    """
    if callback is None or isinstance(getattr(callback, "__self__", None), QObject):
        return
    raise TypeError(
        f"run_async: {name} must be a bound method of a QObject, not "
        f"{type(callback).__name__}. Anything the job needs to say about "
        f"itself belongs in what it returns."
    )


def run_async(parent, fn, on_done, on_failed, *args,
              on_progress=None, on_progress_pct=None, on_item=None,
              **kwargs) -> QThread:
    """Start `fn` on a worker thread. Keeps refs alive on `parent` so the
    thread isn't garbage-collected mid-flight."""
    for name, callback in (("on_done", on_done), ("on_failed", on_failed),
                           ("on_progress", on_progress),
                           ("on_progress_pct", on_progress_pct),
                           ("on_item", on_item)):
        _must_be_bound(name, callback)

    # No parent. A QThread destroyed while its thread is still running takes the
    # process out on the spot — "QThread: Destroyed while thread is still
    # running" and gone — and a thread parented to a window is one closed window
    # away from that. The lists below are what keeps it alive instead.
    thread = QThread()
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
    if on_item is not None:
        task.item.connect(on_item)
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
