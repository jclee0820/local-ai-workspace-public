"""마인드맵: 들여쓰기 목록 ↔ 트리, 좌우 균형 배치, 출력(SVG·PNG·PowerPoint 도형·FreeMind .mm·HTML),
문서 → 마인드맵(AI), 가지 펼치기(AI), 마인드맵 → 슬라이드·웹페이지 데이터.
트리 형식: {"t": "제목", "c": [하위 노드...]}  (인터넷·외부 라이브러리 없이 동작)"""
import html
import json
import math
import re

PALETTE = ["#2E75B6", "#E46C0A", "#00A388", "#8E44AD", "#C0392B", "#B8860B", "#1F9BCF", "#5D6D7E"]
ROOT_COLOR = "#1F2A36"
FONT_FAMILY = "'Noto Sans KR','Malgun Gothic','Apple SD Gothic Neo',sans-serif"
MAX_DEPTH = 5


# ------------------------------------------------------------------ 목록 ↔ 트리
_BULLET = re.compile(r"^(?:[-*+•▪◦·]|□|■|ㅇ|○|●|※)\s*")


def parse_outline(text: str) -> dict:
    """들여쓰기 목록 → 트리. 첫 줄 = 가운데 주제. '#' 제목 수준, 탭·2칸·4칸 들여쓰기 모두 인식."""
    lines = [l.rstrip() for l in (text or "").replace("\t", "    ").split("\n") if l.strip()]
    if not lines:
        return {"t": "주제", "c": []}
    rows = []
    for l in lines:
        s = l.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            rows.append((("h", len(m.group(1)) - 1), m.group(2).strip()))
            continue
        ind = len(l) - len(l.lstrip(" "))
        rows.append((("i", ind), _BULLET.sub("", s).strip()))
    root_t = rows[0][1]
    body = rows[1:]
    inds = sorted({r[0][1] for r in body if r[0][0] == "i" and r[0][1] > 0})
    unit = inds[0] if inds else 2
    root = {"t": root_t, "c": []}
    stack = [(0, root)]
    for (kind, v), t in body:
        if not t:
            continue
        depth = max(1, v) if kind == "h" else 1 + round(v / unit)
        depth = min(depth, MAX_DEPTH)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1] if stack else root
        node = {"t": t, "c": []}
        parent["c"].append(node)
        stack.append((depth, node))
    return root


def to_outline(tree: dict) -> str:
    out = [tree["t"]]

    def walk(n, d):
        for c in n.get("c", []):
            out.append("  " * (d - 1) + "- " + c["t"])
            walk(c, d + 1)
    walk(tree, 1)
    return "\n".join(out)


def count(tree):
    return 1 + sum(count(c) for c in tree.get("c", []))


def depth(tree):
    return 1 + max((depth(c) for c in tree.get("c", [])), default=0)


def paths(tree, prefix=()):
    """[(경로 튜플, 표시 이름)] — 가지 펼치기에서 노드를 고를 때 사용."""
    out = [(prefix, ("  " * len(prefix)) + tree["t"])]
    for i, c in enumerate(tree.get("c", [])):
        out += paths(c, prefix + (i,))
    return out


def node_at(tree, path):
    n = tree
    for i in path:
        n = n["c"][i]
    return n


def clean(tree, max_children=10, max_depth=MAX_DEPTH, _d=1):
    """AI 결과 정리: 빈 이름 제거, 너무 긴 이름 줄이기, 가지 수·깊이 제한, 중복 제거."""
    t = re.sub(r"\s+", " ", str(tree.get("t") or tree.get("title") or "")).strip().strip("-•·").strip()
    t = t[:60]
    kids, seen = [], set()
    if _d < max_depth:
        for c in (tree.get("c") or tree.get("children") or [])[:max_children]:
            if isinstance(c, str):
                c = {"t": c, "c": []}
            if not isinstance(c, dict):
                continue
            cc = clean(c, max_children, max_depth, _d + 1)
            k = re.sub(r"\W", "", cc["t"])
            if cc["t"] and k not in seen:
                seen.add(k)
                kids.append(cc)
    return {"t": t or "주제", "c": kids}


# ------------------------------------------------------------------ 배치 (단위: px, 글꼴 크기 기준)
STYLE = {0: (22, 18, 12), 1: (16, 14, 9), 2: (14, 11, 6), 3: (13, 8, 4)}   # 수준: (글자크기, 좌우여백, 상하여백)


def _em(s):
    return sum(1.0 if ord(ch) > 0x2E80 else (0.32 if ch == " " else 0.6) for ch in s)


