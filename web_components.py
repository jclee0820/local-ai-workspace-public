"""웹페이지 인터랙티브·3D 부품 모음 — 외부 라이브러리 없이 CSS 3D·Canvas·SVG 로만 구현(인터넷 없이 열림, 파일 하나로 전달).

AI는 부품 코드를 쓰지 않고 데이터만 채운다. 부품 함수는 HTML 조각을 돌려주고, 동작 스크립트는 RUNTIME_JS 하나에 모여 있다.
색은 페이지의 CSS 변수(--bg, --sf, --tx, --mu, --ac, --ac2)를 따른다.

3D: hero_particles(표지 입자 네트워크), globe(점 지구본+거점), bars3d(3D 막대 그래프), carousel3d(3D 회전 갤러리), tilt 카드
인터랙티브: table(정렬·검색), bar_chart / line_chart / donut_chart(SVG, 마우스 올리면 값), tabs, accordion,
          timeline(연도 슬라이더), kpis(숫자 올라감), countdown(행사까지 남은 시간)"""
import html
import json
import math
import re

_uid = [0]


def _id(p="c"):
    _uid[0] += 1
    return f"{p}{_uid[0]}"


def _e(s):
    return html.escape(str("" if s is None else s))


def _data(obj):
    """<script type=application/json> 안에 안전하게 넣을 JSON."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def num(v):
    """'1,234억 원' → 1234.0 (못 읽으면 None)"""
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


# ------------------------------------------------------------------ 3D
def hero_particles():
    """표지 배경: 천천히 회전하는 3D 입자 네트워크(Canvas). 마우스 위치에 따라 기울어짐."""
    return '<canvas class="wc-hero3d" data-wc="particles" aria-hidden="true"></canvas>'


def globe(markers, title=""):
    """점으로 된 지구본에 거점 표시. markers=[{'name','lat','lon','value'(선택)}]. 끌어서 회전, 자동 회전."""
    cid = _id("g")
    ms = [m for m in markers if num(m.get("lat")) is not None and num(m.get("lon")) is not None]
    return (f'<figure class="wc-globe-wrap">{f"<figcaption>{_e(title)}</figcaption>" if title else ""}'
            f'<canvas id="{cid}" class="wc-globe" data-wc="globe"></canvas>'
            f'<script type="application/json" data-for="{cid}">{_data(ms)}</script>'
            f'<div class="wc-hint">끌어서 돌려 보세요</div></figure>')


def bars3d(items, title="", unit=""):
    """3D 막대 그래프(CSS 3D). items=[{'label','value'}]. 끌어서 회전, 막대에 마우스를 올리면 값."""
    vals = [(it.get("label", ""), num(it.get("value"))) for it in items]
    vals = [(l, v) for l, v in vals if v is not None][:12]
    if not vals:
        return ""
    mx = max(v for _, v in vals) or 1
    cid = _id("b")
    bars = []
    for i, (l, v) in enumerate(vals):
        h = max(6, int(220 * v / mx))
        bars.append(f'<div class="wc-bar3" style="--h:{h}px;--i:{i}" data-tip="{_e(l)}: {v:,.10g}{_e(unit)}">'
                    f'<i class="f"></i><i class="r"></i><i class="t"></i><span class="lb">{_e(l if len(l) <= 8 else l[:7] + "…")}</span>'
                    f'<span class="vl">{v:,.10g}</span></div>')
    return (f'<figure class="wc-b3-wrap">{f"<figcaption>{_e(title)}</figcaption>" if title else ""}'
            f'<div id="{cid}" class="wc-b3-stage" data-wc="bars3d"><div class="wc-b3-scene" style="--n:{len(vals)}">'
            f'<div class="wc-b3-floor"></div>{"".join(bars)}</div></div>'
            f'<div class="wc-hint">끌어서 돌려 보세요 · 막대에 마우스를 올리면 값이 보입니다</div></figure>')


def carousel3d(cards):
    """3D 회전 갤러리. cards=[{'title','sub','img'(data URI 또는 빈칸)}]. 좌우 버튼·끌기·자동 회전."""
    cards = cards[:12]
    if len(cards) < 3:
        return ""
    cid = _id("r")
    n = len(cards)
    radius = int(150 / math.tan(math.pi / n)) + 40
    items = "".join(
        f'<div class="wc-c3-item" style="transform:rotateY({i * 360 / n}deg) translateZ({radius}px)">'
        + (f'<img src="{c["img"]}" alt="{_e(c.get("title"))}">' if c.get("img") else f'<div class="wc-c3-ph">{_e((c.get("title") or "?")[:1])}</div>')
        + f'<b>{_e(c.get("title"))}</b><span>{_e(c.get("sub"))}</span></div>' for i, c in enumerate(cards))
    return (f'<div class="wc-c3" id="{cid}" data-wc="carousel" data-n="{n}" data-r="{radius}">'
            f'<div class="wc-c3-ring">{items}</div>'
            f'<button class="wc-c3-prev" aria-label="이전">‹</button><button class="wc-c3-next" aria-label="다음">›</button></div>')


def tilt_cards(cards):
    """마우스를 따라 기울어지는 카드. cards=[{'title','sub','body','tag','img'}]"""
    out = []
    for c in cards:
        img = f'<img src="{c["img"]}" alt="">' if c.get("img") else ""
        out.append(f'<article class="wc-tilt card reveal" data-wc="tilt">{img}<div class="wc-tilt-b">'
                   + (f'<span class="wc-chip">{_e(c["tag"])}</span>' if c.get("tag") else "")
                   + f'<h3>{_e(c.get("title"))}</h3>' + (f'<p class="wc-sub">{_e(c["sub"])}</p>' if c.get("sub") else "")
                   + (f'<p>{_e(c["body"])}</p>' if c.get("body") else "") + "</div></article>")
    return f'<div class="wc-tiltgrid">{"".join(out)}</div>'


# ------------------------------------------------------------------ 인터랙티브
def table(rows, search=True):
    """정렬(머리글 클릭)·검색되는 표. rows[0]=머리글."""
    if not rows or len(rows) < 2:
        return ""
    w = max(len(r) for r in rows)
    rows = [list(r) + [""] * (w - len(r)) for r in rows]
    cid = _id("t")
    head = "".join(f'<th data-k="{k}" tabindex="0">{_e(h)}<i>↕</i></th>' for k, h in enumerate(rows[0]))
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
    s = f'<input class="wc-tsearch" placeholder="표에서 찾기…" data-for="{cid}">' if search and len(rows) > 6 else ""
    return f'<div class="wc-table">{s}<div class="wc-tscroll"><table id="{cid}" data-wc="table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></div>'


def bar_chart(items, title="", unit=""):
    """가로 막대 차트(SVG). items=[{'label','value'}]"""
    vals = [(it.get("label", ""), num(it.get("value"))) for it in items]
    vals = [(l, v) for l, v in vals if v is not None][:15]
    if not vals:
        return ""
    mx = max(v for _, v in vals) or 1
    rh, W, lw = 34, 460, 120
    H = rh * len(vals) + 10
    rows = []
    for i, (l, v) in enumerate(vals):
        y = 5 + i * rh
        bw = max(2, (W - lw - 80) * v / mx)
        rows.append(f'<g class="wc-bg"><title>{_e(l)}: {v:,.10g}{_e(unit)}</title>'
                    f'<text x="{lw - 10}" y="{y + 21}" text-anchor="end" class="wc-lbl">{_e(l[:10])}</text>'
                    f'<rect x="{lw}" y="{y + 6}" width="{bw:.1f}" height="{rh - 12}" rx="6" class="wc-barr" style="--d:{i * 60}ms"/>'
                    f'<text x="{lw + bw + 8:.1f}" y="{y + 21}" class="wc-val">{v:,.10g}{_e(unit)}</text></g>')
    return (f'<figure class="wc-chart">{f"<figcaption>{_e(title)}</figcaption>" if title else ""}'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_e(title)}">{"".join(rows)}</svg></figure>')


def line_chart(items, title="", unit=""):
    """선 차트(SVG). items=[{'label','value'}] (순서대로)"""
    vals = [(it.get("label", ""), num(it.get("value"))) for it in items]
    vals = [(l, v) for l, v in vals if v is not None][:24]
    if len(vals) < 2:
        return bar_chart(items, title, unit)
    W, H, pl, pb = 460, 240, 30, 40
    lo, hi = min(v for _, v in vals), max(v for _, v in vals)
    lo = min(lo, 0) if lo >= 0 else lo
    sp = (hi - lo) or 1
    pts = [(pl + i * (W - pl - 20) / (len(vals) - 1), 15 + (H - pb - 15) * (1 - (v - lo) / sp)) for i, (_, v) in enumerate(vals)]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    area = path + f" L{pts[-1][0]:.1f},{H - pb} L{pts[0][0]:.1f},{H - pb} Z"
    dots = "".join(f'<g class="wc-pt"><title>{_e(l)}: {v:,.10g}{_e(unit)}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="5"/>'
                   f'<text x="{x:.1f}" y="{H - pb + 22}" text-anchor="middle" class="wc-lbl">{_e(l[:8])}</text></g>'
                   for (l, v), (x, y) in zip(vals, pts))
    return (f'<figure class="wc-chart">{f"<figcaption>{_e(title)}</figcaption>" if title else ""}'
            f'<svg viewBox="0 0 {W} {H}"><path d="{area}" class="wc-area"/><path d="{path}" class="wc-line"/>{dots}</svg></figure>')


def donut_chart(items, title="", unit=""):
    vals = [(it.get("label", ""), num(it.get("value"))) for it in items]
    vals = [(l, v) for l, v in vals if v and v > 0][:8]
    if len(vals) < 2:
        return bar_chart(items, title, unit)
    tot = sum(v for _, v in vals)
    r, cx, cy, sw = 80, 110, 110, 34
    C = 2 * math.pi * r
    off, segs, leg = 0.0, [], []
    for i, (l, v) in enumerate(vals):
        frac = v / tot
        segs.append(f'<circle class="wc-seg s{i % 8}" cx="{cx}" cy="{cy}" r="{r}" stroke-dasharray="{frac * C:.2f} {C:.2f}" '
                    f'stroke-dashoffset="{-off * C:.2f}"><title>{_e(l)}: {v:,.10g}{_e(unit)} ({frac:.1%})</title></circle>')
        leg.append(f'<li><i class="s{i % 8}"></i>{_e(l)} <b>{frac:.0%}</b></li>')
        off += frac
    return (f'<figure class="wc-chart wc-donut">{f"<figcaption>{_e(title)}</figcaption>" if title else ""}'
            f'<svg viewBox="0 0 220 220" style="--sw:{sw}">{"".join(segs)}<text x="{cx}" y="{cy + 6}" text-anchor="middle" class="wc-tot">{tot:,.10g}</text></svg>'
            f'<ul>{"".join(leg)}</ul></figure>')


def tabs(panels):
    """panels=[(제목, html)]"""
    if not panels:
        return ""
    cid = _id("tb")
    btn = "".join(f'<button role="tab" aria-selected="{str(i == 0).lower()}" data-i="{i}">{_e(t)}</button>' for i, (t, _) in enumerate(panels))
    pn = "".join(f'<div role="tabpanel" class="wc-tp"{" hidden" if i else ""}>{h}</div>' for i, (_, h) in enumerate(panels))
    return f'<div class="wc-tabs" id="{cid}" data-wc="tabs"><div class="wc-tabbar" role="tablist">{btn}</div>{pn}</div>'


def accordion(items, open_first=True):
    """items=[(제목, html)] — <details> 라 스크립트 없이도 동작."""
    return '<div class="wc-acc">' + "".join(
        f'<details{" open" if open_first and i == 0 else ""}><summary>{_e(t)}</summary><div>{h}</div></details>'
        for i, (t, h) in enumerate(items)) + "</div>"


def timeline(items):
    """연도 슬라이더가 붙은 타임라인. items=[{'year','title','sub','body','img'}] — 슬라이더로 그 해까지 보기. img 가 있으면 포스터 썸네일."""
    years = [int(m.group(0)) for it in items for m in [re.search(r"\d{4}", str(it.get("year", "")))] if m]
    cid = _id("tl")
    lis = "".join(
        f'<li class="wc-tli tl-card reveal" data-y="{(re.search(r"[0-9]{4}", str(it.get("year", ""))) or [0])[0] if re.search(r"[0-9]{4}", str(it.get("year", ""))) else ""}">'
        f'<span class="wc-tly">{_e(it.get("year"))}</span><div class="wc-tli-b">'
        + (f'<img class="wc-tli-img" src="{it["img"]}" alt="{_e(it.get("title"))} 포스터" loading="lazy">' if it.get("img") else "")
        + f'<div><h3>{_e(it.get("title"))}</h3>'
        + (f'<p class="wc-sub">{_e(it["sub"])}</p>' if it.get("sub") else "")
        + (f'<p>{_e(it["body"])}</p>' if it.get("body") else "") + "</div></div></li>" for it in items)
    slider = ""
    if len(set(years)) >= 3:
        lo, hi = min(years), max(years)
        slider = (f'<div class="wc-tlbar"><label>연도 <output>{hi}</output>년까지</label>'
                  f'<input type="range" min="{lo}" max="{hi}" value="{hi}" data-for="{cid}"></div>')
    return f'<div class="wc-tl" id="{cid}" data-wc="timeline">{slider}<ol>{lis}</ol></div>'


def kpis(items):
    """숫자가 올라가는 핵심 수치 카드. items=[{'label','value','unit','note'}]"""
    out = []
    for it in items[:8]:
        v = num(it.get("value"))
        shown = _e(it.get("value"))
        attr = f' data-to="{v}" data-dec="{len(str(v).split(".")[1]) if v is not None and "." in str(it.get("value")) else 0}"' if v is not None else ""
        out.append(f'<div class="wc-kpi fact reveal"><strong{attr}>{shown}</strong><em>{_e(it.get("unit"))}</em>'
                   f'<span>{_e(it.get("label"))}</span>' + (f'<p>{_e(it["note"])}</p>' if it.get("note") else "") + "</div>")
    return f'<div class="wc-kpis" data-wc="kpis">{"".join(out)}</div>' if out else ""


def countdown(iso_datetime, label="행사까지"):
    return (f'<div class="wc-cd" data-wc="countdown" data-at="{_e(iso_datetime)}"><span>{_e(label)}</span>'
            '<b data-u="d">-</b><i>일</i><b data-u="h">-</b><i>시간</i><b data-u="m">-</b><i>분</i><b data-u="s">-</b><i>초</i></div>')


# ------------------------------------------------------------------ 공통 CSS·JS
CSS = r"""
.wc-hero3d{position:absolute;inset:0;width:100%;height:100%;z-index:0;opacity:.9}
.wc-hint{font-size:.8rem;color:var(--mu);text-align:center;margin-top:6px}
figure{margin:0} figcaption{font-weight:700;margin-bottom:10px;color:var(--tx)}
/* 지구본 */
.wc-globe-wrap{display:flex;flex-direction:column;align-items:center}
.wc-globe{width:min(460px,90vw);aspect-ratio:1;cursor:grab;touch-action:none}
/* 3D 막대 */
.wc-b3-wrap{margin:10px 0}
.wc-b3-stage{height:380px;perspective:1100px;display:grid;place-items:center;cursor:grab;user-select:none;touch-action:none;overflow:hidden}
.wc-b3-scene{position:relative;transform-style:preserve-3d;transform:rotateX(-22deg) rotateY(-30deg);
  width:calc(var(--n)*64px);height:240px;transition:transform .08s linear}
