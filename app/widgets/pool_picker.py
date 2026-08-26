"""Choosing from what the project has already gathered.

Opened by the plus on a scene, and it only ever shows this project's own pool —
pieces cut out of its fragment, frames saved from it, and whatever else has
been collected. Several can be taken at once, because a scene usually wants
two or three and going back and forth for each would be tedious.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app.services import pool, thumbs

TILE_W, TILE_H = 150, 96
COLUMNS = 4


class PoolTile(QFrame):
    toggled = Signal(str)

    def __init__(self, item: dict, already_used: bool):
        super().__init__()
        self.setObjectName("SceneCard")
        self.item = item
        self.picked = False
        self.setFixedWidth(TILE_W + 16)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(3)

        picture = QLabel()
        picture.setFixedSize(TILE_W, TILE_H)
        picture.setAlignment(Qt.AlignCenter)
        picture.setObjectName("ClipThumb")
        pix = QPixmap(thumbs.small(item.get("thumb") or ""))
        if not pix.isNull():
            picture.setPixmap(pix.scaled(TILE_W, TILE_H, Qt.KeepAspectRatioByExpanding,
                                         Qt.SmoothTransformation))
        else:
            picture.setText(item["kind"])
        lay.addWidget(picture)

        caption = QLabel(("still · " if item["kind"] == "still" else "clip · ")
                         + ("in use" if already_used else "free"))
        caption.setObjectName("ProjMeta")
        caption.setAlignment(Qt.AlignCenter)
        lay.addWidget(caption)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.picked = not self.picked
        # the border does the talking; a checkbox on a thumbnail is a small
        # target and reads as clutter at this size
        self.setProperty("current", "yes" if self.picked else "no")
        self.style().unpolish(self)
        self.style().polish(self)
        self.toggled.emit(self.item["path"])


class PoolPicker(QDialog):
    def __init__(self, project, scene_number: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Footage for scene {scene_number}")
        self.resize(720, 560)
        self.chosen = []
        self._tiles = []

        items = pool.items(project.id)
        used = pool.used_paths(project)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(f"Scene {scene_number}")
        title.setObjectName("DlgTitle")
        hint = QLabel("Pick as many as the scene should show, in the order you want them")
        hint.setObjectName("Hint")
        head.addWidget(title)
        head.addWidget(hint)
        head.addStretch(1)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setSpacing(8)
        for i, item in enumerate(items):
            tile = PoolTile(item, item["path"] in used)
            tile.toggled.connect(self._on_toggled)
            grid.addWidget(tile, i // COLUMNS, i % COLUMNS)
            self._tiles.append(tile)
        if not items:
            empty = QLabel("Nothing gathered yet — cut some pieces out of the "
                           "fragment first.")
            empty.setObjectName("Hint")
            empty.setWordWrap(True)
            grid.addWidget(empty, 0, 0)
        grid.setRowStretch(grid.rowCount(), 1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        foot = QHBoxLayout()
        self.tally = QLabel("nothing picked")
        self.tally.setObjectName("Hint")
        foot.addWidget(self.tally)
        foot.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Add to scene")
        self.ok.setObjectName("Primary")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(self.ok)
        root.addLayout(foot)

    def _on_toggled(self, path: str):
        # kept in click order, because that is the order they will play in
        if path in self.chosen:
            self.chosen.remove(path)
        else:
            self.chosen.append(path)
        self.ok.setEnabled(bool(self.chosen))
        self.tally.setText(f"{len(self.chosen)} picked" if self.chosen
                           else "nothing picked")

    def picked_items(self) -> list:
        by_path = {t.item["path"]: t.item for t in self._tiles}
        return [by_path[p] for p in self.chosen if p in by_path]
