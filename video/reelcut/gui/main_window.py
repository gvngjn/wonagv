"""메인 창: 왼쪽 편집 탭 + 오른쪽 미리보기·내보내기."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSplitter, QStyle, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import __version__, autosave
from ..history import History
from ..textfmt import eta_text
from ..project import ASPECTS, Project, find_aspect
from .audio_devices import AudioDeviceManager, AudioOutputPicker
from .timeline_bar import TimelineBar
from .panels import ClipsPanel, MusicPanel, PipPanel, SubtitlePanel, TitlePanel, fmt_time
from .panels import row as row_widget
from .workers import TaskThread

ASPECT_BUTTONS = [
    ("16:9", "▭  유튜브\n가로 16:9"),
    ("9:16", "▯  릴스·쇼츠\n세로 9:16"),
    ("1:1", "□  정사각형\n1:1"),
    ("4:5", "▯  인스타 피드\n4:5"),
]
SIZES = [("720p", "720p (가벼움)"), ("1080p", "1080p (추천)"), ("4K", "4K (고화질)")]
FADES = [
    ((0.0, 0.0), "페이드 없음"),
    ((0.0, 1.0), "끝만 서서히 사라지기"),
    ((0.5, 0.5), "시작·끝 짧게 (0.5초)"),
    ((1.5, 1.5), "시작·끝 길게 (1.5초)"),
]
FITS = [
    ("blur", "흐린 배경으로 채우기"),
    ("crop", "잘라서 꽉 채우기"),
    ("pad", "검은 여백 넣기"),
]
COLORS = [
    ("none", "색감 그대로"),
    ("warm", "따뜻하게"),
    ("cool", "차갑게"),
    ("vivid", "선명하게"),
    ("vintage", "빈티지"),
    ("bw", "흑백"),
]
QUALITIES = [("높음 (파일 큼)", 18), ("보통", 21), ("작은 파일", 26)]
FPS_CHOICES = [24.0, 25.0, 30.0, 60.0]


def open_external(path: str | None) -> None:
    """운영체제 기본 프로그램으로 파일 열기."""
    import subprocess
    import sys

    if not path or not Path(path).exists():
        return
    if sys.platform == "win32":
        os.startfile(os.path.normpath(path))          # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


MULTI_SUFFIX = {"16:9": "유튜브", "9:16": "릴스", "1:1": "정사각형", "4:5": "인스타피드"}


def multi_output_path(base: str, aspect: str) -> str:
    """완성영상.mp4 + 9:16 → 완성영상_릴스.mp4"""
    p = Path(base)
    stem = p.stem if p.suffix.lower() == ".mp4" else p.name
    return str(p.with_name(f"{stem}_{MULTI_SUFFIX[aspect]}.mp4"))


class MultiExportDialog(QDialog):
    def __init__(self, parent, size: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("여러 비율로 내보내기")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("같은 영상을 고른 비율마다 하나씩 만들어요.\n"
                             "비율이 다른 클립은 '비율이 다른 영상' 설정대로 맞춰요."))
        self.checks = {}
        for key, (label, _) in ASPECTS.items():
            c = QCheckBox(label)
            c.setChecked(key in ("16:9", "9:16"))
            self.checks[key] = c
            lay.addWidget(c)
        self.size = QComboBox()
        for key, label in SIZES:
            self.size.addItem(label, key)
        self.size.setCurrentIndex(max(0, self.size.findData(size)))
        lay.addWidget(row_widget(QLabel("해상도"), self.size))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("내보내기")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def selected(self) -> tuple[list[str], str]:
        return [k for k, c in self.checks.items() if c.isChecked()], self.size.currentData()


class Preview(QWidget):
    """간단한 재생기 (클립 확인, 미리보기 결과 재생)."""
    current_path: str | None = None

    def __init__(self) -> None:
        super().__init__()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        AudioDeviceManager.instance().register(self.audio)
        self.video = QVideoWidget()
        self.video.setMinimumSize(320, 180)
        self.video.setStyleSheet("background: black")
        self.player.setVideoOutput(self.video)

        self.play_btn = QPushButton()
        self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_btn.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(lambda v: self.player.setPosition(v))
        self.time = QLabel("0:00.0 / 0:00.0")
        self.title = QLabel("")
        self.title.setStyleSheet("color: gray")

        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.playbackStateChanged.connect(self._on_state)

        ctl = QHBoxLayout()
        ctl.addWidget(self.play_btn)
        ctl.addWidget(self.slider, 1)
        ctl.addWidget(self.time)
        self.external_btn = QPushButton("↗")
        self.external_btn.setFixedWidth(30)
        self.external_btn.setToolTip("Windows 기본 플레이어로 열기 (앱 재생기에서 소리가 이상할 때 비교용)")
        self.external_btn.setEnabled(False)
        self.external_btn.clicked.connect(lambda: open_external(self.current_path))
        ctl.addWidget(self.external_btn)
        self.still_btn = QPushButton("🖼")
        self.still_btn.setFixedWidth(34)
        self.still_btn.setToolTip("지금 보이는 장면을 이미지로 저장 (유튜브 썸네일 등)")
        self.still_btn.setEnabled(False)
        ctl.addWidget(self.still_btn)
        ctl.addWidget(AudioOutputPicker())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.video, 1)
        lay.addLayout(ctl)
        lay.addWidget(self.title)

    def load(self, path: str, start: float = 0.0, autoplay: bool = False, title: str = "") -> None:
        self.current_path = path
        self.external_btn.setEnabled(True)
        self.still_btn.setEnabled(True)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.title.setText(title or Path(path).name)
        if start > 0:
            QTimer.singleShot(150, lambda: self.player.setPosition(int(start * 1000)))
        if autoplay:
            self.player.play()
        else:
            # 첫 화면이 보이도록 살짝 재생했다 멈춤
            self.player.play()
            QTimer.singleShot(120, self.player.pause)

    def unload(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())

    def position(self) -> float:
        return self.player.position() / 1000

    def seek(self, delta: float) -> None:
        if self.player.duration() > 0:
            ms = int(self.player.position() + delta * 1000)
            self.player.setPosition(max(0, min(self.player.duration(), ms)))

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_pos(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time.setText(f"{fmt_time(ms / 1000)} / {fmt_time(self.player.duration() / 1000)}")

    def _on_state(self, state) -> None:
        icon = QStyle.SP_MediaPause if state == QMediaPlayer.PlayingState else QStyle.SP_MediaPlay
        self.play_btn.setIcon(self.style().standardIcon(icon))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project = Project()
        self.project_path: str | None = None
        self.dirty = False
        self.task: TaskThread | None = None
        self.preview_file = os.path.join(tempfile.gettempdir(), "reelcut_preview.mp4")
        self.setAcceptDrops(True)
        self.resize(1320, 860)

        self.preview = Preview()
        self.clips = ClipsPanel(self.project, self.preview.position)
        self.music = MusicPanel(self.project)
        self.pips = PipPanel(self.project)
        self.subs = SubtitlePanel(self.project)
        self.titles = TitlePanel(self.project)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.clips, "🎬 클립 이어붙이기")
        music_scroll = QScrollArea()
        music_scroll.setWidgetResizable(True)
        music_scroll.setFrameShape(QScrollArea.NoFrame)
        music_scroll.setWidget(self.music)
        self.tabs.addTab(music_scroll, "🎵 음악·비트")
        self.tabs.addTab(self.pips, "🖼 화면 속 화면")
        subs_scroll = QScrollArea()
        subs_scroll.setWidgetResizable(True)
        subs_scroll.setFrameShape(QScrollArea.NoFrame)
        subs_scroll.setWidget(self.subs)
        self.tabs.addTab(subs_scroll, "💬 자막")
        titles_scroll = QScrollArea()
        titles_scroll.setWidgetResizable(True)
        titles_scroll.setFrameShape(QScrollArea.NoFrame)
        titles_scroll.setWidget(self.titles)
        self.tabs.addTab(titles_scroll, "🔤 제목")

        for panel in (self.clips, self.music, self.pips, self.subs, self.titles):
            panel.changed.connect(self._on_changed)
        self.clips.preview_requested.connect(lambda p, s: self.preview.load(p, s))
        self.preview.still_btn.clicked.connect(self.save_still)
        self.music.analyze_requested.connect(self.analyze_music)
        self.music.music_chosen.connect(self._set_music)
        self.music.download_requested.connect(self.download_music)
        self.subs.generate_requested.connect(self.generate_subtitles)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(self.preview, 1)
        self.timeline = TimelineBar()
        self.timeline.clip_clicked.connect(self._select_clip)
        rl.addWidget(self.timeline)
        rl.addWidget(self._build_export_box())

        split = QSplitter()
        split.addWidget(self.tabs)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([560, 760])
        self.setCentralWidget(split)
        self._build_menu()
        self._load_export_settings()
        self._update_title()
        # 자동 저장: 마지막 변경 3초 뒤에 따로 저장
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(3000)
        self._autosave_timer.timeout.connect(self._do_autosave)
        # 실행 취소 기록: 편집이 멈추고 0.4초 뒤 한 단계로 기록 (슬라이더를 끌어도 한 번만)
        self.history = History()
        self._restoring = False
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(400)
        self._history_timer.timeout.connect(self._record_history)
        self._reset_history()
        self._timeline_timer = QTimer(self)
        self._timeline_timer.setSingleShot(True)
        self._timeline_timer.setInterval(150)
        self._timeline_timer.timeout.connect(self._refresh_timeline)
        self._refresh_timeline()

    # ---------------------------------------------------------------- UI 구성
    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("파일")
        for text, key, fn in (
            ("새 프로젝트", QKeySequence.New, self.new_project),
            ("프로젝트 열기…", QKeySequence.Open, self.open_project),
            ("프로젝트 저장", QKeySequence.Save, self.save_project),
            ("다른 이름으로 저장…", QKeySequence.SaveAs, lambda: self.save_project(as_new=True)),
        ):
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        clear_cache = QAction("임시 조각 지우기…", self)
        clear_cache.triggered.connect(self.clear_cache)
        m.addAction(clear_cache)
        m.addSeparator()
        quit_a = QAction("끝내기", self)
        quit_a.triggered.connect(self.close)
        m.addAction(quit_a)
        e = self.menuBar().addMenu("편집")
        self.undo_action = QAction("실행 취소", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction("다시 실행", self)
        self.redo_action.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")])
        self.redo_action.triggered.connect(self.redo)
        e.addAction(self.undo_action)
        e.addAction(self.redo_action)
        # 재생 · 만들기 (글자 입력 칸에서는 스페이스가 그대로 입력돼요)
        v = self.menuBar().addMenu("재생")
        for text, keys, fn in (
            ("재생 / 일시정지", ["Space"], self.preview.toggle),
            ("5초 뒤로", ["Ctrl+Left"], lambda: self.preview.seek(-5)),
            ("5초 앞으로", ["Ctrl+Right"], lambda: self.preview.seek(5)),
            (None, None, None),
            ("미리보기 만들기", ["F5", "Ctrl+R"], lambda: self.render(preview=True)),
            ("영상 내보내기…", ["Ctrl+E"], lambda: self.render(preview=False)),
            ("여러 비율로 한 번에 내보내기…", ["Ctrl+Shift+E"], self.export_multi),
        ):
            if text is None:
                v.addSeparator()
                continue
            a = QAction(text, self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(fn)
            v.addAction(a)
        h = self.menuBar().addMenu("도움말")
        logs_a = QAction("오류 기록 폴더 열기", self)
        logs_a.triggered.connect(self.open_logs)
        h.addAction(logs_a)
        about = QAction("ReelCut 정보", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "ReelCut",
            f"ReelCut {__version__}\n\n이어붙이기 · 자동 자막 · 비트 맞춤 컷 · 화면 속 화면\n"
            "FFmpeg와 faster-whisper를 사용합니다."))
        h.addAction(about)

    def _build_export_box(self) -> QGroupBox:
        box = QGroupBox("내보내기")
        # 화면 비율 (유튜브 / 릴스 …)
        self.aspect_group = QButtonGroup(self)
        self.aspect_group.setExclusive(True)
        aspect_row = QWidget()
        al = QHBoxLayout(aspect_row)
        al.setContentsMargins(0, 0, 0, 0)
        for key, label in ASPECT_BUTTONS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setMinimumHeight(44)
            b.setStyleSheet("QPushButton:checked { background: #ff8c28; color: white; font-weight: bold; }")
            b.setProperty("aspect", key)
            b.setToolTip(ASPECTS[key][0])
            self.aspect_group.addButton(b)
            al.addWidget(b)
        self.aspect_group.buttonClicked.connect(lambda _b: self._store_export())
        self.size_label = QLabel()
        self.size_label.setStyleSheet("color: gray")
        self.size = QComboBox()
        for key, label in SIZES:
            self.size.addItem(label, key)
        self.fit = QComboBox()
        for key, label in FITS:
            self.fit.addItem(label, key)
        self.fit.setToolTip("클립 비율이 화면 비율과 다를 때 (예: 가로 영상을 세로 릴스로)")
        self.fps = QComboBox()
        for f in FPS_CHOICES:
            self.fps.addItem(f"{f:g} fps", f)
        self.quality = QComboBox()
        for label, crf in QUALITIES:
            self.quality.addItem(label, crf)
        self.color = QComboBox()
        for key, label in COLORS:
            self.color.addItem(label, key)
        self.color.setToolTip("영상 전체 색감 (자막·제목 색은 그대로)")
        for w in (self.size, self.fit, self.fps, self.quality, self.color):
            w.currentIndexChanged.connect(self._store_export)
        self.loud = QCheckBox("음량 자동 맞춤 (유튜브·릴스 권장 크기)")
        self.loud.setToolTip("노래와 원본 소리를 합친 최종 음량을 -14 LUFS로 맞춰요. 너무 작거나 커서 깨지는 걸 막아요.")
        self.loud.toggled.connect(self._store_export)
        self.gpu = QCheckBox("그래픽카드로 빠르게")
        self.gpu.setToolTip("NVIDIA·Intel·AMD 그래픽카드 인코더가 있으면 내보내기를 더 빨리 해요.\n"
                            "안 되면 자동으로 원래 방식(CPU)으로 다시 만들어요.")
        self.gpu.toggled.connect(self._store_export)
        self.fade = QComboBox()
        for (fi, fo), label in FADES:
            self.fade.addItem(label, f"{fi}/{fo}")
        self.fade.setToolTip("영상 시작은 검은 화면에서 나타나고, 끝은 검은 화면으로 사라져요 (소리도 함께)")
        self.fade.currentIndexChanged.connect(self._store_export)

        self.preview_btn = QPushButton("▶ 미리보기 만들기")
        self.preview_btn.setToolTip("작은 화질로 빠르게 만들어서 오른쪽 위에서 재생해요 (F5)")
        self.preview_btn.clicked.connect(lambda: self.render(preview=True))
        self.export_btn = QPushButton("💾 영상 내보내기…")
        self.export_btn.setStyleSheet("font-weight: bold; padding: 6px 14px")
        self.export_btn.setToolTip("원래 화질로 영상 파일을 만들어요 (Ctrl+E)")
        self.export_btn.clicked.connect(lambda: self.render(preview=False))
        self.multi_btn = QPushButton("📐 여러 비율로…")
        self.multi_btn.setToolTip("유튜브 가로·릴스 세로 등 여러 비율을 한 번에 내보내요 (Ctrl+Shift+E)")
        self.multi_btn.clicked.connect(self.export_multi)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_task)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.status = QLabel("클립을 추가해서 시작하세요.")
        self.status.setWordWrap(True)

        f = QFormLayout(box)
        f.addRow("화면 비율", aspect_row)
        settings = QWidget()
        sl = QHBoxLayout(settings)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.size, 1)
        sl.addWidget(self.fps, 1)
        sl.addWidget(self.quality, 1)
        f.addRow("해상도·화질", settings)
        f.addRow("비율이 다른 영상", row_widget(self.fit, self.size_label))
        f.addRow("색감", row_widget(self.color, self.gpu))
        f.addRow("시작·끝", row_widget(self.fade, self.loud))
        buttons = QWidget()
        bl = QHBoxLayout(buttons)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.preview_btn)
        bl.addWidget(self.export_btn)
        bl.addWidget(self.multi_btn)
        bl.addStretch(1)
        bl.addWidget(self.cancel_btn)
        f.addRow(buttons)
        f.addRow(self.progress)
        f.addRow(self.status)
        return box

    def _load_export_settings(self) -> None:
        ex = self.project.export
        widgets = (self.size, self.fit, self.fps, self.quality, self.loud, self.fade, self.color, self.gpu)
        for w in widgets:
            w.blockSignals(True)
        found = find_aspect(ex.width, ex.height)
        aspect, size = found if found else (None, "1080p")
        # 프리셋에 없는 크기면 모두 해제해야 하므로 잠깐 단일 선택을 끈다
        self.aspect_group.setExclusive(False)
        for b in self.aspect_group.buttons():
            b.setChecked(b.property("aspect") == aspect)
        self.aspect_group.setExclusive(True)
        self.size.setCurrentIndex(max(0, self.size.findData(size)))
        self.fit.setCurrentIndex(max(0, self.fit.findData(ex.fit)))
        self.color.setCurrentIndex(max(0, self.color.findData(ex.color)))
        self.loud.setChecked(bool(ex.loudness))
        self.gpu.setChecked(ex.gpu)
        key = f"{float(ex.fade_in)}/{float(ex.fade_out)}"
        if self.fade.findData(key) < 0:
            self.fade.addItem(f"사용자 지정 ({ex.fade_in:g}초 / {ex.fade_out:g}초)", key)
        self.fade.setCurrentIndex(self.fade.findData(key))
        self.fps.setCurrentIndex(max(0, self.fps.findData(ex.fps)))
        qi = self.quality.findData(ex.crf)
        self.quality.setCurrentIndex(qi if qi >= 0 else 1)
        for w in widgets:
            w.blockSignals(False)
        self._update_size_label()

    def _store_export(self) -> None:
        ex = self.project.export
        checked = self.aspect_group.checkedButton()
        if checked is not None:
            ex.width, ex.height = ASPECTS[checked.property("aspect")][1][self.size.currentData()]
        ex.fit = self.fit.currentData()
        ex.color = self.color.currentData()
        ex.gpu = self.gpu.isChecked()
        ex.loudness = -14.0 if self.loud.isChecked() else 0.0
        ex.fade_in, ex.fade_out = (float(v) for v in self.fade.currentData().split("/"))
        ex.fps = self.fps.currentData()
        ex.crf = self.quality.currentData()
        self._update_size_label()
        self._on_changed()

    def _update_size_label(self) -> None:
        ex = self.project.export
        found = find_aspect(ex.width, ex.height)
        name = ASPECTS[found[0]][0] if found else "사용자 지정"
        self.size_label.setText(f"{name} · {ex.width}×{ex.height}")

    # ---------------------------------------------------------------- 상태
    def _select_clip(self, k: int) -> None:
        self.tabs.setCurrentIndex(0)
        if 0 <= k < self.clips.list.count():
            self.clips.list.setCurrentRow(k)

    def _refresh_timeline(self) -> None:
        self.timeline.set_project(self.project)

    def _on_changed(self) -> None:
        if hasattr(self, "_timeline_timer"):
            self._timeline_timer.start()
        self.dirty = True
        self._update_title()
        self._autosave_timer.start()
        if not self._restoring:
            self._history_timer.start()
        if self.sender() is not self.music:
            self.music.reload()   # 클립·fps가 바뀌면 컷 정보도 갱신

    def _update_title(self) -> None:
        name = Path(self.project_path).name if self.project_path else "새 프로젝트"
        self.setWindowTitle(f"{'● ' if self.dirty else ''}{name} — ReelCut 영상 편집기")

    def _reload_all(self) -> None:
        for p in (self.clips, self.music, self.pips, self.subs, self.titles):
            p.project = self.project
            p.reload()
        if hasattr(self, "timeline"):
            self._refresh_timeline()
        self._load_export_settings()
        self._update_title()

    def _busy(self, busy: bool) -> None:
        for w in (self.preview_btn, self.export_btn, self.multi_btn, self.music.analyze_btn, self.subs.gen_btn):
            w.setEnabled(not busy)
        self.music.set_downloading(busy)
        if not busy:
            self.music.reload()
        self.cancel_btn.setEnabled(busy)

    def _start(self, fn, on_done, label: str) -> None:
        if self.task and self.task.isRunning():
            # 앞 작업의 완료 알림 안에서 바로 다음 작업을 시작하는 경우 스레드가 끝나길 잠깐 기다린다
            self.task.wait(1000)
        if self.task and self.task.isRunning():
            QMessageBox.information(self, "ReelCut", "다른 작업이 진행 중이에요.")
            return
        self.task = TaskThread(fn, self)
        self.task.progress.connect(self._on_progress)
        self.task.done.connect(lambda r: (self._busy(False), on_done(r)))
        self.task.failed.connect(self._on_failed)
        self._busy(True)
        self.progress.setValue(0)
        self.status.setText(label)
        self._task_started = time.monotonic()
        self.task.start()

    def _on_progress(self, frac: float, msg: str) -> None:
        frac = max(0.0, min(1.0, frac))
        self.progress.setValue(int(frac * 1000))
        if msg:
            eta = eta_text(time.monotonic() - getattr(self, "_task_started", time.monotonic()), frac)
            self.status.setText(f"{msg} · {eta}" if eta else msg)

    def _on_failed(self, msg: str) -> None:
        self._busy(False)
        self.progress.setValue(0)
        self.status.setText(msg)
        if msg != "취소했어요.":
            QMessageBox.warning(self, "ReelCut", msg)

    def cancel_task(self) -> None:
        if self.task and self.task.isRunning():
            self.task.cancel()
            self.status.setText("취소하는 중…")

    # ---------------------------------------------------------------- 작업
    def analyze_music(self) -> None:
        path = self.project.music.path
        if not path:
            return
        from ..beats import analyze_file_with_waveform

        def work(t: TaskThread):
            t.report(0.2, "음악의 템포와 비트를 찾는 중…")
            return analyze_file_with_waveform(path)

        def done(result) -> None:
            beats, peaks = result
            if self.project.music.path != path:
                return
            self.music.set_waveform(peaks)
            self.music.set_beats(beats.bpm, beats.beats, beats.strengths, beats.energy)
            self.progress.setValue(1000)
            self.status.setText(f"비트 분석 완료: 약 {beats.bpm:.1f} BPM, 비트 {len(beats.beats)}개 · "
                                "파형에서 클릭·드래그로 시작 위치를 고르세요.")

        self._start(work, done, "음악 분석 중…")

    def load_music_waveform(self) -> None:
        """프로젝트를 열었을 때 파형만 다시 그리기 (비트는 저장돼 있음)."""
        path = self.project.music.path
        if not path or not Path(path).exists() or (self.task and self.task.isRunning()):
            return
        from ..beats import load_waveform

        def done(peaks) -> None:
            if self.project.music.path == path:
                self.music.set_waveform(peaks)
                self.progress.setValue(1000)
                self.status.setText("프로젝트를 열었어요.")

        self._start(lambda t: load_waveform(path), done, "음악 파형 불러오는 중…")

    def download_music(self, url: str) -> None:
        from ..download import download_audio, is_url

        if not is_url(url):
            QMessageBox.information(self, "음악 받기", "https:// 로 시작하는 링크를 붙여넣어 주세요.")
            return

        def work(t: TaskThread):
            return download_audio(url, on_progress=t.report, should_stop=lambda: t.cancelled)

        def done(result) -> None:
            self.music.url_edit.clear()
            self.status.setText(f"받기 완료: {Path(result.path).name}")
            self._set_music(result.path)

        self._start(work, done, "음악 받는 중…")

    def generate_subtitles(self) -> None:
        from .. import subtitles as subs
        from ..timeline import build_segments, total_duration

        s = self.project.subtitles
        segments = build_segments(self.project)
        music = self.project.music
        if s.source == "music":
            if not music.path:
                QMessageBox.information(self, "자막", "음악 탭에서 음악을 먼저 등록해 주세요.")
                return
            length = total_duration(segments) if segments else max(0.0, music.duration - music.start)
        elif not segments:
            QMessageBox.information(self, "자막", "클립을 먼저 추가해 주세요.")
            return
        if s.entries and QMessageBox.question(
                self, "자막", "지금 있는 자막을 새로 만든 자막으로 바꿀까요?") != QMessageBox.Yes:
            return
        source, model, lang = s.source, s.model, s.language

        def work(t: TaskThread):
            t.report(0.02, "소리를 추출하는 중…")
            if source == "music":
                audio = subs.music_audio(music.path, music.start, length)
            else:
                audio = subs.timeline_audio(segments)
            return subs.transcribe(
                audio, model, lang,
                on_progress=lambda f: t.report(0.1 + 0.9 * f, "음성을 글자로 바꾸는 중…"),
                should_stop=lambda: t.cancelled,
                on_status=lambda m: t.report(0.08, m),
            )

        def done(entries) -> None:
            self.subs.set_entries(entries)
            self.progress.setValue(1000)
            self.status.setText(f"자막 {len(entries)}줄을 만들었어요. 표에서 바로 고칠 수 있어요."
                                if entries else "알아들을 수 있는 말소리를 찾지 못했어요.")

        self._start(work, done, "자동 자막 준비 중…")

    def _can_render(self) -> bool:
        if not self.preview_btn.isEnabled():  # 다른 작업 중 (단축키로 눌렀을 때)
            return False
        if not self.project.clips:
            QMessageBox.information(self, "ReelCut", "클립을 먼저 추가해 주세요.")
            return False
        if not self.offer_relink():
            return False
        bs = self.project.beat_sync
        if bs.enabled and bs.cut_unit == "beats" and not self.project.music.beats:
            QMessageBox.information(self, "ReelCut", "비트 맞춤을 쓰려면 음악 탭에서 '비트 분석'을 먼저 해 주세요.")
            return False
        return True

    def render(self, preview: bool) -> None:
        if not self._can_render():
            return
        self.music.stop_preview()
        if preview:
            out = self.preview_file
            self.preview.unload()   # 재생 중인 파일은 덮어쓸 수 없으므로
        else:
            default = self.project.export.output or str(Path.home() / "Videos" / "완성영상.mp4")
            out, _ = QFileDialog.getSaveFileName(self, "영상 내보내기", default, "MP4 영상 (*.mp4)")
            if not out:
                return
            if not out.lower().endswith(".mp4"):
                out += ".mp4"
            self.project.export.output = out
        # 작업 중 편집해도 안전하게 복사
        self._run_renders([(Project.from_dict(self.project.to_dict()), out)], preview)

    def save_still(self) -> None:
        """미리보기에 보이는 장면을 내보내기 크기의 이미지로 (자막·제목 없이)."""
        from ..render import save_still

        path = getattr(self.preview, "current_path", "")
        if not path:
            return
        t = self.preview.position()
        self.preview.player.pause()
        default = str(Path(self.project.export.output or Path.home() / "Videos" / "완성영상.mp4")
                      .with_name("썸네일.jpg"))
        out, _ = QFileDialog.getSaveFileName(self, "장면을 이미지로 저장", default,
                                             "JPG 이미지 (*.jpg);;PNG 이미지 (*.png)")
        if not out:
            return
        if not out.lower().endswith((".jpg", ".jpeg", ".png")):
            out += ".jpg"
        # 완성 미리보기를 보고 있으면 타임라인 시간, 클립 원본을 보고 있으면 그 파일의 시간
        source = None if path == self.preview_file else (path, t)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            save_still(self.project, out, t=t, source=source)
        except Exception as e:  # noqa: BLE001 - 사용자에게 알린다
            QMessageBox.warning(self, "ReelCut", f"이미지를 저장하지 못했어요.\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        ex = self.project.export
        self.status.setText(f"장면 저장 ({ex.width}×{ex.height}): {out}")

    def export_multi(self) -> None:
        """같은 영상을 여러 화면 비율로 한 번에 (예: 유튜브 가로 + 릴스 세로)."""
        if not self._can_render():
            return
        dlg = MultiExportDialog(self, self.size.currentData() or "1080p")
        if not dlg.exec():
            return
        aspects, size = dlg.selected()
        if not aspects:
            return
        default = self.project.export.output or str(Path.home() / "Videos" / "완성영상.mp4")
        base, _ = QFileDialog.getSaveFileName(self, "여러 비율로 내보내기 (이름 뒤에 비율이 붙어요)",
                                              default, "MP4 영상 (*.mp4)")
        if not base:
            return
        jobs = []
        for key in aspects:
            project = Project.from_dict(self.project.to_dict())
            project.export.width, project.export.height = ASPECTS[key][1][size]
            jobs.append((project, multi_output_path(base, key)))
        self.music.stop_preview()
        self._run_renders(jobs, preview=False)

    def _run_renders(self, jobs: list[tuple[Project, str]], preview: bool) -> None:
        from ..render import Renderer

        renderer = Renderer()
        problems: list[str] = []

        def work(t: TaskThread):
            t.cancel_hook = renderer.cancel
            n = len(jobs)
            for k, (project, out) in enumerate(jobs):
                name = f"[{k + 1}/{n}] {Path(out).name} · " if n > 1 else ""
                renderer.render(project, out, preview=preview,
                                on_progress=lambda f, m: t.report((k + f) / n, name + m))
                problems.extend(f"{Path(out).name}: {p}" if n > 1 else p for p in renderer.problems)
            return [out for _, out in jobs]

        def done(paths: list[str]) -> None:
            self.progress.setValue(1000)
            if problems:
                QMessageBox.warning(self, "결과 확인", "만들어진 영상에서 이상한 점을 찾았어요:\n\n"
                                    + "\n".join(f"· {p}" for p in problems)
                                    + "\n\n같은 설정으로 다시 만들어도 그러면 알려 주세요.")
            if preview:
                self.status.setText("미리보기 완성! 위에서 재생 중이에요.")
                self.preview.load(paths[0], autoplay=True, title="미리보기 (저화질)")
                return
            from .. import hwenc

            enc = renderer.encoder_used
            how = f" ({hwenc.NAMES.get(enc, enc)} 그래픽카드 사용)" if enc != hwenc.SOFTWARE else ""
            self.status.setText(f"내보내기 완료{how}: " + ", ".join(Path(p).name for p in paths))
            box = QMessageBox(self)
            box.setWindowTitle("ReelCut")
            box.setText(("영상을 만들었어요!\n" if len(paths) == 1 else f"영상 {len(paths)}개를 만들었어요!\n")
                        + "\n".join(paths))
            play_btn = box.addButton("재생", QMessageBox.ActionRole)
            open_btn = box.addButton("폴더 열기", QMessageBox.ActionRole)
            box.addButton("확인", QMessageBox.AcceptRole)
            box.exec()
            if box.clickedButton() is open_btn:
                self._reveal(paths[0])
            elif box.clickedButton() is play_btn:
                open_external(paths[0])

        self._start(work, done, "미리보기 만드는 중…" if preview else "영상 만드는 중…")

    @staticmethod
    def _reveal(path: str) -> None:
        import subprocess
        import sys

        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])

    def open_logs(self) -> None:
        from .. import logs

        logs.log_dir().mkdir(parents=True, exist_ok=True)
        open_external(str(logs.log_dir()))

    def clear_cache(self) -> None:
        from .. import cache

        mb = cache.size() / 1024 ** 2
        if QMessageBox.question(
                self, "임시 조각 지우기",
                f"미리보기·내보내기를 빠르게 하려고 저장해 둔 조각이 {mb:.0f}MB 있어요.\n"
                "지워도 영상에는 문제없고, 다음 렌더링이 처음 한 번 느려질 뿐이에요.\n\n지울까요?") == QMessageBox.Yes:
            cache.clear()
            self.status.setText("임시 조각을 지웠어요.")

    # ---------------------------------------------------------------- 실행 취소
    def _reset_history(self) -> None:
        self._history_timer.stop()
        self.history.reset(self.project.to_dict())
        self._update_undo_actions()

    def _record_history(self) -> None:
        self.history.push(self.project.to_dict())
        self._update_undo_actions()

    def _update_undo_actions(self) -> None:
        self.undo_action.setEnabled(self.history.can_undo)
        self.redo_action.setEnabled(self.history.can_redo)

    def _flush_history(self) -> None:
        if self._history_timer.isActive():
            self._history_timer.stop()
            self._record_history()

    def undo(self) -> None:
        self._flush_history()
        state = self.history.undo()
        if state is not None:
            self._apply_state(state, "실행 취소했어요.")

    def redo(self) -> None:
        self._flush_history()
        state = self.history.redo()
        if state is not None:
            self._apply_state(state, "다시 실행했어요.")

    def _apply_state(self, state: dict, message: str) -> None:
        if self.task and self.task.isRunning():
            QMessageBox.information(self, "ReelCut", "작업이 끝난 뒤에 해 주세요.")
            return
        old_music = self.project.music.path
        self._restoring = True
        try:
            self.project = Project.from_dict(state)
            self._reload_all()
        finally:
            self._restoring = False
        self.dirty = True
        self._update_title()
        self._autosave_timer.start()
        if self.project.music.path != old_music:
            self.music.set_waveform([])
            self.load_music_waveform()
        self._update_undo_actions()
        self.status.setText(message)

    # ---------------------------------------------------------------- 자동 저장 / 복구
    def _do_autosave(self) -> None:
        if not self.dirty:
            return
        try:
            autosave.write(self.project, self.project_path)
        except OSError:
            pass          # 자동 저장 실패는 작업을 막지 않는다

    def check_recovery(self) -> None:
        """앱 시작 시: 지난번에 저장하지 않고 꺼진 작업이 있으면 복구할지 묻는다."""
        rec = autosave.read()
        if rec is None:
            return
        when = time.strftime("%m월 %d일 %H:%M", time.localtime(rec.saved_at)) if rec.saved_at else "이전"
        name = Path(rec.original_path).name if rec.original_path else "새 프로젝트"
        r = QMessageBox.question(
            self, "작업 복구",
            f"저장하지 않고 꺼진 작업이 있어요.\n\n{name} · {when} · 클립 {len(rec.project.clips)}개\n\n복구할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r != QMessageBox.Yes:
            autosave.clear()
            return
        self.project = rec.project
        self.project_path = rec.original_path
        self._reload_all()
        self._reset_history()
        self.dirty = True
        self._update_title()
        self.load_music_waveform()
        self.status.setText("작업을 복구했어요. 저장(Ctrl+S)하면 복구 기록이 정리돼요.")

    # ---------------------------------------------------------------- 프로젝트 파일
    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "ReelCut", "저장하지 않은 변경 내용이 있어요. 저장할까요?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_project()
        return r == QMessageBox.Discard

    def new_project(self) -> None:
        if self._confirm_discard():
            self.music.stop_preview()
            autosave.clear()
            self.project = Project()
            self.project_path = None
            self.dirty = False
            self.music.set_waveform([])
            self._reload_all()
            self._reset_history()

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "프로젝트 열기", "", "ReelCut 프로젝트 (*.reelcut.json *.json)")
        if not path:
            return
        try:
            self.project = Project.load(path)
        except Exception as e:
            QMessageBox.warning(self, "ReelCut", f"프로젝트를 열 수 없어요:\n{e}")
            return
        self.project_path = path
        self.dirty = False
        autosave.clear()
        self.music.stop_preview()
        self.music.set_waveform([])
        self._reload_all()
        self.offer_relink()
        self._reset_history()
        self.load_music_waveform()

    def offer_relink(self) -> bool:
        """없어진 파일이 있으면 알려 주고, 폴더를 골라 같은 이름으로 다시 연결. 모두 찾으면 True."""
        missing = self.project.missing_files()
        while missing:
            names = "\n".join(f"· {Path(p).name}" for p in missing[:12])
            more = f"\n… 외 {len(missing) - 12}개" if len(missing) > 12 else ""
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("찾을 수 없는 파일")
            box.setText(f"옮기거나 이름을 바꾼 파일이 있어요:\n{names}{more}\n\n"
                        "파일이 있는 폴더를 고르면 같은 이름으로 찾아서 다시 연결해요.")
            find = box.addButton("폴더에서 찾기…", QMessageBox.AcceptRole)
            box.addButton("나중에", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not find:
                return False
            folder = QFileDialog.getExistingDirectory(self, "파일이 있는 폴더 고르기")
            if not folder:
                return False
            fixed = self.project.relink(folder)
            if fixed:
                self._reload_all()
                self._on_changed()
            missing = self.project.missing_files()
            self.status.setText(f"파일 {fixed}개를 다시 연결했어요." + (f" 아직 {len(missing)}개를 못 찾았어요." if missing else ""))
        return True

    def save_project(self, as_new: bool = False) -> bool:
        path = self.project_path
        if as_new or not path:
            path, _ = QFileDialog.getSaveFileName(self, "프로젝트 저장", "내 영상.reelcut.json",
                                                  "ReelCut 프로젝트 (*.reelcut.json)")
            if not path:
                return False
        try:
            self.project.save(path)
        except OSError as e:
            QMessageBox.warning(self, "ReelCut", f"저장하지 못했어요:\n{e}")
            return False
        self.project_path = path
        self.dirty = False
        self._autosave_timer.stop()
        autosave.clear()
        self._update_title()
        self.status.setText(f"저장했어요: {path}")
        return True

    # ---------------------------------------------------------------- 끌어다 놓기 / 종료
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
        audio = [p for p in paths if Path(p).suffix.lower() in audio_exts]
        others = [p for p in paths if p not in audio]
        if others:
            self.tabs.setCurrentWidget(self.clips)
            self.clips.add_files(others)
        if audio:
            self.tabs.setCurrentWidget(self.music)
            self._set_music(audio[0])

    def _set_music(self, path: str) -> None:
        from ..ffmpeg import probe

        try:
            info = probe(path)
        except Exception as e:
            QMessageBox.warning(self, "음악", str(e))
            return
        if not info.has_audio:
            QMessageBox.warning(self, "음악", "소리가 없는 파일이에요.")
            return
        self.music.stop_preview()
        m = self.project.music
        m.path, m.duration, m.start, m.bpm, m.beats, m.beat_offset = path, info.duration, 0.0, 0.0, [], 0.0
        self.music.set_waveform([])
        self.music.reload()
        self._on_changed()
        self.analyze_music()

    def closeEvent(self, e) -> None:
        if not self._confirm_discard():
            e.ignore()
            return
        if self.task and self.task.isRunning():
            self.task.cancel()
            self.task.wait(3000)
        self.preview.unload()
        self.music.stop_preview()
        self._autosave_timer.stop()
        autosave.clear()       # 저장했거나 '저장 안 함'을 고른 정상 종료
        e.accept()
