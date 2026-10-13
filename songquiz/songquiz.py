#!/usr/bin/env python3
"""스타1 유즈맵 노래 맞추기 만들기 도구.

  python songquiz.py import <유튜브 플레이리스트 URL | Exportify CSV>
  python songquiz.py build --map base.scx

import : 플레이리스트를 playlist.csv 로 가져온다 (이미 있으면 뒤에 추가).
build  : playlist.csv 의 곡을 내려받아 클립으로 자르고,
         euddraft 로 컴파일할 songquiz.edd 와 build/quiz_data.json 을 만든다.

필요: yt-dlp, ffmpeg (PATH 에 있어야 함)
"""
import argparse
import csv
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAYLIST = ROOT / "playlist.csv"
BUILD = ROOT / "build"
CLIPS = BUILD / "clips"
CACHE = BUILD / "download"
FIELDS = ["title", "artist", "answers", "url", "start"]

# chatEvent 한 줄 채팅 최대 78바이트
MAX_CHAT_BYTES = 78


def need(tool):
    if shutil.which(tool) is None:
        sys.exit(f"'{tool}' 를 찾을 수 없어요. 설치 후 PATH 에 추가해 주세요.")


def read_playlist():
    if not PLAYLIST.exists():
        sys.exit("playlist.csv 가 없어요. 먼저 'import' 하거나 playlist.example.csv 를 복사하세요.")
    with PLAYLIST.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("title") or "").strip()]
    if not rows:
        sys.exit("playlist.csv 에 곡이 없어요.")
    return rows


def write_playlist(rows):
    with PLAYLIST.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


# ---------------------------------------------------------------- import

def split_youtube_title(raw, uploader):
    """'가수 - 제목 (Official MV)' 꼴을 최대한 나눠 본다. 틀리면 CSV 에서 고치면 됨."""
    t = re.sub(r"[\(\[](official|m/?v|music video|lyrics?|audio|가사|공식)[^\)\]]*[\)\]]", "",
               raw, flags=re.I)
    t = re.sub(r"\s*(official\s*)?(m/?v|music video|lyric video|audio)\s*$", "", t, flags=re.I).strip()
    for sep in (" - ", " – ", " — "):
        if sep in t:
            artist, title = t.split(sep, 1)
            return title.strip(), artist.strip()
    uploader = re.sub(r"\s*-\s*Topic$", "", uploader or "")
    return t, uploader


def import_youtube(url):
    need("yt-dlp")
    out = subprocess.run(
        ["yt-dlp", "--flat-playlist", "-J", url],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    data = json.loads(out)
    rows = []
    for e in data.get("entries") or [data]:
        if not e:
            continue
        title, artist = split_youtube_title(e.get("title", ""),
                                            e.get("uploader") or e.get("channel"))
        vid = e.get("url") or e.get("id")
        if vid and not vid.startswith("http"):
            vid = f"https://www.youtube.com/watch?v={vid}"
        rows.append({"title": title, "artist": artist, "answers": "", "url": vid, "start": ""})
    return rows


def import_exportify(path):
    """스포티파이 플레이리스트를 exportify.net 으로 내보낸 CSV."""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            title = r.get("Track Name") or r.get("title")
            artist = r.get("Artist Name(s)") or r.get("artist") or ""
            if not title:
                continue
            artist = artist.split(",")[0].strip()
            # 스포티파이는 음원을 받을 수 없어서 유튜브에서 같은 곡을 검색한다
            rows.append({"title": title.strip(), "artist": artist, "answers": "",
                         "url": f"ytsearch1:{artist} {title} audio", "start": ""})
    return rows


def cmd_import(args):
    src = args.source
    if "spotify.com" in src:
        sys.exit("스포티파이 링크는 바로 못 읽어요. https://exportify.net 에서 플레이리스트를 "
                 "CSV 로 내보낸 뒤 그 파일 경로를 넣어 주세요.")
    rows = import_exportify(src) if src.lower().endswith(".csv") else import_youtube(src)
    old = []
    if PLAYLIST.exists():
        with PLAYLIST.open(encoding="utf-8-sig", newline="") as f:
            old = list(csv.DictReader(f))
    write_playlist(old + rows)
    print(f"{len(rows)}곡을 playlist.csv 에 추가했어요. 제목/가수/정답(answers)을 확인해 주세요.")


# ---------------------------------------------------------------- build

def answer_variants(row):
    """채팅으로 인정할 문자열들. answers 칸은 ';' 로 구분."""
    base = [row["title"]] + [a for a in (row.get("answers") or "").split(";")]
    out = []
    for a in base:
        a = a.strip()
        if not a:
            continue
        for v in (a, a.replace(" ", ""), a.lower(), a.lower().replace(" ", ""),
                  a.upper(), a.upper().replace(" ", "")):
            if v and v not in out:
                out.append(v)
    return out


def edd_key(text):
    # euddraft 설정 파일에서 \ : = 는 이스케이프해야 함
    return re.sub(r"([\\:=])", r"\\\1", text)


def download(row, idx):
    CACHE.mkdir(parents=True, exist_ok=True)
    found = list(CACHE.glob(f"{idx:03d}.*"))
    if found:
        return found[0]
    url = row["url"].strip() or f"ytsearch1:{row['artist']} {row['title']} audio"
    need("yt-dlp")
    print(f"  내려받는 중: {row['artist']} - {row['title']}")
    subprocess.run(
        ["yt-dlp", "-f", "bestaudio", "--no-playlist", "-o", str(CACHE / f"{idx:03d}.%(ext)s"), url],
        check=True,
    )
    return next(CACHE.glob(f"{idx:03d}.*"))


def make_clip(src, dst, start, seconds, fmt):
    args = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(seconds),
            "-i", str(src),
            "-af", f"loudnorm=I=-16:TP=-1.5,afade=t=in:d=0.5,afade=t=out:st={seconds - 1}:d=1",
            "-ac", "1"]
    if fmt == "ogg":
        args += ["-ar", "44100", "-c:a", "libvorbis", "-q:a", "2"]
    else:  # 1.16 호환용 wav (용량 큼)
        args += ["-ar", "22050", "-c:a", "pcm_s16le"]
    subprocess.run(args + [str(dst)], check=True)


