"""Breaking a project's fragment into usable pieces.

The fragment arrives as one continuous slice of somebody else's edit. This
window finds the seams already in it, puts a marker on each, and then gets out
of the way: the markers are draggable because a detector that is right most of
the time still needs a human for the rest.

There is no filmstrip under the timeline. A strip of thumbnails is a poor way
to see one exact frame, and the preview above already shows video — so dragging
a marker scrubs the preview to that moment instead. The player does the seeking,
which costs nothing and keeps up with the mouse.
"""

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from app.paths import project_dir
from app.services import cutter, thumbs
from app.services.ideas import fragments, stt
from app.services.worker import run_async

TRACK_H = 34
RULER_H = 20
GRAB_PX = 6                 # how close the cursor counts as "on" a marker
SNAP_PX = 7                 # and how close it re-attaches to a detected seam
ZOOM_MIN, ZOOM_MAX = 1, 20


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


class Timeline(QWidget):
    selectionChanged = Signal(int)
    markersMoved = Signal()
    scrubbed = Signal(float)     # a marker is being dragged over this second

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(TRACK_H + RULER_H)
        self.setMouseTracking(True)
        self.duration = 0.0
        self.marks = []
        self.detected = []
        self._drag = -1
        self.chosen = -1

    def load(self, duration: float, cuts: list):
        self.duration = max(0.001, duration)
        self.detected = list(cuts)
        self.marks = list(cuts)
        self.chosen = -1
        self.update()

    def bounds(self) -> list:
        return cutter.segments(self.marks, self.duration)

    # ---- geometry -----------------------------------------------------------

    def _x(self, seconds: float) -> float:
        # the window is on screen while the analysis runs, and every repaint in
        # that time arrives with no duration yet
        return seconds / max(self.duration, 0.001) * self.width()

    def _t(self, x: float) -> float:
        return max(0.0, min(self.duration, x / max(1, self.width()) * self.duration))

    def _tick_step(self) -> int:
        """Seconds between ruler labels, so they never crowd into each other."""
        for step in (1, 2, 5, 10, 15, 30, 60, 120, 300):
            if self._x(step) >= 64:
                return step
        return 600

    # ---- painting -----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#131318"))
        if not self.duration or self.duration <= 0.002:
            painter.setPen(QColor("#8b8899"))
            painter.drawText(self.rect(), Qt.AlignCenter, "reading the fragment…")
            return

        painter.fillRect(QRectF(0, RULER_H, self.width(), TRACK_H).toRect(),
                         QColor("#1b1b22"))

        segments = self.bounds()
        for i, (start, end) in enumerate(segments):
            left, right = self._x(start), self._x(end)
            shade = QColor(139, 124, 246, 90) if i == self.chosen else QColor("#23232c")
            painter.fillRect(QRectF(left + 1, RULER_H + 1, max(1.0, right - left - 2),
                                    TRACK_H - 2).toRect(), shade)

        painter.setPen(QColor("#8b8899"))
        step = self._tick_step()
        for seconds in range(0, int(self.duration) + 1, step):
            x = int(self._x(seconds))
            painter.drawLine(x, RULER_H - 6, x, RULER_H)
            painter.drawText(x + 3, RULER_H - 8, _clock(seconds))

        for mark in self.marks:
            x = int(self._x(mark))
            painter.setPen(QColor("#f0eef5"))
            painter.drawLine(x, 0, x, RULER_H + TRACK_H)
            painter.fillRect(x - 3, 0, 7, 8, QColor("#8b7cf6"))

    # ---- mouse --------------------------------------------------------------

    def _near(self, x: float) -> int:
        for i, mark in enumerate(self.marks):
            if abs(self._x(mark) - x) <= GRAB_PX:
                return i
        return -1

    def mousePressEvent(self, event):
        x = event.position().x()
        self._drag = self._near(x)
        if self._drag >= 0:
            self.scrubbed.emit(self.marks[self._drag])
            return
        at = self._t(x)
        for i, (start, end) in enumerate(self.bounds()):
            if start <= at <= end:
                self.chosen = i
                self.selectionChanged.emit(i)
                break
        self.update()

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self._drag < 0:
            self.setCursor(Qt.SizeHorCursor if self._near(x) >= 0 else Qt.ArrowCursor)
            return
        # dragging near where the detector found a seam re-attaches to it, so
        # landing exactly on a real cut is easy and landing anywhere else stays
        # possible
        at = self._t(x)
        for seam in self.detected:
            if abs(self._x(seam) - x) <= SNAP_PX:
                at = seam
                break
        self.marks[self._drag] = round(at, 2)
        self.marks.sort()
        self.chosen = -1
        self.scrubbed.emit(at)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag >= 0:
            self._drag = -1
            self.markersMoved.emit()
            self.selectionChanged.emit(-1)

    def mouseDoubleClickEvent(self, event):
        at = round(self._t(event.position().x()), 2)
        if all(abs(at - m) > 0.2 for m in self.marks):
            self.marks.append(at)
            self.marks.sort()
            self.chosen = -1
            self.markersMoved.emit()
            self.update()


