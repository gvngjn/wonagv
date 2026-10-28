"""ReelCut 실행 진입점."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from ..ffmpeg import FFmpegError, ffmpeg_path, ffprobe_path
    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("ReelCut")
    app.setStyle("Fusion")
    try:
        ffmpeg_path()
        ffprobe_path()
    except FFmpegError as e:
        QMessageBox.critical(None, "ReelCut", str(e))
        return 1
    w = MainWindow()
    w.show()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, w.check_recovery)
    return app.exec()
