"""Left pane — project list, with the two filters that make a long list usable."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from app.services import library

ANY_PROGRESS = -1
ANY_VIDEO = "__any__"
NO_VIDEO = "__none__"


class ElidingLabel(QLabel):
    """A label that gives way instead of pushing the pane wider.

    A plain QLabel demands room for its whole text, and one long project title
    was enough to set the floor for the entire column.
    """

    def __init__(self, text=""):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._full = text
        self._applying = False
        self._apply()

    def setText(self, text):
        self._full = text
        self._apply()

    def _apply(self):
        if self._applying:
            return
        self._applying = True
        width = max(0, self.width() - 2)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, width)
                        if width else self._full)
        self._applying = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()


class ProjectCard(QFrame):
    clicked = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, project, pct: int):
        super().__init__()
        self.setObjectName("ProjCard")
        self.project_id = project.id
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 6, 5)
        lay.setSpacing(6)

        name = ElidingLabel(project.title or "Untitled")
        name.setObjectName("ProjName")

        # the second line this card used to carry, now on hover
        scenes = len(project.scenes)
        detail = [f"{scenes} scene{'s' if scenes != 1 else ''}", project.language,
                  f"{pct}% done"]
        if project.source_title:
            detail.append(f"from “{project.source_title}”")
        self.setToolTip(f"{project.title or 'Untitled'}\n" + " · ".join(detail))

        done = QLabel(f"{pct}%")
        done.setObjectName("ProjMeta")
        done.setFixedWidth(30)
        done.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        delete = QPushButton("×")
        delete.setObjectName("CardDel")
        delete.setCursor(Qt.PointingHandCursor)
        delete.setToolTip("Delete project")
        delete.clicked.connect(lambda: self.deleteRequested.emit(self.project_id))

        lay.addWidget(name, 1)
        lay.addWidget(done, 0)
        lay.addWidget(delete, 0)

    def set_selected(self, on: bool):
        self.setProperty("selected", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        self.clicked.emit(self.project_id)
        super().mousePressEvent(event)


class ProjectListPane(QWidget):
    projectSelected = Signal(str)
    addRequested = Signal()
    deleteRequested = Signal(str)
    libraryRequested = Signal()
    ideasRequested = Signal()

    def __init__(self, store):
        super().__init__()
        self.setObjectName("Pane")
        self.store = store
        self._cards = {}
        self._selected = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("PaneHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 9, 10, 9)
        title = QLabel("Projects")
        title.setObjectName("PaneTitle")
        self.count = QLabel("")
        self.count.setObjectName("PaneCount")
        videos = QPushButton("Videos")
        videos.setCursor(Qt.PointingHandCursor)
        videos.setToolTip("All renders and the batch queue  (Ctrl+L)")
        videos.clicked.connect(self.libraryRequested.emit)

        # split button: the left half acts, the right half offers the other way in
        add = QPushButton("New")
        add.setObjectName("AddBtnL")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self.addRequested.emit)

        more = QToolButton()
        more.setObjectName("AddBtnR")
        more.setCursor(Qt.PointingHandCursor)
        more.setPopupMode(QToolButton.InstantPopup)
        more.setText("▾")
        menu = QMenu(more)
        menu.addAction("New project", self.addRequested.emit)
        menu.addAction("New ideas…", self.ideasRequested.emit)
        more.setMenu(menu)

        split = QHBoxLayout()
        split.setSpacing(0)
        split.addWidget(add)
        split.addWidget(more)

        hl.addWidget(title)
        hl.addWidget(self.count)
        hl.addStretch(1)
        hl.addWidget(videos)
        hl.addLayout(split)
        root.addWidget(head)

        # ---- filters --------------------------------------------------------
        filters = QWidget()
        filters.setObjectName("PaneHead")
        fl = QHBoxLayout(filters)
        fl.setContentsMargins(8, 6, 8, 6)
        fl.setSpacing(6)

        self.progress_filter = QComboBox()
        self.progress_filter.setToolTip("How far along a project is")
        self.progress_filter.addItem("Any progress", ANY_PROGRESS)
        for pct in library.STAGES:
            self.progress_filter.addItem(f"{pct}%", pct)
        self.progress_filter.currentIndexChanged.connect(lambda _=0: self.refresh())

        self.video_filter = QComboBox()
        self.video_filter.setToolTip("The video in the ideas base a project came from")
        # long video names must not widen the column
        self.video_filter.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.video_filter.setMinimumContentsLength(8)
        self.video_filter.currentIndexChanged.connect(lambda _=0: self.refresh())

        fl.addWidget(self.progress_filter, 2)
        fl.addWidget(self.video_filter, 3)
        root.addWidget(filters)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.list_layout = QVBoxLayout(holder)
        self.list_layout.setContentsMargins(8, 8, 8, 8)
        self.list_layout.setSpacing(3)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(holder)
        root.addWidget(self.scroll, 1)

        self.empty = QLabel("No projects yet.\nHit New to start one.")
        self.empty.setObjectName("Hint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.list_layout.insertWidget(0, self.empty)

        self.refresh()

    # ---- filters -----------------------------------------------------------

    def _video_choices(self) -> list:
        """(id, name) for every ideas video some project came out of.

        The name is taken from the ideas base rather than from the project, so
        renaming there shows through; a project whose video has been deleted
        keeps the name it was created with.
        """
        from app.services import ideas
        known = {v.get("video_id"): v.get("title") for v in ideas.load_index()}
        found = {}
        for project in self.store.projects:
            vid = project.source_video_id
            if vid and vid not in found:
                found[vid] = known.get(vid) or project.source_title or vid
        return sorted(found.items(), key=lambda pair: pair[1].lower())

    def _rebuild_video_filter(self):
        wanted = self.video_filter.currentData() or ANY_VIDEO
        self.video_filter.blockSignals(True)
        self.video_filter.clear()
        self.video_filter.addItem("Any video", ANY_VIDEO)
        for vid, name in self._video_choices():
            self.video_filter.addItem(name, vid)
        if any(not p.source_video_id for p in self.store.projects):
            self.video_filter.addItem("Not from a video", NO_VIDEO)
        index = self.video_filter.findData(wanted)
        self.video_filter.setCurrentIndex(max(0, index))
        self.video_filter.blockSignals(False)

    def _passes(self, project) -> bool:
        pct = self.progress_filter.currentData()
        if pct not in (None, ANY_PROGRESS) and library.progress_pct(project) != pct:
            return False
        video = self.video_filter.currentData() or ANY_VIDEO
        if video == NO_VIDEO:
            return not project.source_video_id
        if video != ANY_VIDEO and project.source_video_id != video:
            return False
        return True

    # ---- list --------------------------------------------------------------

    def refresh(self):
        for card in self._cards.values():
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        self._rebuild_video_filter()
        everything = self.store.projects
        projects = [p for p in everything if self._passes(p)]

        if len(projects) == len(everything):
            self.count.setText(str(len(everything)) if everything else "")
        else:
            self.count.setText(f"{len(projects)} of {len(everything)}")
        self.empty.setVisible(not projects)
        self.empty.setText("No projects yet.\nHit New to start one." if not everything
                           else "Nothing matches these filters.")

        for i, p in enumerate(projects):
            card = ProjectCard(p, library.progress_pct(p))
            card.clicked.connect(self.select)
            card.deleteRequested.connect(self.deleteRequested.emit)
            self.list_layout.insertWidget(i + 1, card)
            self._cards[p.id] = card

        if self._selected in self._cards:
            self._cards[self._selected].set_selected(True)
        elif self.store.get(self._selected) is None and projects:
            # only when the open project is really gone — a filter hiding it is
            # not a reason to swap what the workspace is showing
            self.select(projects[0].id)

    def select(self, project_id: str):
        for pid, card in self._cards.items():
            card.set_selected(pid == project_id)
        self._selected = project_id
        self.projectSelected.emit(project_id)