def _wrap(s, max_em):
    if _em(s) <= max_em:
        return [s]
    words, lines, cur = s.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if _em(cand) <= max_em or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    out = []                                            # 띄어쓰기 없는 긴 단어는 글자 단위로 자름
    for ln in lines:
        while _em(ln) > max_em * 1.15:
            k = 1
            while _em(ln[:k + 1]) <= max_em:
                k += 1
            out.append(ln[:k])
            ln = ln[k:]
        out.append(ln)
    return out[:3] if len(out) <= 3 else out[:2] + [out[2][:-1] + "…"]


def layout(tree, palette=None, hgap=46, vgap=12):
    """좌우 균형 배치. 반환 {'nodes':[...], 'edges':[...], 'w','h'}"""
    palette = palette or PALETTE

    def box(n, lv):
        fs, px, py = STYLE[min(lv, 3)]
        lines = _wrap(n["t"], 9 if lv == 0 else (11 if lv == 1 else 13))
        w = max(_em(l) for l in lines) * fs + 2 * px
        h = len(lines) * fs * 1.3 + 2 * py
        return {"t": n["t"], "lines": lines, "fs": fs, "w": w, "h": h, "lv": lv}

    def measure(n, lv):
        b = box(n, lv)
        kids = [measure(c, lv + 1) for c in n.get("c", [])]
        sub = sum(k["H"] for k in kids) + vgap * max(len(kids) - 1, 0)
        b["kids"], b["H"] = kids, max(b["h"], sub)
        return b

    root = box(tree, 0)
    l1 = [measure(c, 1) for c in tree.get("c", [])]
    total = sum(k["H"] for k in l1)
    right, left, acc = [], [], 0
    for i, k in enumerate(l1):                          # 위에서부터 오른쪽을 채우고 나머지는 왼쪽
        (right if acc + k["H"] / 2 <= total / 2 or not right else left).append((i, k))
        if right and right[-1][1] is k:
            acc += k["H"]
    nodes, edges = [], []
    root.update(x=-root["w"] / 2, y=-root["h"] / 2, color=ROOT_COLOR, side=0)
    nodes.append(root)

    def place(b, x_edge, cy, side, color, parent):
        b.update(y=cy - b["h"] / 2, x=x_edge if side > 0 else x_edge - b["w"], color=color, side=side)
        nodes.append(b)
        edges.append((parent, b))
        kids = b["kids"]
        sub = sum(k["H"] for k in kids) + vgap * max(len(kids) - 1, 0)
        y = cy - sub / 2
        nx = (b["x"] + b["w"] + hgap * (0.8 if b["lv"] >= 2 else 1)) if side > 0 else (b["x"] - hgap * (0.8 if b["lv"] >= 2 else 1))
        for k in kids:
            place(k, nx, y + k["H"] / 2, side, color, b)
            y += k["H"] + vgap

    for side, group in ((1, right), (-1, left)):
        gap1 = vgap * 2
        sub = sum(k["H"] for _, k in group) + gap1 * max(len(group) - 1, 0)
        y = -sub / 2
        for i, k in group:
            x_edge = (root["x"] + root["w"] + hgap * 1.4) if side > 0 else (root["x"] - hgap * 1.4)
            place(k, x_edge, y + k["H"] / 2, side, palette[i % len(palette)], root)
            y += k["H"] + gap1
    m = 24
    minx, miny = min(n["x"] for n in nodes) - m, min(n["y"] for n in nodes) - m
    for n in nodes:
        n["x"] -= minx
        n["y"] -= miny
    W = max(n["x"] + n["w"] for n in nodes) + m
    H = max(n["y"] + n["h"] for n in nodes) + m
    return {"nodes": nodes, "edges": edges, "w": W, "h": H}


def _anchor(p, c):
    """부모·자식 연결점: 부모 바깥쪽 가장자리 → 자식 안쪽 가장자리."""
    side = c["side"]
    if p["lv"] == 0:
        x1 = p["x"] + p["w"] / 2 + side * p["w"] * 0.32
    else:
        x1 = p["x"] + p["w"] if side > 0 else p["x"]
    y1 = p["y"] + p["h"] / 2
    x2 = c["x"] if side > 0 else c["x"] + c["w"]
    y2 = c["y"] + c["h"] / 2
    if c["lv"] >= 3:                                   # 3수준부터는 밑줄형: 글자 아래로 연결
        y2 = c["y"] + c["h"] - 1
    return x1, y1, x2, y2


def _tint(hex_, a):
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(round(v + (255 - v) * a) for v in (r, g, b))


