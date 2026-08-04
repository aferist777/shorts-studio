"""Launch the app, grab a PNG of the window, close it.

    python tools/snapshot.py [out.png] [step-index]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.main import MainWindow
from app.theme import qss

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/snapshot.png")
STEP = int(sys.argv[2]) if len(sys.argv) > 2 else 0


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(qss())
    window = MainWindow()
    window.show()
    if STEP:
        QTimer.singleShot(300, lambda: window.center.set_step(STEP))

    def grab():
        OUT.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(OUT))
        print(f"saved {OUT.resolve()}")
        window.close()   # runs the media-player teardown
        app.quit()

    QTimer.singleShot(1200, grab)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
