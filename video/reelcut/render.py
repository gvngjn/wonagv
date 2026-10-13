"""최종 영상 만들기.

1단계: 타임라인의 조각마다 같은 해상도·프레임레이트·오디오 형식으로 맞춘 임시 파일을 만든다.
       (조각 길이를 프레임 단위로 정확히 맞춰서 비트에 딱 맞게 컷이 바뀐다)
2단계: 임시 파일들을 이어붙이면서 화면 속 화면, 자막, 배경 음악을 입혀 한 번에 인코딩한다.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ffmpeg import ProcessRunner
from .project import PipOverlay, Project, Segment, SubtitleSettings
from .subtitles import save_srt
from .timeline import build_segments

AUDIO_SR = 48000
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}


def is_image(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def _num(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"


@dataclass
class RenderOptions:
    width: int
    height: int
    fps: float
    crf: int = 20
    preset: str = "medium"


def normalize_video_filter(w: int, h: int, fps: float, frames: int, duration: float) -> str:
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
        f"fps={_num(fps)},format=yuv420p,"
        # 원본이 모자라면 마지막 장면을 늘려서라도 정확한 길이로 맞춘다
        f"tpad=stop_mode=clone:stop_duration={_num(duration + 1)},"
        f"trim=end_frame={frames},setpts=PTS-STARTPTS"
    )


def segment_args(seg: Segment, out_path: str, opt: RenderOptions) -> list[str]:
    """1단계: 조각 하나를 규격화된 임시 파일(.mkv, H.264 + PCM)로."""
    frames = max(1, int(round(seg.duration * opt.fps)))
    dur = frames / opt.fps
    samples = int(round(dur * AUDIO_SR))
    args: list[str] = []
    if is_image(seg.path):
        args += ["-loop", "1", "-framerate", _num(opt.fps), "-t", _num(dur + 0.5), "-i", seg.path]
        has_audio = False
    else:
        if seg.src_start > 0:
            args += ["-ss", _num(seg.src_start)]
        args += ["-t", _num(dur + 0.5), "-i", seg.path]
        has_audio = seg.has_audio
    if not has_audio:
        args += ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_SR}:cl=stereo"]
    a_in = "[0:a]" if has_audio else "[1:a]"
    graph = (
        f"[0:v]{normalize_video_filter(opt.width, opt.height, opt.fps, frames, dur)}[v];"
        f"{a_in}aresample={AUDIO_SR},aformat=sample_fmts=s16:channel_layouts=stereo,"
        f"apad,atrim=end_sample={samples},asetpts=PTS-STARTPTS[a]"
    )
    args += [
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(max(10, opt.crf - 4)),
        "-c:a", "pcm_s16le", "-ar", str(AUDIO_SR),
        out_path,
    ]
    return args


def pip_geometry(p: PipOverlay, w: int, h: int) -> tuple[int, str, str]:
    """(PiP 너비 px, overlay x 식, overlay y 식)"""
    pw = max(16, int(round(w * p.size / 2)) * 2)
    m = int(round(w * p.margin))
    pos = {
        "top-left": (f"{m}", f"{m}"),
        "top-right": (f"main_w-overlay_w-{m}", f"{m}"),
        "bottom-left": (f"{m}", f"main_h-overlay_h-{m}"),
        "bottom-right": (f"main_w-overlay_w-{m}", f"main_h-overlay_h-{m}"),
        "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    }
    if p.position == "custom":
        x, y = str(int(round(p.x * w))), str(int(round(p.y * h)))
    else:
        x, y = pos.get(p.position, pos["bottom-right"])
    return pw, x, y


def pip_window(p: PipOverlay, total: float) -> tuple[float, float]:
    """타임라인에서 PiP가 보이는 [시작, 끝]."""
    start = max(0.0, p.start)
    if p.duration > 0:
        end = start + p.duration
    elif p.src_duration > 0 and not is_image(p.path):
        end = start + max(0.0, p.src_duration - p.src_start)
    else:
        end = total
    return start, min(end, total)


def ass_style(s: SubtitleSettings) -> str:
    return (
        f"FontName={s.font_name},FontSize={s.font_size},PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,BorderStyle=1,Outline={s.outline},Shadow=0,"
        f"Alignment=2,MarginV={s.margin_v}"
    )


def windows_fonts_option() -> str:
    """Windows에서는 libass가 시스템 글꼴(맑은 고딕 등)을 찾도록 글꼴 폴더를 알려준다."""
    if os.name != "nt":
        return ""
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if not fonts.is_dir():
        return ""
    escaped = fonts.as_posix().replace(":", "\\:")
    return f":fontsdir='{escaped}'"


def final_args(project: Project, concat_list: str, total: float, out_path: str,
               opt: RenderOptions, srt_name: str | None) -> list[str]:
    """2단계 명령 인자. srt_name은 작업 폴더(cwd) 기준 상대 경로."""
    args = ["-f", "concat", "-safe", "0", "-i", concat_list]
    vf: list[str] = []
    af: list[str] = []
    mix: list[str] = ["[a0]"]
    af.append(f"[0:a]volume={_num(project.export.clip_volume)}[a0]")
    base = "[0:v]"
    idx = 1
    for k, p in enumerate(project.pips):
        start, end = pip_window(p, total)
        if end - start <= 0.01:
            continue
        span = end - start
        if is_image(p.path):
            args += ["-loop", "1", "-framerate", _num(opt.fps), "-t", _num(span), "-i", p.path]
            has_audio = False
        else:
            if p.src_start > 0:
                args += ["-ss", _num(p.src_start)]
            args += ["-t", _num(span), "-i", p.path]
            has_audio = p.has_audio
        pw, x, y = pip_geometry(p, opt.width, opt.height)
        chain = f"[{idx}:v]scale={pw}:-2,setsar=1"
        if p.border > 0:
            b = int(p.border)
            chain += f",pad=iw+{2 * b}:ih+{2 * b}:{b}:{b}:color={p.border_color}"
        chain += f",format=yuva420p,setpts=PTS-STARTPTS+{_num(start)}/TB[p{k}]"
        vf.append(chain)
        out = f"[v{k}]"
        vf.append(
            f"{base}[p{k}]overlay=x={x}:y={y}:eof_action=pass:"
            f"enable='between(t,{_num(start)},{_num(end)})'{out}"
        )
        base = out
        if has_audio and p.volume > 0:
            ms = int(round(start * 1000))
            af.append(
                f"[{idx}:a]aresample={AUDIO_SR},volume={_num(p.volume)},"
                f"adelay={ms}|{ms}[pa{k}]"
            )
            mix.append(f"[pa{k}]")
        idx += 1

    music = project.music
    if music.path:
        if music.start > 0:
            args += ["-ss", _num(music.start)]
        args += ["-i", music.path]
        chain = f"[{idx}:a]aresample={AUDIO_SR},volume={_num(music.volume)}"
        music_len = (music.duration - music.start) if music.duration > 0 else total
        end = min(total, music_len)
        if music.fade_out > 0 and end > music.fade_out:
            chain += f",afade=t=out:st={_num(end - music.fade_out)}:d={_num(music.fade_out)}"
        af.append(chain + "[am]")
        mix.append("[am]")
        idx += 1

    subs = project.subtitles
    if srt_name and subs.burn_in:
        style = ass_style(subs).replace("'", "")
        vf.append(f"{base}subtitles={srt_name}:charenc=UTF-8{windows_fonts_option()}:force_style='{style}'[vsub]")
        base = "[vsub]"
    vf.append(f"{base}format=yuv420p[vout]")

    if len(mix) > 1:
        af.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0[aout]")
    else:
        af.append("[a0]anull[aout]")

    soft_subs = bool(srt_name) and not subs.burn_in
    if soft_subs:
        args += ["-i", srt_name]
    graph = ";".join(vf + af)
    args += ["-filter_complex", graph, "-map", "[vout]", "-map", "[aout]"]
    if soft_subs:
        args += ["-map", f"{idx}:s", "-c:s", "mov_text", "-metadata:s:s:0", "language=kor"]
    args += [
        "-c:v", "libx264", "-preset", opt.preset, "-crf", str(opt.crf),
        "-r", _num(opt.fps), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SR),
        "-t", _num(total), "-movflags", "+faststart",
        out_path,
    ]
    return args


def concat_list_text(files: list[str]) -> str:
    lines = []
    for f in files:
        p = Path(f).as_posix().replace("'", "'\\''")
        lines.append(f"file '{p}'")
    return "\n".join(lines) + "\n"


class Renderer:
    """프로젝트를 mp4로 렌더링. on_progress(0~1, 상태 메시지)."""

    def __init__(self) -> None:
        self.runner = ProcessRunner()

    def cancel(self) -> None:
        self.runner.cancel()

    def render(self, project: Project, out_path: str, preview: bool = False,
               on_progress: Callable[[float, str], None] | None = None) -> float:
        segments = build_segments(project)
        if not segments:
            raise ValueError("이어붙일 클립이 없어요. 클립을 추가해 주세요.")
        ex = project.export
        if preview:
            scale = min(1.0, 640 / max(ex.width, ex.height))
            w = max(2, int(ex.width * scale) // 2 * 2)
            h = max(2, int(ex.height * scale) // 2 * 2)
            opt = RenderOptions(w, h, ex.fps, crf=30, preset="ultrafast")
        else:
            opt = RenderOptions(ex.width // 2 * 2, ex.height // 2 * 2, ex.fps, ex.crf, ex.preset)

        # 프레임 단위로 맞춘 실제 길이
        total = sum(max(1, int(round(s.duration * opt.fps))) / opt.fps for s in segments)
        work = Path(tempfile.mkdtemp(prefix="reelcut_"))
        report = on_progress or (lambda f, m: None)
        try:
            files = []
            done = 0.0
            for i, seg in enumerate(segments):
                out = work / f"seg_{i:04d}.mkv"
                msg = f"조각 준비 중 ({i + 1}/{len(segments)})"
                report(0.5 * done / total, msg)
                base_done = done
                self.runner.run(
                    segment_args(seg, str(out), opt),
                    lambda t, b=base_done, m=msg: report(0.5 * min(total, b + t) / total, m),
                )
                done += seg.duration
                files.append(out.name)
            (work / "list.txt").write_text(concat_list_text(files), encoding="utf-8")

            srt_name = None
            if project.subtitles.entries:
                srt_name = "subs.srt"
                save_srt(work / srt_name, project.subtitles.entries)

            out_abs = str(Path(out_path).resolve())
            Path(out_abs).parent.mkdir(parents=True, exist_ok=True)
            args = final_args(project, "list.txt", total, out_abs, opt, srt_name)
            self.runner.run(
                args, lambda t: report(0.5 + 0.5 * min(1.0, t / total), "최종 영상 만드는 중"),
                cwd=str(work),
            )
            report(1.0, "완료")
            return total
        finally:
            shutil.rmtree(work, ignore_errors=True)
