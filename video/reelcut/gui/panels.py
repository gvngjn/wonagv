"""왼쪽 탭에 들어가는 편집 패널들."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFontComboBox,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSizePolicy, QSlider, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import subtitles as subs
from ..ffmpeg import probe
from ..project import Clip, PipOverlay, Project, SubtitleEntry
from ..render import is_image
from .music_gauge import MusicGauge, MusicPreviewPlayer
from .thumbnails import THUMB_H, THUMB_W, ThumbnailLoader
from .subtitle_style import ColorButton, SubtitleSample, font_file_families, register_font_file

VIDEO_FILTER = "영상·사진 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.jpg *.jpeg *.png *.bmp *.webp);;모든 파일 (*)"
AUDIO_FILTER = "음악 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4);;모든 파일 (*)"
IMAGE_DEFAULT_SECONDS = 3.0


def fmt_time(sec: float) -> str:
    sec = max(0.0, sec)
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:04.1f}"


def seconds_spin(maximum: float = 36000.0, step: float = 0.1, decimals: int = 2) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(0.0, maximum)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(" 초")
    s.setKeyboardTracking(False)
    return s


def percent_slider(maximum: int = 200) -> tuple[QSlider, QLabel]:
    sl = QSlider(Qt.Horizontal)
    sl.setRange(0, maximum)
    lbl = QLabel()
    lbl.setMinimumWidth(42)
    lbl.setText("0%")
    sl.valueChanged.connect(lambda v: lbl.setText(f"{v}%"))
    return sl, lbl


def row(*widgets) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        if isinstance(x, int):
            h.addSpacing(x)
        elif x is None:
            h.addStretch(1)
        else:
            h.addWidget(x)
    return w


def make_clip(path: str) -> Clip:
    if is_image(path):
        return Clip(path, duration=0.0, in_point=0.0, out_point=IMAGE_DEFAULT_SECONDS, has_audio=False)
    info = probe(path)
    if not info.has_video:
        raise ValueError(f"영상이 없는 파일이에요: {Path(path).name}")
    return Clip(path, info.duration, 0.0, 0.0, info.has_audio, info.width, info.height)


# ------------------------------------------------------------------ 클립

MOTION_CHOICES = [
    ("auto", "자동 (사진마다 번갈아)"),
    ("zoom_in", "천천히 확대"),
    ("zoom_out", "천천히 축소"),
    ("pan_right", "오른쪽으로 이동"),
    ("pan_left", "왼쪽으로 이동"),
    ("none", "움직이지 않음"),
]


def delete_key(widget: QWidget, fn) -> None:
    """목록에서 Delete(맥: Backspace) 키로 선택한 항목 지우기. 칸을 고치는 중에는 그대로 글자 지우기."""
    for key in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
        QShortcut(key, widget, fn, context=Qt.WidgetShortcut)


class ClipsPanel(QWidget):
    changed = Signal()
    preview_requested = Signal(str, float)   # 경로, 시작 위치

    def __init__(self, project: Project, player_position) -> None:
        super().__init__()
        self.project = project
        self._player_position = player_position   # () -> 현재 미리보기 재생 위치(초)
        self._loading = False

        self.thumbs = ThumbnailLoader(self)
        self.thumbs.ready.connect(self._on_thumb)
        self.list = QListWidget()
        self.list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.list.setSpacing(1)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.model().rowsMoved.connect(self._sync_order)
        delete_key(self.list, self.remove_selected)
        self.list.currentRowChanged.connect(self._on_select)

        add = QPushButton("＋ 클립 추가")
        add.clicked.connect(self.add_dialog)
        remove = QPushButton("삭제")
        remove.clicked.connect(self.remove_selected)
        up = QPushButton("▲")
        up.clicked.connect(lambda: self.move(-1))
        down = QPushButton("▼")
        down.clicked.connect(lambda: self.move(1))
        for b in (up, down):
            b.setFixedWidth(36)

        self.total_label = QLabel()

        # 선택한 클립 자르기
        self.edit_box = QGroupBox("선택한 클립 자르기")
        self.in_spin = seconds_spin()
        self.out_spin = seconds_spin()
        self.in_spin.valueChanged.connect(self._on_trim)
        self.out_spin.valueChanged.connect(self._on_trim)
        set_in = QPushButton("현재 위치")
        set_in.setToolTip("미리보기의 현재 재생 위치를 시작점으로")
        set_in.clicked.connect(lambda: self.in_spin.setValue(self._player_position()))
        set_out = QPushButton("현재 위치")
        set_out.setToolTip("미리보기의 현재 재생 위치를 끝점으로")
        set_out.clicked.connect(lambda: self.out_spin.setValue(self._player_position()))
        reset = QPushButton("자르기 취소")
        reset.clicked.connect(self._reset_trim)
        self.clip_info = QLabel()
        self.clip_info.setWordWrap(True)
        self.speed = QComboBox()
        for sp in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0):
            self.speed.addItem(("보통 (1배)" if sp == 1 else f"{sp:g}배" + (" 느리게" if sp < 1 else " 빠르게")), sp)
        self.speed.setCurrentIndex(self.speed.findData(1.0))
        self.speed.currentIndexChanged.connect(self._on_clip_props)
        self.motion = QComboBox()
        for key, label in MOTION_CHOICES:
            self.motion.addItem(label, key)
        self.motion.setToolTip("사진이 가만히 있지 않고 천천히 확대·이동해요 (켄 번즈 효과)")
        self.motion.currentIndexChanged.connect(self._on_clip_props)
        self.clip_vol, clip_vol_lbl = percent_slider(200)
        self.clip_vol.valueChanged.connect(self._on_clip_props)
        self.clip_mute = QCheckBox("음소거")
        self.clip_mute.toggled.connect(self._on_clip_props)
        form = QFormLayout(self.edit_box)
        form.addRow("시작", row(self.in_spin, set_in))
        form.addRow("끝", row(self.out_spin, set_out))
        form.addRow("속도", self.speed)
        form.addRow("사진 움직임", self.motion)
        form.addRow("이 클립 소리", row(self.clip_vol, clip_vol_lbl, self.clip_mute))
        form.addRow(row(self.clip_info, None, reset))
        self.edit_box.setEnabled(False)

        hint = QLabel("파일을 창에 끌어다 놓아도 추가돼요. 목록을 끌어서 순서를 바꿀 수 있어요.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")

        lay = QVBoxLayout(self)
        lay.addWidget(row(add, remove, None, up, down))
        lay.addWidget(self.list, 1)
        lay.addWidget(self.total_label)
        lay.addWidget(self.edit_box)
        lay.addWidget(hint)
        self.reload()

    # --- 목록 ---
    def reload(self) -> None:
        self._loading = True
        cur = self.list.currentRow()
        self.list.clear()
        for c in self.project.clips:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c)
            self._label(item)
            self.list.addItem(item)
        self._loading = False
        if self.project.clips:
            self.list.setCurrentRow(min(max(cur, 0), len(self.project.clips) - 1))
        else:
            self._on_select(-1)
        self._update_total()

    def _label(self, item: QListWidgetItem) -> None:
        c: Clip = item.data(Qt.UserRole)
        kind = "🖼" if is_image(c.path) else ("🎬" if c.has_audio else "🎬🔇")
        trimmed = " ✂" if (c.in_point > 0 or (c.out_point > 0 and c.duration and c.out_point < c.duration)) else ""
        extra = ""
        if c.speed != 1 and not is_image(c.path):
            extra += f"  ⏩{c.speed:g}배" if c.speed > 1 else f"  🐢{c.speed:g}배"
        if c.has_audio and c.volume <= 0:
            extra += "  🔇"
        item.setText(f"{kind} {c.name}   {fmt_time(c.timeline_length)}{trimmed}{extra}")
        at = self._thumb_time(c)
        item.setData(Qt.UserRole + 1, ThumbnailLoader.key(c.path, at))
        pm = self.thumbs.get(c.path, at)
        if pm is not None:
            item.setIcon(QIcon(pm))

    @staticmethod
    def _thumb_time(c: Clip) -> float:
        # 첫 프레임은 검은 화면인 경우가 많아서 조금 뒤 장면을 쓴다
        return 0.0 if is_image(c.path) else round(c.in_point + min(1.0, c.length / 3), 1)

    def _on_thumb(self, key: str, pm) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole + 1) == key:
                item.setIcon(QIcon(pm))

    def add_files(self, paths: list[str]) -> None:
        errors = []
        for p in paths:
            try:
                self.project.clips.append(make_clip(p))
            except Exception as e:
                errors.append(str(e))
        self.reload()
        self.list.setCurrentRow(len(self.project.clips) - 1)
        self.changed.emit()
        if errors:
            QMessageBox.warning(self, "추가하지 못한 파일", "\n".join(errors))

    def add_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "클립 추가", "", VIDEO_FILTER)
        if paths:
            self.add_files(paths)

    def remove_selected(self) -> None:
        r = self.list.currentRow()
        if r >= 0:
            del self.project.clips[r]
            self.reload()
            self.changed.emit()

    def move(self, delta: int) -> None:
        r = self.list.currentRow()
        n = r + delta
        if r < 0 or not (0 <= n < len(self.project.clips)):
            return
        clips = self.project.clips
        clips[r], clips[n] = clips[n], clips[r]
        self.reload()
        self.list.setCurrentRow(n)
        self.changed.emit()

    def _sync_order(self, *args) -> None:
        self.project.clips[:] = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]
        self._update_total()
        self.changed.emit()

    def _update_total(self) -> None:
        total = sum(c.timeline_length for c in self.project.clips)
        self.total_label.setText(f"클립 {len(self.project.clips)}개 · 이어붙인 길이 {fmt_time(total)}")

    # --- 자르기 ---
    def current_clip(self) -> Clip | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_select(self, r: int) -> None:
        c = self.current_clip() if r >= 0 else None
        self.edit_box.setEnabled(c is not None)
        if not c:
            self.clip_info.setText("")
            return
        self._loading = True
        limit = c.duration if c.duration > 0 else 3600.0
        self.in_spin.setMaximum(limit)
        self.out_spin.setMaximum(limit)
        self.in_spin.setValue(c.in_point)
        self.out_spin.setValue(c.end)
        image = is_image(c.path)
        self.speed.setEnabled(not image)
        idx = self.speed.findData(float(c.speed))
        if idx < 0:
            self.speed.addItem(f"{c.speed:g}배", float(c.speed))
            idx = self.speed.count() - 1
        self.speed.setCurrentIndex(idx)
        self.motion.setEnabled(image)
        self.motion.setCurrentIndex(max(0, self.motion.findData(c.motion)))
        self.clip_vol.setEnabled(c.has_audio and not image)
        self.clip_mute.setEnabled(c.has_audio and not image)
        self.clip_vol.setValue(int(round((c.volume if c.volume > 0 else 1.0) * 100)))
        self.clip_mute.setChecked(c.volume <= 0)
        self._loading = False
        self._update_info(c)
        if not is_image(c.path):
            self.preview_requested.emit(c.path, c.in_point)

    def _update_info(self, c: Clip) -> None:
        if is_image(c.path):
            self.clip_info.setText(f"사진 · {fmt_time(c.length)} 동안 표시")
        else:
            size = f"{c.width}×{c.height} · " if c.width else ""
            speed = f" → 영상에서 {fmt_time(c.timeline_length)}" if c.speed != 1 else ""
            self.clip_info.setText(f"{size}원본 {fmt_time(c.duration)} → 사용 {fmt_time(c.length)}{speed}")

    def _on_clip_props(self) -> None:
        if self._loading:
            return
        c = self.current_clip()
        if not c:
            return
        c.speed = float(self.speed.currentData())
        c.motion = self.motion.currentData()
        c.volume = 0.0 if self.clip_mute.isChecked() else self.clip_vol.value() / 100
        self.clip_vol.setEnabled(c.has_audio and not self.clip_mute.isChecked())
        self._label(self.list.currentItem())
        self._update_info(c)
        self._update_total()
        self.changed.emit()

    def _on_trim(self) -> None:
        if self._loading:
            return
        c = self.current_clip()
        if not c:
            return
        a, b = self.in_spin.value(), self.out_spin.value()
        if b <= a + 0.05:
            b = a + 0.1
            self._loading = True
            self.out_spin.setValue(b)
            self._loading = False
        c.in_point = a
        c.out_point = 0.0 if (c.duration and b >= c.duration - 1e-3) else b
        self._label(self.list.currentItem())
        self._update_info(c)
        self._update_total()
        self.changed.emit()

    def _reset_trim(self) -> None:
        c = self.current_clip()
        if not c:
            return
        c.in_point = 0.0
        c.out_point = IMAGE_DEFAULT_SECONDS if is_image(c.path) else 0.0
        self._on_select(self.list.currentRow())
        self._label(self.list.currentItem())
        self._update_total()
        self.changed.emit()


# ------------------------------------------------------------------ 음악·비트

class BeatStrip(QWidget):
    """음악 비트(얇은 선)와 실제 컷 위치(굵은 선)를 보여주는 띠."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.beats: list[float] = []
        self.cuts: list[float] = []
        self.length = 0.0

    def set_data(self, beats: list[float], cuts: list[float], length: float) -> None:
        self.beats, self.cuts, self.length = beats, cuts, length
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.fillRect(r, self.palette().base())
        p.setPen(self.palette().mid().color())
        p.drawRect(r)
        if self.length <= 0:
            p.setPen(self.palette().placeholderText().color())
            p.drawText(r, Qt.AlignCenter, "음악을 등록하고 분석하면 비트가 여기에 표시돼요")
            return
        w = r.width()

        def x(t: float) -> int:
            return int(r.left() + t / self.length * w)

        p.setPen(QPen(QColor(130, 130, 130, 140), 1))
        for b in self.beats:
            if 0 <= b <= self.length:
                p.drawLine(x(b), r.top() + 14, x(b), r.bottom() - 2)
        p.setPen(QPen(QColor(255, 120, 40), 2))
        for c in self.cuts:
            p.drawLine(x(c), r.top() + 2, x(c), r.bottom() - 2)


