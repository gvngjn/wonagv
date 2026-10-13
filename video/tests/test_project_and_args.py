from reelcut.project import Clip, PipOverlay, Project, SubtitleEntry
from reelcut.render import RenderOptions, final_args, pip_geometry, pip_window, segment_args
from reelcut.project import Segment


def test_project_save_load_roundtrip(tmp_path):
    p = Project(clips=[Clip("a.mp4", 5.0, 1.0, 4.0)])
    p.pips.append(PipOverlay("cam.mp4", start=2.0, size=0.25))
    p.subtitles.entries.append(SubtitleEntry(0, 1, "안녕"))
    p.music.beats = [0.5, 1.0]
    path = tmp_path / "p.reelcut.json"
    p.save(path)
    q = Project.load(path)
    assert q.to_dict() == p.to_dict()


def test_load_ignores_unknown_keys():
    q = Project.from_dict({"clips": [{"path": "a.mp4", "future_field": 1}], "export": {"width": 1280}})
    assert q.clips[0].path == "a.mp4" and q.export.width == 1280


def test_pip_default_is_bottom_right():
    p = PipOverlay("cam.mp4")
    w, x, y = pip_geometry(p, 1920, 1080)
    assert w == 576
    assert x.startswith("main_w-overlay_w") and y.startswith("main_h-overlay_h")


def test_pip_window():
    assert pip_window(PipOverlay("x.mp4", start=2, src_duration=5), 20) == (2, 7)
    assert pip_window(PipOverlay("x.mp4", start=2, duration=3), 4) == (2, 4)
    assert pip_window(PipOverlay("x.png", start=1), 9) == (1, 9)


def test_segment_args_pads_silent_clip_and_trims_exact_frames():
    args = segment_args(Segment("v.mp4", 1.5, 0.5, has_audio=False), "o.mkv", RenderOptions(1280, 720, 30))
    graph = args[args.index("-filter_complex") + 1]
    assert "anullsrc" in " ".join(args)
    assert "trim=end_frame=15" in graph
    assert "atrim=end_sample=24000" in graph


def test_final_args_mixes_music_pip_and_subtitles():
    p = Project()
    p.music.path, p.music.duration = "m.mp3", 30
    p.pips.append(PipOverlay("cam.mp4", start=1, src_duration=5, has_audio=True, volume=0.5))
    p.subtitles.entries.append(SubtitleEntry(0, 1, "a"))
    args = final_args(p, "list.txt", 10.0, "out.mp4", RenderOptions(1280, 720, 30), "subs.srt")
    graph = args[args.index("-filter_complex") + 1]
    assert "overlay=" in graph and "subtitles=subs.srt" in graph
    assert "amix=inputs=3" in graph
    p.subtitles.burn_in = False
    args = final_args(p, "list.txt", 10.0, "out.mp4", RenderOptions(1280, 720, 30), "subs.srt")
    assert "mov_text" in args and "subtitles=" not in args[args.index("-filter_complex") + 1]
