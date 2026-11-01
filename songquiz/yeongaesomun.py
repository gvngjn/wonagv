"""playlist.csv 를 '연개소문' 노래 맞히기 오픈소스(v1.1.x)의 sheet.xlsx 로 내보내기.

연개소문은 Map/sheet.xlsx 의 '곡 목록' 시트를 읽어서 worker.bat 이 음악을 받고
build.eds 가 맵을 만든다. worker 는 열을 '순서'로 읽기 때문에 열 순서는 건드리지 않고,
머리글 글자를 보고 어느 열에 무엇을 쓸지 찾는다.

필요: pip install openpyxl
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

SHEET_NAME = "곡 목록"

# (키, 머리글에 들어 있는 글자들) — 앞에서부터 먼저 맞는 것을 쓴다
COLUMNS = [
    ("opening", ("오프닝", "엔딩")),
    ("chosung", ("초성",)),
    ("alt", ("복수",)),
    ("title", ("곡 제목", "곡제목")),
    ("category", ("범주",)),
    ("url", ("링크", "경로")),
    ("unused", ("미사용",)),
    ("time", ("시작", "종료")),
    ("hint2", ("힌트2", "힌트 2")),
    ("hint", ("힌트",)),
    ("answer", ("정답",)),
]


def find_header(ws):
    """머리글 행 번호와 {키: 열 번호} 를 찾는다."""
    for r in range(1, 6):
        cells = {c: str(ws.cell(r, c).value or "") for c in range(1, ws.max_column + 1)}
        if not any("정답" in v for v in cells.values()):
            continue
        cols = {}
        for c, text in cells.items():
            for key, words in COLUMNS:
                if key not in cols and any(w in text for w in words):
                    cols[key] = c
                    break
        return r, cols
    sys.exit(f"'{SHEET_NAME}' 시트에서 '정답' 머리글을 못 찾았어요.")


def fmt_time(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}~"


def resolve_url(url, artist, title):
    """연개소문 worker 는 유튜브 검색을 못 하니 실제 영상 주소로 바꿔 둔다."""
    url = (url or "").strip()
    if url and not url.startswith("ytsearch"):
        return url
    query = url or f"ytsearch1:{artist} {title} audio"
    from songquiz import ytdlp
    print(f"  유튜브에서 찾는 중: {artist} - {title}")
    out = subprocess.run([*ytdlp(), "--print", "webpage_url", "--skip-download", query],
                         capture_output=True, text=True, encoding="utf-8")
    found = out.stdout.strip().splitlines()
    if out.returncode != 0 or not found:
        print(f"  ! 못 찾음, 비워 둘게요: {artist} - {title}")
        return ""
    return found[0]


def difficulty(row, default):
    v = str(row.get("difficulty") if row.get("difficulty") is not None else "").strip()
    if not v:
        return default
    try:
        return int(float(v))
    except ValueError:
        return v


def rank(rows):
    """쉬운 곡부터 줄 세운 (원래 번호, 곡) 목록.

    difficulty 숫자가 작을수록 쉬움. 같은 숫자끼리는 원래 순서를 유지하고,
    비어 있으면 맨 뒤(어려움) 쪽으로 보낸다.
    """
    def key(item):
        i, row = item
        try:
            return float(str(row.get("difficulty") if row.get("difficulty") is not None else "").strip()), i
        except ValueError:
            return float("inf"), i

    return sorted(enumerate(rows), key=key)


def split_part(rows, part, parts):
    """쉬운 순으로 줄 세워 parts 등분한 것 중 part 번째(1부터). 원래 순서 유지."""
    ranked = rank(rows)
    n = len(ranked)
    picked = {i for pos, (i, _) in enumerate(ranked) if pos * parts // n + 1 == part}
    return [r for i, r in enumerate(rows) if i in picked]


def balance(rows, levels):
    """난이도를 단계마다 곡 수가 같게 다시 나눈다.

    difficulty 숫자(작을수록 쉬움)로 줄을 세우고, 같은 숫자끼리는 원래 순서를
    유지한 채 levels 등분한다. 그래서 '1이 2보다 쉽다'는 순서는 지키면서
    1단계에 곡이 몰려 있으면 덜 유명한 쪽부터 2단계로 밀려난다.
    """
    ranked = rank(rows)
    n = len(ranked)
    out = [dict(r) for r in rows]
    for pos, (i, _) in enumerate(ranked):
        out[i]["difficulty"] = pos * levels // n + 1
    return out


def has_hangul(text):
    return any("가" <= ch <= "힣" for ch in text)


def chosung_source(title, alts):
    """초성 힌트를 만들 글자. 일본어 제목처럼 한글도 영어도 아니면
    복수정답 중 한글 발음(요코소자파리파크에)을 쓴다."""
    if has_hangul(title) or re.search(r"[A-Za-z]", title):
        return title
    for a in alts:
        if has_hangul(a):
            return a
    return title


def song_row(row, chosung, accept_artist, category, default_start):
    title = row["title"].strip()
    artist = (row.get("artist") or "").strip()
    alts = [a.strip() for a in (row.get("answers") or "").split(";") if a.strip()]
    if accept_artist and artist:
        alts.append(artist)
    # 쉼표로 나누기 때문에 정답 안의 쉼표는 뺀다
    # 게임에서는 띄어쓰기 없이 쳐야 정답 (연개소문도 띄어쓰기를 지우고 비교한다).
    # 시트에도 띄어쓰기 없는 소문자로 넣고, 띄어쓰기만 다른 중복은 합친다.
    # 쉼표로 나누기 때문에 정답 안의 쉼표도 뺀다.
    def squash(text):
        return re.sub(r"\s+", "", text).replace(",", "").lower()

    main = squash(title)
    alts = [a for a in dict.fromkeys(squash(a) for a in alts) if a and a != main]
    start = row.get("start") or default_start
    if accept_artist:
        # 가수도 정답이라 가수 이름을 그대로 보여 주면 안 됨
        hint = f"가수 초성: {chosung(artist)}" if artist else ""
    else:
        hint = f"가수: {artist}" if artist else ""
    return {
        "opening": None,
        "answer": title,
        # 연개소문은 이 칸의 한글만 초성으로 바꾸고 나머지는 그대로 보여 준다.
        # 영어 제목이 통째로 보이지 않게 미리 'S____ S__' 꼴로 가려서 넣는다.
        "chosung": chosung(chosung_source(title, alts)),
        "title": f"{artist} - {title}" if artist else title,
        # playlist.csv 의 difficulty 칸 = 연개소문 '범주'. 게임 시작 때 방장이 넣을 단계를 고른다
        "category": difficulty(row, category),
        "alt": ", ".join(alts),
        "url": resolve_url(row.get("url"), artist, title),
        "unused": False,
        "time": fmt_time(float(start)) if start not in ("", None) else None,
        "_start": int(float(start)) if start not in ("", None) else 0,
        "hint": hint,
        "hint2": None,
    }


def find_sheet(path):
    """sheet.xlsx 위치 찾기.

    연개소문 Map 폴더의 sheet.xlsx 는 바로가기(.lnk)이고, 진짜 파일은
    Worker\\Worker\\bin\\Release\\netcoreapp3.1\\publish\\Data\\sheet.xlsx 에 있다.
    """
    path = Path(path)
    if path.is_file():
        if path.suffix.lower() == ".lnk":
            path = path.parent
        else:
            return path
    if not path.is_dir():
        sys.exit(f"{path} 가 없어요.")
    for root in (path, path.parent):
        direct = root / "sheet.xlsx"
        if direct.is_file():
            return direct
        found = sorted(root.glob("Worker/**/Data/sheet.xlsx"))
        if found:
            return found[0]
    sys.exit(f"{path} 근처에서 진짜 sheet.xlsx 를 못 찾았어요. "
             "Worker\\...\\Data\\sheet.xlsx 경로를 직접 넣어 주세요.")


def find_build_eds(path):
    """연개소문 폴더 / Map 폴더 / 시트 경로 중 무엇을 받아도 Map\\build.eds 를 찾는다."""
    path = Path(path)
    for base in [path, *path.parents]:
        for cand in (base / "build.eds", base / "Map" / "build.eds"):
            if cand.is_file():
                return cand
    return None


def tag_build_eds(path, part, parts):
    """맵 이름(map_name)과 출력 파일(output) 뒤에 [1/3] 같은 번호를 붙인다."""
    eds = find_build_eds(path)
    if eds is None:
        print("! build.eds 를 못 찾아서 맵 이름은 그대로예요. 직접 바꿔 주세요.")
        return
    raw = eds.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        print("! build.eds 글자 인코딩을 몰라서 맵 이름은 그대로예요.")
        return
    tag = f"[{part}/{parts}]"
    out = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        end = line[len(body):]
        m = re.match(r"(\s*(map_name|output)\s*:\s*)(.*)$", body)
        if m:
            value = re.sub(r"\s*\[\d+/\d+\]", "", m.group(3))
            if m.group(2) == "output" and "." in value:
                stem, ext = value.rsplit(".", 1)
                value = f"{stem.rstrip()} {tag}.{ext}"
            else:
                value = f"{value.rstrip()} {tag}"
            body = m.group(1) + value
        out.append(body + end)
    eds.write_bytes("".join(out).encode("utf-8" if enc == "utf-8-sig" else enc))
    print(f"{eds} 의 맵 이름과 출력 파일 이름에 {tag} 를 붙였어요.")


def find_ffmpeg(sheet_path):
    """연개소문 Worker 폴더에 들어 있는 ffmpeg 를 찾는다. 없으면 PATH 의 ffmpeg."""
    publish = Path(sheet_path).resolve().parent.parent
    if publish.is_dir():
        for f in publish.rglob("*"):
            if f.name.lower() in ("ffmpeg.exe", "ffmpeg") and f.is_file():
                return str(f)
    return shutil.which("ffmpeg")


def video_id(url):
    m = re.search(r"(?:[?&]v=|youtu\.be/)([\w-]{11})", url or "")
    return m.group(1) if m else None


def download_songs(songs, dl_dir, cookies, ffmpeg, window):
    """yt-dlp 로 곡을 미리 받아서 {곡 번호: 파일 경로} 를 돌려준다.

    연개소문 v1.1.2 의 다운로더는 지금 유튜브에서 받질 못해서, 최신 yt-dlp 로
    받은 파일 경로를 시트에 넣는다 (연개소문은 컴퓨터 안 파일도 받아 준다).
    ffmpeg 가 있으면 시작 지점부터 window 초만 받아서 빠르고 용량도 작다.
    """
    from songquiz import ytdlp

    dl_dir.mkdir(parents=True, exist_ok=True)
    got, todo = {}, {}
    for n, song in enumerate(songs):
        vid = video_id(song["url"])
        if not vid:
            continue
        start = song["_start"] if ffmpeg else 0
        name = f"{vid}_{start}" if ffmpeg else vid
        cached = [f for f in dl_dir.glob(name + ".*") if not f.name.endswith((".part", ".ytdl"))]
        if cached:
            got[n] = cached[0]
        else:
            todo.setdefault(start, []).append((n, vid, name))

    total = sum(len(v) for v in todo.values())
    if got:
        print(f"  이미 받아 둔 곡 {len(got)}개는 그대로 써요.")
    if total:
        print(f"  {total}곡을 받을게요. 곡이 많으면 오래 걸려요...")
    done = 0
    for start, items in todo.items():
        by_name = {name: n for n, _, name in items}
        cmd = [*ytdlp(), "-f", "bestaudio/best", "--ignore-errors", "--no-playlist",
               "--no-simulate", "--print", "after_move:%(filepath)s", *cookies,
               "-o", str(dl_dir / ("%(id)s_" + str(start) + ".%(ext)s" if ffmpeg else "%(id)s.%(ext)s"))]
        if ffmpeg:
            cmd += ["--ffmpeg-location", ffmpeg,
                    "--download-sections", f"*{start}-{start + window}"]
        cmd += [f"https://www.youtube.com/watch?v={vid}" for _, vid, _ in items]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            path = Path(line.strip())
            n = by_name.get(path.stem)
            if n is not None:
                got[n] = path
                done += 1
                if done % 10 == 0 or done == total:
                    print(f"  받는 중 {done}/{total}")
        proc.wait()
    return got


def export(rows, sheet_path, out_path, chosung, accept_artist=True, category=1,
           default_start=45, keep_existing=False, levels=0,
           download_dir=None, cookies=(), window=60):
    try:
        import openpyxl
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    except ImportError:
        sys.exit("openpyxl 이 필요해요: pip install openpyxl")

    wb = openpyxl.load_workbook(sheet_path)
    if SHEET_NAME not in wb.sheetnames:
        sys.exit(f"'{SHEET_NAME}' 시트가 없어요. 시트 목록: {wb.sheetnames}")
    ws = wb[SHEET_NAME]
    header, cols = find_header(ws)
    missing = [k for k in ("answer", "url", "category") if k not in cols]
    if missing:
        sys.exit(f"필요한 열을 못 찾았어요: {missing}. 찾은 열: {cols}")
    print("열 위치:", ", ".join(f"{k}={openpyxl.utils.get_column_letter(c)}"
                               for k, c in sorted(cols.items(), key=lambda kv: kv[1])))

    # 기존 행: 오프닝/엔딩 곡은 남기고, 예시 곡들은 지운다
    kept = []
    for r in range(header + 1, ws.max_row + 1):
        values = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        if not any(v not in (None, "") for v in values):
            continue
        is_special = "opening" in cols and ws.cell(r, cols["opening"]).value not in (None, "")
        if keep_existing or is_special:
            kept.append(values)

    if levels:
        rows = balance(rows, levels)
    new = [song_row(row, chosung, accept_artist, category, default_start) for row in rows]

    failed = []
    if download_dir:
        ffmpeg = find_ffmpeg(sheet_path)
        if not ffmpeg:
            print("! ffmpeg 를 못 찾아서 곡 전체를 받아요 (시간과 용량이 더 들어요).")
        got = download_songs(new, Path(download_dir), list(cookies), ffmpeg, window)
        kept_new = []
        for n, song in enumerate(new):
            if n not in got:
                failed.append(song)
                continue
            song["url"] = str(Path(got[n]).resolve())
            if ffmpeg:
                song["time"] = None  # 이미 시작 지점부터 잘라서 받았음
            kept_new.append(song)
        new = kept_new

    def put(r, c, v):
        # 예시 곡 링크 칸이 하이퍼링크라서, 값만 바꾸면 옛 주소가 남는다
        cell = ws.cell(r, c)
        cell.hyperlink = None
        if isinstance(v, str):
            # 유튜브 제목에 섞인 안 보이는 제어 문자는 엑셀에 못 넣는다
            v = ILLEGAL_CHARACTERS_RE.sub("", v)
        cell.value = v

    last_old = ws.max_row
    r = header + 1
    for values in kept:
        for c, v in enumerate(values, 1):
            put(r, c, v)
        r += 1
    for song in new:
        for c in range(1, ws.max_column + 1):
            put(r, c, None)
        for key, c in cols.items():
            put(r, c, song.get(key))
        r += 1
    last = r - 1
    for rr in range(r, last_old + 1):
        for c in range(1, ws.max_column + 1):
            put(rr, c, None)

    # 엑셀 '표'로 되어 있으면 범위를 새 행 수에 맞춘다
    for table in ws.tables.values():
        start, end = table.ref.split(":")
        end_col = re.match(r"[A-Z]+", end).group(0)
        table.ref = f"{start}:{end_col}{max(last, header + 1)}"
        if table.autoFilter is not None:
            table.autoFilter.ref = table.ref

    wb.save(out_path)
    print(f"\n오프닝/엔딩 {len(kept)}곡 유지, 내 곡 {len(new)}곡 추가 → {out_path}")
    counts = {}
    for song in new:
        counts[song["category"]] = counts.get(song["category"], 0) + 1
    print("범주(난이도)별 곡 수: " + ", ".join(f"{k}단계 {v}곡" for k, v in sorted(counts.items(), key=str)))
    if failed:
        print(f"\n! 받지 못해서 뺀 곡 {len(failed)}개 (삭제/비공개/지역 제한 영상일 수 있어요):")
        for song in failed:
            print(f"   {song['title']}  ({song['url']})")
    no_url = [s["answer"] for s in new if not s["url"]]
    if no_url:
        print(f"! 링크가 비어 있는 곡 {len(no_url)}개: {', '.join(no_url)}")