class MusicPanel(QWidget):
    changed = Signal()
    analyze_requested = Signal()
    music_chosen = Signal(str)        # 파일 경로
    download_requested = Signal(str)  # 유튜브 등 링크

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._loading = False

        # 음악 등록
        music_box = QGroupBox("음악 등록")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("유튜브 링크 붙여넣기 (예: https://youtu.be/...)")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self._request_download)
        self.download_btn = QPushButton("⬇ mp3로 받기")
        self.download_btn.clicked.connect(self._request_download)
        url_note = QLabel("받은 mp3는 '음악\\ReelCut' 폴더에 저장돼요. 저작권이 있는 노래는 업로드 시 "
                          "차단·수익 제한될 수 있으니 직접 만든 곡이나 무료 음원을 쓰세요.")
        url_note.setWordWrap(True)
        url_note.setStyleSheet("color: gray")
        self.file_label = QLabel("등록된 음악 없음")
        self.file_label.setWordWrap(True)
        pick = QPushButton("파일 선택…")
        pick.clicked.connect(self.pick_music)
        clear = QPushButton("빼기")
        clear.clicked.connect(self.clear_music)

        # 시작 위치 게이지 + 미리듣기
        self.gauge = MusicGauge()
        self.gauge.start_changed.connect(self._on_gauge_start)
        self.gauge.play_requested.connect(self._play_from)
        self.player = MusicPreviewPlayer(self, self.gauge.set_playhead, self._on_play_stopped)
        self.play_btn = QPushButton("▶ 시작 위치부터 듣기")
        self.play_btn.clicked.connect(self._toggle_play)
        self.start_spin = seconds_spin()
        self.vol_slider, vol_lbl = percent_slider(200)
        self.fade_spin = seconds_spin(30, 0.5, 1)
        self.clip_vol_slider, clip_vol_lbl = percent_slider(200)
        self.duck = QComboBox()
        for key, label in (("off", "줄이지 않음"), ("light", "약하게"), ("normal", "보통"), ("strong", "세게")):
            self.duck.addItem(label, key)
        self.duck.setToolTip("영상 원본·작은 화면에서 말소리가 나오는 동안 음악을 자동으로 줄였다가 다시 키워요")
        mf = QFormLayout(music_box)
        mf.addRow(row(self.url_edit, self.download_btn))
        mf.addRow(url_note)
        mf.addRow(row(self.file_label, None, pick, clear))
        mf.addRow(self.gauge)
        mf.addRow("음악 시작 위치", row(self.start_spin, self.play_btn))
        mf.addRow("음악 소리", row(self.vol_slider, vol_lbl))
        mf.addRow("끝 페이드아웃", self.fade_spin)
        mf.addRow("영상 원본 소리", row(self.clip_vol_slider, clip_vol_lbl))
        mf.addRow("말할 때 음악 줄이기", self.duck)

        # 비트 분석
        beat_box = QGroupBox("템포·비트")
        self.analyze_btn = QPushButton("🎵 비트 분석")
        self.analyze_btn.clicked.connect(self.analyze_requested.emit)
        self.bpm_spin = QDoubleSpinBox()
        self.bpm_spin.setRange(0, 300)
        self.bpm_spin.setDecimals(1)
        self.bpm_spin.setSuffix(" BPM")
        self.bpm_spin.setKeyboardTracking(False)
        apply_bpm = QPushButton("이 BPM으로 맞추기")
        apply_bpm.setToolTip("분석이 틀렸을 때 BPM을 직접 입력해서 일정한 간격의 비트로 바꿔요")
        apply_bpm.clicked.connect(self.apply_manual_bpm)
        dbl = QPushButton("×2")
        dbl.clicked.connect(lambda: self._scale_bpm(2.0))
        half = QPushButton("÷2")
        half.clicked.connect(lambda: self._scale_bpm(0.5))
        for b in (dbl, half):
            b.setFixedWidth(40)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-2, 2)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSingleStep(0.01)
        self.offset_spin.setSuffix(" 초")
        self.offset_spin.setKeyboardTracking(False)
        self.beat_info = QLabel()
        bf = QFormLayout(beat_box)
        bf.addRow(row(self.analyze_btn, None, self.beat_info))
        bf.addRow("템포", row(self.bpm_spin, dbl, half, apply_bpm))
        bf.addRow("비트 위치 조정", self.offset_spin)

        # 비트 맞춤 컷
        sync_box = QGroupBox("노래 비트(또는 일정한 시간)에 맞춰 잘라 이어붙이기")
        self.sync_check = QCheckBox("사용하기 (클립을 잘라서 정해진 순간마다 화면 전환)")
        self.cut_unit = QComboBox()
        self.cut_unit.addItem("음악 비트마다", "beats")
        self.cut_unit.addItem("일정한 초마다", "seconds")
        self.cut_seconds = QDoubleSpinBox()
        self.cut_seconds.setRange(0.2, 60)
        self.cut_seconds.setDecimals(1)
        self.cut_seconds.setSingleStep(0.5)
        self.cut_seconds.setSuffix(" 초마다")
        self.cut_seconds.setKeyboardTracking(False)
        self.per_cut = QComboBox()
        for n in (1, 2, 4, 8, 16):
            self.per_cut.addItem(f"{n}비트마다", n)
        self.order = QComboBox()
        self.order.addItem("파일 번갈아 (컷마다 1→2→3→1…)", "sequential")
        self.order.addItem("파일별로 몰아서 (1번 파일 다 쓰고 2번…)", "grouped")
        self.order.addItem("무작위 (같은 파일 연속 없음)", "random")
        self.order.addItem("이어서 (예전 방식, 원본 흐름 그대로)", "continuous")
        self.shuffle_btn = QPushButton("다시 섞기")
        self.shuffle_btn.clicked.connect(self._reshuffle)
        self.cut_mode = QComboBox()
        self.cut_mode.addItem("일정하게 (정해진 비트마다)", "regular")
        self.cut_mode.addItem("센 비트에서만 (킥·스네어 강한 곳)", "accent")
        self.cut_mode.addItem("신나는 부분은 빠르게, 조용한 부분은 느리게", "energy")
        self.transition = QComboBox()
        for label, key in (("효과 없음 (바로 바뀜)", "none"), ("번쩍 (흰 화면 플래시)", "flash"),
                           ("줌 펀치 (살짝 확대됐다 돌아옴)", "zoom"), ("검은 깜빡임", "dip")):
            self.transition.addItem(label, key)
        self.length_mode = QComboBox()
        self.length_mode.addItem("음악 길이만큼", "music")
        self.length_mode.addItem("클립 길이만큼 (최대 음악 길이)", "clips")
        self.length_mode.addItem("클립 개수 × 컷 길이 (클립마다 한 번씩, 노래도 거기서 끝)", "per_clip")
        self.max_spin = seconds_spin(36000, 1, 0)
        self.max_spin.setSpecialValueText("제한 없음")
        self.strip = BeatStrip()
        self.cut_info = QLabel()
        sf = QFormLayout(sync_box)
        sf.addRow(self.sync_check)
        sf.addRow("자르는 기준", row(self.cut_unit, self.per_cut, self.cut_seconds))
        sf.addRow("컷 리듬", self.cut_mode)
        sf.addRow("클립 고르는 방식", row(self.order, self.shuffle_btn))
        sf.addRow("컷 전환 효과", self.transition)
        sf.addRow("영상 길이", row(self.length_mode, QLabel("최대"), self.max_spin))
        sf.addRow(self.strip)
        sf.addRow(self.cut_info)

        lay = QVBoxLayout(self)
        lay.addWidget(music_box)
        lay.addWidget(beat_box)
        lay.addWidget(sync_box)
        lay.addStretch(1)

        for w in (self.start_spin, self.fade_spin, self.offset_spin, self.max_spin, self.cut_seconds):
            w.valueChanged.connect(self._store)
        for w in (self.vol_slider, self.clip_vol_slider):
            w.valueChanged.connect(self._store)
        self.bpm_spin.valueChanged.connect(self._store)
        self.sync_check.toggled.connect(self._store)
        for w in (self.per_cut, self.order, self.length_mode, self.transition, self.cut_mode, self.cut_unit,
                  self.duck):
            w.currentIndexChanged.connect(self._store)
        self.reload()

    def reload(self) -> None:
        self._loading = True
        m, bs, ex = self.project.music, self.project.beat_sync, self.project.export
        self.file_label.setText(f"🎵 {Path(m.path).name}  ({fmt_time(m.duration)})" if m.path else "등록된 음악 없음")
        self.start_spin.setValue(m.start)
        self.vol_slider.setValue(int(round(m.volume * 100)))
        self.fade_spin.setValue(m.fade_out)
        self.clip_vol_slider.setValue(int(round(ex.clip_volume * 100)))
        self.duck.setCurrentIndex(max(0, self.duck.findData(m.duck)))
        self.bpm_spin.setValue(m.bpm)
        self.offset_spin.setValue(m.beat_offset)
        self.sync_check.setChecked(bs.enabled)
        self.per_cut.setCurrentIndex(max(0, self.per_cut.findData(bs.beats_per_cut)))
        self.order.setCurrentIndex(max(0, self.order.findData("sequential" if bs.order == "spread" else bs.order)))
        self.length_mode.setCurrentIndex(self.length_mode.findData(
            "per_clip" if bs.per_clip else ("music" if bs.use_music_length else "clips")))
        self.cut_unit.setCurrentIndex(max(0, self.cut_unit.findData(bs.cut_unit)))
        self.cut_seconds.setValue(bs.cut_seconds)
        self.transition.setCurrentIndex(max(0, self.transition.findData(bs.transition)))
        self.cut_mode.setCurrentIndex(max(0, self.cut_mode.findData(bs.cut_mode)))
        self.max_spin.setValue(bs.max_duration)
        self._loading = False
        self._refresh_info()

    def _store(self) -> None:
        if self._loading:
            return
        m, bs, ex = self.project.music, self.project.beat_sync, self.project.export
        m.start = self.start_spin.value()
        m.volume = self.vol_slider.value() / 100
        m.fade_out = self.fade_spin.value()
        m.bpm = self.bpm_spin.value()
        m.beat_offset = self.offset_spin.value()
        ex.clip_volume = self.clip_vol_slider.value() / 100
        m.duck = self.duck.currentData()
        was = bs.enabled
        bs.enabled = self.sync_check.isChecked()
        bs.beats_per_cut = self.per_cut.currentData()
        bs.order = self.order.currentData()
        mode = self.length_mode.currentData()
        bs.per_clip = mode == "per_clip"
        bs.use_music_length = mode != "clips"
        bs.cut_unit = self.cut_unit.currentData()
        bs.cut_seconds = self.cut_seconds.value()
        bs.transition = self.transition.currentData()
        bs.cut_mode = self.cut_mode.currentData()
        bs.max_duration = self.max_spin.value()
        if bs.enabled and not was and ex.clip_volume >= 1.0:
            # 비트 맞춤 영상은 보통 음악만 들리게 한다
            self.clip_vol_slider.setValue(0)
            return
        self._refresh_info()
        self.changed.emit()

    def _refresh_info(self) -> None:
        from ..timeline import build_segments, segment_starts, total_duration

        m = self.project.music
        self.shuffle_btn.setEnabled(self.project.beat_sync.order == "random")
        if m.beats:
            self.beat_info.setText(f"비트 {len(m.beats)}개 · 약 {m.bpm:.1f} BPM")
        else:
            self.beat_info.setText("아직 분석 전" if m.path else "")
        self.analyze_btn.setEnabled(bool(m.path))
        self.play_btn.setEnabled(bool(m.path))
        bs = self.project.beat_sync
        seconds = bs.cut_unit == "seconds"
        self.per_cut.setVisible(not seconds)
        self.cut_seconds.setVisible(seconds)
        self.cut_mode.setEnabled(not seconds)
        segs = build_segments(self.project)
        length = max(total_duration(segs), 0.0)
        cuts = segment_starts(segs)[1:] if bs.enabled else []
        if m.path:
            view_len = length if length > 0 else max(0.0, m.duration - m.start)
            beats_rel = [b + m.beat_offset - m.start for b in m.beats]
            if self.gauge.duration != m.duration:
                self.gauge.duration = m.duration
            self.gauge.set_beats([b + m.beat_offset for b in m.beats])
            self.gauge.set_selection(m.start, length if self.project.clips else 0.0)
            self.strip.set_data(beats_rel, cuts, view_len)
        else:
            self.gauge.set_selection(0.0, 0.0)
            self.strip.set_data([], cuts, length if seconds and bs.enabled else 0)
        usable = [c for c in self.project.clips if c.length > 0.05]
        if not bs.enabled:
            self.cut_info.setText("꺼져 있으면 음악은 배경음으로만 깔려요." if m.path else "")
        elif not seconds and not m.path:
            self.cut_info.setText("음악을 등록하거나, 자르는 기준을 '일정한 초마다'로 바꿔 주세요.")
        elif not seconds and not m.beats:
            self.cut_info.setText("먼저 '비트 분석'을 눌러 주세요.")
        elif not usable:
            self.cut_info.setText("클립 탭에서 영상을 추가해 주세요.")
        elif bs.per_clip:
            each = f"{bs.cut_seconds:g}초" if seconds else f"{bs.beats_per_cut}비트"
            text = f"클립 {len(usable)}개 × {each} = 완성 길이 {fmt_time(length)}"
            if len(segs) < len(usable):
                text += f" · 음악이 짧아서 클립 {len(segs)}개까지만 들어가요"
            short = [c.name for c, sg in zip(usable, segs) if c.timeline_length + 1e-6 < sg.duration]
            if short:
                text += f" · {len(short)}개 클립은 컷보다 짧아서 마지막 장면이 멈춰 보여요"
            self.cut_info.setText(text)
        else:
            note = ""
            if not seconds and bs.cut_mode != "regular" and len(m.beat_strengths) != len(m.beats):
                note = " · 컷 리듬을 쓰려면 '비트 분석'을 다시 눌러 주세요"
            self.cut_info.setText(f"컷 {len(segs)}개 · 완성 길이 {fmt_time(length)}{note}")

    def pick_music(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "음악 선택", "", AUDIO_FILTER)
        if path:
            self.music_chosen.emit(path)

    def _request_download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self.url_edit.setFocus()
            return
        self.download_requested.emit(url)

    def set_downloading(self, busy: bool) -> None:
        self.download_btn.setEnabled(not busy)
        self.url_edit.setEnabled(not busy)

    def set_waveform(self, peaks) -> None:
        self.gauge.set_waveform(peaks, self.project.music.duration)

    # --- 미리듣기 ---
    def _on_gauge_start(self, t: float) -> None:
        self.start_spin.setValue(t)          # → _store
        if self.player.playing:
            self._play_from(t)

    def _play_end(self) -> float | None:
        length = self.gauge.length
        return self.project.music.start + length if length > 0 else None

    def _play_from(self, t: float) -> None:
        m = self.project.music
        if not m.path:
            return
        stop = self._play_end()
        if stop is not None and t >= stop:
            stop = None
        self.player.play(m.path, t, stop)
        self.play_btn.setText("■ 정지")

    def _toggle_play(self) -> None:
        if self.player.playing:
            self.player.stop()
        else:
            self._play_from(self.project.music.start)

    def _on_play_stopped(self) -> None:
        self.play_btn.setText("▶ 시작 위치부터 듣기")
        self.gauge.set_playhead(None)

    def stop_preview(self) -> None:
        self.player.unload()

    def clear_music(self) -> None:
        from ..project import MusicSettings

        self.player.unload()
        self.project.music = MusicSettings()
        self.project.beat_sync.enabled = False
        self.gauge.set_waveform([], 0.0)
        self.reload()
        self.changed.emit()

    def set_beats(self, bpm: float, beats: list[float], strengths: list[float] | None = None,
                  energy: list[float] | None = None) -> None:
        m = self.project.music
        m.bpm = bpm
        m.beats = beats
        m.beat_strengths = list(strengths or [])
        m.beat_energy = list(energy or [])
        self.reload()
        self.changed.emit()

    def apply_manual_bpm(self) -> None:
        from ..beats import grid_beats

        m = self.project.music
        bpm = self.bpm_spin.value()
        if bpm <= 0 or not m.path:
            return
        first = m.beats[0] if m.beats else 0.0
        step = 60.0 / bpm
        first = first % step
        self.set_beats(bpm, grid_beats(bpm, first, m.duration))

    def _scale_bpm(self, factor: float) -> None:
        m = self.project.music
        if m.bpm <= 0:
            return
        if factor == 0.5 and len(m.beats) >= 2:
            # 하나 걸러 하나만 남기기
            self.set_beats(round(m.bpm / 2, 1), m.beats[::2], m.beat_strengths[::2], m.beat_energy[::2])
        elif factor == 2.0 and len(m.beats) >= 2:
            mids = [(a + b) / 2 for a, b in zip(m.beats, m.beats[1:])]
            merged = sorted(m.beats + mids)
            strengths, energy = [], []
            if len(m.beat_strengths) == len(m.beats) and len(m.beat_energy) == len(m.beats):
                for i in range(len(m.beats)):
                    strengths.append(m.beat_strengths[i])
                    energy.append(m.beat_energy[i])
                    if i < len(mids):
                        strengths.append(0.0)              # 사이에 끼운 비트는 약한 비트
                        energy.append(m.beat_energy[i])
            self.set_beats(round(m.bpm * 2, 1), merged, strengths, energy)

    def _reshuffle(self) -> None:
        self.project.beat_sync.seed += 1
        self._refresh_info()
        self.changed.emit()


