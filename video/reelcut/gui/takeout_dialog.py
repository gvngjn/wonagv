"""'내가 들은 노래' 창: 테이크아웃 시청 기록에서 그해 많이 들은 노래 → 골라서 mp3로 받기.

오른쪽에 테이크아웃 받는 법을 같이 보여 준다.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from ..takeout import History, TakeoutError, load_history, songs_csv

HOW_TO = """
<h3>구글 테이크아웃 받는 법</h3>
<ol>
<li>PC에서 <a href="https://takeout.google.com">takeout.google.com</a> 접속
(유튜브 쓰는 구글 계정으로 로그인)</li>
<li>맨 위 <b>모두 선택 해제</b></li>
<li>아래로 내려서 <b>YouTube 및 YouTube Music</b>만 체크</li>
<li>그 아래 <b>여러 형식</b> → <b>기록</b>을 <b>HTML → JSON</b>으로 바꾸고 확인
<br><span style="color:#c0392b">← 가장 중요해요</span></li>
<li><b>YouTube 데이터 모두 포함됨</b> → 모두 선택 해제 → <b>기록</b>만 체크 → 확인
<br>(올린 영상 같은 큰 파일이 빠져서 금방 끝나요)</li>
<li><b>다음 단계</b> → 이메일로 다운로드 링크 전송 · 1회 내보내기 · .zip</li>
<li><b>내보내기 생성</b> → 메일이 올 때까지 기다리기 (몇 분 ~ 몇 시간)</li>
<li>메일의 링크로 zip을 받아서 왼쪽 <b>파일 열기</b>로 고르기
<br>(zip 그대로 또는 압축을 풀어
<i>기록/시청 기록.json</i> · <i>history/watch-history.json</i>)</li>
</ol>
<p style="color:gray">· YouTube 기록 저장을 꺼 둔 기간은 파일에 없어요.<br>
· 파일은 이 컴퓨터에서만 읽고 어디로도 보내지 않아요.<br>
· 시청 기록 파일에는 본 영상이 모두 들어 있으니 공유할 때 조심하세요.</p>
"""


class TakeoutDialog(QDialog):
    download_requested = Signal(str)        # 고른 노래 링크 → 음악 탭에서 mp3로 받기

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("내가 들은 노래 (구글 테이크아웃)")
        self.resize(1000, 620)
        self.history: History | None = None
        self.songs = []

        open_btn = QPushButton("📂 파일 열기…")
        open_btn.setToolTip("테이크아웃 zip 또는 시청 기록.json / watch-history.json")
        open_btn.clicked.connect(self.open_file)
        self.file_label = QLabel("테이크아웃 파일을 열어 주세요 →  받는 법은 오른쪽에")
        self.file_label.setStyleSheet("color: gray")
        self.year = QComboBox()
        self.year.currentIndexChanged.connect(self.refresh)
        self.include_yt = QCheckBox("YouTube에서 본 뮤직비디오도")
        self.include_yt.setToolTip("YouTube Music이 아니라 YouTube에서 본 영상 중 음악으로 보이는 것"
                                   "(공식 MV, '- 주제' 채널 등)도 넣어요")
        self.include_yt.toggled.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("제목·아티스트 찾기")
        self.search.textChanged.connect(self._filter)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["순위", "제목", "아티스트", "재생 수", "처음 들은 날", "마지막으로 들은 날"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3, 4, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(lambda _i: self.download_selected())
        self.summary = QLabel()

        self.get_btn = QPushButton("⬇ 이 노래를 mp3로 받아 음악으로 쓰기")
        self.get_btn.clicked.connect(self.download_selected)
        self.csv_btn = QPushButton("목록 저장 (엑셀용 CSV)…")
        self.csv_btn.clicked.connect(self.save_csv)
        self.open_link_btn = QPushButton("유튜브에서 듣기")
        self.open_link_btn.clicked.connect(self.open_link)
        for b in (self.get_btn, self.csv_btn, self.open_link_btn):
            b.setEnabled(False)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(open_btn)
        top.addWidget(self.file_label, 1)
        ll.addLayout(top)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("연도"))
        opts.addWidget(self.year)
        opts.addWidget(self.include_yt)
        opts.addStretch(1)
        opts.addWidget(self.search)
        ll.addLayout(opts)
        ll.addWidget(self.table, 1)
        ll.addWidget(self.summary)
        btns = QHBoxLayout()
        btns.addWidget(self.get_btn)
        btns.addWidget(self.open_link_btn)
        btns.addStretch(1)
        btns.addWidget(self.csv_btn)
        ll.addLayout(btns)

        guide = QTextBrowser()
        guide.setOpenExternalLinks(True)
        guide.setHtml(HOW_TO)
        guide.setMinimumWidth(280)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(guide)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([620, 380])
        lay = QVBoxLayout(self)
        lay.addWidget(split)

    # ------------------------------------------------------------------
    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "테이크아웃 파일", str(Path.home() / "Downloads"),
            "테이크아웃 (*.zip *.json);;모든 파일 (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.history = load_history(path)
        except (TakeoutError, OSError, ValueError) as e:
            QMessageBox.warning(self, "내가 들은 노래", str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        first, last = self.history.span()
        day = lambda t: time.strftime("%Y-%m-%d", time.localtime(t))
        self.file_label.setText(f"{Path(path).name} · 기록 {len(self.history.entries):,}개 · "
                                f"{day(first)} ~ {day(last)}")
        self.file_label.setStyleSheet("")
        self.year.blockSignals(True)
        self.year.clear()
        for y in self.history.years():
            self.year.addItem(f"{y}년", y)
        self.year.addItem("전체 기간", 0)
        self.year.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        if not self.history:
            return
        self.songs = self.history.top_songs(self.year.currentData() or None, self.include_yt.isChecked())
        self.table.setRowCount(len(self.songs))
        for r, s in enumerate(self.songs):
            first = time.strftime("%Y-%m-%d", time.localtime(s.first))
            last = time.strftime("%Y-%m-%d", time.localtime(s.last))
            for c, v in enumerate((r + 1, s.title, s.artist, s.plays, first, last)):
                item = QTableWidgetItem(str(v))
                if c in (0, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        plays = sum(s.plays for s in self.songs)
        period = self.year.currentText()
        self.summary.setText(f"{period}: 노래 {len(self.songs):,}곡 · 재생 {plays:,}번"
                             if self.songs else f"{period}: 들은 노래가 없어요.")
        for b in (self.get_btn, self.csv_btn, self.open_link_btn):
            b.setEnabled(bool(self.songs))
        if self.songs:
            self.table.selectRow(0)
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for r, s in enumerate(self.songs):
            self.table.setRowHidden(r, bool(text) and text not in f"{s.title} {s.artist}".lower())

    def _selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.songs[rows[0].row()] if rows else None

    def download_selected(self) -> None:
        s = self._selected()
        if s:
            self.download_requested.emit(s.url)
            self.accept()

    def open_link(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        s = self._selected()
        if s:
            QDesktopServices.openUrl(QUrl(s.url))

    def save_csv(self) -> None:
        year = self.year.currentData()
        name = f"내가 들은 노래 {year}.csv" if year else "내가 들은 노래.csv"
        path, _ = QFileDialog.getSaveFileName(self, "목록 저장", str(Path.home() / "Documents" / name),
                                              "CSV (*.csv)")
        if not path:
            return
        try:
            Path(path).write_text(songs_csv(self.songs), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "목록 저장", f"저장하지 못했어요: {e}")
