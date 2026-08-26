"""Footage step — the pictures each scene shows, in playing order.

Nothing here is searched for any more. A scene is filled either with drawings
made for it (Gen frames) or with pieces cut out of the project's own source
video (Cut), and both land on the project's shelf first — the + on a row is
what puts them into a scene.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFrame, QGraphicsBlurEffect, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app.models_data import Visual
from app.services import thumbs
from app.services.worker import run_async
from app.widgets.cut_dialog import CutDialog
from app.widgets.frames_dialog import FramesDialog
from app.widgets.pool_picker import PoolPicker

# the posters inside a scene row are small: with up to five of them per row and
# nineteen rows, full-size ones turn the list into a staircase
SHOT_W, SHOT_H = 32, 57
# what hovering one shows instead — big enough to judge a picture by
BIG_W, BIG_H = 248, 440
BLUR = 4


class Magnifier(QLabel):
    """One floating preview shared by every poster on the step.

    A window per poster would be ninety-six of them for a project this size,
    each holding a pixmap, to show one at a time.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("Magnifier")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(BIG_W, BIG_H)

    def show_for(self, path: str, anchor: QWidget):
        pixmap = QPixmap(thumbs.small(path)) if path else QPixmap()
        if pixmap.isNull():
            return
        self.setPixmap(pixmap.scaled(BIG_W, BIG_H, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation))
        # to the right of the poster, nudged back inside the screen if it would
        # otherwise hang off the edge
        spot = anchor.mapToGlobal(anchor.rect().topRight())
        x, y = spot.x() + 10, spot.y() - (BIG_H - anchor.height()) // 2
        screen = QGuiApplication.screenAt(spot) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if x + BIG_W > area.right():
            x = anchor.mapToGlobal(anchor.rect().topLeft()).x() - BIG_W - 10
        y = max(area.top() + 8, min(y, area.bottom() - BIG_H - 8))
        self.move(x, y)
        self.show()


class ShotThumb(QLabel):
    """One poster in a scene row: hover to see it, × to take it out.

    Clicking the picture itself used to delete it, which is a lot to lose to a
    misplaced click — and it was gone for good. Now it steps aside instead: it
    stays in the row, blurred, at the end, and clicking it puts it back where
    it was.
    """

    dropRequested = Signal(int)
    restoreRequested = Signal(int)

    def __init__(self, at: int, visual, magnifier: Magnifier):
        super().__init__()
        self.setObjectName("ClipThumb")
        self.at = at
        self.visual = visual
        self._magnifier = magnifier
        self.setFixedSize(SHOT_W, SHOT_H)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)

        source = visual.thumb or visual.path
        pixmap = QPixmap(thumbs.small(source)) if source else QPixmap()
        if not pixmap.isNull():
            self.setPixmap(pixmap.scaled(SHOT_W, SHOT_H,
                                         Qt.KeepAspectRatioByExpanding,
                                         Qt.SmoothTransformation))
        else:
            self.setText(f"{visual.duration:.0f}s")

        self.drop = QPushButton("×", self)
        self.drop.setObjectName("ShotDrop")
        self.drop.setCursor(Qt.PointingHandCursor)
        self.drop.setFixedSize(14, 14)
        self.drop.move(SHOT_W - 15, 1)
        self.drop.setToolTip("Take this one out of the scene")
        self.drop.clicked.connect(lambda: self.dropRequested.emit(self.at))
        self.drop.setVisible(False)

        if visual.off:
            blur = QGraphicsBlurEffect(self)
            blur.setBlurRadius(BLUR)
            self.setGraphicsEffect(blur)
            self.drop.setParent(None)     # nothing to take out twice
            self.setToolTip("Out of the scene — click to put it back")
        else:
            self.setToolTip(f"{visual.duration:.1f}s · "
                            f"{visual.source or visual.kind}")

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self.visual.off:
            self.drop.setVisible(True)
        self._magnifier.show_for(self.visual.thumb or self.visual.path, self)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self.visual.off:
            self.drop.setVisible(False)
        self._magnifier.hide()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.visual.off:
            self._magnifier.hide()
            self.restoreRequested.emit(self.at)


