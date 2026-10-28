"""자동 저장: 편집 중인 프로젝트를 주기적으로 따로 저장해 두고, 비정상 종료 후 복구."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .project import Project, atomic_write_text


def data_dir() -> Path:
    env = os.environ.get("REELCUT_DATA_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "ReelCut"


def autosave_path() -> Path:
    return data_dir() / "autosave.reelcut.json"


@dataclass
class Recovered:
    project: Project
    original_path: str | None
    saved_at: float


def write(project: Project, original_path: str | None) -> None:
    data = {"autosave": {"original_path": original_path, "saved_at": time.time()},
            "project": project.to_dict()}
    atomic_write_text(autosave_path(), json.dumps(data, ensure_ascii=False))


def read() -> Recovered | None:
    p = autosave_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        meta = data.get("autosave", {})
        project = Project.from_dict(data["project"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return Recovered(project, meta.get("original_path"), float(meta.get("saved_at") or 0))


def clear() -> None:
    try:
        autosave_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