class ShelfCard(QFrame):
    """One kept piece, waiting to be used somewhere."""

    dropRequested = Signal(str)

    def __init__(self, item: dict):
        super().__init__()
        self.setObjectName("SceneCard")
        self.path = item["path"]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(8)

        picture = QLabel()
        picture.setFixedSize(96, 54)
        picture.setAlignment(Qt.AlignCenter)
        pix = QPixmap(thumbs.small(item.get("thumb") or ""))
        if not pix.isNull():
            picture.setPixmap(pix.scaled(96, 54, Qt.KeepAspectRatioByExpanding,
                                         Qt.SmoothTransformation))
        else:
            picture.setText("still" if item["kind"] == "still" else "clip")
        lay.addWidget(picture)

        text = QVBoxLayout()
        text.setSpacing(1)
        what = QLabel("still" if item["kind"] == "still" else f"{item['length']:.1f}s")
        what.setObjectName("SceneNum")
        when = QLabel(_clock(item["at"]))
        when.setObjectName("ProjMeta")
        text.addWidget(what)
        text.addWidget(when)
        lay.addLayout(text, 1)

        drop = QPushButton("×")
        drop.setObjectName("CardClose")
        drop.setFixedSize(18, 18)
        drop.setCursor(Qt.PointingHandCursor)
        drop.setToolTip("Throw this one away")
        drop.clicked.connect(lambda: self.dropRequested.emit(self.path))
        lay.addWidget(drop, 0, Qt.AlignTop)


