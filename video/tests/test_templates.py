from reelcut import templates
from reelcut.project import Clip, PipOverlay, Project, SubtitleEntry, TitleEntry


def japan_project() -> Project:
    p = Project(clips=[Clip("tokyo.mp4", 10)], pips=[PipOverlay("cam.mp4")])
    p.music.path, p.music.duration, p.music.beats, p.music.duck = "song.mp3", 120, [0.5, 1.0], "normal"
    p.beat_sync.enabled, p.beat_sync.cut_unit, p.beat_sync.cut_seconds, p.beat_sync.per_clip = True, "seconds", 1.5, True
    p.subtitles.entries = [SubtitleEntry(0, 1, "시부야")]
    p.subtitles.font_size, p.subtitles.animation = 30, "pop"
    p.titles.entries = [TitleEntry(0, 2, "DAY 1 · TOKYO")]
    p.titles.color = "#FFCC00"
    p.export.width, p.export.height, p.export.color, p.export.output = 1080, 1920, "warm", "C:/v/japan.mp4"
    return p


def test_template_keeps_style_not_content():
    data = templates.template_data(japan_project())
    assert "clips" not in data and "pips" not in data
    assert "entries" not in data["subtitles"] and "entries" not in data["titles"]
    assert "path" not in data["music"] and "beats" not in data["music"] and data["music"]["duck"] == "normal"
    assert "output" not in data["export"]

    osaka = Project(clips=[Clip("osaka.mp4", 8)])
    osaka.subtitles.entries = [SubtitleEntry(0, 1, "도톤보리")]
    osaka.music.path = "other.mp3"
    out = templates.apply_template(osaka, data)
    assert [c.path for c in out.clips] == ["osaka.mp4"] and out.subtitles.entries[0].text == "도톤보리"
    assert out.music.path == "other.mp3"                       # 템플릿에 음악이 없으면 지금 음악 유지
    assert out.beat_sync.per_clip and out.beat_sync.cut_seconds == 1.5
    assert out.subtitles.animation == "pop" and out.subtitles.font_size == 30
    assert out.titles.color == "#FFCC00" and out.export.color == "warm" and out.export.height == 1920


def test_template_with_music_and_files(tmp_path, monkeypatch):
    monkeypatch.setattr(templates, "templates_dir", lambda: tmp_path / "templates")
    path = templates.save_template('여행/릴스:*', japan_project(), include_music=True)
    assert path.name == "여행_릴스_.json"
    assert [n for n, _ in templates.list_templates()] == ["여행_릴스_"]
    data = templates.load_template(path)
    assert templates.has_music(data)
    out = templates.apply_template(Project(), data)
    assert out.music.path == "song.mp3" and out.music.beats == [0.5, 1.0]
