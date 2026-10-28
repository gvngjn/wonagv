"""완성 영상의 흐름을 보여주는 타임라인 막대 (클립 조각·자막·제목·화면 속 화면)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..project import Project
from ..render import pip_window
from ..timeline import build_segments, segment_starts, total_duration

PALETTE = ["#4C8BF5", "#F28B30", "#34A853", "#A142F4", "#EA4335", "#12B5CB", "#F9AB00", "#E8710A"]


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


class TimelineBar(QWidget):
    clip_clicked = Signal(int)          # 클립 목록에서의 번호

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.spans: list[tuple[float, float, int]] = []     # (시작, 끝, 클립 번호)
        self.subs: list[tuple[float, float]] = []
        self.titles: list[tuple[float, float]] = []
        self.pips: list[tuple[float, float]] = []
        self.total = 0.0
        self.names: list[str] = []
        self.hover: int | None = None

    def set_project(self, project: Project) -> None:
        segs = build_segments(project)
        index = {}
        for i, c in enumerate(project.clips):
            index.setdefault(c.path, i)
        starts = segment_starts(segs)
        self.spans = [(t, t + s.duration, index.get(s.path, 0)) for t, s in zip(starts, segs)]
        self.total = total_duration(segs)
        self.names = [c.name for c in project.clips]
        self.subs = [(e.start, e.end) for e in project.subtitles.entries]
        self.titles = [(e.start, e.end) for e in project.titles.entries]
        self.pips = [pip_window(p, self.total) for p in project.pips] if self.total else []
        self.setToolTip(f"완성 영상 {_fmt(self.total)} · 조각 {len(self.spans)}개" if self.spans else "")
        self.update()

    def _x(self, t: float, r: QRectF) -> float:
        return r.left() + (t / self.total) * r.width() if self.total > 0 else r.left()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        r = QRectF(self.rect()).adjusted(4, 4, -4, -14)
        if self.total <= 0:
            p.setPen(pal.placeholderText().color())
            p.drawText(self.rect(), Qt.AlignCenter, "클립을 추가하면 완성 영상의 흐름이 여기에 보여요")
            return
        clip_row = QRectF(r.left(), r.top(), r.width(), r.height() * 0.55)
        for a, b, k in self.spans:
            color = QColor(PALETTE[k % len(PALETTE)])
            if self.hover is not None and k != self.hover:
                color.setAlpha(110)
            x0, x1 = self._x(a, clip_row), self._x(b, clip_row)
            p.fillRect(QRectF(x0, clip_row.top(), max(1.0, x1 - x0), clip_row.height()), color)
        # 컷 경계
        if len(self.spans) <= 400:
            p.setPen(QPen(pal.base().color(), 1))
            for a, _b, _k in self.spans[1:]:
                x = self._x(a, clip_row)
                p.drawLine(int(x), int(clip_row.top()), int(x), int(clip_row.bottom()))
        # 자막 / 제목 / 화면 속 화면 줄
        rows = [(self.subs, QColor(90, 90, 90)), (self.titles, QColor(230, 90, 0)), (self.pips, QColor(20, 140, 200))]
        h = (r.height() - clip_row.height() - 2) / 3
        for i, (items, color) in enumerate(rows):
            y = clip_row.bottom() + 2 + i * h
            for a, b in items:
                x0, x1 = self._x(max(0, a), r), self._x(min(self.total, b), r)
                if x1 > x0:
                    p.fillRect(QRectF(x0, y, max(1.0, x1 - x0), h - 1), color)
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(f)
        y = self.height() - 13
        x = 4.0
        p.setPen(pal.placeholderText().color())
        p.drawText(QRectF(x, y, 40, 12), Qt.AlignLeft | Qt.AlignVCenter, "0:00")
        x += 40
        for (_items, color), label in zip(rows, ("자막", "제목", "화면 속 화면")):
            p.fillRect(QRectF(x, y + 3, 8, 8), color)
            p.setPen(pal.placeholderText().color())
            p.drawText(QRectF(x + 11, y, 90, 12), Qt.AlignLeft | Qt.AlignVCenter, label)
            x += 14 + p.fontMetrics().horizontalAdvance(label) + 10
        p.drawText(QRectF(self.width() - 104, y, 100, 12), Qt.AlignRight | Qt.AlignVCenter, _fmt(self.total))

    def _clip_at(self, x: float) -> int | None:
        r = QRectF(self.rect()).adjusted(4, 4, -4, -14)
        if self.total <= 0 or r.width() <= 0:
            return None
        t = (x - r.left()) / r.width() * self.total
        for a, b, k in self.spans:
            if a <= t < b:
                return k
        return None

    def mouseMoveEvent(self, e) -> None:
        k = self._clip_at(e.position().x())
        if k != self.hover:
            self.hover = k
            name = self.names[k] if k is not None and k < len(self.names) else ""
            self.setToolTip(f"{name} · 누르면 이 클립 선택" if name else
                            f"완성 영상 {_fmt(self.total)} · 조각 {len(self.spans)}개")
            self.update()

    def leaveEvent(self, _e) -> None:
        self.hover = None
        self.update()

    def mousePressEvent(self, e) -> None:
        k = self._clip_at(e.position().x())
        if k is not None:
            self.clip_clicked.emit(k)
