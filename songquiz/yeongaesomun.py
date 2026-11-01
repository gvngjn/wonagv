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
    if shutil.which("yt-dlp") is None:
        sys.exit("유튜브 주소가 없는 곡이 있어서 yt-dlp 로 검색해야 해요. yt-dlp 를 설치해 주세요.")
    print(f"  유튜브에서 찾는 중: {artist} - {title}")
    out = subprocess.run(["yt-dlp", "--print", "webpage_url", "--skip-download", query],
                         capture_output=True, text=True, encoding="utf-8")
    found = out.stdout.strip().splitlines()
    if out.returncode != 0 or not found:
        print(f"  ! 못 찾음, 비워 둘게요: {artist} - {title}")
        return ""
    return found[0]


def song_row(row, chosung, accept_artist, category, default_start):
    title = row["title"].strip()
    artist = (row.get("artist") or "").strip()
    alts = [a.strip() for a in (row.get("answers") or "").split(";") if a.strip()]
    if accept_artist and artist:
        alts.append(artist)
    # 쉼표로 나누기 때문에 정답 안의 쉼표는 뺀다
    alts = [a.replace(",", "") for a in dict.fromkeys(alts) if a != title]
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
        "chosung": chosung(title),
        "title": f"{artist} - {title}" if artist else title,
        "category": category,
        "alt": ", ".join(alts),
        "url": resolve_url(row.get("url"), artist, title),
        "unused": False,
        "time": fmt_time(float(start)) if start not in ("", None) else None,
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


def export(rows, sheet_path, out_path, chosung, accept_artist=True, category=1,
           default_start=45, keep_existing=False):
    try:
        import openpyxl
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

    new = [song_row(row, chosung, accept_artist, category, default_start) for row in rows]

    def put(r, c, v):
        # 예시 곡 링크 칸이 하이퍼링크라서, 값만 바꾸면 옛 주소가 남는다
        cell = ws.cell(r, c)
        cell.hyperlink = None
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
    no_url = [s["answer"] for s in new if not s["url"]]
    if no_url:
        print(f"! 링크가 비어 있는 곡 {len(no_url)}개: {', '.join(no_url)}")
