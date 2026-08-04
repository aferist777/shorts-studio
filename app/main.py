"""Shorts Studio — desktop entry point."""

import sys
from pathlib import Path

# allow running as `python app/main.py` or `python -m app.main`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMessageBox, QSplitter, QWidget,
)

from app import config
from app.paths import find_ffmpeg
from app.services import worker
from app.store import Store
from app.theme import qss
from app.version import APP_NAME, APP_VERSION
from app.widgets.ideas_dialog import IdeasDialog
from app.widgets.library_dialog import LibraryDialog
from app.widgets.narrators_dialog import NarratorsDialog
from app.widgets.preview import PreviewPane
from app.widgets.project_list import ProjectListPane
from app.widgets.settings_dialog import SettingsDialog
from app.widgets.workspace import WorkspacePane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 660)

        self.store = Store()
        self.settings = config.load_settings()
        self._build_menubar()

        central = QWidget()
        central.setObjectName("Root")
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(5)
        splitter.setChildrenCollapsible(False)

        self.left = ProjectListPane(self.store)
        self.center = WorkspacePane(self.settings)
        self.right = PreviewPane()

        splitter.addWidget(self.left)
        splitter.addWidget(self.center)
        splitter.addWidget(self.right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([260, 720, 420])

        lay.addWidget(splitter)
        self.setCentralWidget(central)

        self.left.addRequested.connect(self.new_project)
        self.left.projectSelected.connect(self.open_project)
        self.left.deleteRequested.connect(self.delete_project)
        self.left.libraryRequested.connect(self.open_library)
        self.left.ideasRequested.connect(self.open_ideas)
        self.center.projectChanged.connect(self.on_project_changed)
        self.center.log.connect(self.right.append_log)
        self.center.renderReady.connect(self.right.set_video)

        if not self.store.projects:
            self.new_project()
        else:
            self.left.select(self.store.projects[0].id)

        if not find_ffmpeg(self.settings.get("ffmpeg_path", "")):
            self.right.append_log("ffmpeg not found — set it in Settings before rendering.")

    def _build_menubar(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        file_menu.addAction("New project", self.new_project)
        file_menu.addAction("New ideas…", self.open_ideas)
        file_menu.addAction("Duplicate script", self.duplicate_project)
        file_menu.addSeparator()
        file_menu.addAction("Videos…", self.open_library).setShortcut("Ctrl+L")
        file_menu.addAction("Narrators…", self.open_narrators).setShortcut("Ctrl+N")
        file_menu.addSeparator()
        file_menu.addAction("Settings…", self.open_settings)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        help_menu = mb.addMenu("Help")
        help_menu.addAction("About", self.about)

    # ---- projects ----------------------------------------------------------

    @property
    def current(self):
        return self.store.get(self.left._selected)

    def new_project(self):
        project = self.store.create()
        self.left.refresh()
        self.left.select(project.id)
        self.center.script.topic.setFocus()

    def open_project(self, project_id: str):
        project = self.store.get(project_id)
        self.center.set_project(project)
        self.right.set_project(project)

    def delete_project(self, project_id: str):
        project = self.store.get(project_id)
        if project is None:
            return
        confirm = QMessageBox.question(
            self, "Delete project",
            f"Delete “{project.title}”? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.store.delete(project_id)
        self.left.refresh()
        if not self.store.projects:
            self.new_project()

    def on_project_changed(self):
        project = self.current
        if project:
            self.store.touch(project)
        self.right.refresh()
        self.left.refresh()
        # voicing or attaching footage can be what makes a render possible
        self.center.refresh_render_readiness()

    # ---- misc --------------------------------------------------------------

    def duplicate_project(self):
        project = self.current
        if project is None:
            return
        copy = self.store.duplicate(project.id)
        self.left.refresh()
        self.left.select(copy.id)
        self.right.append_log(f"Duplicated “{project.title}” — script only, no media.")

    def open_ideas(self):
        dialog = IdeasDialog(self.store, self.settings, self)
        dialog.projectsCreated.connect(self._on_projects_created)
        dialog.exec()

    def _on_projects_created(self, project_ids: list):
        self.left.refresh()
        if project_ids:
            self.left.select(project_ids[0])
        self.right.append_log(f"Created {len(project_ids)} projects from a video.")

    def open_narrators(self):
        dialog = NarratorsDialog(self.settings, self)
        dialog.changed.connect(self.center.reload_narrators)
        dialog.exec()
        self.center.reload_narrators()

    def open_library(self):
        dialog = LibraryDialog(self.store, self.settings, self)
        dialog.playRequested.connect(self.right.set_video)
        dialog.storeChanged.connect(self._after_library_change)
        dialog.exec()
        self._after_library_change()

    def _after_library_change(self):
        self.left.refresh()
        self.center.refresh_render_readiness()

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = config.load_settings()
            self.right.append_log("Settings saved.")

    def closeEvent(self, event):
        self.center.shutdown()
        self.right.shutdown()
        worker.shutdown_all()
        super().closeEvent(event)

    def about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\n\n"
            "Topic in, vertical short out — with a stop at every step.",
        )


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(qss())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
