"""자막 모양 설정용 위젯: 색 버튼, 글꼴 파일 등록, 미리보기."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QColorDialog, QPushButton, QSizePolicy, QWidget

from ..project import SubtitleSettings


@lru_cache(maxsize=None)
def _register(path: str) -> tuple[str, ...]:
    fid = QFontDatabase.addApplicationFont(path)
    return tuple(QFontDatabase.applicationFontFamilies(fid)) if fid >= 0 else ()


def register_font_file(path: str) -> list[str]:
    """글꼴 파일을 앱에 등록하고 글꼴 이름 목록을 돌려준다 (설치 없이 사용)."""
    return list(_register(path))


def font_file_families(path: str) -> list[str]:
    return register_font_file(path) if path else []


class ColorButton(QPushButton):
    color_changed = Signal(str)

    def __init__(self, color: str = "#FFFFFF") -> None:
        super().__init__()
        self.setFixedSize(46, 24)
        self.clicked.connect(self._pick)
        self.color = ""
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.color = QColor(color).name().upper() if QColor(color).isValid() else "#FFFFFF"
        self.setStyleSheet(f"background: {self.color}; border: 1px solid #888; border-radius: 3px")
        self.setToolTip(self.color)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self, "색 고르기")
        if c.isValid():
            self.set_color(c.name())
            self.color_changed.emit(self.color)


class SubtitleSample(QWidget):
    """16:9 화면 위에 자막이 어떻게 보일지 대략 그려 준다."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.style_ = SubtitleSettings()
        self.text = "자막 미리보기"

    def set_style(self, s: SubtitleSettings, text: str) -> None:
        self.style_ = s
        self.text = text
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        w = min(self.width(), h * 16 / 9)
        frame = QRectF((self.width() - w) / 2, 0, w, h)
        g = QLinearGradient(frame.topLeft(), frame.bottomRight())
        g.setColorAt(0, QColor(70, 110, 160))
        g.setColorAt(1, QColor(150, 120, 90))
        p.fillRect(frame, g)

        s = self.style_
        scale = h / 288.0              # libass 기준 높이 288에 맞춘 비율
        font = QFont(s.font_name)
        font.setPixelSize(max(6, int(s.font_size * scale)))
        font.setBold(s.bold)
        fm = QFontMetricsF(font)
        lines = self.text.split("\n")[:3]
        line_h = fm.height()
        block_h = line_h * len(lines)
        margin = s.margin_v * scale
        if s.position == "top":
            top = frame.top() + margin
        elif s.position == "middle":
            top = frame.center().y() - block_h / 2
        else:
            top = frame.bottom() - margin - block_h
        outline = s.outline * scale
        text_color = QColor(s.color)
        edge = QColor(s.outline_color)
        for i, line in enumerate(lines):
            tw = fm.horizontalAdvance(line)
            x = frame.center().x() - tw / 2
            y = top + i * line_h + fm.ascent()
            if s.box:
                box = QColor(edge)
                box.setAlpha(160)
                pad = max(2.0, outline)
                p.fillRect(QRectF(x - pad, top + i * line_h - pad / 2, tw + 2 * pad, line_h + pad), box)
            path = QPainterPath()
            path.addText(QPointF(x, y), font, line)
            if outline > 0 and not s.box:
                p.strokePath(path, QPen(edge, outline * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.fillPath(path, text_color)
