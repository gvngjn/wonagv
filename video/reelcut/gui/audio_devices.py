"""소리 출력 장치 관리: 장치 선택, 헤드폰을 꽂거나 기본 장치가 바뀌면 자동으로 따라가기."""
from __future__ import annotations

import weakref

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtMultimedia import QAudioDevice, QAudioOutput, QMediaDevices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

SYSTEM_DEFAULT = ""   # 선택값: 빈 문자열 = 시스템 기본 장치 따라가기


class AudioDeviceManager(QObject):
    """앱의 모든 재생기(QAudioOutput)가 같은 출력 장치를 쓰도록 관리."""

    devices_changed = Signal()

    _instance: "AudioDeviceManager | None" = None

    @classmethod
    def instance(cls) -> "AudioDeviceManager":
        if cls._instance is None:
            cls._instance = AudioDeviceManager()
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        self._media = QMediaDevices(self)
        self._outputs: list[weakref.ref] = []
        self._settings = QSettings("ReelCut", "ReelCut")
        self.choice: str = str(self._settings.value("audio/output", SYSTEM_DEFAULT) or "")
        self._media.audioOutputsChanged.connect(self._on_system_change)

    # ---- 장치 목록 ----
    def devices(self) -> list[QAudioDevice]:
        return list(QMediaDevices.audioOutputs())

    def default_device(self) -> QAudioDevice:
        return QMediaDevices.defaultAudioOutput()

    @staticmethod
    def device_key(dev: QAudioDevice) -> str:
        return bytes(dev.id()).hex()

    def current_device(self) -> QAudioDevice:
        if self.choice:
            for d in self.devices():
                if self.device_key(d) == self.choice:
                    return d
        return self.default_device()

    # ---- 재생기 연결 ----
    def register(self, output: QAudioOutput) -> None:
        self._outputs.append(weakref.ref(output))
        output.setDevice(self.current_device())

    def set_choice(self, key: str) -> None:
        self.choice = key
        self._settings.setValue("audio/output", key)
        self.apply()

    def apply(self) -> None:
        dev = self.current_device()
        alive = []
        for ref in self._outputs:
            out = ref()
            if out is None:
                continue
            try:
                out.setDevice(dev)
            except RuntimeError:      # 이미 삭제된 Qt 객체
                continue
            alive.append(ref)
        self._outputs = alive

    def refresh(self) -> None:
        """'다시 찾기' 버튼: 장치 목록을 새로 읽고 재생기를 다시 연결."""
        self.apply()
        self.devices_changed.emit()

    def _on_system_change(self) -> None:
        # 헤드폰 연결/해제 등으로 장치 목록이나 기본 장치가 바뀜
        self.apply()
        self.devices_changed.emit()


class AudioOutputPicker(QWidget):
    """🔊 출력 장치 콤보박스 + 다시 찾기 버튼."""

    def __init__(self) -> None:
        super().__init__()
        self.mgr = AudioDeviceManager.instance()
        self.combo = QComboBox()
        self.combo.setToolTip("소리를 낼 장치 (헤드폰을 꽂으면 '시스템 기본'은 자동으로 따라가요)")
        self.combo.setMinimumWidth(160)
        self.combo.currentIndexChanged.connect(self._on_pick)
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setFixedWidth(30)
        self.refresh_btn.setToolTip("소리 장치 다시 찾기")
        self.refresh_btn.clicked.connect(self.mgr.refresh)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.refresh_btn)
        self.mgr.devices_changed.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        default = self.mgr.default_device()
        name = default.description() if not default.isNull() else "없음"
        self.combo.addItem(f"🔊 시스템 기본 ({name})", SYSTEM_DEFAULT)
        for d in self.mgr.devices():
            self.combo.addItem(f"🔊 {d.description()}", self.mgr.device_key(d))
        i = self.combo.findData(self.mgr.choice)
        self.combo.setCurrentIndex(i if i >= 0 else 0)
        self.combo.blockSignals(False)

    def _on_pick(self, _i: int) -> None:
        self.mgr.set_choice(self.combo.currentData() or SYSTEM_DEFAULT)