# ------------------------------------------------------------------ 화면 속 화면

POSITION_LABELS = [
    ("오른쪽 아래", "bottom-right"), ("오른쪽 위", "top-right"), ("왼쪽 아래", "bottom-left"),
    ("왼쪽 위", "top-left"), ("가운데", "center"), ("직접 지정", "custom"),
]
BORDER_COLORS = [("흰색", "white"), ("검정", "black"), ("노랑", "yellow"), ("빨강", "red")]


class PipPanel(QWidget):
    changed = Signal()

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._loading = False
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)
        delete_key(self.list, self.remove_selected)
        add = QPushButton("＋ 작은 화면 추가")
        add.clicked.connect(self.add_dialog)
        remove = QPushButton("삭제")
        remove.clicked.connect(self.remove_selected)

        self.box = QGroupBox("선택한 작은 화면")
        self.pos = QComboBox()
        for label, key in POSITION_LABELS:
            self.pos.addItem(label, key)
        self.x_spin = QDoubleSpinBox()
        self.y_spin = QDoubleSpinBox()
        for s in (self.x_spin, self.y_spin):
            s.setRange(0, 100)
            s.setSuffix(" %")
            s.setDecimals(1)
            s.setKeyboardTracking(False)
        self.size_slider, size_lbl = percent_slider(100)
        self.size_slider.setMinimum(5)
        self.start_spin = seconds_spin()
        self.dur_spin = seconds_spin()
        self.dur_spin.setSpecialValueText("끝까지")
        self.src_spin = seconds_spin()
        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 40)
        self.border_spin.setSuffix(" px")
        self.border_color = QComboBox()
        for label, key in BORDER_COLORS:
            self.border_color.addItem(label, key)
        self.vol_slider, vol_lbl = percent_slider(200)
        self.info = QLabel()
        self.info.setWordWrap(True)

        f = QFormLayout(self.box)
        f.addRow("위치", self.pos)
        f.addRow("직접 지정 (왼쪽, 위)", row(self.x_spin, self.y_spin))
        f.addRow("크기 (화면 너비 대비)", row(self.size_slider, size_lbl))
        f.addRow("나타나는 시점", self.start_spin)
        f.addRow("보이는 시간", self.dur_spin)
        f.addRow("원본에서 시작할 위치", self.src_spin)
        f.addRow("테두리", row(self.border_spin, self.border_color))
        f.addRow("작은 화면 소리", row(self.vol_slider, vol_lbl))
        f.addRow(self.info)
        self.box.setEnabled(False)

        hint = QLabel("완성 영상의 오른쪽 아래(기본 위치)에 다른 영상을 작게 넣어요. 리액션 캠, 해설 화면, 로고 사진 등에 쓰세요.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")

        lay = QVBoxLayout(self)
        lay.addWidget(row(add, remove, None))
        lay.addWidget(self.list, 1)
        lay.addWidget(self.box)
        lay.addWidget(hint)

        for w in (self.x_spin, self.y_spin, self.start_spin, self.dur_spin, self.src_spin):
            w.valueChanged.connect(self._store)
        for w in (self.size_slider, self.vol_slider, self.border_spin):
            w.valueChanged.connect(self._store)
        for w in (self.pos, self.border_color):
            w.currentIndexChanged.connect(self._store)
        self.reload()

    def reload(self) -> None:
        cur = self.list.currentRow()
        self._loading = True
        self.list.clear()
        for p in self.project.pips:
            self.list.addItem(self._text(p))
        self._loading = False
        if self.project.pips:
            self.list.setCurrentRow(min(max(cur, 0), len(self.project.pips) - 1))
        else:
            self._on_select(-1)

    def _text(self, p: PipOverlay) -> str:
        label = dict((k, l) for l, k in POSITION_LABELS).get(p.position, p.position)
        icon = "🖼" if is_image(p.path) else "🎬"
        return f"{icon} {Path(p.path).name} · {label} · {fmt_time(p.start)}부터"

    def add_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "작은 화면으로 넣을 영상/사진", "", VIDEO_FILTER)
        if not path:
            return
        p = PipOverlay(path)
        if not is_image(path):
            try:
                info = probe(path)
            except Exception as e:
                QMessageBox.warning(self, "화면 속 화면", str(e))
                return
            p.src_duration = info.duration
            p.has_audio = info.has_audio
        else:
            p.border = 0
        self.project.pips.append(p)
        self.reload()
        self.list.setCurrentRow(len(self.project.pips) - 1)
        self.changed.emit()

    def remove_selected(self) -> None:
        r = self.list.currentRow()
        if r >= 0:
            del self.project.pips[r]
            self.reload()
            self.changed.emit()

    def current(self) -> PipOverlay | None:
        r = self.list.currentRow()
        return self.project.pips[r] if 0 <= r < len(self.project.pips) else None

    def _on_select(self, _r: int) -> None:
        p = self.current()
        self.box.setEnabled(p is not None)
        if not p:
            return
        self._loading = True
        self.pos.setCurrentIndex(max(0, self.pos.findData(p.position)))
        self.x_spin.setValue(p.x * 100)
        self.y_spin.setValue(p.y * 100)
        self.size_slider.setValue(int(round(p.size * 100)))
        self.start_spin.setValue(p.start)
        self.dur_spin.setValue(p.duration)
        self.src_spin.setValue(p.src_start)
        self.border_spin.setValue(p.border)
        self.border_color.setCurrentIndex(max(0, self.border_color.findData(p.border_color)))
        self.vol_slider.setValue(int(round(p.volume * 100)))
        self._loading = False
        self._update_enabled(p)

    def _update_enabled(self, p: PipOverlay) -> None:
        custom = p.position == "custom"
        self.x_spin.setEnabled(custom)
        self.y_spin.setEnabled(custom)
        video = not is_image(p.path)
        self.src_spin.setEnabled(video)
        self.vol_slider.setEnabled(video and p.has_audio)
        if video:
            self.info.setText(f"원본 길이 {fmt_time(p.src_duration)}" + ("" if p.has_audio else " · 소리 없음"))
        else:
            self.info.setText("사진은 '보이는 시간' 동안 표시돼요 (끝까지 = 영상 끝까지).")

    def _store(self) -> None:
        if self._loading:
            return
        p = self.current()
        if not p:
            return
        p.position = self.pos.currentData()
        p.x = self.x_spin.value() / 100
        p.y = self.y_spin.value() / 100
        p.size = self.size_slider.value() / 100
        p.start = self.start_spin.value()
        p.duration = self.dur_spin.value()
        p.src_start = self.src_spin.value()
        p.border = self.border_spin.value()
        p.border_color = self.border_color.currentData()
        p.volume = self.vol_slider.value() / 100
        self.list.currentItem().setText(self._text(p))
        self._update_enabled(p)
        self.changed.emit()