# ------------------------------------------------------------------ SVG / HTML
def to_svg(L, dark=False, marks=None):
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {L["w"]:.0f} {L["h"]:.0f}" '
           f'width="{L["w"]:.0f}" height="{L["h"]:.0f}" font-family="{FONT_FAMILY}">']
    ink = "#E8EEF2" if dark else "#1F2A36"
    for p, c in L["edges"]:
        x1, y1, x2, y2 = _anchor(p, c)
        mx = (x1 + x2) / 2
        w = 3.2 if c["lv"] == 1 else (2.2 if c["lv"] == 2 else 1.5)
        out.append(f'<path d="M{x1:.1f},{y1:.1f} C{mx:.1f},{y1:.1f} {mx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" '
                   f'fill="none" stroke="{c["color"]}" stroke-width="{w}" stroke-linecap="round" opacity=".9"/>')
        if c["lv"] >= 3:
            out.append(f'<line x1="{c["x"]:.1f}" y1="{y2:.1f}" x2="{c["x"] + c["w"]:.1f}" y2="{y2:.1f}" '
                       f'stroke="{c["color"]}" stroke-width="1.5"/>')
    for n in L["nodes"]:
        lv, col = n["lv"], n["color"]
        if lv <= 1:
            fill, stroke, tc, weight = col, col, "#FFFFFF", 700
        elif lv == 2:
            fill, stroke, tc, weight = (_tint(col, 0.86) if not dark else "#18232B"), col, (ink if not dark else "#E8EEF2"), 600
        else:
            fill, stroke, tc, weight = "none", "none", ink, 400
        if fill != "none":
            r = n["h"] / 2 if lv == 0 else 8
            out.append(f'<rect x="{n["x"]:.1f}" y="{n["y"]:.1f}" width="{n["w"]:.1f}" height="{n["h"]:.1f}" rx="{r:.1f}" '
                       f'fill="{fill}" stroke="{stroke}" stroke-width="{1.6 if lv == 2 else 0}"/>')
        lh = n["fs"] * 1.3
        y0 = n["y"] + n["h"] / 2 - lh * (len(n["lines"]) - 1) / 2 + n["fs"] * 0.36
        for i, ln in enumerate(n["lines"]):
            out.append(f'<text x="{n["x"] + n["w"] / 2:.1f}" y="{y0 + i * lh:.1f}" font-size="{n["fs"]}" font-weight="{weight}" '
                       f'fill="{tc}" text-anchor="middle">{html.escape(ln)}</text>')
        if marks and n["t"] in marks and lv > 0:              # 참고 자료에서 확인된 노드: 초록 ✓
            cx, cy = n["x"] + n["w"] - 2, n["y"] + 2
            out.append(f'<g><title>참고 자료에서 확인됨</title><circle cx="{cx:.1f}" cy="{cy:.1f}" r="6.5" fill="#1E9E5A" '
                       f'stroke="#FFFFFF" stroke-width="1.5"/><path d="M{cx - 3:.1f},{cy:.1f} l2,2.2 l4,-4.4" fill="none" '
                       f'stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></g>')
    out.append("</svg>")
    return "\n".join(out)