class SceneClipRow(QFrame):
    playRequested = Signal(int)
    addRequested = Signal(int)
    changed = Signal(int)

    def __init__(self, index: int, scene, magnifier):
        super().__init__()
        self.setObjectName("SceneCard")
        self.index = index
        self.scene = scene
        self._magnifier = magnifier

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        # One small poster per shot, in playing order — built only once asked
        # for. A drawn picture is a 3 MB png, and nineteen rows of them cost
        # four seconds of frozen window to show a strip 57 pixels tall.
        self.shots_row = QWidget()
        self.shots = QHBoxLayout(self.shots_row)
        self.shots.setContentsMargins(0, 0, 0, 0)
        self.shots.setSpacing(3)
        self.shots.addStretch(1)
        self.shots_row.setVisible(False)
        self._shot_labels = []
        self._open = False

        self.toggle = QPushButton()
        self.toggle.setObjectName("Disclose")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.clicked.connect(self.toggle_shots)

        middle = QVBoxLayout()
        middle.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        num = QLabel(f"SCENE {index + 1}")
        num.setObjectName("SceneNum")
        self.credit = QLabel()
        self.credit.setObjectName("ProjMeta")
        top.addWidget(num)
        top.addWidget(self.credit)
        top.addStretch(1)
        middle.addLayout(top)

        # the line this scene speaks — read-only, but you cannot judge whether a
        # picture fits without seeing what is said over it
        self.line = QLabel()
        self.line.setObjectName("SceneLine")
        self.line.setWordWrap(True)
        self.line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        middle.addWidget(self.line)
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.addWidget(self.toggle)
        toggle_row.addStretch(1)
        middle.addLayout(toggle_row)
        middle.addWidget(self.shots_row)

        self.length = QLabel()
        self.length.setObjectName("Chip")
        self.length.setFixedWidth(52)
        self.length.setAlignment(Qt.AlignCenter)

        # hearing the line is how you judge whether a picture belongs under it
        self.play = QPushButton("▶")
        self.play.setObjectName("GBtn")
        self.play.setCursor(Qt.PointingHandCursor)
        self.play.setToolTip("Play this scene's voice track")
        self.play.clicked.connect(lambda: self.playRequested.emit(self.index))

        self.add = QPushButton("+")
        self.add.setObjectName("GBtn")
        self.add.setCursor(Qt.PointingHandCursor)
        self.add.setToolTip("Take footage this project has already gathered")
        self.add.clicked.connect(lambda: self.addRequested.emit(self.index))

        lay.addLayout(middle, 1)
        lay.addWidget(self.length, 0, Qt.AlignVCenter)   # chips must not stretch to row height
        lay.addWidget(self.play, 0, Qt.AlignVCenter)
        lay.addWidget(self.add, 0, Qt.AlignVCenter)

        self.refresh()

    def drop_shot(self, at: int):
        """Out of the scene, not out of the project."""
        self._set_off(at, True)

    def restore_shot(self, at: int):
        self._set_off(at, False)

    def _set_off(self, at: int, off: bool):
        if 0 <= at < len(self.scene.visuals):
            self.scene.visuals[at].off = off
            self.scene.rebalance()
            self.refresh()
            self.changed.emit(self.index)

    def toggle_shots(self):
        self._open = not self._open
        self.shots_row.setVisible(self._open)
        if self._open:
            self._build_shots()
        else:
            self._clear_shots()      # and with them the pixels they were holding
        self._sync_toggle()

    def _clear_shots(self):
        for label in self._shot_labels:
            label.setParent(None)
            label.deleteLater()
        self._shot_labels.clear()

    def _sync_toggle(self):
        total = len(self.scene.visuals)
        playing = len(self.scene.shots)
        self.toggle.setVisible(bool(total))
        if not total:
            return
        aside = f"  (+{total - playing} out)" if total > playing else ""
        self.toggle.setText(("▾  Hide frames · " if self._open else "▸  Show frames · ")
                            + str(playing) + aside)

    def refresh(self):
        self.scene.rebalance()
        self._clear_shots()
        if self._open:
            self._build_shots()
        self._sync_toggle()

        playing = self.scene.shots
        if playing:
            each = playing[0].duration
            self.credit.setText(f"{len(playing)} shot{'s' if len(playing) > 1 else ''} · "
                                f"{each:.1f}s each")
        elif self.scene.visuals:
            self.credit.setText("every frame taken out")
        else:
            self.credit.setText("no footage yet")
            self.shots_row.setVisible(False)
        self.length.setText(f"{self.scene.duration:.1f}s" if self.scene.duration else "—")
        self.line.setText(self.scene.text or "—")

    def _build_shots(self):
        """Playing ones in their order, then the ones taken out.

        The list itself is never reordered — only shown that way — which is why
        putting one back needs no record of where it came from.
        """
        order = ([(i, v) for i, v in enumerate(self.scene.visuals) if not v.off]
                 + [(i, v) for i, v in enumerate(self.scene.visuals) if v.off])
        for slot, (at, visual) in enumerate(order):
            thumb = ShotThumb(at, visual, self._magnifier)
            thumb.dropRequested.connect(self.drop_shot)
            thumb.restoreRequested.connect(self.restore_shot)
            self.shots.insertWidget(slot, thumb)
            self._shot_labels.append(thumb)

    def set_playing(self, on: bool):
        self.play.setText("■" if on else "▶")


