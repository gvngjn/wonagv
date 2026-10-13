"""편집 프로젝트 데이터 모델 (JSON으로 저장/불러오기)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Clip:
    """타임라인에 이어붙일 영상 하나. in/out은 원본 기준 초."""
    path: str
    duration: float = 0.0          # 원본 전체 길이
    in_point: float = 0.0
    out_point: float = 0.0         # 0이면 끝까지
    has_audio: bool = True
    width: int = 0
    height: int = 0

    @property
    def end(self) -> float:
        if self.out_point > 0:
            return min(self.out_point, self.duration) if self.duration else self.out_point
        return self.duration

    @property
    def length(self) -> float:
        return max(0.0, self.end - self.in_point)

    @property
    def name(self) -> str:
        return Path(self.path).name


@dataclass
class Segment:
    """실제로 렌더링할 조각 (원본 파일, 원본 시작점, 길이)."""
    path: str
    src_start: float
    duration: float
    has_audio: bool = True


# 화면 속 화면 위치
PIP_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right", "center", "custom")


@dataclass
class PipOverlay:
    path: str
    start: float = 0.0             # 타임라인에서 나타나는 시점
    duration: float = 0.0          # 0이면 원본 끝(또는 영상 끝)까지
    src_start: float = 0.0         # 원본에서 시작할 위치
    position: str = "bottom-right"
    x: float = 0.0                 # custom일 때 왼쪽 위 좌표 (화면 비율 0~1)
    y: float = 0.0
    size: float = 0.3              # 화면 너비 대비 비율
    margin: float = 0.03           # 가장자리 여백 (화면 너비 비율)
    border: int = 4                # 테두리 두께(px), 0이면 없음
    border_color: str = "white"
    volume: float = 0.0            # PiP 원본 소리 크기 (0 = 음소거)
    src_duration: float = 0.0      # 원본 전체 길이 (probe 결과)
    has_audio: bool = False


@dataclass
class MusicSettings:
    path: str = ""
    duration: float = 0.0
    start: float = 0.0             # 음악에서 사용할 시작 위치
    volume: float = 1.0
    fade_out: float = 2.0          # 끝부분 페이드아웃(초)
    bpm: float = 0.0               # 분석 결과 또는 직접 입력
    beat_offset: float = 0.0       # 비트 위치 미세 조정(초, +면 늦게)
    beats: list[float] = field(default_factory=list)


@dataclass
class BeatSyncSettings:
    enabled: bool = False
    beats_per_cut: int = 2         # 몇 비트마다 화면을 바꿀지
    order: str = "sequential"      # sequential | spread | random
    seed: int = 7
    use_music_length: bool = True  # 음악 길이만큼 만들기 (아니면 클립을 다 쓸 때까지)
    max_duration: float = 0.0      # 0이면 제한 없음


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str


@dataclass
class SubtitleSettings:
    entries: list[SubtitleEntry] = field(default_factory=list)
    burn_in: bool = True           # True: 영상에 입히기 / False: 자막 트랙으로 넣기
    font_size: int = 22            # libass 기준 크기 (영상 높이 288 기준 스케일)
    font_name: str = "Malgun Gothic"
    outline: int = 2
    margin_v: int = 24
    model: str = "small"
    language: str = "ko"           # "" = 자동 감지
    source: str = "video"          # video | music


@dataclass
class ExportSettings:
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    crf: int = 20
    preset: str = "medium"
    clip_volume: float = 1.0       # 원본 영상 소리 크기
    output: str = ""


@dataclass
class Project:
    clips: list[Clip] = field(default_factory=list)
    music: MusicSettings = field(default_factory=MusicSettings)
    beat_sync: BeatSyncSettings = field(default_factory=BeatSyncSettings)
    pips: list[PipOverlay] = field(default_factory=list)
    subtitles: SubtitleSettings = field(default_factory=SubtitleSettings)
    export: ExportSettings = field(default_factory=ExportSettings)

    # ---- 저장 / 불러오기 ----
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        def build(dc, data):
            if data is None:
                return dc()
            names = {f.name for f in fields(dc)}
            return dc(**{k: v for k, v in data.items() if k in names})

        p = cls()
        p.clips = [build(Clip, c) for c in d.get("clips", [])]
        p.music = build(MusicSettings, d.get("music"))
        p.beat_sync = build(BeatSyncSettings, d.get("beat_sync"))
        p.pips = [build(PipOverlay, x) for x in d.get("pips", [])]
        subs = d.get("subtitles") or {}
        p.subtitles = build(SubtitleSettings, {k: v for k, v in subs.items() if k != "entries"})
        p.subtitles.entries = [build(SubtitleEntry, e) for e in subs.get("entries", [])]
        p.export = build(ExportSettings, d.get("export"))
        return p

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
