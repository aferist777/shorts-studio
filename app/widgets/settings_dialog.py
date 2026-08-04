"""API keys + ffmpeg location."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from app import config
from app.paths import find_ffmpeg


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.settings = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("API keys")
        title.setObjectName("DlgTitle")
        root.addWidget(title)

        hint = QLabel("Keys are stored in the Windows credential manager, never in the project folder.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)
        self.fields = {}
        for provider, label in config.PROVIDERS:
            edit = QLineEdit(config.get_key(provider))
            edit.setEchoMode(QLineEdit.Password)
            edit.setPlaceholderText("not set")
            self.fields[provider] = edit
            form.addRow(label, edit)
        root.addLayout(form)

        ff_title = QLabel("ffmpeg")
        ff_title.setObjectName("DlgTitle")
        root.addWidget(ff_title)

        ff_row = QHBoxLayout()
        self.ffmpeg_edit = QLineEdit(settings.get("ffmpeg_path", ""))
        self.ffmpeg_edit.setPlaceholderText(find_ffmpeg() or "not found — pick ffmpeg.exe")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        ff_row.addWidget(self.ffmpeg_edit, 1)
        ff_row.addWidget(browse)
        root.addLayout(ff_row)

        found = find_ffmpeg(settings.get("ffmpeg_path", ""))
        state = QLabel(f"Using: {found}" if found else "No ffmpeg found — rendering will not work.")
        state.setObjectName("Hint")
        state.setWordWrap(True)
        root.addWidget(state)

        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Locate ffmpeg", "", "ffmpeg (ffmpeg.exe ffmpeg)")
        if path:
            self.ffmpeg_edit.setText(path)

    def _save(self):
        for provider, edit in self.fields.items():
            config.set_key(provider, edit.text().strip())
        self.settings["ffmpeg_path"] = self.ffmpeg_edit.text().strip()
        config.save_settings(self.settings)
        self.accept()
