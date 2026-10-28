"""설정 템플릿: 한 여행 영상의 스타일(컷·자막 모양·제목 모양·색감·내보내기)을 다음 여행에 그대로.

클립·작은 화면·자막 내용·제목 내용처럼 그 영상에만 해당하는 것은 빼고 저장한다.
음악은 고를 수 있다 (같은 노래로 시리즈를 만들 때).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .autosave import data_dir
from .project import Project, atomic_write_text

# 템플릿에 넣지 않는 것 (그 영상에만 해당)
_MUSIC_TRACK = ("path", "duration", "start", "bpm", "beat_offset", "beats", "beat_strengths", "beat_energy")


def templates_dir() -> Path:
    return data_dir() / "templates"


def template_data(project: Project, include_music: bool = False) -> dict:
    d = project.to_dict()
    for key in ("clips", "pips"):
        d.pop(key, None)
    d["subtitles"].pop("entries", None)
    d["titles"].pop("entries", None)
    d["export"].pop("output", None)
    if not include_music:
        for key in _MUSIC_TRACK:
            d["music"].pop(key, None)
    return d


def apply_template(project: Project, data: dict) -> Project:
    """현재 프로젝트의 클립·자막 내용 등은 두고 설정만 바꾼 새 프로젝트."""
    merged = project.to_dict()
    for section, values in data.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(copy.deepcopy(values))
    return Project.from_dict(merged)      # 템플릿에 음악 파일이 없으면 지금 음악은 그대로


def _safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")
    return name or "템플릿"


def save_template(name: str, project: Project, include_music: bool = False) -> Path:
    path = templates_dir() / f"{_safe_name(name)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(template_data(project, include_music), ensure_ascii=False, indent=2))
    return path


def list_templates() -> list[tuple[str, Path]]:
    d = templates_dir()
    if not d.exists():
        return []
    return [(p.stem, p) for p in sorted(d.glob("*.json"), key=lambda p: p.stem.lower())]


def load_template(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def has_music(data: dict) -> bool:
    return bool(data.get("music", {}).get("path"))