class CutDialog(QDialog):
    added = Signal()

    def __init__(self, project, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cut the fragment")
        self.resize(1060, 620)
        self.project = project
        self.settings = settings
        self.duration = 0.0
        self._player = None
        self._added = 0
        self._stop_at = 0.0
        self._zoom = 1
        self._kept = []          # what this session has gathered
        self._cards = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Cut the fragment")
        title.setObjectName("DlgTitle")
        hint = QLabel("Drag a marker to move a seam · double click to add one")
        hint.setObjectName("Hint")
        head.addWidget(title)
        head.addWidget(hint)
        head.addStretch(1)
        root.addLayout(head)

        # preview on the left, everything kept so far on the right — the shelf
        # is the point of the window, not a side effect of it
        middle = QHBoxLayout()
        middle.setSpacing(10)

        stage = QVBoxLayout()
        stage.setSpacing(0)
        self.blank = QLabel("Click a piece on the timeline, then play it.")
        self.blank.setObjectName("ClipThumb")
        self.blank.setAlignment(Qt.AlignCenter)
        self.blank.setWordWrap(True)
        stage.addWidget(self.blank, 1)
        self.video = QVideoWidget()
        self.video.setVisible(False)
        stage.addWidget(self.video, 1)
        middle.addLayout(stage, 1)

        shelf_box = QVBoxLayout()
        shelf_box.setSpacing(6)
        self.shelf_cap = QLabel("KEPT")
        self.shelf_cap.setObjectName("FieldLabel")
        shelf_box.addWidget(self.shelf_cap)
        self.shelf_scroll = QScrollArea()
        self.shelf_scroll.setWidgetResizable(True)
        self.shelf_scroll.setFixedWidth(240)
        self.shelf_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.shelf_lay = QVBoxLayout(holder)
        self.shelf_lay.setContentsMargins(0, 0, 6, 0)
        self.shelf_lay.setSpacing(5)
        self.shelf_empty = QLabel("Nothing kept yet.")
        self.shelf_empty.setObjectName("Hint")
        self.shelf_empty.setWordWrap(True)
        self.shelf_lay.addWidget(self.shelf_empty)
        self.shelf_lay.addStretch(1)
        self.shelf_scroll.setWidget(holder)
        shelf_box.addWidget(self.shelf_scroll, 1)
        middle.addLayout(shelf_box)
        root.addLayout(middle, 1)

        # ---- zoom + timeline ------------------------------------------------
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(8)
        zoom_row.addWidget(QLabel("Zoom"))
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(ZOOM_MIN, ZOOM_MAX)
        self.zoom.setValue(ZOOM_MIN)
        self.zoom.setFixedWidth(220)
        # a slider as well as the wheel: a laptop trackpad makes wheel-zoom a
        # fight, and this is the control that decides how precisely a marker
        # can be placed at all
        self.zoom.valueChanged.connect(self._on_zoom)
        self.zoom_label = QLabel("1×")
        self.zoom_label.setObjectName("Hint")
        zoom_row.addWidget(self.zoom)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addStretch(1)
        root.addLayout(zoom_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(TRACK_H + RULER_H + 16)
        self.timeline = Timeline()
        self.timeline.selectionChanged.connect(lambda _: self._refresh())
        self.timeline.markersMoved.connect(self._refresh)
        self.timeline.scrubbed.connect(self._scrub)
        self.scroll.setWidget(self.timeline)
        root.addWidget(self.scroll)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        root.addWidget(self.progress)

        foot = QHBoxLayout()
        self.status = QLabel("Reading the fragment…")
        self.status.setObjectName("Hint")
        self.status.setMinimumWidth(400)
        foot.addWidget(self.status, 1)
        self.shot_btn = QPushButton("Screenshot")
        self.shot_btn.setToolTip("Keep the frame the preview is showing")
        self.play_btn = QPushButton("▶ Play piece")
        self.add_btn = QPushButton("Add fragment")
        self.add_btn.setObjectName("Primary")
        self.shot_btn.clicked.connect(self.take_shot)
        self.play_btn.clicked.connect(self.play_piece)
        self.add_btn.clicked.connect(self.add_piece)
        for b in (self.shot_btn, self.play_btn, self.add_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(False)
            foot.addWidget(b)
        root.addLayout(foot)

        self._start()

    # ---- opening ------------------------------------------------------------

    def _start(self):
        source = self.project.fragment_path if self.project else ""
        if not source or not Path(source).exists():
            self.progress.setVisible(False)
            self.status.setText("This project has no fragment to cut.")
            return
        run_async(self, self._analyse, self._on_ready, self._fail,
                  source, self.settings.get("ffmpeg_path", ""),
                  on_progress=self.status.setText)

    @staticmethod
    def _analyse(source: str, ffmpeg_path: str, progress=None) -> dict:
        duration = stt.probe_duration(source, ffmpeg_path)
        cuts = cutter.detect_cuts(source, ffmpeg_path, progress)
        return {"duration": duration, "cuts": cuts}

    def _on_ready(self, data: dict):
        self.progress.setVisible(False)
        self.duration = data["duration"]
        self.timeline.load(data["duration"], data["cuts"])
        self._on_zoom(self.zoom.value())
        self._ensure_player()
        # loaded and held still, so dragging a marker can seek it instantly
        self._player.pause()
        self.shot_btn.setEnabled(True)
        self._refresh()
        self.status.setText(
            f"{len(data['cuts'])} seams found in {_clock(data['duration'])}")

    def _fail(self, message: str):
        self.progress.setVisible(False)
        self.status.setText(message[:200])

    # ---- zoom and scrub -----------------------------------------------------

    def _on_zoom(self, value: int):
        self._zoom = value
        self.zoom_label.setText(f"{value}×")
        width = max(self.scroll.viewport().width(), 200) * value
        self.timeline.setFixedWidth(width)
        self.timeline.update()

    def wheelEvent(self, event):
        if self.scroll.underMouse():
            step = 1 if event.angleDelta().y() > 0 else -1
            self.zoom.setValue(max(ZOOM_MIN, min(ZOOM_MAX, self.zoom.value() + step)))
            return
        super().wheelEvent(event)

    def _ensure_player(self):
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._player.setVideoOutput(self.video)
            self._player.positionChanged.connect(self._watch_position)
            self._player.setSource(QUrl.fromLocalFile(
                str(Path(self.project.fragment_path).resolve())))

    def _scrub(self, seconds: float):
        """Show the frame the marker is standing on."""
        self._ensure_player()
        self._stop_at = 0.0
        self.blank.setVisible(False)
        self.video.setVisible(True)
        self._player.pause()
        self._player.setPosition(int(seconds * 1000))

    # ---- the chosen piece ---------------------------------------------------

    def _piece(self):
        segments = self.timeline.bounds()
        i = self.timeline.chosen
        return segments[i] if 0 <= i < len(segments) else None

    def _refresh(self):
        piece = self._piece()
        self.play_btn.setEnabled(piece is not None)
        self.add_btn.setEnabled(piece is not None)
        total = len(self.timeline.bounds())
        tail = f" · {len(self._kept)} kept" if self._kept else ""
        if piece:
            start, end = piece
            self.status.setText(f"{_clock(start)} – {_clock(end)} · {end - start:.1f}s · "
                                f"piece {self.timeline.chosen + 1} of {total}{tail}")
        elif self.duration:
            self.status.setText(f"{total} pieces · click one to keep it{tail}")

    def play_piece(self):
        piece = self._piece()
        if not piece:
            return
        self._ensure_player()
        self.blank.setVisible(False)
        self.video.setVisible(True)
        self._player.setPosition(int(piece[0] * 1000))
        self._stop_at = piece[1]
        self._player.play()

    def _watch_position(self, ms: int):
        # the player runs on past the marker unless it is told where to stop
        if self._stop_at and ms / 1000 >= self._stop_at:
            self._player.pause()
            self._stop_at = 0.0

    # ---- keeping ------------------------------------------------------------

    def _pool(self) -> Path:
        folder = project_dir(self.project.id) / "clips"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def add_piece(self):
        piece = self._piece()
        if not piece:
            return
        start, end = piece
        self.status.setText("Cutting…")
        run_async(self, self._cut_job, self._on_kept, self._fail,
                  start, end, on_progress=self.status.setText)

    def _cut_job(self, start: float, end: float, progress=None) -> dict:
        ffmpeg = self.settings.get("ffmpeg_path", "")
        stem = f"cut_{int(start * 1000):08d}"
        path = fragments.cut(self.project.fragment_path, start, end,
                             str(self._pool() / f"{stem}.mp4"), ffmpeg)
        poster = cutter.thumb(self.project.fragment_path, start,
                              str(self._pool() / "thumbs" / f"{stem}.jpg"), ffmpeg)
        return {"kind": "clip", "path": path, "thumb": poster,
                "at": start, "length": end - start}

    def take_shot(self):
        at = (self._player.position() / 1000) if self._player else 0.0
        self.status.setText("Saving the frame…")
        run_async(self, self._shot_job, self._on_kept, self._fail, at)

    def _shot_job(self, at: float) -> dict:
        ffmpeg = self.settings.get("ffmpeg_path", "")
        stem = f"still_{int(at * 1000):08d}"
        path = cutter.grab_frame(self.project.fragment_path, at,
                                 str(self._pool() / f"{stem}.jpg"), ffmpeg)
        poster = cutter.thumb(self.project.fragment_path, at,
                              str(self._pool() / "thumbs" / f"{stem}.jpg"), ffmpeg)
        return {"kind": "still", "path": path, "thumb": poster,
                "at": at, "length": 0.0}

    # ---- the shelf ----------------------------------------------------------

    def _on_kept(self, item: dict):
        self._kept.append(item)
        self._rebuild_shelf()
        size = Path(item["path"]).stat().st_size / 1e6
        self.status.setText(f"Kept {Path(item['path']).name} · {size:.1f} MB")
        self.added.emit()

    def _rebuild_shelf(self):
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        self.shelf_empty.setVisible(not self._kept)
        for i, item in enumerate(self._kept):
            card = ShelfCard(item)
            card.dropRequested.connect(self.drop_kept)
            self.shelf_lay.insertWidget(i + 1, card)
            self._cards.append(card)

        clips = sum(1 for i in self._kept if i["kind"] == "clip")
        stills = len(self._kept) - clips
        parts = []
        if clips:
            parts.append(f"{clips} clip{'s' if clips > 1 else ''}")
        if stills:
            parts.append(f"{stills} still{'s' if stills > 1 else ''}")
        self.shelf_cap.setText("KEPT — " + (" · ".join(parts) if parts else "nothing yet"))

    def drop_kept(self, path: str):
        """Throwing one away deletes the file too — it was only ever a candidate."""
        self._kept = [i for i in self._kept if i["path"] != path]
        Path(path).unlink(missing_ok=True)
        self._rebuild_shelf()
        self.added.emit()

    # ---- closing ------------------------------------------------------------

    def _stop(self):
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())

    def closeEvent(self, event):
        self._stop()
        super().closeEvent(event)

    def reject(self):
        self._stop()
        super().reject()
