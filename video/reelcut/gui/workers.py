"""오래 걸리는 작업(분석·자막·렌더링)을 화면이 멈추지 않게 별도 스레드에서 실행."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from .. import logs
from ..ffmpeg import Cancelled


class TaskThread(QThread):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[["TaskThread"], Any], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False
        self.cancel_hook: Callable[[], None] | None = None

    def run(self) -> None:
        try:
            result = self._fn(self)
        except Cancelled:
            self.failed.emit("취소했어요.")
            return
        except Exception as e:  # 사용자에게 메시지로 보여준다
            if self._cancelled:
                self.failed.emit("취소했어요.")
            else:
                logs.exception("작업 실패", e)
                self.failed.emit(str(e) or e.__class__.__name__)
            return
        if self._cancelled:
            self.failed.emit("취소했어요.")
        else:
            self.done.emit(result)

    # 작업 함수에서 호출
    def report(self, fraction: float, message: str = "") -> None:
        self.progress.emit(float(fraction), message)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True
        if self.cancel_hook:
            self.cancel_hook()
