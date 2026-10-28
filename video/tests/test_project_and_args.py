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
    p = Project(clips=[Clip("a.mp4", 5)])
    args = final_args(p, "list.txt", 5.0, "o.mp4", RenderOptions(640, 360, 30), None)
    assert "loudnorm=I=-14" in args[args.index("-filter_complex") + 1]
    p.export.loudness = 0
    args = final_args(p, "list.txt", 5.0, "o.mp4", RenderOptions(640, 360, 30), None)
    assert "loudnorm" not in args[args.index("-filter_complex") + 1]
    # 소리가 전혀 없으면(무음 영상·사진만, 음악 없음) 음량 맞춤을 건너뛴다 (무음에 걸면 NaN으로 실패)
    silent = Project(clips=[Clip("a.mp4", 5, has_audio=False), Clip("p.jpg", 0, 0, 3, False)])
    args = final_args(silent, "list.txt", 5.0, "o.mp4", RenderOptions(640, 360, 30), None)
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


def test_titles_ass_and_roundtrip(tmp_path):
    from reelcut.project import TitleEntry
    from reelcut.render import titles_ass

    p = Project()
    p.titles.entries = [TitleEntry(1.0, 4.5, "제목 {괄호}\n둘째 줄 \\ 끝"), TitleEntry(5, 4, "잘못된 시간")]
    p.titles.position = "top"
    ass = titles_ass(p.titles, 1080, 1920)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Style: Title,Malgun Gothic,173," in ass           # 1920 * 9%
    assert ",8,54,54,154,1" in ass                              # 위쪽 정렬, 여백
    assert "0:00:01.00,0:00:04.50" in ass
    assert "{\\fad(400,400)}제목 \\{괄호\\}\\N둘째 줄 ＼ 끝" in ass
    assert "잘못된 시간" not in ass
    path = tmp_path / "p.json"
    p.save(path)
    assert Project.load(path).titles.entries[0].text == "제목 {괄호}\n둘째 줄 \\ 끝"


def test_final_args_with_titles():
    p = Project()
    args = final_args(p, "list.txt", 5.0, "o.mp4", RenderOptions(640, 360, 30), None, "fonts", "titles.ass")
    assert "subtitles=titles.ass:fontsdir=fonts[vtitle]" in args[args.index("-filter_complex") + 1]


def test_speed_and_volume_args():
    from reelcut.render import atempo_chain

    assert atempo_chain(1.0) == ""
    assert atempo_chain(4.0) == "atempo=2,atempo=2,"
    assert atempo_chain(0.25) == "atempo=0.5,atempo=0.5,"
    args = segment_args(Segment("v.mp4", 3.0, 2.0, True, speed=2.0, volume=0.5), "o.mkv", RenderOptions(320, 180, 30))
    g = args[args.index("-filter_complex") + 1]
    assert args[args.index("-t") + 1] == "4.5"                    # 원본 4초 + 여유
    assert "setpts=(PTS-STARTPTS)/2" in g and "atempo=2," in g and "volume=0.5," in g
    muted = segment_args(Segment("v.mp4", 0, 1.0, True, volume=0.0), "o.mkv", RenderOptions(320, 180, 30))
    assert "anullsrc" in " ".join(muted)


