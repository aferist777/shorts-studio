"""Everything about Gen frames that is a setting rather than a step.

It used to be a bare menu hanging off a gear — three lists of options one after
another with no word saying which was which — plus a style editor taking half
the main window while the pictures it describes had nowhere to go.

Sections on the left, their settings on the right: the same shape as the app's
own settings, and it leaves the window behind it about its actual work.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from app.config import DEFAULTS, save_settings
from app.services import frames, kie_images

ENGINE, STYLE = 0, 1
WANTED_W, WANTED_H = 820, 560
EDGE = 40


class FramesSettings(QDialog):
    def __init__(self, project, settings: dict, style: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gen frames settings")
        self.setModal(True)
        self.project = project
        self.settings = settings
        self.style = style

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.sections = QListWidget()
        self.sections.setObjectName("CompactList")
        self.sections.addItems(["Engine", "Style"])
        self.sections.setCurrentRow(ENGINE)
        self.sections.currentRowChanged.connect(self._pick_section)
        body.addWidget(self.sections, 1)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_engine())
        self.pages.addWidget(self._build_style())
        body.addWidget(self.pages, 2)
        root.addLayout(body, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("Primary")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        root.addLayout(foot)

        self._load_engine()
        self._load_styles()
        self._fit_over_parent()

    def _fit_over_parent(self):
        window = self.parent().window() if self.parent() else None
        area = window.geometry() if window else self.screen().availableGeometry()
        self.resize(min(WANTED_W, max(area.width() - 2 * EDGE, self.minimumWidth())),
                    min(WANTED_H, max(area.height() - 2 * EDGE, self.minimumHeight())))
        self.move(area.center() - self.rect().center())

    def _pick_section(self, row: int):
        self.pages.setCurrentIndex(max(0, row))

    # ---- engine -------------------------------------------------------------

    def _build_engine(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.model_box = QComboBox()
        for key, label in kie_images.model_choices():
            self.model_box.addItem(label, key)
        self.aspect_box = QComboBox()
        self.aspect_box.addItems(kie_images.ASPECTS)
        self.res_box = QComboBox()
        self.res_box.addItems(kie_images.RESOLUTIONS)

        for caption, widget in (("MODEL", self.model_box),
                                ("SHAPE", self.aspect_box),
                                ("QUALITY", self.res_box)):
            label = QLabel(caption)
            label.setObjectName("FieldLabel")
            lay.addWidget(label)
            lay.addWidget(widget)

        # what it costs sits under the dial that changes it
        self.prices = QLabel()
        self.prices.setObjectName("Hint")
        self.prices.setTextFormat(Qt.RichText)
        lay.addWidget(self.prices)

        self.estimate = QLabel()
        self.estimate.setObjectName("ProjMeta")
        self.estimate.setWordWrap(True)
        lay.addWidget(self.estimate)

        lay.addStretch(1)
        self.model_box.currentIndexChanged.connect(
            lambda _=0: self._save("draw_model", self.model_box.currentData()))
        self.aspect_box.currentIndexChanged.connect(
            lambda _=0: self._save("draw_aspect", self.aspect_box.currentText()))
        self.res_box.currentIndexChanged.connect(
            lambda _=0: self._save("draw_resolution", self.res_box.currentText()))
        return page

    def _load_engine(self):
        for box, key in ((self.model_box, "draw_model"),
                         (self.aspect_box, "draw_aspect"),
                         (self.res_box, "draw_resolution")):
            wanted = self.settings.get(key, DEFAULTS[key])
            box.blockSignals(True)
            index = box.findData(wanted) if box is self.model_box else box.findText(wanted)
            box.setCurrentIndex(max(0, index))
            box.blockSignals(False)
        self._show_prices()

    def _save(self, key: str, value: str):
        self.settings[key] = value
        save_settings(self.settings)
        self._show_prices()

    def _pictures(self) -> int:
        """How many this project would draw — prompts if it has them, shots if not."""
        prompts = frames.load_prompts(self.project.id, self.style)
        if prompts:
            return sum(len(v) for v in prompts.values())
        base = frames.load_base(self.project.id)
        if base["scenes"]:
            return sum(len(v) for v in base["scenes"].values())
        return len(self.project.scenes)

    def _show_prices(self):
        model = self.model_box.currentData()
        chosen = self.res_box.currentText()
        rows = []
        for resolution in kie_images.RESOLUTIONS:
            credits, dollars = kie_images.price_of(model, resolution)
            line = f"{resolution} — {credits} credits · ${dollars:.2f} per picture"
            rows.append(f"<b>{line}</b>" if resolution == chosen else line)
        self.prices.setText("<br>".join(rows))

        count = self._pictures()
        _, dollars = kie_images.price_of(model, chosen)
        self.estimate.setText(
            f"This project draws about {count} pictures — "
            f"${dollars * count:.2f} at {chosen}."
            if count else "")

    # ---- style --------------------------------------------------------------

    def _build_style(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        cap = QLabel("STYLE")
        cap.setObjectName("FieldLabel")
        lay.addWidget(cap)
        self.style_box = QComboBox()
        self.style_box.currentTextChanged.connect(self._on_style)
        lay.addWidget(self.style_box)

        note = QLabel("What the pictures are drawn like. It is the whole instruction "
                      "the model is given, so it is worth rewriting rather than "
                      "tweaking around.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        lay.addWidget(note)

        self.style_text = QTextEdit()
        self.style_text.setAcceptRichText(False)
        lay.addWidget(self.style_text, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.save_btn = QPushButton("Save style")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._save_style)
        row.addWidget(self.save_btn)
        lay.addLayout(row)
        return page

    def _load_styles(self):
        names = frames.style_names() or ["mad"]
        self.style_box.blockSignals(True)
        self.style_box.clear()
        self.style_box.addItems(names)
        index = self.style_box.findText(self.style)
        self.style_box.setCurrentIndex(max(0, index))
        self.style_box.blockSignals(False)
        self.style = self.style_box.currentText()
        self.style_text.setPlainText(frames.load_style(self.style))

    def _on_style(self, name: str):
        if not name:
            return
        self.style = name
        self.style_text.setPlainText(frames.load_style(name))
        self.settings["draw_style"] = name
        save_settings(self.settings)
        self._show_prices()      # a different style has its own prompts, and count

    def _save_style(self):
        frames.save_style(self.style, self.style_text.toPlainText())
        self.save_btn.setText("Saved")
        self.save_btn.setEnabled(False)
        self.style_text.textChanged.connect(self._style_edited)

    def _style_edited(self):
        self.save_btn.setText("Save style")
        self.save_btn.setEnabled(True)
