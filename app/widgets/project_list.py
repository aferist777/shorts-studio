"""Left pane — project list."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)

from app.theme import C


class ProjectCard(QFrame):
    clicked = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, project):
        super().__init__()
        self.setObjectName("ProjCard")
        self.project_id = project.id
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 8, 8)
        lay.setSpacing(8)

        text = QVBoxLayout()
        text.setSpacing(1)
        name = QLabel(project.title or "Untitled")
        name.setObjectName("ProjName")
        scenes = len(project.scenes)
        meta = QLabel(f"{scenes} scene{'s' if scenes != 1 else ''} · {project.language}")
        meta.setObjectName("ProjMeta")
        text.addWidget(name)
        text.addWidget(meta)

        delete = QPushButton("×")
        delete.setObjectName("CardDel")
        delete.setCursor(Qt.PointingHandCursor)
        delete.setToolTip("Delete project")
        delete.clicked.connect(lambda: self.deleteRequested.emit(self.project_id))

        lay.addLayout(text, 1)
        lay.addWidget(delete, 0, Qt.AlignTop)

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

    def refresh(self):
        for card in self._cards.values():
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        projects = self.store.projects
        self.count.setText(str(len(projects)) if projects else "")
        self.empty.setVisible(not projects)

        for i, p in enumerate(projects):
            card = ProjectCard(p)
            card.clicked.connect(self.select)
            card.deleteRequested.connect(self.deleteRequested.emit)
            self.list_layout.insertWidget(i + 1, card)
            self._cards[p.id] = card

        if self._selected in self._cards:
            self._cards[self._selected].set_selected(True)
        elif projects:
            self.select(projects[0].id)

    def select(self, project_id: str):
        for pid, card in self._cards.items():
            card.set_selected(pid == project_id)
        self._selected = project_id
        self.projectSelected.emit(project_id)