def test_photo_motion_only_for_images():
    from reelcut.render import motion_filter, resolve_motion

    assert [resolve_motion("auto", i) for i in range(5)] == ["zoom_in", "pan_right", "zoom_out", "pan_left", "zoom_in"]
    assert resolve_motion("weird", 0) == "none" and motion_filter("none", 320, 180, 30, 60, 2.0) == ""
    m = motion_filter("zoom_in", 320, 180, 30, 60, 2.0)
    assert "zoompan" in m and "d=60" in m and "s=320x180" in m and "scale=960:540" in m
    # 짧은 컷은 덜 움직이고, 길어도 15%까지만
    assert "0.0400" in motion_filter("zoom_in", 320, 180, 30, 15, 0.5)
    assert "0.1500" in motion_filter("zoom_in", 320, 180, 30, 300, 10.0)

    photo = segment_args(Segment("p.jpg", 0, 2.0, False, motion="auto"), "o.mkv", RenderOptions(320, 180, 30), index=1)
    graph = photo[photo.index("-filter_complex") + 1]
    assert "zoompan" in graph and "(iw-iw/zoom)*min(1,on/59)" in graph   # 1번 조각 → 오른쪽으로 이동
    video = segment_args(Segment("v.mp4", 0, 2.0, motion="auto"), "o.mkv", RenderOptions(320, 180, 30))
    assert "zoompan" not in video[video.index("-filter_complex") + 1]
    still = segment_args(Segment("p.jpg", 0, 2.0, False, motion="none"), "o.mkv", RenderOptions(320, 180, 30))
    assert "zoompan" not in still[still.index("-filter_complex") + 1]


def test_clip_motion_reaches_segments():
    from reelcut.timeline import build_segments

    p = Project(clips=[Clip("p.jpg", 0, 0, 3, False, motion="pan_left"), Clip("v.mp4", 5)])
    assert [s.motion for s in build_segments(p)] == ["pan_left", "auto"]
    assert Project.from_dict({"clips": [{"path": "p.jpg"}]}).clips[0].motion == "auto"


def test_music_ducking_graph():
    from reelcut.render import duck_filter

    assert duck_filter("off") == "" and duck_filter("bogus") == ""
    p = Project()
    p.music.path, p.music.duration, p.music.duck = "m.mp3", 30, "normal"
    p.pips.append(PipOverlay("cam.mp4", start=1, src_duration=5, has_audio=True, volume=0.5))
    graph = final_args(p, "list.txt", 10.0, "out.mp4", RenderOptions(320, 180, 30), None)
    graph = graph[graph.index("-filter_complex") + 1]
    # 원본+작은 화면 소리를 먼저 섞어서 음악을 누르는 신호로 쓴다
    assert "amix=inputs=2:duration=first:normalize=0,asplit=2[voice][sc]" in graph
    assert "[am_raw][sc_hp]sidechaincompress=threshold=0.015:ratio=6" in graph
    assert "[voice][am]amix=inputs=2" in graph
    p.pips.clear()
    graph = final_args(p, "list.txt", 10.0, "out.mp4", RenderOptions(320, 180, 30), None)
    assert "[a0]asplit=2[voice][sc]" in graph[graph.index("-filter_complex") + 1]


def test_color_filter_before_subtitles():
    from reelcut.render import COLOR_FILTERS, color_filter

    assert color_filter("none") == "" and color_filter("bogus") == ""
    assert set(COLOR_FILTERS) == {"warm", "cool", "bw", "vivid", "vintage"}
    p = Project()
    p.export.color = "bw"
    p.subtitles.entries.append(SubtitleEntry(0, 1, "a"))
    args = final_args(p, "list.txt", 5.0, "out.mp4", RenderOptions(320, 180, 30), "subs.srt")
    graph = args[args.index("-filter_complex") + 1]
    assert graph.index("hue=s=0") < graph.index("subtitles=subs.srt")   # 자막 색은 그대로
    assert Project.from_dict({}).export.color == "none"


def test_gpu_codec_args():
    from reelcut import hwenc

    assert hwenc.codec_args("libx264", 20, "medium") == ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    nv = hwenc.codec_args("h264_nvenc", 20, "medium")
    assert nv[:2] == ["-c:v", "h264_nvenc"] and nv[nv.index("-cq") + 1] == "22"
    assert "-global_quality" in hwenc.codec_args("h264_qsv", 20, "medium")
    assert "-qp_i" in hwenc.codec_args("h264_amf", 20, "medium")
    p = Project()
    args = final_args(p, "list.txt", 5.0, "out.mp4", RenderOptions(320, 180, 30, encoder="h264_nvenc"), None)
    assert args[args.index("-c:v") + 1] == "h264_nvenc"


