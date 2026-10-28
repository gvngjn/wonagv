"""찍은 시각을 모르는 클립(메신저로 받은 사진 등)의 날짜를 직접 정하는 창."""
from __future__ import annotations

from PySide6.QtCore import QDate, QDateTime, QSize, QTime
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..project import Clip
from .thumbnails import THUMB_H, THUMB_W


def with_date(t: float, day: QDate) -> float:
    """시각(t)의 시:분은 그대로 두고 날짜만 바꾼다 (같은 날 안의 순서 유지)."""
    dt = QDateTime.fromSecsSinceEpoch(int(t))
    return float(QDateTime(day, dt.time()).toSecsSinceEpoch())


class ShotTimeDialog(QDialog):
    """확인을 누르면 고친 시각을 클립에 넣는다 (출처: manual). 건너뛰면 파일 시각 그대로."""

    def __init__(self, clips: list[Clip], thumbs=None, parent=None) -> None:
        super().__init__(parent)
        self.clips = clips
        self.setWindowTitle("찍은 날짜 정하기")
        self.resize(560, min(640, 180 + 56 * len(clips)))
        note = QLabel(f"클립 {len(clips)}개에 찍은 날짜 정보가 없어요 (메신저로 받았거나 편집한 파일은 지워지기도 해요).\n"
                      "지금은 파일 시각으로 넣어 뒀어요 — 날짜순 정렬이 맞도록 언제 찍었는지 알려 주세요.")
        note.setWordWrap(True)

        # 한꺼번에: 날짜만 바꾸고 시:분은 그대로 (같은 날 찍은 것들 순서 유지)
        self.all_date = QDateEdit(QDateTime.fromSecsSinceEpoch(int(clips[0].shot_at or 0)).date())
        self.all_date.setCalendarPopup(True)
        self.all_date.setDisplayFormat("yyyy-MM-dd")
        apply_all = QPushButton("모두 이 날짜로")
        apply_all.clicked.connect(self._apply_all)
        top = QHBoxLayout()
        top.addWidget(QLabel("한꺼번에:"))
        top.addWidget(self.all_date)
        top.addWidget(apply_all)
        top.addStretch(1)

        self.table = QTableWidget(len(clips), 3)
        self.table.setHorizontalHeaderLabels(["", "파일", "찍은 시각"])
        self.table.verticalHeader().setVisible(False)
        self.table.setIconSize(QSize(THUMB_W, THUMB_H))
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.edits: list[QDateTimeEdit] = []
        for r, c in enumerate(clips):
            icon = QTableWidgetItem()
            if thumbs is not None:
                pm = thumbs.get(c.path, 0.0)
                if pm is not None:
                    icon.setIcon(QIcon(pm))
            self.table.setItem(r, 0, icon)
            self.table.setItem(r, 1, QTableWidgetItem(c.name))
            e = QDateTimeEdit(QDateTime.fromSecsSinceEpoch(int(c.shot_at or 0)))
            e.setDisplayFormat("yyyy-MM-dd HH:mm")
            e.setCalendarPopup(True)
            self.table.setCellWidget(r, 2, e)
            self.edits.append(e)
            self.table.setRowHeight(r, THUMB_H + 8)
        if thumbs is not None:
            thumbs.ready.connect(self._on_thumb)
        self._thumbs = thumbs

        buttons = QDialogButtonBox()
        ok = buttons.addButton("이 날짜로 정하기", QDialogButtonBox.AcceptRole)
        skip = buttons.addButton("건너뛰기 (파일 시각 그대로)", QDialogButtonBox.RejectRole)
        ok.clicked.connect(self.accept)
        skip.clicked.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(buttons)

    def _on_thumb(self, key: str) -> None:
        from .thumbnails import ThumbnailLoader

        for r, c in enumerate(self.clips):
            if ThumbnailLoader.key(c.path, 0.0) == key:
                pm = self._thumbs.get(c.path, 0.0)
                if pm is not None:
                    self.table.item(r, 0).setIcon(QIcon(pm))

    def _apply_all(self) -> None:
        day = self.all_date.date()
        for e in self.edits:
            e.setDateTime(QDateTime(day, e.time()))

    def accept(self) -> None:
        for c, e in zip(self.clips, self.edits):
            c.shot_at = float(e.dateTime().toSecsSinceEpoch())
            c.shot_source = "manual"
        super().accept()


__all__ = ["QTime", "ShotTimeDialog", "with_date"]