def to_html(tree, title=None, height=None, marks=None):
    """확대·축소·이동이 되는 단독 HTML (외부 파일 없음). Streamlit 미리보기와 다운로드 겸용."""
    L = layout(tree)
    svg = to_svg(L, marks=marks)
    h = height or max(360, min(int(L["h"]) + 60, 820))
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(title or tree["t"])}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{{margin:0;height:100%;background:#F7F9FA;font-family:{FONT_FAMILY}}}
#v{{width:100%;height:{h}px;overflow:hidden;cursor:grab;position:relative;background:#F7F9FA}} #v:active{{cursor:grabbing}}
#v svg{{width:100%;height:100%}} .bar{{position:absolute;right:10px;top:10px;display:flex;gap:6px;z-index:2}}
.bar button{{font:600 13px {FONT_FAMILY};border:1px solid #CBD5DC;background:#fff;border-radius:6px;padding:4px 10px;cursor:pointer}}
.hint{{position:absolute;left:12px;bottom:8px;font-size:12px;color:#7A8790}}</style></head><body>
<div id="v"><div class="bar"><button id="zi">＋</button><button id="zo">－</button><button id="zf">맞춤</button></div>
<div class="hint">드래그로 이동 · 휠로 확대/축소</div>{svg}</div>
<script>(function(){{var s=document.querySelector('#v svg'),W={L["w"]:.0f},H={L["h"]:.0f},vb=[0,0,W,H];
s.removeAttribute('width');s.removeAttribute('height');s.setAttribute('preserveAspectRatio','xMidYMid meet');
function set(){{s.setAttribute('viewBox',vb.join(' '))}}
function zoom(f,cx,cy){{cx=cx==null?vb[0]+vb[2]/2:cx;cy=cy==null?vb[1]+vb[3]/2:cy;vb=[cx-(cx-vb[0])*f,cy-(cy-vb[1])*f,vb[2]*f,vb[3]*f];set()}}
var v=document.getElementById('v'),d=null;
v.addEventListener('wheel',function(e){{e.preventDefault();var r=s.getBoundingClientRect(),k=Math.max(vb[2]/r.width,vb[3]/r.height);
zoom(e.deltaY>0?1.12:0.89,vb[0]+(e.clientX-r.left)*k,vb[1]+(e.clientY-r.top)*k)}},{{passive:false}});
v.addEventListener('mousedown',function(e){{d=[e.clientX,e.clientY]}});window.addEventListener('mouseup',function(){{d=null}});
window.addEventListener('mousemove',function(e){{if(!d)return;var r=s.getBoundingClientRect(),k=Math.max(vb[2]/r.width,vb[3]/r.height);
vb[0]-=(e.clientX-d[0])*k;vb[1]-=(e.clientY-d[1])*k;d=[e.clientX,e.clientY];set()}});
document.getElementById('zi').onclick=function(){{zoom(0.8)}};document.getElementById('zo').onclick=function(){{zoom(1.25)}};
document.getElementById('zf').onclick=function(){{vb=[0,0,W,H];set()}};}})();</script></body></html>"""


# ------------------------------------------------------------------ PNG (PIL, 한글 글꼴 직접 사용)
def to_png(tree, scale=2.0) -> bytes:
    import io
    from PIL import Image, ImageDraw, ImageFont
    import exporters
    L = layout(tree)
    S = scale
    img = Image.new("RGB", (int(L["w"] * S), int(L["h"] * S)), "#FFFFFF")
    d = ImageDraw.Draw(img)
    fonts = {}

    def font(sz, bold):
        k = (sz, bold)
        if k not in fonts:
            try:
                fonts[k] = ImageFont.truetype(exporters.FONT_BOLD if bold else exporters.FONT_REG, int(sz * S))
            except Exception:
                fonts[k] = ImageFont.load_default()
        return fonts[k]

    def rgb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    for p, c in L["edges"]:
        x1, y1, x2, y2 = _anchor(p, c)
        mx = (x1 + x2) / 2
        pts = []
        for i in range(25):
            t = i / 24
            bx = (1 - t) ** 3 * x1 + 3 * (1 - t) ** 2 * t * mx + 3 * (1 - t) * t ** 2 * mx + t ** 3 * x2
            by = (1 - t) ** 3 * y1 + 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3 * y2
            pts.append((bx * S, by * S))
        w = 3.2 if c["lv"] == 1 else (2.2 if c["lv"] == 2 else 1.5)
        d.line(pts, fill=rgb(c["color"]), width=max(1, int(w * S)), joint="curve")
        if c["lv"] >= 3:
            d.line([(c["x"] * S, y2 * S), ((c["x"] + c["w"]) * S, y2 * S)], fill=rgb(c["color"]), width=max(1, int(1.5 * S)))
    for n in L["nodes"]:
        lv, col = n["lv"], n["color"]
        box = [n["x"] * S, n["y"] * S, (n["x"] + n["w"]) * S, (n["y"] + n["h"]) * S]
        if lv <= 1:
            d.rounded_rectangle(box, radius=(n["h"] / 2 if lv == 0 else 8) * S, fill=rgb(col))
            tc = (255, 255, 255)
        elif lv == 2:
            d.rounded_rectangle(box, radius=8 * S, fill=rgb(_tint(col, 0.86)), outline=rgb(col), width=max(1, int(1.6 * S)))
            tc = rgb("#1F2A36")
        else:
            tc = rgb("#1F2A36")
        f = font(n["fs"], lv <= 2)
        lh = n["fs"] * 1.3
        y0 = n["y"] + n["h"] / 2 - lh * (len(n["lines"]) - 1) / 2
        for i, ln in enumerate(n["lines"]):
            d.text(((n["x"] + n["w"] / 2) * S, (y0 + i * lh) * S), ln, font=f, fill=tc, anchor="mm")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


# ------------------------------------------------------------------ PowerPoint 도형 (편집 가능)
def draw_pptx(slide, left, top, width, height, tree, font="맑은 고딕", palette=None):
    """슬라이드의 지정 영역(EMU)에 마인드맵을 PowerPoint 도형·곡선 연결선으로 그림 (받은 뒤 직접 고칠 수 있음)."""
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Pt
    L = layout(tree, palette)
    s = min(width / L["w"], height / L["h"])
    ox = left + (width - L["w"] * s) / 2
    oy = top + (height - L["h"] * s) / 2
    E = lambda v: Emu(int(v))
    X = lambda v: E(ox + v * s)
    Y = lambda v: E(oy + v * s)
    rgb = lambda h: RGBColor.from_string(h.lstrip("#"))
    for p, c in L["edges"]:
        x1, y1, x2, y2 = _anchor(p, c)
        cn = slide.shapes.add_connector(MSO_CONNECTOR.CURVE, X(x1), Y(y1), X(x2), Y(y2))
        cn.line.color.rgb = rgb(c["color"])
        cn.line.width = Emu(int((3.2 if c["lv"] == 1 else (2.2 if c["lv"] == 2 else 1.5)) * s))
        if c["lv"] >= 3:
            ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, X(c["x"]), Y(y2), X(c["x"] + c["w"]), Y(y2))
            ln.line.color.rgb = rgb(c["color"])
            ln.line.width = Emu(int(1.5 * s))
    for n in L["nodes"]:
        lv, col = n["lv"], n["color"]
        if lv <= 2:
            sp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, X(n["x"]), Y(n["y"]), E(n["w"] * s), E(n["h"] * s))
            sp.adjustments[0] = 0.5 if lv == 0 else min(0.5, 8 / max(n["h"], 1))
            sp.fill.solid()
            sp.fill.fore_color.rgb = rgb(col if lv <= 1 else _tint(col, 0.86))
            if lv == 2:
                sp.line.color.rgb = rgb(col)
                sp.line.width = Emu(int(1.6 * s))
            else:
                sp.line.fill.background()
            sp.shadow.inherit = False
            tc = "#FFFFFF" if lv <= 1 else "#1F2A36"
        else:
            sp = slide.shapes.add_textbox(X(n["x"]), Y(n["y"]), E(n["w"] * s), E(n["h"] * s))
            tc = "#1F2A36"
        tf = sp.text_frame
        tf.word_wrap = False
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        for i, line in enumerate(n["lines"]):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = PP_ALIGN.CENTER
            r = para.add_run()
            r.text = line
            r.font.size = Pt(max(6, n["fs"] * s / 12700))
            r.font.bold = lv <= 2
            r.font.color.rgb = rgb(tc)
            r.font.name = font
            rpr = r._r.get_or_add_rPr()
            ea = rpr.find(qn("a:ea"))
            if ea is None:
                from lxml import etree
                ea = etree.SubElement(rpr, qn("a:ea"))
            ea.set("typeface", font)
    return L


def to_pptx(tree, title=None) -> bytes:
    """마인드맵 한 장짜리 16:9 PPTX (흰 배경)."""
    import io
    from pptx import Presentation
    from pptx.util import Emu, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    tb = sl.shapes.add_textbox(Emu(457200), Emu(228600), Emu(11277600), Emu(500000))
    r = tb.text_frame.paragraphs[0].add_run()
    r.text = title or tree["t"]
    r.font.size, r.font.bold, r.font.name = Pt(22), True, "맑은 고딕"
    draw_pptx(sl, 457200, 800000, 11277600, 5800000, tree)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


# ------------------------------------------------------------------ FreeMind (.mm) — XMind·FreeMind·Freeplane 에서 열림
def to_freemind(tree) -> bytes:
    def node(n, lv, i):
        attrs = f'TEXT="{html.escape(n["t"], quote=True)}"'
        if lv == 1:
            attrs += f' POSITION="{"right" if i % 2 == 0 else "left"}" COLOR="{PALETTE[i % len(PALETTE)]}"'
        kids = "".join(node(c, lv + 1, j) for j, c in enumerate(n.get("c", [])))
        return f"<node {attrs}>{kids}</node>" if kids else f"<node {attrs}/>"
    return ('<map version="1.0.1">' + node(tree, 0, 0) + "</map>").encode("utf-8")


# ------------------------------------------------------------------ AI: 문서 → 마인드맵, 가지 펼치기, 내용 보강
_HEAD = re.compile(r"^\s*(#{1,6}\s|\d+(\.\d+)*[.)]\s|[가-하][.)]\s|[IVX]+\.\s|[□■ㅇ○●◦\-•※▪]\s?|\|)")


def skeleton(text, budget=6500):
    """긴 문서를 구조 위주로 압축: 제목·개조식 줄은 남기고 긴 문단은 앞부분만."""
    out, n = [], 0
    for l in (text or "").replace("\r", "").split("\n"):
        s = re.sub(r"\s+", " ", l).strip()
        if not s:
            continue
        if _HEAD.match(l) or len(s) <= 60:
            line = s[:110]
        else:
            line = s[:70] + "…"
        if n + len(line) > budget:
            break
        out.append(line)
        n += len(line) + 1
    return "\n".join(out)


SYS_DOC = """너는 문서를 한눈에 보이는 마인드맵으로 구조화하는 전문가다. 주어진 문서 내용만으로 마인드맵을 만들고 JSON만 출력한다.
규칙:
- 가운데 주제(t)는 문서의 핵심 주제(20자 이내).
- 1단계 가지는 4~7개: 문서의 큰 덩어리(배경, 현황, 문제, 목표, 추진 내용, 일정, 기대효과 등 문서에 실제로 있는 것).
- 각 가지 아래 2~5개, 필요하면 3단계까지. 전체 노드는 60개 이하.
- 모든 노드 이름은 명사형 키워드 구(18자 이내). 문장으로 쓰지 말 것. 수치·고유명사는 원문 그대로.
- 문서에 없는 내용은 만들지 말 것.
형식: {"t":"주제","c":[{"t":"가지","c":[{"t":"하위","c":[]}]}]}"""


REF_RULE = ("\n[참고 자료]는 지식보관함(내부 문서)·웹 검색에서 찾은 발췌다. 주제와 관련된 사실(기관명·수치·제도명 등)은 "
            "참고 자료에 적힌 표기 그대로 노드로 쓰고, 참고 자료에 없는 사실은 지어내지 말 것.")


def _ref(context, limit=2500):
    c = (context or "").strip()
    return ("\n[참고 자료]\n" + c[:limit]) if c else ""


def from_document(text, chat_fn, focus="", doc_name="", context=""):
    ref = _ref(context, 2000)
    body = skeleton(text, max(3500, 6500 - len(ref)))          # 8K 문맥 안에 문서 + 참고 자료를 함께 넣음
    user = (f"[문서명] {doc_name}\n" if doc_name else "") + (f"[사용자 요청] {focus}\n" if focus else "") + "[문서]\n" + body
    if ref:
        user += "\n(아래 참고 자료는 보조 자료다. 마인드맵의 뼈대는 위 [문서]로 잡고, 참고 자료는 관련 사실을 보탤 때만 쓸 것.)" + ref
    out = chat_fn([{"role": "system", "content": SYS_DOC + (REF_RULE if ref else "")}, {"role": "user", "content": user}],
                  {"temperature": 0.2, "num_predict": 2500}, fmt="json")
    d = _json(out)
    if not d:
        raise ValueError("AI 결과를 해석하지 못했습니다. 다시 시도해 주세요.")
    return clean(d, max_children=8, max_depth=4)


SYS_IDEA = """너는 기획 회의를 돕는 마인드맵 도우미다. 주제에 대한 생각 정리용 마인드맵 초안을 JSON으로만 출력한다.
- 1단계 가지 5~7개(관점: 배경·목표·대상·추진 내용·자원·위험·일정·효과 등 주제에 맞게), 각 가지 아래 2~4개, 3단계까지.
- 노드 이름은 18자 이내 명사형 키워드 구. 구체적인 수치·기관명·통계는 지어내지 말 것(확인이 필요한 사실은 넣지 않음).
형식: {"t":"주제","c":[{"t":"가지","c":[{"t":"하위","c":[]}]}]}"""


def brainstorm(topic, chat_fn, context=""):
    """문서 없이 주제만으로 마인드맵 초안 (아이디어 정리용). context: 지식보관함·웹 검색 발췌."""
    ref = _ref(context)
    out = chat_fn([{"role": "system", "content": SYS_IDEA + (REF_RULE if ref else "")},
                   {"role": "user", "content": f"[주제] {topic}" + ref}],
                  {"temperature": 0.5, "num_predict": 2000}, fmt="json")
    d = _json(out)
    if not d:
        raise ValueError("AI 결과를 해석하지 못했습니다. 다시 시도해 주세요.")
    return clean(d, max_children=8, max_depth=4)


SYS_EXPAND ="""너는 마인드맵 아이디어 도우미다. 지정한 가지에 붙일 하위 항목을 제안한다.
- 4~6개, 각 18자 이내 명사형 키워드 구. 이미 있는 항목과 겹치지 않게. 한국어로.
출력: {"items":["...","..."]}"""


def expand(tree, path, chat_fn, hint="", context=""):
    target = node_at(tree, path)
    chain = []
    n = tree
    chain.append(n["t"])
    for i in path:
        n = n["c"][i]
        chain.append(n["t"])
    user = (f"[마인드맵 전체]\n{to_outline(tree)[:2500]}\n\n[펼칠 가지] {' > '.join(chain)}\n"
            f"[이미 있는 하위 항목] {', '.join(c['t'] for c in target.get('c', [])) or '없음'}\n" + (f"[요청] {hint}\n" if hint else ""))
    ref = _ref(context, 2500)
    out = chat_fn([{"role": "system", "content": SYS_EXPAND + (REF_RULE if ref else "")},
                   {"role": "user", "content": user + ref}],
                  {"temperature": 0.5, "num_predict": 400}, fmt="json")
    d = _json(out) or {}
    items = [re.sub(r"\s+", " ", str(x)).strip()[:40] for x in d.get("items", []) if str(x).strip()]
    have = {re.sub(r"\W", "", c["t"]) for c in target.get("c", [])}
    new = [x for x in items if re.sub(r"\W", "", x) not in have][:6]
    target.setdefault("c", []).extend({"t": x, "c": []} for x in new)
    return new


SYS_ENRICH = """너는 마인드맵을 발표자료·웹페이지 문장으로 풀어 쓰는 작가다. JSON만 출력한다.
- 각 1단계 가지마다: keypoint(그 가지의 핵심 메시지 한 문장, 40자 이내), intro(2문장 소개), items(하위 항목별 한 문장 설명, 50자 이내).
- [참고 문서]가 있으면 그 내용만 근거로 쓰고, 없으면 마인드맵에 적힌 범위를 넘지 말 것. 수치를 지어내지 말 것.
- headline 은 전체를 꿰는 핵심 메시지 한 문장(38자 이내), summary 는 전체 요약 한 문장(70자 이내).
형식: {"headline":"38자 이내 핵심 메시지","summary":"전체 한 문장","branches":[{"t":"가지 이름","keypoint":"...","intro":"...","items":{"하위 이름":"설명"}}]}"""


def enrich(tree, chat_fn, doc_text="", style="", context=""):
    user = f"[마인드맵]\n{to_outline(tree)[:3500]}\n"
    if style:
        user += f"[문체] {style}\n"
    ref = _ref(context, 2000)
    if doc_text:
        user += "[참고 문서]\n" + skeleton(doc_text, 3500 - (len(ref) // 2 if ref else 0))
    user += ref
    out = chat_fn([{"role": "system", "content": SYS_ENRICH + (REF_RULE if ref else "")}, {"role": "user", "content": user}],
                  {"temperature": 0.3, "num_predict": 3000}, fmt="json")
    d = _json(out) or {}
    by = {}
    for b in d.get("branches", []) or []:
        if isinstance(b, dict) and b.get("t"):
            by[re.sub(r"\W", "", b["t"])] = b
    return {"summary": str(d.get("summary", "") or ""), "headline": str(d.get("headline", "") or ""), "branches": by}


def _nrm(s):
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


def grounded(tree, context):
    """참고 자료(지식보관함·웹·문서)에서 확인되는 노드 이름 집합.
    이름 전체가 자료에 있거나, 이름의 핵심 낱말(2글자 이상)이 모두 자료에 있으면 '근거 있음'."""
    src = _nrm(context)
    if not src:
        return set()
    out = set()

    def walk(n, d):
        t = n["t"]
        k = _nrm(t)
        words = [_nrm(w) for w in re.split(r"[\s,·/()]+", t) if len(_nrm(w)) >= 2]
        if d > 0 and len(k) >= 2 and (k in src or (words and all(w in src for w in words))):
            out.add(t)
        for c in n.get("c", []):
            walk(c, d + 1)
    walk(tree, 0)
    return out


def prune(tree, max_depth=3, _d=1):
    """보기용으로 깊이 제한 (max_depth=3 → 가운데 주제 + 2단계)."""
    return {"t": tree["t"], "c": [prune(c, max_depth, _d + 1) for c in tree.get("c", [])] if _d < max_depth else []}


def _fit(s, n=42):
    """KEY POINT 띠에 들어가게 줄이기 (띄어쓰기 기준)."""
    s = re.sub(r"\s+", " ", s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return (cut if len(cut) >= n * 0.6 else s[:n]).rstrip(",. ") + "…"


def _branch_info(info, t):
    if not info:
        return {}
    k = re.sub(r"\W", "", t)
    if k in info["branches"]:
        return info["branches"][k]
    for kk, v in info["branches"].items():                 # 이름을 조금 바꿔 쓴 경우
        if kk and (kk in k or k in kk):
            return v
    return {}


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    for cand in (m.group(0), re.sub(r",\s*([}\]])", r"\1", m.group(0))):
        try:
            return json.loads(cand)
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ 마인드맵 → 슬라이드 / 웹페이지
def to_slides_data(tree, info=None, overview=True, source=""):
    slides = []
    if overview:
        kp0 = _fit((info or {}).get("headline") or (info or {}).get("summary", "")) or \
            _fit(f"{len(tree.get('c', []))}개 가지로 본 {tree['t']}")
        view = prune(tree, 3) if count(tree) > 30 else tree      # 노드가 많으면 2단계까지만 (글자가 읽히게)
        slides.append({"title": "전체 구조", "mindmap": view, "keypoint": kp0,
                       "bullets": [], "table": None, "notes": "", "source": source})
    for b in tree.get("c", []):
        bi = _branch_info(info, b["t"])
        bullets = []
        for c in b.get("c", []):
            desc = (bi.get("items") or {}).get(c["t"], "")
            bullets.append((0, c["t"]))
            if desc:                                         # 설명이 있으면 설명만 (하위 항목은 설명에 녹아 있음)
                bullets.append((1, desc))
            else:
                for g in c.get("c", [])[:4]:
                    bullets.append((1, g["t"]))
        bullets = bullets[:12]
        kp = _fit(bi.get("keypoint") or (b["t"] + " — " + ", ".join(c["t"] for c in b.get("c", [])[:3])))
        if not bullets:
            bullets = [(0, b["t"])]
        sd = {"title": b["t"], "keypoint": kp, "bullets": bullets[:14], "table": None,
              "notes": bi.get("intro", ""), "source": source}
        if not bi.get("items") and len(b.get("c", [])) >= 2:   # 설명 문장이 없으면 그 가지만의 작은 마인드맵으로
            sd["mindmap"] = b
        slides.append(sd)
    return {"title": tree["t"], "subtitle": _fit((info or {}).get("summary", ""), 70) or "마인드맵으로 정리한 핵심 구조",
            "slides": slides}


def to_web(tree, info=None, source_name=""):
    import web_builder
    secs = []
    for b in tree.get("c", []):
        bi = _branch_info(info, b["t"])
        items = []
        for c in b.get("c", []):
            body = (bi.get("items") or {}).get(c["t"], "") or " · ".join(g["t"] for g in c.get("c", []))
            items.append({"title": c["t"], "body": body, "tag": ""})
        lay = "cards" if items else "prose"
        secs.append({"nav": b["t"][:8], "heading": b["t"], "layout": lay, "intro": bi.get("intro", "") or bi.get("keypoint", ""),
                     "items": items})
    content = {"title": tree["t"], "tagline": (info or {}).get("summary", "") or "한눈에 보는 핵심 구조",
               "subtitle": f"원문: {source_name}" if source_name else "", "sections": secs}
    theme = {"bg": "#0E1A22", "bg2": "#132430", "surface": "#18303D", "text": "#EEF4F7", "muted": "#9FB3BE",
             "accent": "#1F9BCF", "accent2": "#6FD3F7", "heading_font": "IBM Plex Sans KR", "body_font": "Noto Sans KR",
             "hero": "grid", "mood": ["MIND MAP"]}
    page = web_builder.render(content, theme, [])
    mm_svg = to_svg(layout(tree)).replace("<svg ", '<svg style="width:100%;height:auto" ', 1)   # f-string 밖에서 처리(Python 3.10·3.11 호환)
    block = (f'<section id="mindmap" class="sec"><header class="sec-head"><span class="sec-no">MAP</span><h2>한눈에 보기</h2></header>'
             f'<div style="background:#F7F9FA;border-radius:16px;padding:12px;overflow-x:auto">'
             f'<div style="min-width:640px">{mm_svg}</div></div></section>')
    page = page.replace("<main>", "<main>" + block, 1)
    page = re.sub(r"<footer>.*?</footer>", f"<footer><p>마인드맵{(' · 원문: ' + html.escape(source_name)) if source_name else ''}"
                  f" · 로컬 AI 작업실에서 만들었습니다.</p></footer>", page, flags=re.S)
    return page
