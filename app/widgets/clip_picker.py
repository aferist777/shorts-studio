"""Thumbnail grid for choosing one clip. No video plays here — thumbs only."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.services import footage
from app.services.worker import run_async

TILE_W, TILE_H = 108, 192   # 9:16, small enough to fit five across
COLUMNS = 5


def _fetch_thumbs(candidates: list, progress=None) -> list:
    paths = []
    for i, candidate in enumerate(candidates):
        if progress:
            progress(f"Thumbnail {i + 1} of {len(candidates)}")
        paths.append(footage.thumbnail(candidate))
    return paths


class ClipTile(QFrame):
    chosen = Signal(int)

    def __init__(self, index: int, candidate: dict):
        super().__init__()
        self.setObjectName("ClipTile")
        self.index = index
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(TILE_W + 12)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self.image = QLabel("…")
        self.image.setObjectName("ClipThumb")
        self.image.setFixedSize(TILE_W, TILE_H)
        self.image.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.image)

        meta = QLabel(f"{candidate['source']} · {candidate['duration']:.0f}s")
        meta.setObjectName("ProjMeta")
        meta.setAlignment(Qt.AlignCenter)
        lay.addWidget(meta)

        self.setToolTip(f"{candidate['term']}\n{candidate['credit']}")

    def set_thumb(self, path: str):
        if not path:
            self.image.setText("no preview")
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image.setText("no preview")
            return
        self.image.setPixmap(pixmap.scaled(TILE_W, TILE_H, Qt.KeepAspectRatioByExpanding,
                                           Qt.SmoothTransformation))

    def mousePressEvent(self, event):
        self.chosen.emit(self.index)
        super().mousePressEvent(event)


class ClipPicker(QDialog):
    def __init__(self, candidates: list, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick a clip")
        self.resize(680, 620)
        self.candidates = candidates
        self.selected = None
        self._tiles = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QLabel(title)
        head.setObjectName("DlgTitle")
        head.setWordWrap(True)
        root.addWidget(head)

        hint = QLabel(f"{len(candidates)} clips · click one to use it")
        hint.setObjectName("Hint")
        root.addWidget(hint)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        root.addWidget(self.progress)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setSpacing(8)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        for i, candidate in enumerate(candidates):
            tile = ClipTile(i, candidate)
            tile.chosen.connect(self._choose)
            grid.addWidget(tile, i // COLUMNS, i % COLUMNS)
            self._tiles.append(tile)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        run_async(self, _fetch_thumbs, self._on_thumbs, self._on_thumb_fail, candidates)

    def _on_thumbs(self, paths: list):
        for tile, path in zip(self._tiles, paths):
            tile.set_thumb(path)
        self.progress.setVisible(False)

    def _on_thumb_fail(self, message: str):
        self.progress.setVisible(False)

    def _choose(self, index: int):
        self.selected = self.candidates[index]
        self.accept()
