"""devlog.json → DEVLOG.html (휴대폰·브라우저에서 바로 보는 개발 일지 페이지)."""
from __future__ import annotations

from collections import OrderedDict
from html import escape
from pathlib import Path

TYPE_CLASS = {"기능": "feat", "버그": "bug", "수정": "fix", "사용자 제보": "report", "테스트": "test", "계획": "plan"}
STATUS_CLASS = {"완료": "done", "진행 중": "doing", "대기": "wait"}
FILTERS = [("all", "전체"), ("feat", "기능"), ("bugfix", "버그·수정"), ("report", "사용자 제보"),
           ("test", "테스트"), ("plan", "계획")]

CSS = """
:root{
  /* 영상 편집기 일지: 필름 스트립 모티프, 한 줄 기둥 레이아웃 */
  --bg:#F5F6F8; --surface:#FFFFFF; --fg:#1B2129; --muted:#5D6774; --line:#DDE2E8;
  --accent:#D9661A; --accent-soft:#FBE7D8; --strip:#20262E; --hole:#F5F6F8;
  --ok:#2C7D52; --ok-soft:#DCF0E4; --warn:#9A6A12; --warn-soft:#F7ECD3;
  --bug:#B83A33; --bug-soft:#F7DEDC; --info:#2D64A6; --info-soft:#DDE8F6;
  --plan:#6B4FA8; --plan-soft:#E9E2F6;
  --f-body:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;
  --f-mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#12161B; --surface:#1A2027; --fg:#E5E9EE; --muted:#97A1AD; --line:#2B333D;
  --accent:#FF9447; --accent-soft:#3B2716; --strip:#0B0E12; --hole:#2B333D;
  --ok:#5CC48C; --ok-soft:#173327; --warn:#E3B24C; --warn-soft:#3A2E14;
  --bug:#F0766C; --bug-soft:#3D1D1B; --info:#74A9E8; --info-soft:#18283D;
  --plan:#B39AF0; --plan-soft:#2A2340; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#12161B; --surface:#1A2027; --fg:#E5E9EE; --muted:#97A1AD; --line:#2B333D;
  --accent:#FF9447; --accent-soft:#3B2716; --strip:#0B0E12; --hole:#2B333D;
  --ok:#5CC48C; --ok-soft:#173327; --warn:#E3B24C; --warn-soft:#3A2E14;
  --bug:#F0766C; --bug-soft:#3D1D1B; --info:#74A9E8; --info-soft:#18283D;
  --plan:#B39AF0; --plan-soft:#2A2340; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:var(--f-body);font-size:15px;line-height:1.6;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.wrap{max-width:920px;margin:0 auto;padding-block:28px 56px;display:grid;gap:36px}
header{display:grid;gap:6px}
.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{font-size:30px;line-height:1.2;margin:0;text-wrap:balance}
h2{font-size:19px;margin:0;text-wrap:balance}
.meta{color:var(--muted);font-size:13px}
.mono{font-family:var(--f-mono);font-size:12.5px;font-variant-numeric:tabular-nums}
section{display:grid;gap:14px;min-width:0}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
.sec-head .meta{font-size:13px}
/* 요약 */
.summary{display:grid;gap:18px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px}
.stats{display:flex;flex-wrap:wrap;gap:12px 32px}
.stat{display:grid;gap:2px}
.stat b{font-size:24px;font-variant-numeric:tabular-nums;line-height:1.1}
.stat span{color:var(--muted);font-size:13px}
.strip{background:var(--strip);border-radius:6px;padding:9px 8px;display:grid;gap:6px;overflow-x:auto}
.holes{display:flex;gap:6px;justify-content:space-between;padding-inline:2px}
.holes i{width:7px;height:5px;border-radius:1.5px;background:var(--hole);flex:none}
.frames{display:grid;grid-template-columns:repeat(var(--n),minmax(22px,1fr));gap:4px;min-width:calc(var(--n) * 26px)}
.frame{height:30px;border-radius:2px;background:#3A424D;display:grid;place-items:center;
  font-family:var(--f-mono);font-size:10.5px;color:#9AA4B0}
.frame.done{background:var(--accent);color:#fff}
.frame.doing{background:repeating-linear-gradient(135deg,var(--accent) 0 5px,#5A4636 5px 10px);color:#fff}
/* 로드맵 */
.road{list-style:none;margin:0;padding:0;display:grid;border:1px solid var(--line);border-radius:10px;background:var(--surface);overflow:hidden}
.road li{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:4px 12px;padding:12px 14px;border-top:1px solid var(--line);align-items:start}
.road li:first-child{border-top:0}
.rank{font-family:var(--f-mono);color:var(--muted);font-size:13px;padding-top:2px}
.road .item{font-weight:600;min-width:0}
.road .why{grid-column:2 / 3;color:var(--muted);font-size:13.5px;min-width:0}
.road .tags{display:flex;gap:6px;align-items:center;justify-content:flex-end;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:12px;line-height:1;padding:5px 8px;border-radius:999px;
  border:1px solid var(--line);color:var(--muted);white-space:nowrap;background:transparent}
.pill{font-size:12px;line-height:1;padding:5px 9px;border-radius:999px;font-weight:600;white-space:nowrap}
.pill.done{background:var(--ok-soft);color:var(--ok)}
.pill.doing{background:var(--accent-soft);color:var(--accent)}
.pill.wait{background:var(--warn-soft);color:var(--warn)}
/* 기준 */
.criteria{margin:0;padding-left:22px;display:grid;gap:4px}
.criteria li::marker{font-family:var(--f-mono);color:var(--accent)}
/* 기록 */
.filters{display:flex;flex-wrap:wrap;gap:8px}
.filters button{font:inherit;font-size:13px;padding:6px 12px;border-radius:999px;border:1px solid var(--line);
  background:var(--surface);color:var(--fg);cursor:pointer}
.filters button[aria-pressed="true"]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.filters button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.day{display:grid;gap:10px}
.day h3{font-size:13px;margin:0;color:var(--muted);font-family:var(--f-mono);font-weight:500;letter-spacing:.02em}
.entry{background:var(--surface);border:1px solid var(--line);border-left-width:4px;border-radius:8px;padding:12px 14px;display:grid;gap:6px;min-width:0}
.entry.feat{border-left-color:var(--info)} .entry.bug{border-left-color:var(--bug)} .entry.fix{border-left-color:var(--ok)}
.entry.report{border-left-color:var(--accent)} .entry.test{border-left-color:var(--muted)} .entry.plan{border-left-color:var(--plan)}
.entry .top{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.entry .title{font-weight:600}
.entry p{margin:0;color:var(--fg);overflow-wrap:anywhere}
.entry .foot{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:13px}
.entry .result{color:var(--fg);font-weight:600}
.type{font-size:11.5px;font-weight:600;padding:3px 7px;border-radius:4px}
.type.feat{background:var(--info-soft);color:var(--info)} .type.bug{background:var(--bug-soft);color:var(--bug)}
.type.fix{background:var(--ok-soft);color:var(--ok)} .type.report{background:var(--accent-soft);color:var(--accent)}
.type.test{background:var(--line);color:var(--fg)} .type.plan{background:var(--plan-soft);color:var(--plan)}
/* 테스트 차트 */
.chart{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px;overflow-x:auto}
.chart svg{display:block;width:100%;min-width:520px;height:auto}
.chart text{fill:var(--muted);font-family:var(--f-mono);font-size:11px}
.chart .bar{fill:var(--accent)} .chart .bar.last{fill:var(--ok)}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .val{fill:var(--fg);font-size:11px}
@media (max-width:560px){
  h1{font-size:25px}
  .road li{grid-template-columns:28px minmax(0,1fr)}
  .road .tags{grid-column:2 / 3;justify-content:flex-start}
}
@media (prefers-reduced-motion:no-preference){.filters button{transition:background .15s,color .15s}}
"""

