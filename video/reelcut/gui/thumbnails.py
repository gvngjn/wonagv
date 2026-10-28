"""클립 썸네일을 뒤에서 만들어 주는 도우미 (화면이 멈추지 않게)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap

from ..ffmpeg import thumbnail_png
from ..render import is_image

THUMB_W = 96
THUMB_H = THUMB_W * 9 // 16


def fit_box(pm: QPixmap) -> QPixmap:
    """가로세로 비율을 지키며 썸네일 칸(16:9) 안에 들어가게 줄인다."""
    return pm.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class ThumbnailLoader(QObject):
    ready = Signal(str, QPixmap)          # (키, 썸네일)
    _png = Signal(str, bytes)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cache: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._png.connect(self._on_png)      # 스레드 → 화면 스레드로 넘겨서 QPixmap 생성

    @staticmethod
    def key(path: str, at: float) -> str:
        return f"{path}|{at:.1f}"

    def get(self, path: str, at: float) -> QPixmap | None:
        """있으면 바로 돌려주고, 없으면 만들기 시작 (끝나면 ready 신호)."""
        k = self.key(path, at)
        if k in self._cache:
            return self._cache[k]
        if is_image(path):
            pm = QPixmap(path)
            if not pm.isNull():
                pm = fit_box(pm)
                self._cache[k] = pm
                return pm
            return None
        if k not in self._pending:
            self._pending.add(k)
            self._pool.submit(self._work, k, path, at)
        return None

    def _work(self, k: str, path: str, at: float) -> None:
        self._png.emit(k, thumbnail_png(path, at, THUMB_W * 2))

    def _on_png(self, k: str, data: bytes) -> None:
        self._pending.discard(k)
        pm = QPixmap()
        if data and pm.loadFromData(data, "PNG"):
            pm = fit_box(pm)
            self._cache[k] = pm
            self.ready.emit(k, pm)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
