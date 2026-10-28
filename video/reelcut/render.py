"""최종 영상 만들기.

1단계: 타임라인의 조각마다 같은 해상도·프레임레이트·오디오 형식으로 맞춘 임시 파일을 만든다.
       (조각 길이를 프레임 단위로 정확히 맞춰서 비트에 딱 맞게 컷이 바뀐다)
2단계: 임시 파일들을 이어붙이면서 화면 속 화면, 자막, 배경 음악을 입혀 한 번에 인코딩한다.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ffmpeg import FFmpegError, ProcessRunner
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
    fit: str = "pad"


def fit_graph(src: str, out: str, w: int, h: int, fit: str) -> str:
    """원본 영상을 w×h 화면에 맞추는 필터 그래프 조각.

    blur: 화면을 꽉 채운 흐린 배경 위에 원본을 비율 그대로 (릴스·쇼츠에서 흔한 방식)
    crop: 가운데를 기준으로 잘라서 화면을 꽉 채움
    pad:  비율 그대로 두고 남는 곳은 검은 여백
    """
    if fit == "crop":
        return (f"{src}scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1{out}")
    if fit == "blur":
        # 배경은 작게 줄여서 흐리게 한 뒤 키워야 빠르다
        bw, bh = max(16, w // 8 // 2 * 2), max(16, h // 8 // 2 * 2)
        # 흐림 반경은 색 평면(가로세로 절반) 크기의 절반을 넘을 수 없다
        r = max(1, min(6, min(bw, bh) // 4 - 1))
        return (
            f"{src}split=2[fg_in][bg_in];"
            f"[bg_in]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"boxblur={r}:2,scale={w}:{h},setsar=1,eq=brightness=-0.08[bg];"
            f"[fg_in]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{out}"
        )
    return (f"{src}scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1{out}")


def normalize_video_graph(w: int, h: int, fps: float, frames: int, duration: float,
                          fit: str = "pad") -> str:
    """[0:v] → [v] : 화면 맞추기 + 프레임레이트 + 정확한 프레임 수."""
    return (
        fit_graph("[0:v]", "[fit]", w, h, fit) + ";"
        f"[fit]fps={_num(fps)},format=yuv420p,"
        # 원본이 모자라면 마지막 장면을 늘려서라도 정확한 길이로 맞춘다
        f"tpad=stop_mode=clone:stop_duration={_num(duration + 1)},"
        f"trim=end_frame={frames},setpts=PTS-STARTPTS[v]"
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
        f"{normalize_video_graph(opt.width, opt.height, opt.fps, frames, dur, opt.fit)};"
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


FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}
# ffmpeg의 SRT 자막은 옛 SSA 정렬 번호를 쓴다 (2 아래, 10 가운데, 6 위)
_ALIGN = {"bottom": 2, "middle": 10, "top": 6}


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """'#RRGGBB' → ASS 색 '&HAABBGGRR'."""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_style(s: SubtitleSettings) -> str:
    name = s.font_name.replace(",", " ").replace("'", "")
    parts = [
        f"FontName={name}", f"FontSize={s.font_size}", f"Bold={-1 if s.bold else 0}",
        f"PrimaryColour={ass_color(s.color)}",
    ]
    if s.box:
        # BorderStyle=3: 외곽선 대신 상자, 상자 색은 OutlineColour(반투명)
        parts += ["BorderStyle=3", f"OutlineColour={ass_color(s.outline_color, 0x60)}",
                  f"Outline={max(1, s.outline)}"]
    else:
        parts += ["BorderStyle=1", f"OutlineColour={ass_color(s.outline_color)}", f"Outline={s.outline}"]
    parts += ["Shadow=0", f"Alignment={_ALIGN.get(s.position, 2)}", f"MarginV={s.margin_v}"]
    return ",".join(parts)


def windows_font_file(family: str) -> str | None:
    """Windows 레지스트리에서 글꼴 이름에 해당하는 파일 찾기 (사용자 설치 글꼴 포함)."""
    if os.name != "nt" or not family:
        return None
    import winreg

    key_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    want = family.lower()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                label = name.split(" (")[0].lower()
                names = [n.strip() for n in label.split("&")]
                if want in names or label == want:
                    p = Path(value)
                    if not p.is_absolute():
                        p = fonts_dir / p
                    if p.exists():
                        return str(p)
    return None


def prepare_fonts(subs: SubtitleSettings, work: Path) -> str | None:
    """자막 글꼴 파일을 작업 폴더의 fonts/에 복사. 복사했으면 'fonts' 반환."""
    candidates = []
    if subs.font_file and Path(subs.font_file).suffix.lower() in FONT_EXTS and Path(subs.font_file).exists():
        candidates.append(subs.font_file)
    else:
        found = windows_font_file(subs.font_name)
        if found:
            candidates.append(found)
    if not candidates:
        return None
    d = work / "fonts"
    d.mkdir(exist_ok=True)
    for i, f in enumerate(candidates):
        shutil.copy(f, d / f"font{i}{Path(f).suffix.lower()}")
    return "fonts"


def fonts_option(fonts_dir: str | None) -> str:
    if fonts_dir:
        return f":fontsdir={fonts_dir}"
    return windows_fonts_option()


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
               opt: RenderOptions, srt_name: str | None, fonts_dir: str | None = None) -> list[str]:
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
        vf.append(f"{base}subtitles={srt_name}:charenc=UTF-8{fonts_option(fonts_dir)}:force_style='{style}'[vsub]")
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


class MissingFilesError(FileNotFoundError):
    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        names = "\n".join(f"· {Path(p).name}" for p in paths[:10])
        more = f"\n… 외 {len(paths) - 10}개" if len(paths) > 10 else ""
        super().__init__(f"찾을 수 없는 파일이 있어요 (옮기거나 지웠나요?):\n{names}{more}")


def temp_output_path(out_path: str) -> Path:
    """완성되기 전까지 쓰는 임시 결과 파일 (같은 폴더, 숨김 이름)."""
    p = Path(out_path)
    return p.with_name(f".{p.stem}.reelcut-part{p.suffix}")


def default_workers() -> int:
    """동시에 돌릴 ffmpeg 수: 코어 절반, 최대 4."""
    return max(1, min(4, (os.cpu_count() or 2) // 2))


class Renderer:
    """프로젝트를 mp4로 렌더링. on_progress(0~1, 상태 메시지)."""

    def __init__(self, workers: int | None = None) -> None:
        self.runner = ProcessRunner()
        self.workers = workers or default_workers()
        self._runners: list[ProcessRunner] = [self.runner]
        self._lock = threading.Lock()
        self._cancelled = False
        self._w1 = 0.5

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            runners = list(self._runners)
        for r in runners:
            r.cancel()

    def _new_runner(self) -> ProcessRunner:
        r = ProcessRunner()
        with self._lock:
            if self._cancelled:
                r.cancel()
            self._runners.append(r)
        return r

    def _render_segments(self, segments: list[Segment], work: Path, opt: RenderOptions,
                         total: float, report: Callable[[float, str], None]) -> list[str]:
        """1단계를 여러 개 동시에 실행 (조각이 많을수록 빨라짐)."""
        n = len(segments)
        progress = [0.0] * n
        finished = [0]
        lock = threading.Lock()

        def show() -> None:
            with lock:
                done = sum(progress)
                count = finished[0]
            report(self._w1 * min(total, done) / total, f"조각 준비 중 ({count}/{n})")

        def job(i: int) -> str:
            seg = segments[i]
            out = work / f"seg_{i:04d}.mkv"
            runner = self._new_runner()

            def on_time(t: float) -> None:
                progress[i] = min(seg.duration, t)
                show()

            try:
                runner.run(segment_args(seg, str(out), opt), on_time)
            except FFmpegError as e:
                raise FFmpegError(f"'{Path(seg.path).name}' 처리 중 문제가 생겼어요.\n{e}") from e
            with lock:
                progress[i] = seg.duration
                finished[0] += 1
            show()
            return out.name

        show()
        if self.workers <= 1 or n <= 1:
            return [job(i) for i in range(n)]
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(job, i) for i in range(n)]
            try:
                return [f.result() for f in futures]
            except BaseException:
                self.cancel()          # 하나라도 실패하면 나머지 중단
                for f in futures:
                    f.cancel()
                raise

    def render(self, project: Project, out_path: str, preview: bool = False,
               on_progress: Callable[[float, str], None] | None = None) -> float:
        missing = project.missing_files()
        if missing:
            raise MissingFilesError(missing)
        segments = build_segments(project)
        if not segments:
            raise ValueError("이어붙일 클립이 없어요. 클립을 추가해 주세요.")
        ex = project.export
        if preview:
            scale = min(1.0, 640 / max(ex.width, ex.height))
            w = max(2, int(ex.width * scale) // 2 * 2)
            h = max(2, int(ex.height * scale) // 2 * 2)
            opt = RenderOptions(w, h, ex.fps, crf=30, preset="ultrafast", fit=ex.fit)
        else:
            opt = RenderOptions(ex.width // 2 * 2, ex.height // 2 * 2, ex.fps, ex.crf, ex.preset, ex.fit)

        # 진행률에서 1단계가 차지하는 비율 (실측: 내보내기 약 절반, 저화질 미리보기 약 3/4)
        self._w1 = 0.75 if preview else 0.5
        # 프레임 단위로 맞춘 실제 길이
        total = sum(max(1, int(round(s.duration * opt.fps))) / opt.fps for s in segments)
        work = Path(tempfile.mkdtemp(prefix="reelcut_"))
        report = on_progress or (lambda f, m: None)
        try:
            files = self._render_segments(segments, work, opt, total, report)
            (work / "list.txt").write_text(concat_list_text(files), encoding="utf-8")

            srt_name = None
            fonts_dir = None
            if project.subtitles.entries:
                srt_name = "subs.srt"
                save_srt(work / srt_name, project.subtitles.entries)
                if project.subtitles.burn_in:
                    fonts_dir = prepare_fonts(project.subtitles, work)

            out_final = Path(out_path).resolve()
            out_final.parent.mkdir(parents=True, exist_ok=True)
            # 끝까지 성공했을 때만 진짜 이름으로 바꾼다 → 취소·오류 시 깨진 파일이 남거나
            # 같은 이름의 기존 영상이 지워지는 일이 없다
            part = temp_output_path(str(out_final))
            args = final_args(project, "list.txt", total, str(part), opt, srt_name, fonts_dir)
            try:
                self.runner.run(
                    args, lambda t: report(self._w1 + (1 - self._w1) * min(1.0, t / total), "최종 영상 만드는 중"),
                    cwd=str(work),
                )
                try:
                    os.replace(part, out_final)
                except PermissionError as e:
                    raise PermissionError(
                        f"'{out_final.name}' 파일이 다른 프로그램에서 열려 있어서 바꿀 수 없어요. "
                        "플레이어를 닫고 다시 내보내 주세요.") from e
            finally:
                if part.exists():
                    part.unlink(missing_ok=True)
            report(1.0, "완료")
            return total
        finally:
            shutil.rmtree(work, ignore_errors=True)