JS = """
(function(){
  var buttons=[].slice.call(document.querySelectorAll('.filters button'));
  function apply(f){
    buttons.forEach(function(b){b.setAttribute('aria-pressed', b.dataset.f===f?'true':'false')});
    document.querySelectorAll('.entry').forEach(function(e){
      var t=e.dataset.t, show=f==='all'||t===f||(f==='bugfix'&&(t==='bug'||t==='fix'));
      e.hidden=!show;
    });
    document.querySelectorAll('.day').forEach(function(d){
      d.hidden=!d.querySelector('.entry:not([hidden])');
    });
    try{localStorage.setItem('devlog-filter',f)}catch(e){}
  }
  buttons.forEach(function(b){b.addEventListener('click',function(){apply(b.dataset.f)})});
  var saved='all'; try{saved=localStorage.getItem('devlog-filter')||'all'}catch(e){}
  apply(saved);
})();
"""


def _chart(tests: list[dict]) -> str:
    if not tests:
        return ""
    w, h, left, bottom, top = 640, 190, 34, 34, 14
    n = len(tests)
    top_val = max(t["total"] for t in tests)
    ymax = ((top_val // 20) + 1) * 20
    plot_w, plot_h = w - left - 8, h - bottom - top
    bw = plot_w / n
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="테스트 개수 변화">']
    for v in range(0, ymax + 1, 20):
        y = top + plot_h - v / ymax * plot_h
        parts.append(f'<line class="grid" x1="{left}" x2="{w - 8}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{v}</text>')
    for i, t in enumerate(tests):
        x = left + i * bw + bw * 0.18
        bh = t["passed"] / ymax * plot_h
        y = top + plot_h - bh
        cls = "bar last" if i == n - 1 else "bar"
        parts.append(f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{bw * 0.64:.1f}" height="{bh:.1f}" rx="2">'
                     f'<title>{escape(t["date"])} · {t["passed"]}/{t["total"]} 통과 · {escape(t["note"])}</title></rect>')
        if i == n - 1 or i == 0:
            parts.append(f'<text class="val" x="{x + bw * 0.32:.1f}" y="{y - 4:.1f}" text-anchor="middle">{t["passed"]}</text>')
    first, last = tests[0]["date"][5:], tests[-1]["date"][5:]
    parts.append(f'<text x="{left}" y="{h - 12}">{escape(first)}</text>')
    parts.append(f'<text x="{w - 8}" y="{h - 12}" text-anchor="end">{escape(last)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_html(data: dict, out: Path) -> None:
    road = data["roadmap"]
    entries = data["entries"]
    tests = data["tests"]
    done = sum(1 for r in road if r["status"] == "완료")
    reports = sum(1 for e in entries if e["type"] == "사용자 제보")
    last_test = tests[-1] if tests else {"passed": 0, "total": 0}
    last_date = max([e["date"] for e in entries] + [t["date"] for t in tests])
    commits = [e["commit"] for e in entries if e["commit"] and len(e["commit"]) == 7]
    last_commit = commits[-1] if commits else ""

    frames = "".join(
        f'<div class="frame {STATUS_CLASS.get(r["status"], "wait")}" title="{r["rank"]}. {escape(r["item"])} · {escape(r["status"])}">{r["rank"]}</div>'
        for r in road)
    holes = "<i></i>" * max(12, len(road) * 2)

    road_items = []
    for r in road:
        road_items.append(
            f'<li><span class="rank">{r["rank"]:02d}</span>'
            f'<span class="item">{escape(r["item"])}</span>'
            f'<span class="tags"><span class="chip">기준 {r["criterion"]}</span>'
            f'<span class="pill {STATUS_CLASS.get(r["status"], "wait")}">{escape(r["status"])}'
            f'{" · " + escape(r["done"][5:]) if r.get("done") else ""}</span></span>'
            f'<span class="why">{escape(r["reason"])}</span></li>')

    days: "OrderedDict[str, list]" = OrderedDict()
    for e in reversed(entries):
        days.setdefault(e["date"], []).append(e)
    day_html = []
    for date, items in days.items():
        rows = []
        for e in items:
            t = TYPE_CLASS.get(e["type"], "feat")
            foot = []
            if e["result"]:
                foot.append(f'<span>결과 <span class="result">{escape(e["result"])}</span></span>')
            if e["commit"]:
                foot.append(f'<span class="mono">{escape(e["commit"])}</span>')
            rows.append(
                f'<article class="entry {t}" data-t="{t}"><div class="top">'
                f'<span class="type {t}">{escape(e["type"])}</span>'
                f'<span class="title">{escape(e["title"])}</span></div>'
                f'<p>{escape(e["detail"])}</p>'
                + (f'<div class="foot">{"".join(foot)}</div>' if foot else "") + "</article>")
        day_html.append(f'<div class="day"><h3>{escape(date)}</h3>{"".join(rows)}</div>')

    filters = "".join(f'<button type="button" data-f="{k}" aria-pressed="false">{v}</button>' for k, v in FILTERS)
    criteria = "".join(f"<li>{escape(c)}</li>" for c in data["criteria"])

    html = f"""<title>ReelCut 개발 일지</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <span class="eyebrow">ReelCut · 영상 편집기</span>
  <h1>개발 일지</h1>
  <span class="meta">마지막 갱신 {escape(last_date)}{f' · 커밋 <span class="mono">{escape(last_commit)}</span>' if last_commit else ''}</span>
</header>

<section class="summary" aria-label="요약">
  <div class="stats">
    <div class="stat"><b>{done}/{len(road)}</b><span>로드맵 완료</span></div>
    <div class="stat"><b>{last_test['passed']}/{last_test['total']}</b><span>최근 테스트 통과</span></div>
    <div class="stat"><b>{len(entries)}</b><span>기록 (사용자 제보 {reports}건)</span></div>
  </div>
  <div class="strip" style="--n:{len(road)}">
    <div class="holes" aria-hidden="true">{holes}</div>
    <div class="frames">{frames}</div>
    <div class="holes" aria-hidden="true">{holes}</div>
  </div>
</section>

<section aria-labelledby="road-h">
  <div class="sec-head"><h2 id="road-h">로드맵</h2><span class="meta">순위 = 개발 순서</span></div>
  <ul class="road">{''.join(road_items)}</ul>
</section>

<section aria-labelledby="crit-h">
  <h2 id="crit-h">우선순위 기준</h2>
  <ol class="criteria">{criteria}</ol>
</section>

<section aria-labelledby="log-h">
  <div class="sec-head"><h2 id="log-h">개발 기록</h2><span class="meta">최신순</span></div>
  <div class="filters" role="group" aria-label="종류로 거르기">{filters}</div>
  {''.join(day_html)}
</section>

<section aria-labelledby="test-h">
  <div class="sec-head"><h2 id="test-h">자동 테스트 개수</h2><span class="meta">막대 = 통과한 테스트 · 마지막(초록)이 현재</span></div>
  <div class="chart">{_chart(tests)}</div>
</section>
</div>
<script>{JS}</script>
"""
    out.write_text(html, encoding="utf-8")