def cmd_build(args):
    need("ffmpeg")
    rows = read_playlist()
    order = list(range(len(rows)))
    if not args.no_shuffle:
        random.shuffle(order)
    if args.limit:
        order = order[: args.limit]

    CLIPS.mkdir(parents=True, exist_ok=True)
    songs, chat_lines, used = [], [], {}
    for n, idx in enumerate(order):
        row = rows[idx]
        src = download(row, idx)
        clip = CLIPS / f"{idx:03d}.{args.format}"
        start = float(row.get("start") or args.start)
        if args.force or not clip.exists():
            make_clip(src, clip, start, args.seconds, args.format)
        songs.append({
            "title": row["title"].strip(),
            "artist": (row.get("artist") or "").strip(),
            "file": str(clip.resolve()),
            "mpq_name": f"songquiz\\{n:03d}.{args.format}",
        })
        for ans in answer_variants(row):
            if len(ans.encode("utf-8")) > MAX_CHAT_BYTES:
                print(f"  ! 너무 긴 정답이라 건너뜀: {ans}")
                continue
            if ans.startswith("^") and ans.endswith("$"):
                continue
            if ans in used:
                if used[ans] != n:
                    print(f"  ! '{ans}' 가 두 곡의 정답이라 먼저 나온 곡에만 인정돼요.")
                continue
            used[ans] = n
            chat_lines.append(f"{edd_key(ans)} : {n + 2}")

    BUILD.mkdir(exist_ok=True)
    data_path = BUILD / "quiz_data.json"
    data_path.write_text(json.dumps({
        "songs": songs,
        "clip_seconds": args.seconds,
        "hint_seconds": args.hint,
        "gap_seconds": 3,
        "chat_addr": "0x58D900",
        "signal_unit": args.signal_unit,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    base = Path(args.map).resolve()
    out = Path(args.out).resolve() if args.out else base.with_name(base.stem + "_songquiz" + base.suffix)
    edd = ROOT / "songquiz.edd"
    edd.write_text("\n".join([
        ":: songquiz.py build 가 만든 파일. 직접 고치지 말고 다시 build 하세요.",
        "[main]",
        f"input: {base}",
        f"output: {out}",
        "",
        "[chatEvent]",
        "__addr__ : 0x58D900",
        *chat_lines,
        "",
        f"[{(ROOT / 'map' / 'quiz.py').resolve()}]",
        f"data : {data_path.resolve()}",
        "",
    ]), encoding="utf-8")
    print(f"\n{len(songs)}곡 준비 완료.")
    print(f"euddraft 로 {edd} 를 컴파일하면 {out} 이 만들어져요.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="플레이리스트 가져오기")
    p.add_argument("source", help="유튜브 플레이리스트 URL 또는 Exportify CSV 경로")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("build", help="클립 만들고 euddraft 설정 생성")
    p.add_argument("--map", required=True, help="베이스 맵 (.scx)")
    p.add_argument("--out", help="출력 맵 경로 (기본: <베이스>_songquiz.scx)")
    p.add_argument("--seconds", type=float, default=20, help="한 곡 재생 길이(초)")
    p.add_argument("--start", type=float, default=45, help="start 칸이 비었을 때 시작 지점(초)")
    p.add_argument("--hint", type=float, default=10, help="가수 힌트가 나오는 시점(초)")
    p.add_argument("--limit", type=int, help="최대 곡 수")
    p.add_argument("--format", choices=["ogg", "wav"], default="ogg")
    p.add_argument("--signal-unit", default="Terran Command Center",
                   help="플레이어마다 1개씩 미리 놓아 둘 신호 건물 (랠리 가능한 건물)")
    p.add_argument("--no-shuffle", action="store_true", help="플레이리스트 순서대로 출제")
    p.add_argument("--force", action="store_true", help="클립 다시 자르기")
    p.set_defaults(func=cmd_build)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
