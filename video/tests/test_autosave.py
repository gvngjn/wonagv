from reelcut import autosave
from reelcut.project import Clip, Project, atomic_write_text


def test_autosave_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("REELCUT_DATA_DIR", str(tmp_path))
    assert autosave.read() is None
    p = Project(clips=[Clip("가.mp4", 3.0)])
    autosave.write(p, "C:/작업/내 영상.reelcut.json")
    rec = autosave.read()
    assert rec.project.to_dict() == p.to_dict()
    assert rec.original_path == "C:/작업/내 영상.reelcut.json" and rec.saved_at > 0
    autosave.clear()
    assert autosave.read() is None
    autosave.clear()                         # 없어도 오류 없음


def test_broken_autosave_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("REELCUT_DATA_DIR", str(tmp_path))
    autosave.autosave_path().parent.mkdir(parents=True, exist_ok=True)
    autosave.autosave_path().write_text("{깨진 파일", encoding="utf-8")
    assert autosave.read() is None


def test_atomic_write_keeps_old_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "p.json"
    atomic_write_text(target, "old")
    import os

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    try:
        atomic_write_text(target, "new")
    except OSError:
        pass
    assert target.read_text(encoding="utf-8") == "old"