def test_multi_export_file_names():
    import pytest
    pytest.importorskip("PySide6")
    from reelcut.gui.main_window import multi_output_path

    assert multi_output_path("/v/완성.mp4", "9:16").replace("\\", "/") == "/v/완성_릴스.mp4"
    assert multi_output_path("/v/완성", "16:9").replace("\\", "/") == "/v/완성_유튜브.mp4"
    assert multi_output_path("/v/a.b.MP4", "4:5").replace("\\", "/") == "/v/a.b_인스타피드.mp4"


def test_frame_source_maps_timeline_to_original():
    from reelcut.render import frame_source

    p = Project(clips=[Clip("a.mp4", 10, 2, 6), Clip("p.jpg", 0, 0, 3, False), Clip("b.mp4", 10, 0, 10, speed=2.0)])
    assert frame_source(p, 1.0) == ("a.mp4", 3.0)          # a는 2초부터 사용
    assert frame_source(p, 5.0) == ("p.jpg", 0.0)          # 4~7초는 사진
    assert frame_source(p, 8.0) == ("b.mp4", 2.0)          # 2배속: 1초 지나면 원본 2초
    assert frame_source(p, 999)[0] == "b.mp4"              # 끝을 넘어도 마지막 장면


def test_animated_subtitles_ass():
    from reelcut.render import animated_subs_ass

    text = animated_subs_ass([SubtitleEntry(1.0, 2.5, "첫 줄\n{둘째}")], "pop")
    assert "PlayResY: 288" in text                       # SRT와 같은 좌표 → force_style 크기 그대로
    line = [l for l in text.splitlines() if l.startswith("Dialogue:")][0]
    assert line.startswith("Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\fad(60,120)\\fscx70")
    assert line.endswith("첫 줄\\N\\{둘째\\}")
    assert "\\fad(150,150)" in animated_subs_ass([SubtitleEntry(0, 1, "a")], "fade")


def test_tonemap_only_for_hdr(monkeypatch):
    import reelcut.render as render

    monkeypatch.setattr(render, "hdr_transfer", lambda path: "arib-std-b67" if "iphone" in path else "")
    hdr = segment_args(Segment("iphone.mov", 0, 1.0), "o.mkv", RenderOptions(320, 180, 30))
    graph = hdr[hdr.index("-filter_complex") + 1]
    assert graph.startswith("[0:v]zscale=tin=arib-std-b67") and "tonemap=tonemap=mobius" in graph
    sdr = segment_args(Segment("android.mp4", 0, 1.0), "o.mkv", RenderOptions(320, 180, 30))
    assert "tonemap" not in sdr[sdr.index("-filter_complex") + 1]


def test_parse_shot_times():
    from reelcut.ffmpeg import parse_probe_json, parse_time

    utc = parse_time("2025-03-14T03:00:00.000000Z")
    assert parse_time("2025-03-14T12:00:00+0900") == utc == parse_time("2025-03-14T12:00:00+09:00")
    assert parse_time("") == 0 and parse_time("garbage") == 0 and parse_time("1970-01-01T00:00:00Z") == 0
    # 아이폰: 현지 시간대가 붙은 creationdate를 creation_time(UTC)보다 먼저 쓴다
    info = parse_probe_json("a.mov", {"format": {"duration": "2", "tags": {
        "creation_time": "2025-03-14T03:00:05Z", "com.apple.quicktime.creationdate": "2025-03-14T12:00:00+0900"}},
        "streams": [{"codec_type": "video", "width": 10, "height": 10}]})
    assert info.created == utc