# ------------------------------------------------------------------ 자막

class SubtitlePanel(QWidget):
    changed = Signal()
    generate_requested = Signal()

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._loading = False

        gen_box = QGroupBox("자동 자막 만들기 (Whisper 음성 인식)")
        self.model = QComboBox()
        for name, desc in (("tiny", "가장 빠름"), ("base", "빠름"), ("small", "추천"),
                           ("medium", "정확"), ("large-v3", "가장 정확·느림")):
            self.model.addItem(f"{name} ({desc})", name)
        self.lang = QComboBox()
        for code, label in subs.LANGUAGES.items():
            self.lang.addItem(label, code)
        self.source = QComboBox()
        self.source.addItem("영상 속 말소리", "video")
        self.source.addItem("등록한 음악의 가사", "music")
        self.gen_btn = QPushButton("✨ 자동 자막 만들기")
        self.gen_btn.clicked.connect(self.generate_requested.emit)
        gf = QFormLayout(gen_box)
        gf.addRow("인식 모델", self.model)
        gf.addRow("언어", self.lang)
        gf.addRow("인식할 소리", self.source)
        gf.addRow(self.gen_btn)
        note = QLabel("처음 사용할 때 모델을 내려받아요 (small 약 500MB). 이후에는 인터넷 없이 동작해요.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")
        gf.addRow(note)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["시작", "끝", "자막 내용"])
        delete_key(self.table, self.remove_rows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setMinimumHeight(160)
        self.table.currentCellChanged.connect(lambda r, *_: self._update_sample())

        add = QPushButton("＋ 줄 추가")
        add.clicked.connect(self.add_row)
        rm = QPushButton("줄 삭제")
        rm.clicked.connect(self.remove_rows)
        load = QPushButton("SRT 불러오기")
        load.clicked.connect(self.load_srt)
        save = QPushButton("SRT 저장")
        save.clicked.connect(self.save_srt)
        clear = QPushButton("모두 지우기")
        clear.clicked.connect(self.clear_all)

        style_box = QGroupBox("자막 모양")
        self.burn = QComboBox()
        self.burn.addItem("영상에 입히기 (어디서나 보임)", True)
        self.burn.addItem("자막 트랙으로 넣기 (끄고 켤 수 있음)", False)
        self.animation = QComboBox()
        for key, label in (("none", "없음"), ("fade", "스르륵 나타나기"), ("pop", "톡 튀어나오기")):
            self.animation.addItem(label, key)
        self.animation.setToolTip("자막이 나타날 때 효과 (영상에 입힐 때만)")
        self.font = QFontComboBox()
        self.font.setToolTip("컴퓨터에 설치된 글꼴")
        font_file_btn = QPushButton("글꼴 파일…")
        font_file_btn.setToolTip("설치하지 않은 .ttf / .otf 글꼴 파일을 바로 사용")
        font_file_btn.clicked.connect(self.pick_font_file)
        self.font_file_label = QLabel()
        self.font_file_label.setStyleSheet("color: gray")
        self.font_file_clear = QPushButton("파일 해제")
        self.font_file_clear.clicked.connect(self.clear_font_file)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 120)
        self.bold = QCheckBox("굵게")
        self.color_btn = ColorButton("#FFFFFF")
        self.outline_color_btn = ColorButton("#000000")
        self.outline = QSpinBox()
        self.outline.setRange(0, 10)
        self.box = QCheckBox("배경 상자")
        self.box.setToolTip("외곽선 대신 글자 뒤에 반투명 상자 (상자 색 = 외곽선 색)")
        self.position = QComboBox()
        for label, key in (("아래", "bottom"), ("가운데", "middle"), ("위", "top")):
            self.position.addItem(label, key)
        self.margin = QSpinBox()
        self.margin.setRange(0, 200)
        self.sample = SubtitleSample()
        sf = QFormLayout(style_box)
        sf.addRow("넣는 방식", row(self.burn, QLabel("등장 효과"), self.animation))
        sf.addRow("글꼴", row(self.font, font_file_btn))
        sf.addRow("", row(self.font_file_label, None, self.font_file_clear))
        sf.addRow("크기", row(self.font_size, self.bold, None))
        sf.addRow("글자색", row(self.color_btn, QLabel("외곽선"), self.outline_color_btn, self.outline, self.box, None))
        sf.addRow("위치", row(self.position, QLabel("여백"), self.margin, None))
        sf.addRow(self.sample)

        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: #c0392b")

        lay = QVBoxLayout(self)
        lay.addWidget(gen_box)
        lay.addWidget(row(add, rm, None, load, save, clear))
        lay.addWidget(self.table, 1)
        lay.addWidget(self.warn)
        lay.addWidget(style_box)

        for w in (self.model, self.lang, self.source, self.burn, self.animation):
            w.currentIndexChanged.connect(self._store)
        self.font.currentFontChanged.connect(self._on_font_picked)
        for w in (self.font_size, self.outline, self.margin):
            w.valueChanged.connect(self._store)
        for w in (self.bold, self.box):
            w.toggled.connect(self._store)
        self.position.currentIndexChanged.connect(self._store)
        for w in (self.color_btn, self.outline_color_btn):
            w.color_changed.connect(self._store)
        self.reload()

    def reload(self) -> None:
        s = self.project.subtitles
        self._loading = True
        self.model.setCurrentIndex(max(0, self.model.findData(s.model)))
        self.lang.setCurrentIndex(max(0, self.lang.findData(s.language)))
        self.source.setCurrentIndex(max(0, self.source.findData(s.source)))
        self.burn.setCurrentIndex(0 if s.burn_in else 1)
        self.animation.setCurrentIndex(max(0, self.animation.findData(s.animation)))
        self.animation.setEnabled(s.burn_in)
        from PySide6.QtGui import QFont
        if s.font_file:
            register_font_file(s.font_file)
        self.font.setCurrentFont(QFont(s.font_name))
        self.font_size.setValue(s.font_size)
        self.bold.setChecked(s.bold)
        self.color_btn.set_color(s.color)
        self.outline_color_btn.set_color(s.outline_color)
        self.outline.setValue(s.outline)
        self.box.setChecked(s.box)
        self.position.setCurrentIndex(max(0, self.position.findData(s.position)))
        self.margin.setValue(s.margin_v)
        self._update_font_file_label()
        self.table.setRowCount(0)
        for e in sorted(s.entries, key=lambda x: x.start):
            self._append(e)
        self._loading = False
        self._validate()

    def _append(self, e: SubtitleEntry) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(subs.format_ts(e.start)))
        self.table.setItem(r, 1, QTableWidgetItem(subs.format_ts(e.end)))
        self.table.setItem(r, 2, QTableWidgetItem(e.text))

    def _store(self) -> None:
        if self._loading:
            return
        s = self.project.subtitles
        s.model = self.model.currentData()
        s.language = self.lang.currentData()
        s.source = self.source.currentData()
        s.burn_in = bool(self.burn.currentData())
        s.animation = self.animation.currentData()
        self.animation.setEnabled(s.burn_in)
        s.font_size = self.font_size.value()
        s.bold = self.bold.isChecked()
        s.color = self.color_btn.color
        s.outline_color = self.outline_color_btn.color
        s.outline = self.outline.value()
        s.box = self.box.isChecked()
        s.position = self.position.currentData()
        s.margin_v = self.margin.value()
        self._update_sample()
        self.changed.emit()

    def _on_item_changed(self, _item) -> None:
        if not self._loading:
            self._validate()
            self.changed.emit()

    def _validate(self) -> None:
        entries, bad = [], 0
        self._loading = True
        for r in range(self.table.rowCount()):
            items = [self.table.item(r, c) for c in range(3)]
            try:
                a = subs.parse_ts(items[0].text())
                b = subs.parse_ts(items[1].text())
                ok = b > a
            except (ValueError, AttributeError):
                ok = False
            for it in items[:2]:
                if it:
                    it.setBackground(QColor(0, 0, 0, 0) if ok else QColor(255, 120, 120, 90))
            if ok:
                entries.append(SubtitleEntry(a, b, items[2].text() if items[2] else ""))
            else:
                bad += 1
        self._loading = False
        self.project.subtitles.entries = entries
        self.warn.setText(f"시간 형식이 잘못된 줄 {bad}개는 빠져요 (예: 00:01:02,500)." if bad else "")

    def set_entries(self, entries: list[SubtitleEntry]) -> None:
        self.project.subtitles.entries = entries
        self.reload()
        self.changed.emit()

    def add_row(self) -> None:
        last = self.project.subtitles.entries[-1].end if self.project.subtitles.entries else 0.0
        self._loading = True
        self._append(SubtitleEntry(last, last + 2.0, "새 자막"))
        self._loading = False
        self._validate()
        self.table.scrollToBottom()
        self.changed.emit()

    def remove_rows(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._validate()
        self.changed.emit()
        self.changed.emit()

    def clear_all(self) -> None:
        if self.table.rowCount() and QMessageBox.question(self, "자막", "자막을 모두 지울까요?") == QMessageBox.Yes:
            self.set_entries([])

    def load_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "SRT 불러오기", "", "자막 (*.srt);;모든 파일 (*)")
        if path:
            try:
                self.set_entries(subs.load_srt(path))
            except ValueError as e:
                QMessageBox.warning(self, "자막", str(e))

    def save_srt(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "SRT 저장", "자막.srt", "자막 (*.srt)")
        if path:
            subs.save_srt(path, self.project.subtitles.entries)

    # --- 글꼴 ---
    def _on_font_picked(self, font) -> None:
        if self._loading:
            return
        s = self.project.subtitles
        s.font_name = font.family()
        if s.font_file and s.font_name not in font_file_families(s.font_file):
            s.font_file = ""          # 목록에서 다른 글꼴을 고르면 파일 글꼴은 해제
        self._update_font_file_label()
        self._store()

    def pick_font_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "글꼴 파일 선택", "", "글꼴 (*.ttf *.otf *.ttc);;모든 파일 (*)")
        if not path:
            return
        families = register_font_file(path)
        if not families:
            QMessageBox.warning(self, "글꼴", "글꼴 파일을 읽을 수 없어요.")
            return
        s = self.project.subtitles
        s.font_file, s.font_name = path, families[0]
        self._loading = True
        from PySide6.QtGui import QFont
        self.font.setCurrentFont(QFont(families[0]))
        self._loading = False
        self._update_font_file_label()
        self._store()

    def clear_font_file(self) -> None:
        s = self.project.subtitles
        s.font_file = ""
        s.font_name = self.font.currentFont().family()
        self._update_font_file_label()
        self._store()

    def _update_font_file_label(self) -> None:
        f = self.project.subtitles.font_file
        self.font_file_label.setText(f"파일 글꼴 사용 중: {Path(f).name}" if f else "설치된 글꼴 사용 중")
        self.font_file_clear.setVisible(bool(f))
        self._update_sample()

    def _update_sample(self) -> None:
        text = "자막 미리보기 Subtitle 123"
        r = self.table.currentRow()
        if 0 <= r < self.table.rowCount() and self.table.item(r, 2) and self.table.item(r, 2).text().strip():
            text = self.table.item(r, 2).text()
        self.sample.set_style(self.project.subtitles, text)