class FootageStep(QWidget):
    projectChanged = Signal()
    log = Signal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.project = None
        self._rows = []
        self._player = None
        self._playing = -1      # which row is sounding, or -1
        self._magnifier = Magnifier(self)
        self._warming = set()   # projects whose thumbnails are being built
        self._warm_id = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.cut_btn = QPushButton("Cut…")
        self.cut_btn.setCursor(Qt.PointingHandCursor)
        self.cut_btn.setToolTip(
            "Break this project's fragment into pieces you can use as footage")
        self.cut_btn.clicked.connect(self.open_cutter)
        controls.addWidget(self.cut_btn)

        controls.addStretch(1)
        self.gen_btn = QPushButton("Gen frames…")
        self.gen_btn.setObjectName("Primary")
        self.gen_btn.setCursor(Qt.PointingHandCursor)
        self.gen_btn.setToolTip("Draw the pictures for this video")
        self.gen_btn.clicked.connect(self.open_frames)
        controls.addWidget(self.gen_btn)
        root.addLayout(controls)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.row_layout = QVBoxLayout(holder)
        self.row_layout.setContentsMargins(0, 2, 6, 2)
        self.row_layout.setSpacing(6)
        self.row_layout.addStretch(1)
        self.scroll.setWidget(holder)
        root.addWidget(self.scroll, 1)

        self.placeholder = QLabel("Write a script first — footage is chosen per scene.")
        self.placeholder.setObjectName("Hint")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.row_layout.insertWidget(0, self.placeholder)

        self.total = QLabel("")
        self.total.setObjectName("Hint")
        self.total.setAlignment(Qt.AlignRight)
        root.addWidget(self.total)

    # ---- project binding ---------------------------------------------------

    def set_project(self, project):
        self.project = project
        self._rebuild_rows()
        self._warm_thumbs()

    # ---- thumbnails --------------------------------------------------------

    def _warm_thumbs(self):
        """Build the small copies for this project, off the window's thread.

        Opening a scene is instant once they exist, and they only have to be
        made once per picture, ever — so the whole project is done at once
        rather than a scene's worth at a time.
        """
        if not self.project:
            return
        wanted = [v.thumb or v.path for s in self.project.scenes for v in s.visuals]
        todo = thumbs.missing(wanted)
        if not todo or self.project.id in self._warming:
            return
        self._warming.add(self.project.id)
        self._warm_id = self.project.id
        self.log.emit(f"Preparing {len(todo)} thumbnails in the background…")
        run_async(self, thumbs.build, self._on_warm, self._on_warm_failed, todo)

    def _on_warm(self, made: int):
        self._warming.discard(self._warm_id)
        self.log.emit(f"{made} thumbnails ready")
        # only rows already open have anything on screen to replace
        for row in self._rows:
            if row._open:
                row.refresh()

    def _on_warm_failed(self, message: str):
        self._warming.discard(self._warm_id)
        self.log.emit(f"Thumbnails: {message}")

    def sync(self):
        """Catch up with a scene list that changed while this step was off screen."""
        scenes = self.project.scenes if self.project else []
        same = (len(self._rows) == len(scenes)
                and all(row.scene is scene for row, scene in zip(self._rows, scenes)))
        if same:
            for row in self._rows:
                row.refresh()
            self._update_total()
            return
        self._rebuild_rows()

    def _rebuild_rows(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        scenes = self.project.scenes if self.project else []
        self.placeholder.setVisible(not scenes)
        for i, scene in enumerate(scenes):
            row = SceneClipRow(i, scene, self._magnifier)
            row.playRequested.connect(self.toggle_play)
            row.addRequested.connect(self.add_from_pool)
            row.changed.connect(self._on_row_changed)
            self.row_layout.insertWidget(i + 1, row)
            self._rows.append(row)
        self._update_total()

    def _update_total(self):
        scenes = self.project.scenes if self.project else []
        filled = [s for s in scenes if s.shots]
        shots = sum(len(s.shots) for s in scenes)
        self.total.setText(f"{len(filled)}/{len(scenes)} scenes filled · {shots} shots"
                           if scenes else "")

    def _on_row_changed(self, index: int):
        self._update_total()
        self.projectChanged.emit()

    # ---- taking from the pool ----------------------------------------------

    def add_from_pool(self, index: int):
        """Put gathered footage into one scene, splitting its time evenly."""
        if not self.project:
            return
        scene = self.project.scenes[index]
        picker = PoolPicker(self.project, index + 1, self)
        if not picker.exec():
            return
        for item in picker.picked_items():
            scene.visuals.append(Visual(
                path=item["path"], kind=item["kind"], source="fragment",
                thumb=item.get("thumb", "")))
        scene.rebalance()
        self._rows[index].refresh()
        self._update_total()
        self.projectChanged.emit()
        each = scene.visuals[0].duration if scene.visuals else 0
        self.log.emit(f"Scene {index + 1} · {len(scene.visuals)} shots, "
                      f"{each:.1f}s each")

    # ---- drawing the pictures ----------------------------------------------

    def open_frames(self):
        if not self.project or not self.project.scenes:
            return
        self._stop_audio()
        dialog = FramesDialog(self.project, self.settings, self)
        dialog.added.connect(self._on_frames_placed)
        dialog.exec()

    def _on_frames_placed(self):
        for row in self._rows:
            row.refresh()
        self._update_total()
        self.projectChanged.emit()
        self._warm_thumbs()      # freshly drawn pictures have no small copy yet

    # ---- cutting the fragment ----------------------------------------------

    def open_cutter(self):
        if not self.project:
            return
        if not self.project.fragment_path or not Path(self.project.fragment_path).exists():
            self.log.emit("This project has no fragment — it came from a topic "
                          "whose video was never fetched.")
            return
        self._stop_audio()
        dialog = CutDialog(self.project, self.settings, self)
        dialog.added.connect(self._on_cut_added)
        dialog.exec()

    def _on_cut_added(self):
        self.log.emit("Pieces kept — add them to a scene with + on its row.")

    # ---- listening ---------------------------------------------------------

    def toggle_play(self, index: int):
        """One player for the whole list: starting a scene stops the last one.

        Nineteen rows each with their own player would let you stack a chorus
        by clicking around, and there would be no way to stop it.
        """
        if self._playing == index:
            self._stop_audio()
            return
        scene = self.project.scenes[index] if self.project else None
        if not scene or not scene.audio_path or not Path(scene.audio_path).exists():
            return

        self._stop_audio()
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_out)
            self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.setSource(QUrl.fromLocalFile(str(Path(scene.audio_path).resolve())))
        self._player.play()
        self._playing = index
        self._rows[index].set_playing(True)

    def _stop_audio(self):
        if self._player is not None:
            self._player.stop()
        if 0 <= self._playing < len(self._rows):
            self._rows[self._playing].set_playing(False)
        self._playing = -1

    def _on_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self._stop_audio()