def test_folder_scan_and_photo_date(tmp_path):
    import pytest
    pytest.importorskip("PySide6")
    PIL = pytest.importorskip("PIL")
    from PIL import Image

    from reelcut.ffmpeg import parse_time
    from reelcut.gui.panels import media_in_folder
    from reelcut.photos import shot_time

    (tmp_path / "day2").mkdir()
    (tmp_path / ".cache").mkdir()
    for name in ("b.MP4", "day2/a.mov", "note.AAE", ".hidden.mp4", ".cache/x.jpg", "readme.txt"):
        (tmp_path / name).write_bytes(b"x")
    im = Image.new("RGB", (8, 8))
    exif = im.getexif()
    exif.get_ifd(0x8769)[0x9003] = "2025:03:14 20:30:00"
    exif.get_ifd(0x8769)[0x9011] = "+09:00"
    im.save(tmp_path / "photo.jpg", exif=exif.tobytes())
    found = [p.replace("\\", "/").split(tmp_path.name + "/")[1] for p in media_in_folder(str(tmp_path))]
    assert found == ["b.MP4", "photo.jpg", "day2/a.mov"]
    assert shot_time(str(tmp_path / "photo.jpg")) == parse_time("2025-03-14T20:30:00+09:00")
    assert shot_time(str(tmp_path / "b.MP4")) > 0                     # 날짜 정보가 없으면 파일 시각
    assert shot_time(str(tmp_path / "b.MP4"), created=123456789.0) == 123456789.0


def test_reels_safe_area():
    from reelcut.project import SubtitleSettings, TitleEntry
    from reelcut.render import NO_INSETS, REELS_INSETS, ass_style, safe_insets, safe_subtitles, titles_ass

    assert safe_insets(1080, 1920) == REELS_INSETS
    assert safe_insets(1920, 1080) == NO_INSETS and safe_insets(1080, 1080) == NO_INSETS
    assert safe_insets(1080, 1920, enabled=False) == NO_INSETS
    s = safe_subtitles(SubtitleSettings(margin_v=24), REELS_INSETS)
    assert s.margin_v == 63 and s.margin_r == 50 and "MarginR=50" in ass_style(s)   # 아래 22%, 오른쪽 13%
    assert safe_subtitles(SubtitleSettings(margin_v=100), REELS_INSETS).margin_v == 100   # 이미 높으면 그대로
    assert safe_subtitles(SubtitleSettings(position="middle"), REELS_INSETS).margin_v == 24
    # 작은 화면(오른쪽 아래)도 버튼·설명 밖으로
    w, x, y = pip_geometry(PipOverlay("cam.mp4"), 1080, 1920, REELS_INSETS)
    assert x.endswith(f"-{round(1080 * 0.13)}") and y.endswith(f"-{round(1920 * 0.22)}")
    p = Project()
    p.titles.entries = [TitleEntry(0, 2, "DAY 1")]
    p.titles.position = "bottom"
    style = [l for l in titles_ass(p.titles, 1080, 1920, REELS_INSETS).splitlines() if l.startswith("Style:")][0]
    assert style.endswith(f",{round(1080 * 0.13)},{round(1920 * 0.22)},1")


def test_safe_guide_only_in_preview_option():
    p = Project(clips=[Clip("a.mp4", 5)])
    args = final_args(p, "list.txt", 5.0, "o.mp4", RenderOptions(1080, 1920, 30, safe_guide=True), None)
    assert args[args.index("-filter_complex") + 1].count("drawbox") == 3
    args = final_args(p, "list.txt", 5.0, "o.mp4", RenderOptions(1080, 1920, 30), None)
    assert "drawbox" not in args[args.index("-filter_complex") + 1]


def test_export_without_music_keeps_beat_cuts():
    from reelcut.timeline import build_segments

    p = Project(clips=[Clip("a.mp4", 30), Clip("b.mp4", 30)])
    p.music.path, p.music.duration, p.music.beats = "song.mp3", 10, [i * 0.5 for i in range(21)]
    p.beat_sync.enabled = True
    with_music = build_segments(p)
    p.export.include_music = False
    assert build_segments(p) == with_music                       # 컷은 그대로
    args = final_args(p, "list.txt", 10.0, "o.mp4", RenderOptions(320, 180, 30), None)
    assert "song.mp3" not in args and "[am]" not in args[args.index("-filter_complex") + 1]
    assert "loudnorm" in args[args.index("-filter_complex") + 1]   # 원본 소리는 음량 맞춤
