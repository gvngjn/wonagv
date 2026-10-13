"""음악 파형 위에서 '몇 초부터 쓸지'를 고르는 게이지 + 미리듣기."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


def _mmss(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


class MusicGauge(QWidget):
    """파형 + 사용 구간(주황) + 시작 핸들. 클릭/드래그로 시작 위치를 정한다."""

    start_changed = Signal(float)
    play_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("클릭하거나 끌어서 음악 시작 위치를 정해요 · 더블클릭: 그 위치부터 듣기 · ←/→: 0.1초씩")
        self.peaks: list[float] = []
        self.duration = 0.0
        self.start = 0.0
        self.length = 0.0         # 실제로 쓰이는 길이 (완성 영상 길이)
        self.beats: list[float] = []
        self.playhead: float | None = None
        self._drag_offset: float | None = None

    # ---- 데이터 ----
    def set_waveform(self, peaks, duration: float) -> None:
        self.peaks = [float(p) for p in peaks]
        self.duration = duration
        self.update()

    def set_selection(self, start: float, length: float) -> None:
        self.start, self.length = start, length
        self.update()

    def set_beats(self, beats: list[float]) -> None:
        self.beats = beats
        self.update()

    def set_playhead(self, t: float | None) -> None:
        self.playhead = t
        self.update()

    # ---- 좌표 ----
    def _area(self) -> QRectF:
        return QRectF(self.rect()).adjusted(6, 18, -6, -6)

    def _x(self, t: float) -> float:
        a = self._area()
        return a.left() + (t / self.duration) * a.width() if self.duration > 0 else a.left()

    def _t(self, x: float) -> float:
        a = self._area()
        if self.duration <= 0 or a.width() <= 0:
            return 0.0
        return min(max(0.0, (x - a.left()) / a.width() * self.duration), self.duration)

    def _max_start(self) -> float:
        # 노래가 영상보다 짧아져도 고를 수 있게 끝 0.5초 전까지 허용
        return max(0.0, self.duration - 0.5)

    def _set_start(self, t: float) -> None:
        t = round(min(max(0.0, t), self._max_start()), 2)
        if abs(t - self.start) > 1e-6:
            self.start = t
            self.update()
            self.start_changed.emit(t)

    # ---- 그리기 ----
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        a = self._area()
        p.fillRect(self.rect(), pal.base())
        if self.duration <= 0:
            p.setPen(pal.placeholderText().color())
            p.drawText(self.rect(), Qt.AlignCenter, "음악을 등록하면 파형이 표시돼요")
            return

        end = min(self.duration, self.start + self.length) if self.length > 0 else self.duration
        sel = QRectF(self._x(self.start), a.top(), max(2.0, self._x(end) - self._x(self.start)), a.height())
        p.fillRect(sel, QColor(255, 140, 40, 45))

        # 파형 (사용 구간은 진하게)
        mid = a.center().y()
        n = len(self.peaks)
        if n:
            cols = max(1, int(a.width()))
            for i in range(cols):
                t = (i + 0.5) / cols * self.duration
                k = min(n - 1, int(i / cols * n))
                k2 = min(n, max(k + 1, int((i + 1) / cols * n)))
                v = max(self.peaks[k:k2])
                h = max(1.0, v * a.height() * 0.48)
                inside = self.start <= t <= end
                p.setPen(QColor(230, 110, 20) if inside else QColor(150, 150, 150, 150))
                x = a.left() + i
                p.drawLine(int(x), int(mid - h), int(x), int(mid + h))

        # 비트 눈금
        p.setPen(QPen(QColor(90, 90, 90, 110), 1))
        for b in self.beats:
            if 0 <= b <= self.duration:
                x = self._x(b)
                p.drawLine(int(x), int(a.bottom() - 6), int(x), int(a.bottom()))

        # 시작 핸들
        sx = self._x(self.start)
        p.setPen(QPen(QColor(230, 90, 0), 2))
        p.drawLine(int(sx), int(a.top()), int(sx), int(a.bottom()))
        tri = QPainterPath()
        tri.moveTo(sx - 6, a.top() - 8)
        tri.lineTo(sx + 6, a.top() - 8)
        tri.lineTo(sx, a.top())
        tri.closeSubpath()
        p.fillPath(tri, QColor(230, 90, 0))

        # 재생 위치
        if self.playhead is not None:
            px = self._x(self.playhead)
            p.setPen(QPen(QColor(30, 120, 255), 2))
            p.drawLine(int(px), int(a.top()), int(px), int(a.bottom()))

        # 글자
        p.setPen(pal.text().color())
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f)
        label = f"{_mmss(self.start)}부터"
        if self.length > 0:
            label += f" · {_mmss(end - self.start)} 사용"
        p.drawText(QRectF(sx + 8, 0, 260, 16), Qt.AlignLeft | Qt.AlignVCenter, label)
        p.setPen(pal.placeholderText().color())
        p.drawText(QRectF(0, 0, self.width() - 6, 16), Qt.AlignRight | Qt.AlignVCenter, _mmss(self.duration))

    # ---- 마우스 / 키보드 ----
    def mousePressEvent(self, e) -> None:
        if self.duration <= 0 or e.button() != Qt.LeftButton:
            return
        t = self._t(e.position().x())
        end = self.start + self.length if self.length > 0 else self.duration
        if self.start <= t <= end and abs(self._x(t) - self._x(self.start)) > 6:
            self._drag_offset = t - self.start     # 구간 통째로 옮기기
        else:
            self._drag_offset = 0.0
            self._set_start(t)

    def mouseMoveEvent(self, e) -> None:
        if self._drag_offset is not None:
            self._set_start(self._t(e.position().x()) - self._drag_offset)
        elif self.duration > 0:
            near = abs(e.position().x() - self._x(self.start)) <= 6
            self.setCursor(Qt.SizeHorCursor if near else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, _e) -> None:
        self._drag_offset = None

    def mouseDoubleClickEvent(self, e) -> None:
        if self.duration > 0:
            self.play_requested.emit(self._t(e.position().x()))

    def keyPressEvent(self, e) -> None:
        step = 1.0 if e.modifiers() & Qt.ShiftModifier else 0.1
        if e.key() == Qt.Key_Left:
            self._set_start(self.start - step)
        elif e.key() == Qt.Key_Right:
            self._set_start(self.start + step)
        elif e.key() == Qt.Key_Space:
            self.play_requested.emit(self.start)
        else:
            super().keyPressEvent(e)


class MusicPreviewPlayer:
    """음악 미리듣기 (재생기는 처음 들을 때 만든다)."""

    def __init__(self, parent: QWidget, on_position, on_stopped) -> None:
        self._parent = parent
        self._on_position = on_position
        self._on_stopped = on_stopped
        self._player = None
        self._stop_at: float | None = None
        self._pending: float | None = None

    def _ensure(self):
        if self._player is None:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._player = QMediaPlayer(self._parent)
            self._audio = QAudioOutput(self._parent)
            self._player.setAudioOutput(self._audio)
            from .audio_devices import AudioDeviceManager
            AudioDeviceManager.instance().register(self._audio)
            self._player.positionChanged.connect(self._pos)
            self._player.mediaStatusChanged.connect(self._status)
            self._player.playbackStateChanged.connect(self._state)
        return self._player

    def play(self, path: str, start: float, stop_at: float | None = None) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        pl = self._ensure()
        self._stop_at = stop_at
        if pl.source() != QUrl.fromLocalFile(path):
            pl.setSource(QUrl.fromLocalFile(path))
            self._pending = start       # 파일이 열린 뒤에 위치 이동
        else:
            pl.setPosition(int(start * 1000))
        pl.play()
        if pl.mediaStatus() in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            pl.setPosition(int(start * 1000))

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def unload(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())

    @property
    def playing(self) -> bool:
        from PySide6.QtMultimedia import QMediaPlayer

        return self._player is not None and self._player.playbackState() == QMediaPlayer.PlayingState

    def _status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if self._pending is not None and status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._player.setPosition(int(self._pending * 1000))
            self._pending = None

    def _pos(self, ms: int) -> None:
        t = ms / 1000
        if self._stop_at is not None and t >= self._stop_at:
            self._player.pause()
            self._on_stopped()
            return
        self._on_position(t)

    def _state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if state != QMediaPlayer.PlayingState:
            self._on_stopped()