# ------------------------------------------------------------------ 제목

class TitlePanel(QWidget):
    """자막과 별개로 화면에 크게 띄우는 제목 글자."""
    changed = Signal()

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._loading = False

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["시작", "끝", "제목 (줄을 바꾸려면 \\n)"])
        delete_key(self.table, self.remove_rows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(140)
        self.table.itemChanged.connect(self._on_item_changed)
        add = QPushButton("＋ 제목 추가")
        add.clicked.connect(self.add_row)
        rm = QPushButton("삭제")
        rm.clicked.connect(self.remove_rows)
        self.warn = QLabel()
        self.warn.setStyleSheet("color: #c0392b")

        style = QGroupBox("제목 모양")
        self.font = QFontComboBox()
        font_file_btn = QPushButton("글꼴 파일…")
        font_file_btn.clicked.connect(self.pick_font_file)
        self.font_file_label = QLabel()
        self.font_file_label.setStyleSheet("color: gray")
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(3, 25)
        self.size_lbl = QLabel()
        self.size_slider.valueChanged.connect(lambda v: self.size_lbl.setText(f"화면 높이의 {v}%"))
        self.bold = QCheckBox("굵게")
        self.color_btn = ColorButton("#FFFFFF")
        self.outline_color_btn = ColorButton("#000000")
        self.position = QComboBox()
        for label, key in (("가운데", "center"), ("위", "top"), ("아래", "bottom")):
            self.position.addItem(label, key)
        self.fade = QDoubleSpinBox()
        self.fade.setRange(0, 3)
        self.fade.setSingleStep(0.1)
        self.fade.setSuffix(" 초")
        self.fade.setKeyboardTracking(False)
        f = QFormLayout(style)
        f.addRow("글꼴", row(self.font, font_file_btn))
        f.addRow("", self.font_file_label)
        f.addRow("크기", row(self.size_slider, self.size_lbl, self.bold))
        f.addRow("색", row(self.color_btn, QLabel("외곽선"), self.outline_color_btn, None))
        f.addRow("위치", row(self.position, QLabel("나타나는 시간"), self.fade, None))

        hint = QLabel("영상 위에 큰 글자로 제목을 띄워요 (서서히 나타났다 사라짐). 시간은 완성 영상 기준이에요.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")

        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(row(add, rm, None))
        lay.addWidget(self.table, 1)
        lay.addWidget(self.warn)
        lay.addWidget(style)

        self.font.currentFontChanged.connect(self._on_font_picked)
        self.size_slider.valueChanged.connect(self._store)
        self.bold.toggled.connect(self._store)
        self.position.currentIndexChanged.connect(self._store)
        self.fade.valueChanged.connect(self._store)
        for w in (self.color_btn, self.outline_color_btn):
            w.color_changed.connect(self._store)
        self.reload()

    def reload(self) -> None:
        t = self.project.titles
        self._loading = True
        if t.font_file:
            register_font_file(t.font_file)
        from PySide6.QtGui import QFont
        self.font.setCurrentFont(QFont(t.font_name))
        self.size_slider.setValue(int(round(t.size)))
        self.size_lbl.setText(f"화면 높이의 {int(round(t.size))}%")
        self.bold.setChecked(t.bold)
        self.color_btn.set_color(t.color)
        self.outline_color_btn.set_color(t.outline_color)
        self.position.setCurrentIndex(max(0, self.position.findData(t.position)))
        self.fade.setValue(t.fade)
        self.table.setRowCount(0)
        for e in sorted(t.entries, key=lambda x: x.start):
            self._append(e)
        self._loading = False
        self._update_font_label()
        self._validate()

    def _append(self, e) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(subs.format_ts(e.start)))
        self.table.setItem(r, 1, QTableWidgetItem(subs.format_ts(e.end)))
        self.table.setItem(r, 2, QTableWidgetItem(e.text.replace("\n", "\\n")))

    def _store(self) -> None:
        if self._loading:
            return
        t = self.project.titles
        t.size = float(self.size_slider.value())
        t.bold = self.bold.isChecked()
        t.color = self.color_btn.color
        t.outline_color = self.outline_color_btn.color
        t.position = self.position.currentData()
        t.fade = self.fade.value()
        self.changed.emit()

    def _on_item_changed(self, _item) -> None:
        if not self._loading:
            self._validate()
            self.changed.emit()

    def _validate(self) -> None:
        from ..project import TitleEntry

        entries, bad = [], 0
        self._loading = True
        for r in range(self.table.rowCount()):
            items = [self.table.item(r, c) for c in range(3)]
            try:
                a = subs.parse_ts(items[0].text())
                b = subs.parse_ts(items[1].text())
                ok = b > a
            except (ValueError, AttributeError):
                ok = False
            for it in items[:2]:
                if it:
                    it.setBackground(QColor(0, 0, 0, 0) if ok else QColor(255, 120, 120, 90))
            if ok:
                text = (items[2].text() if items[2] else "").replace("\\n", "\n")
                entries.append(TitleEntry(a, b, text))
            else:
                bad += 1
        self._loading = False
        self.project.titles.entries = entries
        self.warn.setText(f"시간 형식이 잘못된 줄 {bad}개는 빠져요 (예: 00:00:03,000)." if bad else "")

    def add_row(self) -> None:
        from ..project import TitleEntry

        last = self.project.titles.entries[-1].end if self.project.titles.entries else 0.0
        self._loading = True
        self._append(TitleEntry(last, last + 3.0, "제목을 입력하세요"))
        self._loading = False
        self._validate()
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 2))
        self.changed.emit()

    def remove_rows(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
        self._validate()
        self.changed.emit()

    def _on_font_picked(self, font) -> None:
        if self._loading:
            return
        t = self.project.titles
        t.font_name = font.family()
        if t.font_file and t.font_name not in font_file_families(t.font_file):
            t.font_file = ""
        self._update_font_label()
        self.changed.emit()

    def pick_font_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "글꼴 파일 선택", "", "글꼴 (*.ttf *.otf *.ttc);;모든 파일 (*)")
        if not path:
            return
        families = register_font_file(path)
        if not families:
            QMessageBox.warning(self, "글꼴", "글꼴 파일을 읽을 수 없어요.")
            return
        t = self.project.titles
        t.font_file, t.font_name = path, families[0]
        self._loading = True
        from PySide6.QtGui import QFont
        self.font.setCurrentFont(QFont(families[0]))
        self._loading = False
        self._update_font_label()
        self.changed.emit()

    def _update_font_label(self) -> None:
        f = self.project.titles.font_file
        self.font_file_label.setText(f"파일 글꼴 사용 중: {Path(f).name}" if f else "설치된 글꼴 사용 중")