.wc-b3-floor{position:absolute;left:-20px;right:-20px;bottom:-40px;height:80px;transform:rotateX(90deg);
  background:repeating-linear-gradient(90deg,color-mix(in srgb,var(--tx) 10%,transparent) 0 1px,transparent 1px 64px),color-mix(in srgb,var(--sf) 85%,transparent);
  transform-origin:bottom;border-radius:8px}
.wc-bar3{position:absolute;bottom:0;left:calc(var(--i)*64px + 12px);width:40px;height:var(--h);transform-style:preserve-3d}
.wc-bar3 i{position:absolute;display:block}
.wc-bar3 .f{left:0;top:0;width:40px;height:100%;background:linear-gradient(var(--ac2),var(--ac));transform:translateZ(20px)}
.wc-bar3 .r{left:0;top:0;width:40px;height:100%;background:color-mix(in srgb,var(--ac) 70%,#000);transform:rotateY(90deg) translateZ(20px)}
.wc-bar3 .t{left:0;top:-20px;width:40px;height:40px;background:color-mix(in srgb,var(--ac2) 85%,#fff);transform:rotateX(90deg)}
.wc-bar3 .lb{position:absolute;top:calc(100% + 8px);left:50%;transform:translateX(-50%) translateZ(22px);font-size:.75rem;white-space:nowrap;color:var(--mu)}
.wc-bar3 .vl{position:absolute;bottom:calc(100% + 26px);left:50%;transform:translateX(-50%) translateZ(22px);font-size:.78rem;font-weight:700;opacity:0;transition:opacity .2s;white-space:nowrap}
.wc-bar3:hover .vl{opacity:1} .wc-bar3:hover .f{filter:brightness(1.15)}
/* 3D 회전 갤러리 */
.wc-c3{position:relative;height:380px;perspective:1200px;display:grid;place-items:center;overflow:hidden;touch-action:pan-y;user-select:none}
.wc-c3-ring{position:relative;width:240px;height:300px;transform-style:preserve-3d;transition:transform .8s cubic-bezier(.2,.7,.2,1)}
.wc-c3-item{position:absolute;inset:0;background:var(--sf);border-radius:18px;overflow:hidden;display:flex;flex-direction:column;
  box-shadow:0 18px 40px rgba(0,0,0,.25);border:1px solid color-mix(in srgb,var(--tx) 10%,transparent);backface-visibility:hidden}
.wc-c3-item img{width:100%;height:190px;object-fit:contain;background:#fff}
.wc-c3-ph{height:190px;display:grid;place-items:center;font-size:3rem;font-weight:800;color:#fff;background:linear-gradient(135deg,var(--ac),var(--ac2))}
.wc-c3-item b{padding:12px 14px 2px;font-size:1rem} .wc-c3-item span{padding:0 14px;color:var(--mu);font-size:.86rem}
.wc-c3 button{position:absolute;top:50%;transform:translateY(-50%);width:44px;height:44px;border-radius:50%;border:0;background:var(--ac);color:#fff;font-size:1.6rem;cursor:pointer;z-index:2}
.wc-c3-prev{left:10px} .wc-c3-next{right:10px}
/* 기울어지는 카드 */
.wc-tiltgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:22px;perspective:1000px}
.wc-tilt{background:var(--sf);border-radius:18px;overflow:hidden;border:1px solid color-mix(in srgb,var(--tx) 9%,transparent);
  transform-style:preserve-3d;transition:transform .15s ease,box-shadow .3s;box-shadow:0 6px 20px rgba(0,0,0,.08)}
.wc-tilt:hover{box-shadow:0 22px 44px rgba(0,0,0,.18)} .wc-tilt img{width:100%;height:170px;object-fit:contain;background:#fff}
.wc-tilt-b{padding:20px 22px;transform:translateZ(30px)} .wc-tilt h3{font-size:1.15rem;margin:6px 0}
.wc-sub{color:var(--ac);font-size:.9rem;margin-bottom:6px} .wc-tilt p:not(.wc-sub){color:var(--mu);font-size:.95rem}
.wc-chip{display:inline-block;font-size:.75rem;padding:3px 10px;border-radius:999px;background:color-mix(in srgb,var(--ac) 18%,transparent);color:var(--ac)}
/* 표 */
.wc-table{margin:8px 0} .wc-tsearch{width:100%;max-width:320px;padding:10px 14px;border-radius:10px;border:1px solid color-mix(in srgb,var(--tx) 18%,transparent);background:var(--sf);color:var(--tx);margin-bottom:10px}
.wc-tscroll{overflow-x:auto;border-radius:14px;border:1px solid color-mix(in srgb,var(--tx) 12%,transparent);background:var(--sf)}
.wc-table table{width:100%;border-collapse:collapse;min-width:520px} .wc-table th{text-align:left;padding:12px 14px;font-size:.85rem;cursor:pointer;
  background:color-mix(in srgb,var(--ac) 10%,var(--sf));white-space:nowrap} .wc-table th i{font-style:normal;opacity:.4;margin-left:6px}
.wc-table td{padding:12px 14px;border-top:1px solid color-mix(in srgb,var(--tx) 8%,transparent);font-size:.95rem}
.wc-table tr:hover td{background:color-mix(in srgb,var(--ac2) 8%,transparent)}
/* 차트 */
.wc-chart{background:var(--sf);border-radius:16px;padding:18px;border:1px solid color-mix(in srgb,var(--tx) 9%,transparent)}
.wc-chart svg{width:100%;height:auto;overflow:visible} .wc-lbl{fill:var(--mu);font-size:14px} .wc-val{fill:var(--tx);font-size:14px;font-weight:700}
.wc-barr{fill:url(#none);fill:var(--ac);transform-origin:left;animation:wcgrow .9s cubic-bezier(.2,.7,.2,1) both;animation-delay:var(--d)}
.wc-bg:hover .wc-barr{fill:var(--ac2)} @keyframes wcgrow{from{transform:scaleX(0)}}
.wc-line{fill:none;stroke:var(--ac);stroke-width:3;stroke-linejoin:round} .wc-area{fill:color-mix(in srgb,var(--ac) 16%,transparent)}
.wc-pt circle{fill:var(--sf);stroke:var(--ac);stroke-width:3} .wc-pt:hover circle{fill:var(--ac2);r:8}
.wc-donut{display:flex;gap:24px;align-items:center;flex-wrap:wrap} .wc-donut svg{width:220px;transform:rotate(-90deg)} .wc-donut .wc-tot{transform:rotate(90deg);transform-origin:110px 110px;fill:var(--tx);font-size:22px;font-weight:800}
.wc-seg{fill:none;stroke-width:var(--sw);transition:stroke-width .2s} .wc-seg:hover{stroke-width:calc(var(--sw) + 8px)}
.s0{stroke:var(--ac);background:var(--ac)} .s1{stroke:var(--ac2);background:var(--ac2)} .s2{stroke:#8B5CF6;background:#8B5CF6} .s3{stroke:#F59E0B;background:#F59E0B}
.s4{stroke:#10B981;background:#10B981} .s5{stroke:#EF4444;background:#EF4444} .s6{stroke:#64748B;background:#64748B} .s7{stroke:#EC4899;background:#EC4899}
.wc-donut ul{list-style:none;display:grid;gap:6px} .wc-donut li i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:8px;vertical-align:-1px}
/* 탭·펼침 */
.wc-tabbar{display:flex;gap:6px;flex-wrap:wrap;border-bottom:2px solid color-mix(in srgb,var(--tx) 10%,transparent);margin-bottom:18px}
.wc-tabbar button{padding:10px 16px;border:0;background:none;color:var(--mu);font-weight:600;cursor:pointer;border-bottom:3px solid transparent;margin-bottom:-2px;font:inherit}
.wc-tabbar button[aria-selected=true]{color:var(--ac);border-bottom-color:var(--ac)}
.wc-acc details{background:var(--sf);border-radius:14px;margin-bottom:10px;border:1px solid color-mix(in srgb,var(--tx) 9%,transparent)}
.wc-acc summary{padding:16px 20px;font-weight:700;cursor:pointer;list-style:none;display:flex;justify-content:space-between}
.wc-acc summary::after{content:"+";color:var(--ac);font-size:1.3rem} .wc-acc details[open] summary::after{content:"−"}
.wc-acc details>div{padding:0 20px 18px;color:var(--mu)} .wc-acc li{margin:6px 0 6px 18px}
/* 타임라인 */
.wc-tlbar{display:flex;gap:14px;align-items:center;margin-bottom:22px;flex-wrap:wrap} .wc-tlbar input{flex:1;min-width:200px;accent-color:var(--ac)}
.wc-tl ol{list-style:none;position:relative;padding-left:30px} .wc-tl ol::before{content:"";position:absolute;left:8px;top:4px;bottom:4px;width:3px;border-radius:2px;background:linear-gradient(var(--ac),var(--ac2))}
.wc-tli{position:relative;margin-bottom:20px;display:grid;grid-template-columns:110px 1fr;gap:16px;background:var(--sf);padding:18px 20px;border-radius:14px;
  border:1px solid color-mix(in srgb,var(--tx) 9%,transparent);transition:opacity .3s,transform .3s}
.wc-tli::before{content:"";position:absolute;left:-28px;top:24px;width:14px;height:14px;border-radius:50%;background:var(--ac);box-shadow:0 0 0 5px color-mix(in srgb,var(--ac) 22%,transparent)}
.wc-tli.off{display:none} .wc-tly{font-weight:800;color:var(--ac);font-size:1.1rem} .wc-tli h3{font-size:1.05rem;margin-bottom:4px} .wc-tli p:not(.wc-sub){color:var(--mu);font-size:.94rem}
.wc-tli-b{display:flex;gap:16px;align-items:flex-start} .wc-tli-img{width:96px;height:140px;object-fit:cover;border-radius:10px;flex:none;box-shadow:0 6px 16px rgba(0,0,0,.18);background:#fff}
@media(max-width:640px){.wc-tli{grid-template-columns:1fr} .wc-tli-img{width:72px;height:104px}}
/* 핵심 수치 */
.wc-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:18px}
.wc-kpi{background:var(--sf);border-radius:18px;padding:24px;border:1px solid color-mix(in srgb,var(--tx) 9%,transparent);position:relative;overflow:hidden}
.wc-kpi::after{content:"";position:absolute;right:-30px;top:-30px;width:110px;height:110px;border-radius:50%;background:color-mix(in srgb,var(--ac) 12%,transparent)}
.wc-kpi strong{font-size:2.3rem;font-weight:800;color:var(--ac);letter-spacing:-.02em} .wc-kpi em{font-style:normal;margin-left:4px;color:var(--ac);font-weight:700}
.wc-kpi span{display:block;font-weight:700;margin-top:6px} .wc-kpi p{color:var(--mu);font-size:.88rem;margin-top:6px}
/* 카운트다운 */
.wc-cd{display:inline-flex;align-items:baseline;gap:6px;flex-wrap:wrap;justify-content:center;margin-top:26px;padding:14px 22px;border-radius:16px;background:color-mix(in srgb,var(--sf) 70%,transparent);backdrop-filter:blur(6px)}
.wc-cd span{margin-right:8px;color:var(--mu)} .wc-cd b{font-size:2rem;font-weight:800;color:var(--ac);min-width:1.6em;text-align:right} .wc-cd i{font-style:normal;color:var(--mu);margin-right:8px}
@media(prefers-reduced-motion:reduce){.wc-barr{animation:none}.wc-c3-ring{transition:none}}
"""

RUNTIME_JS = r"""
(function(){
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim()||'#3b82f6';
const RM=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function hexA(c,a){const d=document.createElement('div');d.style.color=c;document.body.appendChild(d);const m=getComputedStyle(d).color.match(/\d+(\.\d+)?/g)||[0,0,0];d.remove();return `rgba(${m[0]},${m[1]},${m[2]},${a})`}
function fit(cv){const r=cv.getBoundingClientRect(),p=Math.min(devicePixelRatio||1,2);cv.width=Math.max(10,r.width*p);cv.height=Math.max(10,r.height*p);return p}
// 표지 3D 입자 네트워크
document.querySelectorAll('[data-wc=particles]').forEach(cv=>{
  const ctx=cv.getContext('2d');if(!ctx)return;let P=fit(cv),N=Math.min(140,Math.floor(cv.width*cv.height/(14000*P*P))+40);
  const pts=[...Array(N)].map(()=>[Math.random()*2-1,Math.random()*2-1,Math.random()*2-1]);let a=0,mx=0,my=0;
  const c1=hexA(css('--ac'),.85),c2=css('--ac2');
  addEventListener('resize',()=>{P=fit(cv)});cv.parentElement.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect();mx=(e.clientX-r.left)/r.width-.5;my=(e.clientY-r.top)/r.height-.5});
  (function draw(){const W=cv.width,H=cv.height,f=Math.min(W,H)*.9;ctx.clearRect(0,0,W,H);if(!RM)a+=.0016;
    const ca=Math.cos(a+mx*.6),sa=Math.sin(a+mx*.6),cb=Math.cos(my*.6),sb=Math.sin(my*.6);
    const pr=pts.map(([x,y,z])=>{let X=x*ca-z*sa,Z=x*sa+z*ca,Y=y*cb-Z*sb;Z=y*sb+Z*cb;const s=f/(Z+3.2);return[W/2+X*s*1.5,H/2+Y*s,s,Z]});
    ctx.lineWidth=P*.8;for(let i=0;i<N;i++)for(let j=i+1;j<N;j++){const dx=pr[i][0]-pr[j][0],dy=pr[i][1]-pr[j][1],d=dx*dx+dy*dy,L=(f*.16)**2;
      if(d<L){ctx.strokeStyle=hexA(c2,(1-d/L)*.35);ctx.beginPath();ctx.moveTo(pr[i][0],pr[i][1]);ctx.lineTo(pr[j][0],pr[j][1]);ctx.stroke()}}
    pr.forEach(p=>{ctx.fillStyle=c1;ctx.beginPath();ctx.arc(p[0],p[1],Math.max(1,p[2]*.012),0,7);ctx.fill()});
    requestAnimationFrame(draw)})()});
// 점 지구본
document.querySelectorAll('[data-wc=globe]').forEach(cv=>{
  const ctx=cv.getContext('2d');if(!ctx)return;let P=fit(cv);const ms=JSON.parse((document.querySelector(`[data-for="${cv.id}"]`)||{}).textContent||'[]');
  const D=[],n=900;for(let i=0;i<n;i++){const y=1-2*(i+.5)/n,r=Math.sqrt(1-y*y),t=i*2.39996;D.push([Math.cos(t)*r,y,Math.sin(t)*r])}
  const ll=(la,lo)=>{la*=Math.PI/180;lo*=Math.PI/180;return[Math.cos(la)*Math.sin(lo),-Math.sin(la),Math.cos(la)*Math.cos(lo)]};
  const M=ms.map(m=>({...m,p:ll(+m.lat,+m.lon)}));const lon0=M.length?M.reduce((s,m)=>s+(+m.lon),0)/M.length:0,lat0=M.length?M.reduce((s,m)=>s+(+m.lat),0)/M.length:20;let base=-lon0*Math.PI/180,rot=base,tilt=-lat0*Math.PI/180*.9,drag=null,auto=!RM,t0=performance.now();
  cv.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY,rot,tilt];auto=false;cv.setPointerCapture(e.pointerId)});
  cv.addEventListener('pointermove',e=>{if(drag){rot=drag[2]+(e.clientX-drag[0])*.01;tilt=Math.max(-1.2,Math.min(1.2,drag[3]+(e.clientY-drag[1])*.01))}});
  cv.addEventListener('pointerup',()=>{drag=null;base=rot;t0=performance.now();auto=!RM});addEventListener('resize',()=>{P=fit(cv)});
  const ac=css('--ac'),ac2=css('--ac2'),tx=css('--tx');
  (function draw(){const W=cv.width,H=cv.height,R=Math.min(W,H)*.42;ctx.clearRect(0,0,W,H);if(auto)rot=M.length?base+Math.sin((performance.now()-t0)/2600)*.55:rot+.003;
    const cr=Math.cos(rot),sr=Math.sin(rot),ct=Math.cos(tilt),st=Math.sin(tilt);
    const pj=([x,y,z])=>{let X=x*cr+z*sr,Z=-x*sr+z*cr,Y=y*ct-Z*st;Z=y*st+Z*ct;return[W/2+X*R,H/2+Y*R,Z]};
    const g=ctx.createRadialGradient(W/2-R*.3,H/2-R*.3,R*.1,W/2,H/2,R);g.addColorStop(0,hexA(ac2,.18));g.addColorStop(1,hexA(ac,.05));ctx.fillStyle=g;ctx.beginPath();ctx.arc(W/2,H/2,R,0,7);ctx.fill();
    D.forEach(p=>{const q=pj(p);if(q[2]>-.05){ctx.fillStyle=hexA(tx,.22+q[2]*.45);ctx.fillRect(q[0],q[1],2*P,2*P)}});
    M.forEach(m=>{const q=pj(m.p);if(q[2]<0)return;const s=(4+q[2]*4)*P;ctx.fillStyle=hexA(ac,.25);ctx.beginPath();ctx.arc(q[0],q[1],s*2.2,0,7);ctx.fill();
      ctx.fillStyle=ac;ctx.beginPath();ctx.arc(q[0],q[1],s,0,7);ctx.fill();ctx.fillStyle=tx;ctx.font=`${12*P}px sans-serif`;ctx.fillText(m.name||'',q[0]+s+4*P,q[1]+4*P)});
    requestAnimationFrame(draw)})()});
// 3D 막대 회전
document.querySelectorAll('[data-wc=bars3d]').forEach(st=>{const sc=st.querySelector('.wc-b3-scene');let rx=-22,ry=-30,d=null;
  st.addEventListener('pointerdown',e=>{d=[e.clientX,e.clientY,rx,ry];st.setPointerCapture(e.pointerId)});
  st.addEventListener('pointermove',e=>{if(!d)return;ry=d[3]+(e.clientX-d[0])*.4;rx=Math.max(-70,Math.min(0,d[2]-(e.clientY-d[1])*.3));sc.style.transform=`rotateX(${rx}deg) rotateY(${ry}deg)`});
  st.addEventListener('pointerup',()=>d=null)});
// 3D 회전 갤러리
document.querySelectorAll('[data-wc=carousel]').forEach(c=>{const ring=c.querySelector('.wc-c3-ring'),n=+c.dataset.n,r=+c.dataset.r;let i=0,t=null,sx=null;
  const go=k=>{i+=k;ring.style.transform=`translateZ(-${r}px) rotateY(${-i*360/n}deg)`};go(0);
  c.querySelector('.wc-c3-prev').onclick=()=>{go(-1);stop()};c.querySelector('.wc-c3-next').onclick=()=>{go(1);stop()};
  const stop=()=>{clearInterval(t);t=null};if(!RM)t=setInterval(()=>go(1),3500);
  c.addEventListener('pointerdown',e=>sx=e.clientX);c.addEventListener('pointerup',e=>{if(sx!==null&&Math.abs(e.clientX-sx)>30){go(e.clientX<sx?1:-1);stop()}sx=null})});
// 기울어지는 카드
document.querySelectorAll('[data-wc=tilt]').forEach(c=>{c.addEventListener('mousemove',e=>{const r=c.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;
  c.style.transform=`rotateY(${x*10}deg) rotateX(${-y*10}deg) translateY(-4px)`});c.addEventListener('mouseleave',()=>c.style.transform='')});
// 표 정렬·검색
document.querySelectorAll('[data-wc=table]').forEach(tb=>{const body=tb.tBodies[0];let dir={};
  tb.querySelectorAll('th').forEach(th=>th.addEventListener('click',()=>{const k=+th.dataset.k;dir[k]=!dir[k];const nb=s=>{const m=String(s).replace(/,/g,'').match(/-?\d+(\.\d+)?/);return m?parseFloat(m[0]):null};
    [...body.rows].sort((a,b)=>{const A=a.cells[k].textContent,B=b.cells[k].textContent,x=nb(A),y=nb(B);const v=(x!==null&&y!==null)?x-y:A.localeCompare(B,'ko');return dir[k]?v:-v}).forEach(r=>body.appendChild(r))}))});
document.querySelectorAll('.wc-tsearch').forEach(inp=>inp.addEventListener('input',()=>{const q=inp.value.trim().toLowerCase();
  document.getElementById(inp.dataset.for).tBodies[0].querySelectorAll('tr').forEach(r=>r.style.display=!q||r.textContent.toLowerCase().includes(q)?'':'none')}));
// 탭
document.querySelectorAll('[data-wc=tabs]').forEach(t=>{const bs=t.querySelectorAll('[role=tab]'),ps=t.querySelectorAll('.wc-tp');
  bs.forEach(b=>b.addEventListener('click',()=>{bs.forEach(x=>x.setAttribute('aria-selected','false'));b.setAttribute('aria-selected','true');ps.forEach((p,i)=>p.hidden=i!=+b.dataset.i)}))});
// 타임라인 연도 슬라이더
document.querySelectorAll('.wc-tlbar input').forEach(inp=>inp.addEventListener('input',()=>{const y=+inp.value;inp.parentElement.querySelector('output').textContent=y;
  document.getElementById(inp.dataset.for).querySelectorAll('.wc-tli').forEach(li=>li.classList.toggle('off',li.dataset.y&&+li.dataset.y>y))}));
// 숫자 올라가기
const io=new IntersectionObserver(es=>es.forEach(e=>{if(!e.isIntersecting)return;io.unobserve(e.target);const el=e.target,to=+el.dataset.to,dec=+el.dataset.dec||0,txt=el.textContent;
  if(RM||!isFinite(to))return;const t0=performance.now(),fmt=v=>v.toLocaleString('ko-KR',{minimumFractionDigits:dec,maximumFractionDigits:dec});
  (function f(t){const k=Math.min(1,(t-t0)/1200);el.textContent=txt.replace(/-?\d[\d,]*\.?\d*/,fmt(to*(1-Math.pow(1-k,3))));if(k<1)requestAnimationFrame(f)})(t0)}),{threshold:.4});
document.querySelectorAll('.wc-kpi strong[data-to]').forEach(el=>io.observe(el));
// 카운트다운
document.querySelectorAll('[data-wc=countdown]').forEach(c=>{const at=new Date(c.dataset.at);if(isNaN(at))return c.remove();
  const u=k=>c.querySelector(`[data-u=${k}]`);(function tick(){let s=Math.max(0,Math.floor((at-new Date())/1000));
    u('d').textContent=Math.floor(s/86400);u('h').textContent=Math.floor(s%86400/3600);u('m').textContent=Math.floor(s%3600/60);u('s').textContent=s%60;if(s>0)setTimeout(tick,1000)})()});
})();
"""
