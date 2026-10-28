"""ReelCut 실행 진입점."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from ..ffmpeg import FFmpegError, ffmpeg_path, ffprobe_path
    from .main_window import MainWindow

    from .. import __version__, logs

    logs.setup(__version__)
    app = QApplication(sys.argv)
    app.setApplicationName("ReelCut")
    app.setStyle("Fusion")

    def show_crash(msg: str) -> None:
        QMessageBox.critical(
            None, "ReelCut 오류",
            f"예상 못한 문제가 생겼어요.\n{msg}\n\n작업은 자동 저장돼 있어요. 계속 쓰셔도 되지만, 이상하면 앱을 다시 켜 주세요.\n"
            f"자세한 기록: {logs.log_file()}")

    logs.install_crash_handler(show_crash)
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
