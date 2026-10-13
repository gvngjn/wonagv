"""메인 창: 왼쪽 편집 탭 + 오른쪽 미리보기·내보내기."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSplitter, QStyle, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import __version__
from ..project import ASPECTS, Project, find_aspect
from .audio_devices import AudioDeviceManager, AudioOutputPicker
from .panels import ClipsPanel, MusicPanel, PipPanel, SubtitlePanel, fmt_time
from .panels import row as row_widget
from .workers import TaskThread

ASPECT_BUTTONS = [
    ("16:9", "▭  유튜브\n가로 16:9"),
    ("9:16", "▯  릴스·쇼츠\n세로 9:16"),
    ("1:1", "□  정사각형\n1:1"),
    ("4:5", "▯  인스타 피드\n4:5"),
]
SIZES = [("720p", "720p (가벼움)"), ("1080p", "1080p (추천)"), ("4K", "4K (고화질)")]
FITS = [
    ("blur", "흐린 배경으로 채우기"),
    ("crop", "잘라서 꽉 채우기"),
    ("pad", "검은 여백 넣기"),
]
QUALITIES = [("높음 (파일 큼)", 18), ("보통", 21), ("작은 파일", 26)]
FPS_CHOICES = [24.0, 25.0, 30.0, 60.0]


class Preview(QWidget):
    """간단한 재생기 (클립 확인, 미리보기 결과 재생)."""

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
        ctl.addWidget(AudioOutputPicker())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.video, 1)
        lay.addLayout(ctl)
        lay.addWidget(self.title)

    def load(self, path: str, start: float = 0.0, autoplay: bool = False, title: str = "") -> None:
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

        for panel in (self.clips, self.music, self.pips, self.subs):
            panel.changed.connect(self._on_changed)
        self.clips.preview_requested.connect(lambda p, s: self.preview.load(p, s))
        self.music.analyze_requested.connect(self.analyze_music)
        self.music.music_chosen.connect(self._set_music)
        self.music.download_requested.connect(self.download_music)
        self.subs.generate_requested.connect(self.generate_subtitles)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(self.preview, 1)
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
        quit_a = QAction("끝내기", self)
        quit_a.triggered.connect(self.close)
        m.addAction(quit_a)
        h = self.menuBar().addMenu("도움말")
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
        for w in (self.size, self.fit, self.fps, self.quality):
            w.currentIndexChanged.connect(self._store_export)

        self.preview_btn = QPushButton("▶ 미리보기 만들기")
        self.preview_btn.setToolTip("작은 화질로 빠르게 만들어서 오른쪽 위에서 재생해요")
        self.preview_btn.clicked.connect(lambda: self.render(preview=True))
        self.export_btn = QPushButton("💾 영상 내보내기…")
        self.export_btn.setStyleSheet("font-weight: bold; padding: 6px 14px")
        self.export_btn.clicked.connect(lambda: self.render(preview=False))
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
        buttons = QWidget()
        bl = QHBoxLayout(buttons)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.preview_btn)
        bl.addWidget(self.export_btn)
        bl.addStretch(1)
        bl.addWidget(self.cancel_btn)
        f.addRow(buttons)
        f.addRow(self.progress)
        f.addRow(self.status)
        return box

    def _load_export_settings(self) -> None:
        ex = self.project.export
        widgets = (self.size, self.fit, self.fps, self.quality)
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
    def _on_changed(self) -> None:
        self.dirty = True
        self._update_title()
        if self.sender() is not self.music:
            self.music.reload()   # 클립·fps가 바뀌면 컷 정보도 갱신

    def _update_title(self) -> None:
        name = Path(self.project_path).name if self.project_path else "새 프로젝트"
        self.setWindowTitle(f"{'● ' if self.dirty else ''}{name} — ReelCut 영상 편집기")

    def _reload_all(self) -> None:
        for p in (self.clips, self.music, self.pips, self.subs):
            p.project = self.project
            p.reload()
        self._load_export_settings()
        self._update_title()

    def _busy(self, busy: bool) -> None:
        for w in (self.preview_btn, self.export_btn, self.music.analyze_btn, self.subs.gen_btn):
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
        self.task.start()

    def _on_progress(self, frac: float, msg: str) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, frac)) * 1000))
        if msg:
            self.status.setText(msg)

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
            self.music.set_beats(beats.bpm, beats.beats)
            self.progress.setValue(1000)
            self.status.setText(f"비트 분석 완료: 약 {beats.bpm:.1f} BPM, 비트 {len(beats.beats)}개 · "
                                "파형에서 클릭·드래그로 시작 위치를 고르세요.")

        self._start(work, done, "음악 분석 중…")

    def load_music_waveform(self) -> None:
        """프로젝트를 열었을 때 파형만 다시 그리기 (비트는 저장돼 있음)."""
        path = self.project.music.path
        if not path or not Path(path).exists():
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

    def render(self, preview: bool) -> None:
        from ..render import Renderer

        if not self.project.clips:
            QMessageBox.information(self, "ReelCut", "클립을 먼저 추가해 주세요.")
            return
        bs = self.project.beat_sync
        if bs.enabled and not self.project.music.beats:
            QMessageBox.information(self, "ReelCut", "비트 맞춤을 쓰려면 음악 탭에서 '비트 분석'을 먼저 해 주세요.")
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
        renderer = Renderer()
        project = Project.from_dict(self.project.to_dict())   # 작업 중 편집해도 안전하게 복사

        def work(t: TaskThread):
            t.cancel_hook = renderer.cancel
            renderer.render(project, out, preview=preview, on_progress=t.report)
            return out

        def done(path: str) -> None:
            self.progress.setValue(1000)
            if preview:
                self.status.setText("미리보기 완성! 위에서 재생 중이에요.")
                self.preview.load(path, autoplay=True, title="미리보기 (저화질)")
            else:
                self.status.setText(f"내보내기 완료: {path}")
                box = QMessageBox(self)
                box.setWindowTitle("ReelCut")
                box.setText(f"영상을 만들었어요!\n{path}")
                open_btn = box.addButton("폴더 열기", QMessageBox.ActionRole)
                box.addButton("확인", QMessageBox.AcceptRole)
                box.exec()
                if box.clickedButton() is open_btn:
                    self._reveal(path)

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
            self.project = Project()
            self.project_path = None
            self.dirty = False
            self.music.set_waveform([])
            self._reload_all()

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
        self.music.stop_preview()
        self.music.set_waveform([])
        self._reload_all()
        self.load_music_waveform()
        missing = [c.path for c in self.project.clips if not Path(c.path).exists()]
        if missing:
            QMessageBox.warning(self, "ReelCut", "찾을 수 없는 파일:\n" + "\n".join(missing))

    def save_project(self, as_new: bool = False) -> bool:
        path = self.project_path
        if as_new or not path:
            path, _ = QFileDialog.getSaveFileName(self, "프로젝트 저장", "내 영상.reelcut.json",
                                                  "ReelCut 프로젝트 (*.reelcut.json)")
            if not path:
                return False
        self.project.save(path)
        self.project_path = path
        self.dirty = False
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
        e.accept()
