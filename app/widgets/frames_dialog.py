"""Drawing the pictures for a project instead of finding them.

The window follows the passes in order and lights the next button only when the
one before it has something to hand over: read where and when this happens, read
the scenes and invent the running jokes, turn it all into prompts, draw the
poster, then draw the rest to match it.

The poster is what the rest are drawn against. It used to be the first frame of
the first scene, which handed every other frame that scene's subject along with
its manner — fifty pictures quietly inheriting an orator at a podium. The poster
carries the jokes, the world and the manner, and no scene at all.

Two of it are made. The one with the title across the middle is for looking at;
the one without is what goes to the model, because a sample with large lettering
in the middle teaches every frame to put lettering in the middle.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from app import config
from app.services import frames, kie_images, thumbs
from app.services.worker import run_async
from app.widgets.frames_settings import FramesSettings

# The size it opens at, and the gap it keeps from the edges of the window it
# opens over. It asked for 1180x820 before and got 1238x820, because its own
# contents would not go narrower — and 820 is taller than a maximised window
# has room for on a 1536x864 screen, so it hung off the bottom.
WANTED_W, WANTED_H = 1100, 700
EDGE = 48


POSTER_W = 124
POSTER_KINDS = ["titled", "plain"]
VIEW_EDGE = 40          # gap the enlarged view keeps from the screen edges
# a picture beside its prompt: five parts of text to two of picture
PROMPT_SHARE, SLOT_SHARE = 5, 2
SLOT_W = 96
# how many pictures may be at the model at once, however many were asked for.
# The same width Draw the rest uses, for the same reason: kie is happy with it
# and a failure stays cheap.
DRAW_LANES = 4


class ShotSlot(QLabel):
    """Where one picture goes. Empty, it is the button that draws it."""

    asked = Signal()
    viewAsked = Signal(str)

    def __init__(self, path: str, drawing: bool, queued: bool, ready: bool):
        super().__init__()
        self.setObjectName("ClipThumb")
        self.setFixedWidth(SLOT_W)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.path = ""
        self.clickable = False
        self.render(path, drawing, queued, ready)

    def render(self, path: str, drawing: bool, queued: bool, ready: bool):
        """Change what this slot shows without replacing the slot.

        A picture arriving used to rebuild the whole feed, which meant deleting
        the very widget the mouse was over — and if a modal viewer was open at
        the time, Qt was left holding a pointer to it. Nothing is created or
        destroyed here.
        """
        self.path = path
        self.clickable = ready and not drawing and not queued and not path
        self.setCursor(Qt.PointingHandCursor if (path or self.clickable)
                       else Qt.ArrowCursor)
        if path:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            pixmap = QPixmap(thumbs.small(path))
            if not pixmap.isNull():
                self.setPixmap(pixmap.scaledToWidth(SLOT_W, Qt.SmoothTransformation))
            else:
                self.setText("не читается")
            self.setToolTip(f"{Path(path).name} — нажми, чтобы рассмотреть")
            return
        self.setPixmap(QPixmap())
        self.setFixedHeight(int(SLOT_W * 16 / 9))
        self.setToolTip("")
        if drawing:
            self.setText("рисуется…")
        elif queued:
            self.setText("в очереди")
        elif ready:
            self.setText("нажми,\nчтобы\nнарисовать")
        else:
            self.setText("нет\nпромпта")

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.path:
            self.viewAsked.emit(self.path)
        elif self.clickable:
            self.asked.emit()


class SceneCard(QFrame):
    """One beat in the feed: what is said, and the pictures said over it."""

    toggled = Signal(int)
    redoAsked = Signal(int)
    drawAsked = Signal(int, int)
    drawAllAsked = Signal(int)
    viewAsked = Signal(str, str)

    def __init__(self, index: int, said: str, prompts: list, paths: list,
                 drawing: set, queued: set, is_open: bool, selected: bool):
        super().__init__()
        self.setObjectName("SceneCard")
        self.index = index
        self.slots = {}          # picture number -> the widget showing it
        self.draw_all = None
        self.setProperty("selected", "true" if selected else "false")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        num = QLabel(f"SCENE {index + 1}")
        num.setObjectName("SceneNum")
        num.setFixedWidth(58)
        line = QLabel(said or "—")
        line.setObjectName("SceneLine")
        line.setWordWrap(True)
        line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(num, 0, Qt.AlignTop)
        top.addWidget(line, 1)
        made = sum(1 for p in paths if p)
        if prompts:
            # both stay in reach with the row folded away: a scene is worked on
            # from its own line, not by opening it first
            waiting = [i for i, p in enumerate(paths)
                       if not p and (index, i) not in drawing
                       and (index, i) not in queued]
            draw_all = QPushButton("▦ pictures")
            draw_all.setObjectName("Disclose")
            draw_all.setCursor(Qt.PointingHandCursor)
            draw_all.clicked.connect(lambda: self.drawAllAsked.emit(self.index))
            self.draw_all = draw_all
            self.set_waiting(len(waiting))
            redo = QPushButton("↻ prompts")
            redo.setObjectName("Disclose")
            redo.setCursor(Qt.PointingHandCursor)
            redo.setToolTip("Write this scene's prompts again")
            redo.clicked.connect(lambda: self.redoAsked.emit(self.index))
            top.addWidget(draw_all, 0, Qt.AlignTop)
            top.addWidget(redo, 0, Qt.AlignTop)
        root.addLayout(top)
        self.toggle = QPushButton()
        self.toggle.setObjectName("Disclose")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self._open = is_open
        self._total = len(prompts)
        if prompts:
            self.set_counts(made)
            self.toggle.clicked.connect(lambda: self.toggled.emit(self.index))
        else:
            self.toggle.setText("▸  no prompts yet")
            self.toggle.setEnabled(False)
        root.addWidget(self.toggle, 0, Qt.AlignLeft)

        if not (is_open and prompts):
            return
        for i, prompt in enumerate(prompts):
            row = QHBoxLayout()
            row.setSpacing(8)
            text = QLabel(prompt)
            text.setObjectName("ProjMeta")
            text.setWordWrap(True)
            text.setAlignment(Qt.AlignTop)
            slot = ShotSlot(paths[i] if i < len(paths) else "",
                            (index, i) in drawing, (index, i) in queued, True)
            slot.asked.connect(lambda at=i: self.drawAsked.emit(self.index, at))
            slot.viewAsked.connect(
                lambda path, at=i: self.viewAsked.emit(
                    path, f"Scene {self.index + 1} · picture {at + 1}"))
            row.addWidget(text, PROMPT_SHARE)
            row.addWidget(slot, SLOT_SHARE, Qt.AlignTop)
            root.addLayout(row)
            self.slots[i] = slot

    # ---- changed in place, never rebuilt --------------------------------

    def set_counts(self, made: int):
        self.toggle.setText(f"{'▾' if self._open else '▸'}  {self._total} shots · "
                            f"{made}/{self._total} drawn")

    def set_waiting(self, waiting: int):
        if self.draw_all is None:
            return
        self.draw_all.setEnabled(bool(waiting))
        self.draw_all.setToolTip(f"Draw the {waiting} this scene is missing"
                                 if waiting else "Every picture here is drawn")


class Zoomable(QGraphicsView):
    """Wheel zooms about the cursor, drag pans. Nothing else."""

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        board = QGraphicsScene(self)
        self.item = board.addPixmap(pixmap)
        self.setScene(board)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.black)
        self._floor = 1.0

    def fit(self):
        self.fitInView(self.item, Qt.KeepAspectRatio)
        self._floor = self.transform().m11()

    def wheelEvent(self, event):
        step = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        # never smaller than the whole picture, never past twice its own pixels
        now = self.transform().m11()
        if not (self._floor <= now * step <= 2.0):
            return
        self.scale(step, step)


class ImageViewer(QDialog):
    """A picture on its own, large, with the pixels it was drawn at.

    Not scaled into a corner of some other window: the whole point of drawing
    at 4K is the detail, and the detail is what this is for.
    """

    def __init__(self, path: str, caption: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(caption or Path(path).name)
        self.setModal(True)

        pixmap = QPixmap(path)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        name = QLabel(caption or Path(path).name)
        name.setObjectName("FieldLabel")
        size = QLabel(f"{pixmap.width()}×{pixmap.height()}"
                      if not pixmap.isNull() else "не читается")
        size.setObjectName("Hint")
        hint = QLabel("колесо — приблизить · тянуть — двигать · Esc — закрыть")
        hint.setObjectName("Hint")
        head.addWidget(name)
        head.addWidget(size)
        head.addStretch(1)
        head.addWidget(hint)
        lay.addLayout(head)

        self.view = Zoomable(pixmap)
        lay.addWidget(self.view, 1)

        screen = (parent.screen() if parent else None) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.resize(area.width() - 2 * VIEW_EDGE, area.height() - 2 * VIEW_EDGE)
        self.move(area.center() - self.rect().center())

    def showEvent(self, event):
        super().showEvent(event)
        # only once the view has its final size does fitting mean anything
        QTimer.singleShot(0, self.view.fit)


class PosterView(QLabel):
    """One of the samples the rest of the pictures are drawn to match.

    Sized by whatever room the column gives it rather than by the picture:
    both samples have to be on screen at once — comparing them is the only
    reason there are two — and a strip that scrolls shows one at a time again.
    """

    drawRequested = Signal()
    viewRequested = Signal(str)

    def __init__(self, kind: str):
        super().__init__()
        self.setObjectName("ClipThumb")
        self.kind = kind
        self.path = ""
        self._source = QPixmap()
        self.setMinimumSize(40, 40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)

    def show_poster(self, path: str):
        self.path = path
        if not path:
            self._source = QPixmap()
            self.setPixmap(QPixmap())
            self.setText(f"{self.kind}\nнет")
            self.setToolTip("")
            return
        self._source = QPixmap(thumbs.small(path))
        if self._source.isNull():
            self.setText("не читается")
            return
        self.setToolTip(f"{self.kind} — нажми, чтобы рассмотреть")
        self._fit()

    def _fit(self):
        if self._source.isNull():
            return
        self.setPixmap(self._source.scaled(self.size(), Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.path:
            self.viewRequested.emit(self.path)
        else:
            self.drawRequested.emit()


class FramesDialog(QDialog):
    added = Signal()

    def __init__(self, project, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gen frames")
        self.project = project
        self.settings = settings
        self.style = ""
        self._current = 0
        self._busy = False
        self._open_scene = -1        # only one card in the feed is open at a time
        self._drawing = set()        # (scene, index) currently at the model
        self._pending = []           # asked for, waiting for a lane
        self._redo_index = 0
        self._cards = []
        self._viewing = False        # a picture is open over the window
        self._feed_dirty = False     # something wanted the feed rebuilt meanwhile
        self._read_engine()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        root.addLayout(self._build_head())

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_scenes())
        split.addWidget(self._build_right())
        split.setSizes([300, 840])
        root.addWidget(split, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        root.addLayout(self._build_foot())

        self._world_save = QTimer(self)
        self._world_save.setSingleShot(True)
        self._world_save.setInterval(700)
        self._world_save.timeout.connect(self._store_world)

        self._load_styles()
        self._load_world()
        self._refresh()
        self._fit_over_parent()

    # ---- size ---------------------------------------------------------------

    def _fit_over_parent(self):
        """Open inside the window this belongs to, never over its edges.

        Sized here rather than in the constructor's first line: what it may
        shrink to is not known until everything inside it has been built.
        """
        window = self.parent().window() if self.parent() else None
        area = window.geometry() if window else self.screen().availableGeometry()
        self.resize(min(WANTED_W, max(area.width() - 2 * EDGE, self.minimumWidth())),
                    min(WANTED_H, max(area.height() - 2 * EDGE, self.minimumHeight())))
        self.move(area.center() - self.rect().center())

    # ---- building -----------------------------------------------------------

    def _build_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("Gen frames")
        title.setObjectName("DlgTitle")
        self.hint = QLabel("Read the scenes, choose a manner, draw them")
        self.hint.setObjectName("Hint")
        head.addWidget(title)
        head.addWidget(self.hint)
        head.addStretch(1)

        self.gear = QPushButton("⚙")
        self.gear.setObjectName("GBtn")
        self.gear.setCursor(Qt.PointingHandCursor)
        self.gear.setToolTip("Which model draws, at what size and in what manner")
        self.gear.clicked.connect(self.open_settings)
        head.addWidget(self.gear)
        return head

    def _build_scenes(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        cap = QLabel("SCENES")
        cap.setObjectName("FieldLabel")
        lay.addWidget(cap)
        self.scene_list = QListWidget()
        self.scene_list.setObjectName("CompactList")
        self.scene_list.currentRowChanged.connect(self._pick_scene)
        lay.addWidget(self.scene_list, 1)
        self.redo_btn = QPushButton("Read this scene again")
        self.redo_btn.setCursor(Qt.PointingHandCursor)
        self.redo_btn.setToolTip("When one scene came back wrong or failed")
        self.redo_btn.clicked.connect(self.redo_scene)
        lay.addWidget(self.redo_btn)
        return panel

    def _build_right(self) -> QWidget:
        panel = QSplitter(Qt.Vertical)
        panel.setChildrenCollapsible(False)

        top = QWidget()
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(6)
        cap = QLabel("WHERE AND WHEN — every pass after this draws inside it")
        cap.setObjectName("FieldLabel")
        top_lay.addWidget(cap)
        self.world_text = QTextEdit()
        self.world_text.setAcceptRichText(False)
        self.world_text.setPlaceholderText(
            "Press “Read the world” — or write it yourself: place, period, "
            "architecture, dress, objects, signage, props.")
        self.world_text.textChanged.connect(self._world_edited)

        pair = QHBoxLayout()
        pair.setContentsMargins(0, 0, 0, 0)
        pair.setSpacing(8)
        pair.addWidget(self.world_text, 1)

        # both samples one under the other, always both visible. They are the
        # same drawing bar the middle, and comparing them is the only reason to
        # have two — which anything that shows one at a time undoes.
        self.posters = QWidget()
        self.posters.setFixedWidth(POSTER_W)
        strip_lay = QVBoxLayout(self.posters)
        strip_lay.setContentsMargins(0, 0, 0, 0)
        strip_lay.setSpacing(5)
        self.poster_views = {}
        for kind in POSTER_KINDS:
            view = PosterView(kind)
            view.drawRequested.connect(self.draw_poster)
            view.viewRequested.connect(self.open_viewer)
            strip_lay.addWidget(view, 1)
            self.poster_views[kind] = view
        pair.addWidget(self.posters)
        top_lay.addLayout(pair, 1)
        panel.addWidget(top)

        bottom = QWidget()
        lay = QVBoxLayout(bottom)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.shots_cap = QLabel("THE SCENES")
        self.shots_cap.setObjectName("FieldLabel")
        lay.addWidget(self.shots_cap)
        self.feed = QScrollArea()
        self.feed.setWidgetResizable(True)
        self.feed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.feed_layout = QVBoxLayout(holder)
        self.feed_layout.setContentsMargins(0, 0, 6, 0)
        self.feed_layout.setSpacing(7)
        self.feed_layout.addStretch(1)
        self.feed.setWidget(holder)
        lay.addWidget(self.feed, 1)
        panel.addWidget(bottom)
        panel.setSizes([210, 430])
        return panel

    def _build_foot(self) -> QHBoxLayout:
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.status = QLabel("")
        self.status.setObjectName("Hint")
        # it stretches to whatever is left over; demanding 300 up front only set
        # a floor under the whole window
        self.status.setMinimumWidth(150)
        foot.addWidget(self.status, 1)

        self.world_btn = QPushButton("Read the world")
        self.world_btn.setToolTip("Where and when this happens, from the script "
                                  "and whatever it was made from")
        self.world_btn.clicked.connect(self.read_world)
        self.detect_btn = QPushButton("Detect scenes")
        self.detect_btn.clicked.connect(self.detect)
        self.stylize_btn = QPushButton("Stylize all")
        self.stylize_btn.clicked.connect(self.stylize)
        self.poster_btn = QPushButton("Draw the poster")
        self.poster_btn.setToolTip("The sample the rest are drawn to match — "
                                   "jokes and manner, no scene")
        self.poster_btn.clicked.connect(self.draw_poster)
        self.rest_btn = QPushButton("Draw the rest")
        self.rest_btn.clicked.connect(self.draw_rest)
        self.add_btn = QPushButton("Add to project")
        self.add_btn.setObjectName("Primary")
        self.add_btn.clicked.connect(self.place)
        for b in (self.world_btn, self.detect_btn, self.stylize_btn,
                  self.poster_btn, self.rest_btn, self.add_btn):
            b.setCursor(Qt.PointingHandCursor)
            foot.addWidget(b)
        return foot

    # ---- styles -------------------------------------------------------------

    def _read_engine(self):
        """Which model, shape and size — all four defaults live in config."""
        for attr, key in (("_model", "draw_model"), ("_aspect", "draw_aspect"),
                          ("_resolution", "draw_resolution")):
            setattr(self, attr, self.settings.get(key, config.DEFAULTS[key]))

    def _load_styles(self):
        names = frames.style_names() or [config.DEFAULTS["draw_style"]]
        wanted = self.settings.get("draw_style", config.DEFAULTS["draw_style"])
        self.style = wanted if wanted in names else names[0]

    def open_settings(self):
        dialog = FramesSettings(self.project, self.settings, self.style, self)
        dialog.exec()
        self.style = dialog.style
        self._read_engine()
        self._refresh()

    # ---- pass zero: the world -----------------------------------------------

    def _load_world(self):
        self.world_text.blockSignals(True)
        self.world_text.setPlainText(frames.load_base(self.project.id)["world"])
        self.world_text.blockSignals(False)

    def read_world(self):
        self._busy_on("Reading where and when this happens…")
        run_async(self, frames.read_world, self._on_world, self._fail, self.project)

    def _on_world(self, world: str):
        self._busy = False
        self.progress.setVisible(False)
        self.world_text.blockSignals(True)
        self.world_text.setPlainText(world)
        self.world_text.blockSignals(False)
        self._store_world(world)
        self.status.setText("World read — worth checking before anything is drawn")
        self._refresh()

    def _world_edited(self):
        # saved on a pause rather than on a button: it is a note, not a form
        self._world_save.start()

    def _store_world(self, world: str = None):
        base = frames.load_base(self.project.id)
        base["world"] = (self.world_text.toPlainText() if world is None
                         else world).strip()
        frames.save_base(self.project.id, base)

    # ---- the passes ---------------------------------------------------------

    def _busy_on(self, message: str):
        self._busy = True
        self.progress.setVisible(True)
        self.status.setText(message)
        for b in (self.world_btn, self.detect_btn, self.stylize_btn,
                  self.poster_btn, self.rest_btn, self.add_btn, self.redo_btn,
                  self.gear, self.world_text, self.posters):
            b.setEnabled(False)

    def _fail(self, message: str):
        self._busy = False
        self.progress.setVisible(False)
        self.status.setText(message[:200])
        self._refresh()

    def detect(self):
        self._busy_on("Reading the scenes…")
        run_async(self, self._detect_job, self._on_detected, self._fail,
                  on_progress=self.status.setText)

    def _detect_job(self, progress=None) -> dict:
        world = frames.load_base(self.project.id)["world"]
        read = frames.analyse_project(self.project, world, progress)
        details = frames.build_details(self.project, world=world, progress=progress)
        base = {"scenes": read["scenes"], "details": details, "world": world}
        frames.save_base(self.project.id, base)
        return {"scenes": len(read["scenes"]), "details": len(details),
                "failed": read["failed"]}

    def _on_detected(self, result: dict):
        self._busy = False
        self.progress.setVisible(False)
        note = f" · {len(result['failed'])} failed" if result["failed"] else ""
        self.status.setText(f"{result['scenes']} scenes read · "
                            f"{result['details']} background jokes{note}")
        self._refresh()

    def redo_scene(self):
        base = frames.load_base(self.project.id)
        if not base["scenes"]:
            return
        self._busy_on(f"Reading scene {self._current + 1} again…")
        run_async(self, frames.redo_scene, self._on_redone, self._fail,
                  self.project, self._current)

    def _on_redone(self, shots: list):
        base = frames.load_base(self.project.id)
        base["scenes"][str(self._current)] = shots
        frames.save_base(self.project.id, base)
        self._busy = False
        self.progress.setVisible(False)
        self.status.setText(f"Scene {self._current + 1} read again")
        self._refresh()

    def stylize(self):
        self._busy_on("Turning them into prompts…")
        run_async(self, frames.stylize_project, self._on_stylized, self._fail,
                  self.project, self.style, on_progress=self.status.setText)

    def _on_stylized(self, result: dict):
        self._busy = False
        self.progress.setVisible(False)
        total = sum(len(v) for v in result["prompts"].values())
        note = f" · {len(result['failed'])} failed" if result["failed"] else ""
        self.status.setText(f"{total} prompts ready{note}")
        self._refresh()

    def draw_poster(self):
        if not self._has_jokes():
            return
        self._busy_on("Drawing the poster…")
        run_async(self, frames.draw_poster, self._on_poster, self._fail,
                  self.project, self.style, self.world_text.toPlainText(),
                  self._model, self._aspect, self._resolution,
                  on_progress=self.status.setText)

    def _has_jokes(self) -> bool:
        if frames.load_base(self.project.id)["details"]:
            return True
        self.status.setText("Detect scenes first — the poster is built from "
                            "the background jokes.")
        return False

    def _on_poster(self, result: dict):
        self._busy = False
        self.progress.setVisible(False)
        made = [k for k in POSTER_KINDS if result.get(k)]
        note = f" · {'; '.join(result['failed'])}" if result["failed"] else ""
        self.status.setText(f"{len(made)} posters drawn{note}")
        self._refresh()

    def _show_poster(self):
        made = frames.posters_so_far(self.project.id, self.style)
        for kind, view in self.poster_views.items():
            view.show_poster(made.get(kind, ""))

    def open_viewer(self, path: str, caption: str = ""):
        """A picture on its own, over everything, until it is closed.

        Freed afterwards on purpose: a viewer holds the whole picture, which is
        sixty-eight megabytes at 4K, and being a child of this window it would
        otherwise sit there for the rest of the session. Eight of them viewed
        and never released measured as ninety megabytes gone at 1K alone.

        Nothing rebuilds the feed while it is open. That is what killed the
        window before: a picture landing under the viewer deleted every card,
        including the one whose click opened it.
        """
        if not path or not Path(path).exists():
            return
        viewer = ImageViewer(path, caption, self)
        self._viewing = True
        try:
            viewer.exec()
        finally:
            self._viewing = False
            viewer.setParent(None)
            viewer.deleteLater()
        if self._feed_dirty:
            self._feed_dirty = False
            self._show_feed()

    def _reference(self) -> str:
        """What the rest are drawn to match — the poster without the lettering.

        Titled is the fallback rather than nothing: a sample with words across
        the middle is worse than one without, and far better than none at all.
        """
        made = frames.posters_so_far(self.project.id, self.style)
        return made["plain"] or made["titled"]

    def draw_rest(self):
        reference = self._reference()
        if not reference:
            self.status.setText("Draw the poster first — the rest follow it.")
            return
        self._busy_on("Drawing the rest…")
        run_async(self, frames.draw_rest, self._on_rest, self._fail,
                  self.project, self.style, reference, self._model,
                  self._aspect, self._resolution, on_progress=self.status.setText)

    def _on_rest(self, result: dict):
        self._busy = False
        self.progress.setVisible(False)
        note = f" · {len(result['failed'])} failed" if result["failed"] else ""
        self.status.setText(f"{len(result['drawn'])} drawn{note}")
        self._refresh()

    def place(self):
        result = frames.place_in_scenes(self.project, self.style)
        self.status.setText(f"{result['pictures']} pictures placed "
                            f"across {result['scenes']} scenes")
        self.added.emit()
        self._refresh()

    # ---- showing ------------------------------------------------------------

    def _pick_scene(self, row: int):
        """The list stopped being a switch when the feed arrived — it points."""
        if row < 0:
            return
        self._current = row
        self._open_scene = row
        self._show_feed()
        if row < len(self._cards):
            self.feed.ensureWidgetVisible(self._cards[row], 0, 40)

    def _refresh(self):
        base = frames.load_base(self.project.id)
        prompts = frames.load_prompts(self.project.id, self.style)
        drawn = {(d["scene"], d["index"]) for d in
                 frames.drawn_so_far(self.project.id, self.style)}

        self.scene_list.blockSignals(True)
        self.scene_list.clear()
        for i, scene in enumerate(self.project.scenes):
            shots = len(base["scenes"].get(str(i), []))
            ready = len(prompts.get(str(i), []))
            pictures = sum(1 for s, _ in drawn if s == i)
            mark = "·" if not shots else ("✓" if pictures else ("»" if ready else "◔"))
            self.scene_list.addItem(QListWidgetItem(
                f"{mark}  {i + 1}. {shots} shots · {pictures}/{ready} drawn"))
        self.scene_list.setCurrentRow(min(self._current,
                                          max(0, self.scene_list.count() - 1)))
        self.scene_list.blockSignals(False)

        has_base = bool(base["scenes"])
        has_prompts = bool(prompts)
        has_poster = bool(self._reference())
        for widget, on in ((self.world_btn, True), (self.world_text, True),
                           (self.detect_btn, True),
                           (self.stylize_btn, has_base),
                           (self.poster_btn, bool(base["details"])),
                           (self.posters, True),
                           (self.rest_btn, has_prompts and has_poster),
                           (self.add_btn, bool(drawn)),
                           (self.redo_btn, has_base), (self.gear, True)):
            widget.setEnabled(on and not self._busy)
        self._show_poster()

        label, *_ = kie_images.MODELS.get(self._model, ("?",))
        self.hint.setText(f"{label} · {self._aspect} · {self._resolution} · "
                          f"{len(base['details'])} jokes")
        self._show_feed()

    def _show_feed(self):
        """The feed, all scenes at once.

        One card is open at a time. Nineteen scenes of two or three pictures
        each, all expanded, is a scroll nobody can find their place in — and the
        pictures inside a closed card are never loaded at all.
        """
        if self._viewing:
            # a picture is being looked at; taking the feed apart underneath it
            # is what brought the window down
            self._feed_dirty = True
            return
        top = self.feed.verticalScrollBar().value()
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []

        base = frames.load_base(self.project.id)
        by_scene = frames.load_prompts(self.project.id, self.style)
        made = 0
        for i, scene in enumerate(self.project.scenes):
            prompts = by_scene.get(str(i), [])
            paths = []
            for j in range(len(prompts)):
                path = frames.picture_path(self.project.id, self.style, str(i), j)
                paths.append(str(path) if path.exists() else "")
            made += sum(1 for p in paths if p)
            card = SceneCard(i, scene.text, prompts, paths, self._drawing,
                             set(self._pending), i == self._open_scene,
                             i == self._current)
            card.toggled.connect(self._toggle_scene)
            card.redoAsked.connect(self.redo_prompts)
            card.drawAsked.connect(self.draw_slot)
            card.drawAllAsked.connect(self.draw_scene)
            card.viewAsked.connect(self.open_viewer)
            self.feed_layout.insertWidget(i, card)
            self._cards.append(card)

        wanted = sum(len(v) for v in by_scene.values())
        shots = sum(len(v) for v in base["scenes"].values())
        self.shots_cap.setText(
            f"THE SCENES — {shots} shots · {made}/{wanted} drawn"
            if wanted else f"THE SCENES — {shots} shots")
        self.feed.verticalScrollBar().setValue(top)

    def _toggle_scene(self, index: int):
        self._open_scene = -1 if self._open_scene == index else index
        self._current = index
        self._show_feed()
        self._sync_list_mark()

    def _sync_list_mark(self):
        self.scene_list.blockSignals(True)
        self.scene_list.setCurrentRow(min(self._current,
                                          max(0, self.scene_list.count() - 1)))
        self.scene_list.blockSignals(False)

    # ---- one picture at a time ----------------------------------------------

    def draw_slot(self, scene: int, index: int):
        """Draw the one picture that was clicked, leaving the window alone.

        A single frame is twenty seconds of waiting; locking the whole window
        for it would mean the other fifty cannot be looked at meanwhile.
        """
        self._queue([(scene, index)])

    def draw_scene(self, scene: int):
        """Every picture this scene is still missing."""
        prompts = frames.load_prompts(self.project.id, self.style).get(str(scene), [])
        self._queue([(scene, i) for i in range(len(prompts))])

    def _queue(self, keys: list):
        """Put pictures in line, then let as many start as the lanes allow.

        One thread per click was fine while a click was one picture. A button
        that asks for a whole scene, pressed on several scenes, would have kie
        working on a dozen at once and the machine holding a dozen threads to
        wait for them.
        """
        if self._busy:
            return
        reference = self._reference()
        if not reference:
            self.status.setText("Draw the poster first — every picture follows it.")
            return

        added = 0
        for key in keys:
            scene, index = key
            if key in self._drawing or key in self._pending:
                continue
            # the slot only offers itself when empty, but the guard belongs here
            # as well: this is where money is spent and a picture overwritten
            if frames.picture_path(self.project.id, self.style,
                                   str(scene), index).exists():
                continue
            self._pending.append(key)
            added += 1
        if not added:
            return
        self._pump()
        self._touch(keys)

    def _pump(self):
        reference = self._reference()
        while self._pending and len(self._drawing) < DRAW_LANES:
            scene, index = self._pending.pop(0)
            self._drawing.add((scene, index))
            run_async(self, frames.draw_slot_job, self._slot_done, self._slot_broke,
                      self.project.id, self.style, scene, index,
                      self._model, self._aspect, self._resolution, reference)
        self._say_progress()

    def _touch(self, keys: list):
        """Redraw only the slots named, and the counts that go with them.

        Everything a finished picture changes is small and local. Rebuilding
        the feed for it deleted nineteen cards including whichever one the
        mouse was resting on, which is how the window came down.
        """
        scenes = {scene for scene, _ in keys}
        by_scene = frames.load_prompts(self.project.id, self.style)
        for scene in scenes:
            if not 0 <= scene < len(self._cards):
                continue
            card = self._cards[scene]
            total = len(by_scene.get(str(scene), []))
            paths = [self._picture(scene, i) for i in range(total)]
            for index in range(total):
                slot = card.slots.get(index)
                if slot is not None:
                    slot.render(paths[index], (scene, index) in self._drawing,
                                (scene, index) in self._pending, True)
            card.set_counts(sum(1 for p in paths if p))
            card.set_waiting(sum(1 for i, p in enumerate(paths)
                                 if not p and (scene, i) not in self._drawing
                                 and (scene, i) not in self._pending))
            self._touch_list_row(scene, by_scene)
        self._touch_totals(by_scene)

    def _picture(self, scene: int, index: int) -> str:
        path = frames.picture_path(self.project.id, self.style, str(scene), index)
        return str(path) if path.exists() else ""

    def _touch_list_row(self, scene: int, by_scene: dict):
        item = self.scene_list.item(scene)
        if item is None:
            return
        base = frames.load_base(self.project.id)
        shots = len(base["scenes"].get(str(scene), []))
        ready = len(by_scene.get(str(scene), []))
        made = sum(1 for i in range(ready) if self._picture(scene, i))
        mark = "·" if not shots else ("✓" if made and made == ready
                                      else ("»" if ready else "◔"))
        item.setText(f"{mark}  {scene + 1}. {shots} shots · {made}/{ready} drawn")

    def _touch_totals(self, by_scene: dict):
        base = frames.load_base(self.project.id)
        wanted = sum(len(v) for v in by_scene.values())
        made = sum(1 for scene in by_scene
                   for i in range(len(by_scene[scene]))
                   if self._picture(int(scene), i))
        shots = sum(len(v) for v in base["scenes"].values())
        self.shots_cap.setText(
            f"THE SCENES — {shots} shots · {made}/{wanted} drawn"
            if wanted else f"THE SCENES — {shots} shots")
        self.add_btn.setEnabled(bool(made) and not self._busy)

    def _say_progress(self):
        if not (self._drawing or self._pending):
            return
        self.status.setText(f"{len(self._drawing)} drawing"
                            + (f", {len(self._pending)} waiting"
                               if self._pending else ""))

    def _slot_done(self, result: dict):
        key = (result["scene"], result["index"])
        self._drawing.discard(key)
        if result["error"]:
            self.status.setText(f"Scene {key[0] + 1}, picture {key[1] + 1}: "
                                f"{result['error']}")
        started = list(self._pending[:DRAW_LANES])
        self._pump()
        if not (self._drawing or self._pending):
            self.status.setText(f"Scene {key[0] + 1}, picture {key[1] + 1} drawn")
        # this one, plus whichever the freed lane just picked up
        self._touch([key] + started)

    def _slot_broke(self, message: str):
        """The job itself fell over — it catches its own failures, so this is
        something else entirely. Nothing is known about which slot it was, so
        the queue is dropped rather than left half-running."""
        self._drawing.clear()
        self._pending.clear()
        self.status.setText(f"Drawing stopped: {message[:140]}")
        self._refresh()

    def redo_prompts(self, index: int):
        """Write one scene's prompts again, keeping every other scene's."""
        base = frames.load_base(self.project.id)
        shots = base["scenes"].get(str(index), [])
        if not shots:
            self.status.setText("That scene has not been read yet.")
            return
        self._redo_index = index
        self._busy_on(f"Writing scene {index + 1} again…")
        run_async(self, frames.stylize_scene, self._on_reprompted, self._fail,
                  shots, base["details"], frames.load_style(self.style), set(),
                  base["world"])

    def _on_reprompted(self, written: list):
        index = self._redo_index
        by_scene = frames.load_prompts(self.project.id, self.style)
        by_scene[str(index)] = written
        frames.save_prompts(self.project.id, self.style, by_scene)
        self._busy = False
        self.progress.setVisible(False)
        self.status.setText(f"Scene {index + 1} · {len(written)} prompts rewritten")
        self._open_scene = index
        self._refresh()
