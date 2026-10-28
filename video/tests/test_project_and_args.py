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


def test_ass_style_colors_position_and_box():
    from reelcut.project import SubtitleSettings
    from reelcut.render import ass_color, ass_style

    assert ass_color("#FFE000") == "&H0000E0FF"
    assert ass_color("#000000", 0x60) == "&H60000000"
    s = SubtitleSettings(font_name="My, Font", bold=True, color="#FF0000", position="top")
    style = ass_style(s)
    assert "FontName=My  Font" in style and "Bold=-1" in style
    assert "PrimaryColour=&H000000FF" in style and "Alignment=6" in style and "BorderStyle=1" in style
    s.box, s.position = True, "middle"
    style = ass_style(s)
    assert "BorderStyle=3" in style and "Alignment=10" in style


def test_prepare_fonts_copies_font_file(tmp_path):
    from reelcut.project import SubtitleSettings
    from reelcut.render import prepare_fonts

    font = tmp_path / "Cute.ttf"
    font.write_bytes(b"fake")
    work = tmp_path / "work"
    work.mkdir()
    assert prepare_fonts(SubtitleSettings(font_file=str(font)), work) == "fonts"
    assert (work / "fonts" / "font0.ttf").read_bytes() == b"fake"
    import os
    if os.name != "nt":
        assert prepare_fonts(SubtitleSettings(font_file=str(tmp_path / "없음.ttf")), work) is None


def test_final_args_uses_relative_fonts_dir():
    p = Project()
    p.subtitles.entries.append(SubtitleEntry(0, 1, "a"))
    args = final_args(p, "list.txt", 5.0, "out.mp4", RenderOptions(640, 360, 30), "subs.srt", "fonts")
    assert "subtitles=subs.srt:charenc=UTF-8:fontsdir=fonts:force_style=" in args[args.index("-filter_complex") + 1]


def test_aspect_presets():
    from reelcut.project import ASPECTS, find_aspect

    assert ASPECTS["9:16"][1]["1080p"] == (1080, 1920)
    assert ASPECTS["16:9"][1]["1080p"] == (1920, 1080)
    assert find_aspect(1080, 1920) == ("9:16", "1080p")
    assert find_aspect(1280, 720) == ("16:9", "720p")
    assert find_aspect(1000, 500) is None
    assert Project().export.fit == "blur"


def test_segment_args_fit_modes():
    seg = Segment("v.mp4", 0, 1.0)
    graphs = {}
    for fit in ("blur", "crop", "pad"):
        args = segment_args(seg, "o.mkv", RenderOptions(1080, 1920, 30, fit=fit))
        graphs[fit] = args[args.index("-filter_complex") + 1]
    assert "boxblur" in graphs["blur"] and "overlay" in graphs["blur"]
    assert "force_original_aspect_ratio=increase,crop=1080:1920" in graphs["crop"]
    assert "pad=1080:1920" in graphs["pad"]
    assert all("trim=end_frame=30" in g for g in graphs.values())


def test_relink_finds_moved_files(tmp_path):
    new_dir = tmp_path / "새 폴더" / "하위"
    new_dir.mkdir(parents=True)
    (new_dir / "클립A.MP4").write_bytes(b"x")
    (new_dir / "노래.mp3").write_bytes(b"x")
    p = Project(clips=[Clip("D:/옛날/클립A.mp4", 3.0), Clip("D:/옛날/없음.mp4", 3.0)])
    p.music.path = "D:/옛날/노래.mp3"
    assert len(p.missing_files()) == 3
    assert p.relink(tmp_path) == 2
    assert p.clips[0].path == str(new_dir / "클립A.MP4")
    assert p.music.path == str(new_dir / "노래.mp3")
    assert p.missing_files() == ["D:/옛날/없음.mp4"]


def test_friendly_ffmpeg_messages():
    from reelcut.ffmpeg import friendly_message

    assert "디스크 공간" in friendly_message("av_interleaved_write_frame(): No space left on device")
    assert "다른 프로그램" in friendly_message("out.mp4: Permission denied")
    assert friendly_message("something odd") == ""


def test_loudness_filter_in_final_args():
    p = Project()
    args = final_args(p, "list.txt", 5.0, "o.mp4", RenderOptions(640, 360, 30), None)
    assert "loudnorm=I=-14" in args[args.index("-filter_complex") + 1]
    p.export.loudness = 0
    args = final_args(p, "list.txt", 5.0, "o.mp4", RenderOptions(640, 360, 30), None)
    assert "loudnorm" not in args[args.index("-filter_complex") + 1]


def test_fade_filters():
    from reelcut.render import fade_filters

    assert fade_filters(0, 0, 10, "v") == ""
    assert fade_filters(1, 2, 10, "v") == "fade=t=in:st=0:d=1,fade=t=out:st=8:d=2,"
    assert fade_filters(0, 1, 10, "a") == "afade=t=out:st=9:d=1,"
    assert fade_filters(5, 5, 4, "v") == "fade=t=in:st=0:d=2,fade=t=out:st=2:d=2,"   # 영상보다 길면 절반으로


def test_transition_filters():
    from reelcut.render import transition_filter

    assert transition_filter("none", 1080, 1920, 30) == ""
    assert "color=white" in transition_filter("flash", 1080, 1920, 30)
    assert "color=black" in transition_filter("dip", 1080, 1920, 30)
    z = transition_filter("zoom", 1080, 1920, 30)
    assert "zoompan" in z and "s=1080x1920" in z and "on/9" in z
    args = segment_args(Segment("v.mp4", 0, 1.0), "o.mkv", RenderOptions(320, 180, 30), "flash")
    assert "color=white" in args[args.index("-filter_complex") + 1]


def test_segments_always_same_pixel_format():
    for tr in ("none", "flash", "zoom", "dip"):
        args = segment_args(Segment("v.mp4", 0, 1.0), "o.mkv", RenderOptions(320, 180, 30), tr)
        assert args[args.index("-pix_fmt") + 1] == "yuv420p"
        assert args[args.index("-filter_complex") + 1].count("format=yuv420p[v]") == 1
