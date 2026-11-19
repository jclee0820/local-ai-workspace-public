"""디자인 시스템 기반 PPTX 테마 엔진 (편집 가능한 도형으로 직접 그림).

- modern : 어두운 표지의 대형 화면 테마 (1920×1080 기준, 1px = 6350 EMU = 0.5pt)
- blue   : 밝은 보고형 테마 (960×540 기준, 1px = 12700 EMU = 1pt)
입력 데이터: {'title','subtitle','slides':[{'title','bullets':[(lvl,txt)],'table','notes','keypoint','source'}]}"""
import copy
import datetime
import io
import os
import re

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET = os.path.join(HERE, "slide_themes")

THEMES = {
    "modern": {"label": "모던 (기본)", "desc": "어두운 표지·간지 + 밝은 본문, 청록→녹색 그라디언트, KEY POINT 바 · 개조식",
                    "style": "개조식, 명사형 종결(~약화, ~필요, ~수립). '합니다'체 금지. 수치는 단위와 함께."},
    "blue": {"label": "블루", "desc": "남색 표지 + 밝은 본문, 파랑·시안, 번호 카드·출처 각주 · 존댓말 평서체",
                  "style": "존댓말 평서체(~합니다). 제목은 '주제 — 핵심 메시지.' 형식(긴 줄표 앞뒤 띄움). 과장 없이 사실과 판단 구분."},
}
DEFAULT_THEME = "modern"

ROMAN = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ"]


def rgb(h):
    h = h.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ======================================================================= 공통 도형 도우미
class Canvas:
    def __init__(self, prs, slide, emu_per_px, pt_per_px):
        self.prs, self.s, self.k, self.f = prs, slide, emu_per_px, pt_per_px

    def E(self, v):
        return Emu(int(round(v * self.k)))

    def rect(self, x, y, w, h, fill=None, line=None, shape=MSO_SHAPE.RECTANGLE, radius=None, line_w=1):
        sp = self.s.shapes.add_shape(shape, self.E(x), self.E(y), self.E(w), self.E(h))
        if fill:
            sp.fill.solid()
            sp.fill.fore_color.rgb = rgb(fill)
        else:
            sp.fill.background()
        if line:
            sp.line.color.rgb = rgb(line)
            sp.line.width = Pt(line_w * self.f)
        else:
            sp.line.fill.background()
        if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
            sp.adjustments[0] = min(0.5, radius / max(1, min(w, h)))
        sp.shadow.inherit = False
        sp.text_frame.text = ""
        return sp

    def gradient(self, sp, stops, angle=0):
        """stops: [(pos 0..1, '#hex')]  angle: 0=좌→우, 90=위→아래"""
        sp.fill.gradient()
        sp.fill.gradient_angle = angle
        gs = sp.fill.gradient_stops
        # python-pptx 기본 2개 스톱을 원하는 개수로 맞춤
        gsLst = sp.fill._xPr.find(qn("a:gradFill")).find(qn("a:gsLst"))
        for g in list(gsLst):
            gsLst.remove(g)
        for pos, col in stops:
            g = etree.SubElement(gsLst, qn("a:gs"), pos=str(int(pos * 100000)))
            etree.SubElement(g, qn("a:srgbClr"), val=col.lstrip("#").upper())
        return sp

    def text(self, x, y, w, h, anchor=MSO_ANCHOR.TOP, wrap=True):
        tb = self.s.shapes.add_textbox(self.E(x), self.E(y), self.E(w), self.E(h))
        tf = tb.text_frame
        tf.word_wrap = wrap
        tf.auto_size = None
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        return tf

    def run(self, p, text, family, size_px, color=None, bold=False, grad=None, spacing=None):
        r = p.add_run()
        r.text = text
        rPr = r._r.get_or_add_rPr()
        if grad:                                            # 그라디언트 글자 (브랜드 그라디언트)
            gf = etree.SubElement(rPr, qn("a:gradFill"), rotWithShape="1")
            gl = etree.SubElement(gf, qn("a:gsLst"))
            for pos, col in grad:
                g = etree.SubElement(gl, qn("a:gs"), pos=str(int(pos * 100000)))
                etree.SubElement(g, qn("a:srgbClr"), val=col.lstrip("#").upper())
            etree.SubElement(gf, qn("a:lin"), ang="0", scaled="0")
        elif color:
            r.font.color.rgb = rgb(color)
        r.font.size = Pt(size_px * self.f)
        r.font.bold = bold
        r.font.name = family
        latin = rPr.find(qn("a:latin"))
        ea = rPr.find(qn("a:ea"))
        if ea is None:
            ea = etree.Element(qn("a:ea"))
            latin.addnext(ea)
        ea.set("typeface", family)
        if spacing is not None:
            rPr.set("spc", str(int(spacing * self.f * 100)))
        return r

    def para(self, tf, first=False, align=PP_ALIGN.LEFT, line=None, after=0):
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        p.alignment = align
        if line:
            p.line_spacing = line
        if after:
            p.space_after = Pt(after * self.f)
        return p

    def bullet(self, p, char, color, indent_px, level_px=0):
        """내어쓰기 불릿: 기호와 본문을 분리해 둘째 줄이 본문 시작에 맞춰짐."""
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", str(int((indent_px + level_px) * self.k)))
        pPr.set("indent", str(-int(indent_px * self.k)))
        for tag in ("a:buNone", "a:buChar", "a:buClr", "a:buFont"):
            for e in pPr.findall(qn(tag)):
                pPr.remove(e)
        bc = etree.SubElement(pPr, qn("a:buClr"))
        etree.SubElement(bc, qn("a:srgbClr"), val=color.lstrip("#").upper())
        etree.SubElement(pPr, qn("a:buFont"), typeface="Arial")
        etree.SubElement(pPr, qn("a:buChar"), char=char)

    def picture(self, path, x, y, w=None, h=None, alpha=None):
        pic = self.s.shapes.add_picture(path, self.E(x), self.E(y), self.E(w) if w else None, self.E(h) if h else None)
        if alpha is not None:
            blip = pic._element.find(".//" + qn("a:blip"))
            etree.SubElement(blip, qn("a:alphaModFix"), amt=str(int(alpha * 100000)))
        return pic

    def shadow(self, sp, blur_px, dist_px, alpha, color="0B234F"):
        spPr = sp._element.spPr
        eff = spPr.find(qn("a:effectLst"))
        if eff is None:
            eff = etree.SubElement(spPr, qn("a:effectLst"))
        for e in list(eff):
            eff.remove(e)
        sh = etree.SubElement(eff, qn("a:outerShdw"), blurRad=str(int(blur_px * self.k)), dist=str(int(dist_px * self.k)),
                              dir="5400000", algn="t", rotWithShape="0")
        c = etree.SubElement(sh, qn("a:srgbClr"), val=color)
        etree.SubElement(c, qn("a:alpha"), val=str(int(alpha * 100000)))

    def flip_v(self, sp):
        sp._element.spPr.find(qn("a:xfrm")).set("flipV", "1")


_LN_ORDER = {qn("a:lnL"): 0, qn("a:lnR"): 1, qn("a:lnT"): 2, qn("a:lnB"): 3}


def _cell_border(cell, side, color, width_emu):
    """셀 테두리. 스키마 순서(lnL, lnR, lnT, lnB 가 채우기보다 앞)를 지켜 삽입해야 PowerPoint 복구 경고가 안 남."""
    tcPr = cell._tc.get_or_add_tcPr()
    tag = qn({"L": "a:lnL", "R": "a:lnR", "T": "a:lnT", "B": "a:lnB"}[side])
    for e in tcPr.findall(tag):
        tcPr.remove(e)
    ln = etree.Element(tag, w=str(int(width_emu)), cap="flat", cmpd="sng", algn="ctr")
    if color:
        sf = etree.SubElement(ln, qn("a:solidFill"))
        etree.SubElement(sf, qn("a:srgbClr"), val=color.lstrip("#").upper())
    else:
        etree.SubElement(ln, qn("a:noFill"))
    idx = len(tcPr)
    for i, ch in enumerate(tcPr):
        if ch.tag not in _LN_ORDER or _LN_ORDER[ch.tag] > _LN_ORDER[tag]:
            idx = i
            break
    tcPr.insert(idx, ln)


def _plain_table_style(tbl_shape):
    tblPr = tbl_shape.table._tbl.tblPr
    tblPr.set("firstRow", "0")
    tblPr.set("bandRow", "0")
    sid = tblPr.find(qn("a:tableStyleId"))
    if sid is None:
        sid = etree.SubElement(tblPr, qn("a:tableStyleId"))
    sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"    # No Style, No Grid


def _vw(t):
    """글자 폭(em): 한글·한자 ≈ 0.95, 영문·숫자·기호 ≈ 0.56."""
    return sum(0.95 if ord(ch) >= 0x2E80 else 0.56 for ch in str(t))


def _fit_size(bullets, w, h, sizes, line=1.5, after=8, indent=34):
    """카드 글상자(w×h px)에 다 들어가는 가장 큰 글자 크기. 한글 1자 ≈ 글자 크기 1em 폭으로 어림."""
    import math
    for s in sizes:
        need = 0
        for lvl, t in bullets:
            sz = s if lvl == 0 else s - 2
            cw = max(w - indent * (lvl + 1), 60)
            need += math.ceil(max(_vw(t), 1) * sz / cw) * sz * line + after
        if need <= h:
            return s
    return sizes[-1]


def _col_widths(rows, w, min_frac=0.12):
    """칸 폭: 열마다 가장 긴 글자 수에 비례(너무 좁지 않게)."""
    nc = max(len(r) for r in rows)
    lens = [max(min(_vw(r[i]) if i < len(r) else 0, 30) for r in rows) + 2 for i in range(nc)]
    tot = sum(lens)
    fr = [max(min_frac, l / tot) for l in lens]
    s = sum(fr)
    return [w * f / s for f in fr]


def _table_font(rows, widths, h, sizes, pad=40, line=1.25, vpad=16):
    import math
    for s in sizes:
        need = 0
        for r in rows:
            need += max(math.ceil(max(_vw(r[i]) if i < len(r) else 0, 1) * s / max(widths[i] - pad, 30))
                        for i in range(len(widths))) * s * line + vpad
        if need <= h:
            return s
    return sizes[-1]


def _figure(c, png, x, y, w, h):
    """그림을 상자(w×h) 안에 비율 유지로 가운데 배치."""
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    iw, ih = im.size
    sc = min(w / iw, h / ih)
    pw, ph = iw * sc, ih * sc
    return c.s.shapes.add_picture(io.BytesIO(png), c.E(x + (w - pw) / 2), c.E(y + (h - ph) / 2), c.E(pw), c.E(ph))


def _groups(bullets):
    """레벨0 항목 단위로 묶음: [(제목, [하위 줄...])]"""
    out = []
    for lvl, t in bullets:
        if lvl == 0 or not out:
            out.append([t, []])
        else:
            out[-1][1].append((lvl, t))
    return out


def _split_title(t):
    """표지 제목을 2줄로: 쉼표/공백 기준 가운데 근처에서 나눔."""
    if len(t) <= 12:
        return [t]
    m = re.search(r"[,，:]\s*", t)                     # 쉼표·쌍점이 있으면 그 뒤에서 나눔 (양쪽이 너무 짧지 않을 때)
    if m and 4 <= m.start() and len(t) - m.end() >= 4:
        return [t[:m.end()].strip(), t[m.end():].strip()]
    cands = [m.end() for m in re.finditer(r"[,，:·]\s*|\s", t)]
    if not cands:
        return [t]
    mid = len(t) / 2
    cut = min(cands, key=lambda c: abs(c - mid))
    return [t[:cut].strip(), t[cut:].strip()]


def _pick_icons(texts, hint="", icon_set="lucide"):
    """여러 카드에 서로 다른 아이콘을 고름. 하나라도 못 찾으면 None (아이콘·번호 혼용 방지)."""
    try:
        import icon_library as il
        if not il.available():
            return None
        used, out = [], []
        for i, t in enumerate(texts):
            n = il.guess(t, icon_set, hint if i == 0 else "", avoid=used)   # 슬라이드 키워드는 첫 카드에
            if not n:
                return None
            used.append(n)
            out.append(n)
        return out
    except Exception:
        return None


def _icon(c, name, color, x, y, size, icon_set="lucide"):
    """아이콘 이름 → 색을 입힌 투명 PNG 배치."""
    try:
        import icon_library as il
        p = il.png(name, color, icon_set, 256) if name else None
        if p:
            c.picture(p, x, y, size, size)
            return True
    except Exception:
        pass
    return False


def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


# ======================================================================= 슬라이드 마스터 레이아웃
# 배경·로고·장식 띠·고정 문구·쪽 번호는 마스터 아래 레이아웃(표지·목차·본문·마무리)에 한 번만 두고,
# 각 슬라이드에는 내용(제목·본문·표·그림)만 넣는다. → PowerPoint '슬라이드 마스터 보기'에서 디자인을 한 곳에서 고칠 수 있음.
_BLANK_IDX = 6                                          # 기본 서식의 '빈 화면' 레이아웃 (임시 그리기용)


def _drop_slide(prs, slide):
    lst = prs.slides._sldIdLst
    for sid in list(lst):
        if prs.part.related_part(sid.rId) is slide.part:
            prs.part.drop_rel(sid.rId)
            lst.remove(sid)
            return


def _title_ph(K, F, x, y, w, h, anchor="ctr", font="", size_px=40, color="#000000", bold=False):
    """레이아웃용 제목 개체 틀(<p:ph type="title">). 글꼴·크기·색은 lstStyle 기본값으로."""
    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    xml = (f'<p:sp xmlns:p="{P}" xmlns:a="{A}"><p:nvSpPr><p:cNvPr id="9000" name="제목 개체 틀"/>'
           '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
           f'<p:spPr><a:xfrm><a:off x="{int(x * K)}" y="{int(y * K)}"/><a:ext cx="{int(w * K)}" cy="{int(h * K)}"/></a:xfrm>'
           '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
           f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:noAutofit/></a:bodyPr>'
           f'<a:lstStyle><a:lvl1pPr algn="l"><a:lnSpc><a:spcPct val="100000"/></a:lnSpc>'
           f'<a:defRPr sz="{int(size_px * F * 100)}" b="{1 if bold else 0}"><a:solidFill><a:srgbClr val="{color.lstrip("#")}"/>'
           f'</a:solidFill><a:latin typeface="{font}"/><a:ea typeface="{font}"/></a:defRPr></a:lvl1pPr></a:lstStyle>'
           '<a:p><a:endParaRPr lang="ko-KR"/></a:p></p:txBody></p:sp>')
    return etree.fromstring(xml)


def _slide_num(c, x, y, w, h, family, size_px, color, suffix="", suffix_color=None, align=PP_ALIGN.RIGHT):
    """쪽 번호 필드(슬라이드마다 PowerPoint 가 자동으로 번호를 넣음) + 뒤 글자(예: ' / 18')."""
    import uuid
    tf = c.text(x, y, w, h, MSO_ANCHOR.MIDDLE)
    p = c.para(tf, True, align)
    r = c.run(p, "‹#›", family, size_px, color)
    r._r.tag = qn("a:fld")
    r._r.set("id", "{" + str(uuid.uuid4()).upper() + "}")
    r._r.set("type", "slidenum")
    if suffix:
        c.run(p, suffix, family, size_px, suffix_color or color)


class _Layouts:
    """테마 클래스에 섞어 쓰는 레이아웃 도우미. 하위 클래스: K, F, prs."""

    def make_layout(self, idx, name, draw, title=None):
        """기본 서식의 idx 번 레이아웃을 비우고 name 으로 바꾼 뒤, draw(c) 로 그린 도형을 옮겨 넣음."""
        lay = self.prs.slide_layouts[idx]
        lay._element.cSld.set("name", name)
        tree = lay.shapes._spTree
        for el in list(tree)[2:]:
            tree.remove(el)
        tmp = self.prs.slides.add_slide(self.prs.slide_layouts[_BLANK_IDX])
        c = Canvas(self.prs, tmp, self.K, self.F)
        draw(c)
        from pptx.opc.constants import RELATIONSHIP_TYPE as RT
        for el in list(tmp.shapes._spTree)[2:]:
            for node in el.iter():
                rid = node.get(qn("r:embed"))
                if rid:
                    node.set(qn("r:embed"), lay.part.relate_to(tmp.part.related_part(rid), RT.IMAGE))
            tree.append(el)
        if title:
            tree.append(_title_ph(self.K, self.F, **title))
        _drop_slide(self.prs, tmp)
        return lay

    def drop_unused_layouts(self, keep):
        for lay in list(self.prs.slide_layouts):
            if lay not in keep:
                self.prs.slide_layouts.remove(lay)

    def on(self, layout):
        return Canvas(self.prs, self.prs.slides.add_slide(layout), self.K, self.F)

    def title_tf(self, c, anchor=None):
        ph = c.s.shapes.title
        tf = ph.text_frame
        tf.word_wrap = True
        if anchor is not None:
            tf.vertical_anchor = anchor
        return tf


# ======================================================================= 모던 (1920×1080)
class Modern(_Layouts):
    K, F = 6350, 0.5
    DISPLAY, SANS, SANS_L, SANS_B, NUM = ("Gmarket Sans TTF Bold", "KoPubDotum Medium", "KoPubDotum Light",
                                          "KoPubDotum Bold", "KoPubBatang Light")
    DISPLAY_M = "Gmarket Sans TTF Medium"
    C = {"night": "#0B1419", "paper": "#F5F7F8", "surface": "#FFFFFF", "row-alt": "#F1F5F7", "tint-teal": "#EAF4F8",
         "hairline": "#DDE4E8", "ink": "#14212B", "ink-soft": "#3A4851", "muted": "#55636D", "subtle": "#8A979F",
         "teal": "#005878", "teal-deep": "#004A66", "teal-bright": "#009DCB", "teal-chip": "#035370", "navy": "#1F4E79",
         "brand-cyan": "#00B0F0", "brand-green": "#00B050", "cyan-on-dark": "#6FD3F7", "muted-dark": "#A9B6BE",
         "subtitle-dark": "#C5D0D6", "night-raised": "#13212A", "on-dark": "#FFFFFF"}
    GRAD = [(0, "#00B0F0"), (1, "#00B050")]
    A = os.path.join(ASSET, "modern")

    def __init__(self, data):
        self.d = data
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Emu(1920 * self.K), Emu(1080 * self.K)

    def cv(self):
        return Canvas(self.prs, _blank(self.prs), self.K, self.F)

    def dark_ground(self, c, alpha=0.3):
        c.rect(0, 0, 1920, 1080, self.C["night"])
        bg = os.path.join(self.A, "bg-dark.jpg")
        if os.path.exists(bg):
            c.picture(bg, 0, 0, 1920, 1080, alpha=alpha)
        c.gradient(c.rect(0, 0, 1920, 6), self.GRAD)

    def logo(self, c, kind, x, y, w):
        p = os.path.join(self.A, f"logo-{kind}.png")
        if os.path.exists(p):
            c.picture(p, x, y, w=w)

    # ---- 표지
    def _lay_cover(self, c):
        self.dark_ground(c, 0.38)
        city = os.path.join(self.A, "city-v2x.png")
        if os.path.exists(city):
            c.picture(city, 820, 483, 1100, 597)
        chip = c.rect(120, 740, 220, 52, shape=MSO_SHAPE.SNIP_1_RECTANGLE)
        chip.adjustments[0] = 22 / 52
        c.gradient(chip, [(0, self.C["night-raised"]), (1, self.C["teal-chip"])])
        self.logo(c, "white", 120, 940, 260)
        c.gradient(c.rect(0, 1068, 1920, 12), self.GRAD)

    def cover(self):
        c = self.on(self.L["cover"])
        tf = c.text(120, 236, 1300, 40)
        c.run(c.para(tf, True), (self.d.get("eyebrow") or "BRIEFING").upper(), self.DISPLAY_M, 24,
              self.C["cyan-on-dark"], spacing=4)
        lines = _split_title(self.d.get("title") or "발표 자료")
        tf = self.title_tf(c)
        # 가장 긴 줄이 1300px 안에 들도록 글자 크기 자동 축소 (한글 1em, 영문·숫자·공백 약 0.55em)
        em = max(sum(1.0 if ord(ch) > 0x2E80 else 0.58 for ch in ln) for ln in lines[:2])
        size = max(60, min(104, int(1260 / max(em, 1))))
        for i, ln in enumerate(lines[:2]):
            p = c.para(tf, i == 0, line=1.16)
            c.run(p, ln, self.DISPLAY, size, self.C["on-dark"] if i == 0 or len(lines) == 1 else None,
                  grad=self.GRAD if (i == 1) else None, spacing=-2)
        if self.d.get("subtitle"):
            tf = c.text(120, 580, 1000, 110)
            c.run(c.para(tf, True, line=1.45), self.d["subtitle"], self.SANS, 34, self.C["subtitle-dark"])
        tf = c.text(120, 740, 200, 52, MSO_ANCHOR.MIDDLE)
        c.run(c.para(tf, True, PP_ALIGN.CENTER), datetime.date.today().strftime("%Y. %m."), self.DISPLAY_M, 24,
              self.C["on-dark"])

    # ---- 목차
    def _lay_contents(self, c):
        self.dark_ground(c, 0.3)
        tf = c.text(120, 200, 740, 120, wrap=False)
        c.run(c.para(tf, True), "CONTENTS", self.DISPLAY, 96, self.C["on-dark"], spacing=-1)
        c.gradient(c.rect(0, 1068, 1920, 12), self.GRAD)

    def contents(self, titles):
        c = self.on(self.L["contents"])
        tf = c.text(120, 330, 680, 120)
        c.run(c.para(tf, True, line=1.4), self.d.get("title", ""), self.SANS, 26, self.C["muted-dark"])
        n = min(len(titles), 6)
        row = min(140, 760 / max(n, 1))
        for i, t in enumerate(titles[:n]):
            y = 180 + i * row
            tf = c.text(900, y + 10, 140, row - 20, MSO_ANCHOR.MIDDLE)
            c.run(c.para(tf, True), ROMAN[i], self.NUM, 80 if row >= 120 else 64, grad=self.GRAD)
            tf = c.text(1060, y + 10, 740, row - 20, MSO_ANCHOR.MIDDLE)
            c.run(c.para(tf, True, line=1.3), t, self.DISPLAY, 40 if len(t) < 22 else 34, self.C["on-dark"])
            if i < n - 1:
                ln = c.rect(900, y + row - 1, 900, 1.5, "#FFFFFF")
                ln.fill.fore_color.brightness = 0
                self._alpha(ln, 0.16)

    def _alpha(self, sp, a):
        sf = sp.fill._xPr.find(qn("a:solidFill"))
        clr = sf[0]
        etree.SubElement(clr, qn("a:alpha"), val=str(int(a * 100000)))

    # ---- 본문
    def _lay_content(self, c, total):
        C = self.C
        c.rect(0, 0, 1920, 1080, C["paper"])
        c.gradient(c.rect(0, 0, 1920, 6), self.GRAD)
        tf = c.text(300, 52, 1476, 34)
        c.run(c.para(tf, True), self.d.get("title", ""), self.SANS_L, 24, C["muted"])
        c.rect(120, 196, 1656, 2, C["hairline"])
        lab = c.rect(120, 264, 230, 88, C["teal"], shape=MSO_SHAPE.SNIP_1_RECTANGLE)
        lab.adjustments[0] = 24 / 88
        tf = c.text(120, 264, 230, 88, MSO_ANCHOR.MIDDLE)
        c.run(c.para(tf, True, PP_ALIGN.CENTER), "KEY POINT", self.SANS_B, 24, C["on-dark"], spacing=1)
        bar = c.rect(358, 264, 1418, 88, shape=MSO_SHAPE.SNIP_1_RECTANGLE)
        bar.adjustments[0] = 24 / 88
        c.flip_v(bar)
        c.gradient(bar, self.GRAD)
        _slide_num(c, 1290, 1006, 200, 40, self.DISPLAY_M, 24, C["ink"], f" / {total}", C["subtle"])
        self.logo(c, "gray", 1776 - 168, 1004, 168)

    def content(self, idx, total, sd, chapter_name, page=None):
        c = self.on(self.L["content"])
        C = self.C
        tf = c.text(120, 52, 170, 110, MSO_ANCHOR.MIDDLE)
        c.run(c.para(tf, True), f"{idx:02d}", self.DISPLAY, 92, grad=self.GRAD, spacing=-3)
        title = sd.get("title", "")
        tf = self.title_tf(c)
        c.run(c.para(tf, True), title, self.DISPLAY, 54 if len(title) <= 30 else 44, C["ink"], spacing=-1)
        tf = c.text(120, 214, 1656, 34)
        c.run(c.para(tf, True), f"{chapter_name} 〉 {title}", self.SANS, 24, C["muted"])
        # KEY POINT
        bullets = list(sd.get("bullets", []))
        kp = sd.get("keypoint") or (bullets.pop(0)[1] if bullets else title)
        tf = c.text(392, 264, 1340, 88, MSO_ANCHOR.MIDDLE)
        c.run(c.para(tf, True), kp, self.SANS, 34 if len(kp) <= 44 else 30, C["on-dark"])
        # 콘텐츠 영역 388–964
        tbl = sd.get("table")
        hint = sd.get("icon", "")
        if sd.get("mindmap"):                               # 마인드맵 장: 편집 가능한 도형으로 그림
            import mindmap
            mindmap.draw_pptx(c.s, c.E(120), c.E(376), c.E(1656), c.E(600), sd["mindmap"], font=self.SANS)
            bullets, tbl = [], None
        one =(_pick_icons([title + " " + kp + " " + " ".join(t for _, t in bullets)], hint) or [None])[0]
        img, cap = sd.get("image"), sd.get("caption")
        if (tbl or img) and bullets:
            self.cards(c, bullets, 120, 388, 680, 576, icon=None)
            vx, vw = 828, 948
        else:
            vx, vw = 120, 1656
        if tbl or img:
            vy, vh = 388, 576
            if cap:
                tf = c.text(vx, vy - 4, vw, 36, MSO_ANCHOR.MIDDLE)
                c.run(c.para(tf, True), cap, self.SANS_B, 22, C["teal"])
                vy, vh = vy + 40, vh - 40
            if img:
                c.rect(vx, vy, vw, vh, C["surface"], C["hairline"], MSO_SHAPE.ROUNDED_RECTANGLE, radius=12, line_w=1.5)
                _figure(c, img, vx + 16, vy + 16, vw - 32, vh - 32)
            else:
                self.table(c, tbl, vx, vy, vw, vh)
        else:
            groups = _groups(bullets)
            if len(groups) >= 2 and sum(1 + len(g[1]) for g in groups) > 4:
                half = (len(groups) + 1) // 2
                a, b = groups[:half], groups[half:]
                ic = _pick_icons([" ".join(g[0] + " " + " ".join(t for _, t in g[1]) for g in part)
                                  for part in (a, b)], hint) or [None, None]
                self.cards(c, [x for g in a for x in [(0, g[0])] + g[1]], 120, 388, 816, 576, icon=ic[0])
                self.cards(c, [x for g in b for x in [(0, g[0])] + g[1]], 960, 388, 816, 576, tint=True, icon=ic[1])
            else:
                self.cards(c, bullets, 120, 388, 1656, 576, icon=one)
        # 바닥글
        if sd.get("source"):
            tf = c.text(120, 1006, 1140, 40, MSO_ANCHOR.MIDDLE)
            c.run(c.para(tf, True), f"자료: {sd['source']}", self.SANS, 24, C["muted"])
        if sd.get("notes"):
            c.s.notes_slide.notes_text_frame.text = sd["notes"]

    def cards(self, c, bullets, x, y, w, h, tint=False, icon=None):
        C = self.C
        if not bullets:
            return
        card = c.rect(x, y, w, h, C["tint-teal"] if tint else C["surface"], C["teal"] if tint else C["hairline"],
                      MSO_SHAPE.ROUNDED_RECTANGLE, radius=12, line_w=2 if tint else 1.5)
        pad_r = 80
        if icon and _icon(c, icon, C["teal"] if tint else C["teal-bright"], x + w - 40 - 64, y + 32, 64):
            pad_r = 80 + 80          # 우상단 단색 선형 아이콘 자리만큼 글상자 폭을 줄임
        tf = c.text(x + 40, y + 32, w - pad_r, h - 64)
        size = _fit_size(bullets, w - pad_r - 20, h - 64, (26, 24, 22, 20, 18))
        for i, (lvl, t) in enumerate(bullets):
            p = c.para(tf, i == 0, line=1.5, after=8)
            if lvl == 0:
                c.bullet(p, "▪", C["teal"] if tint else C["subtle"], 34)
                c.run(p, t, self.SANS_B if len(bullets) > 1 and any(l > 0 for l, _ in bullets) else self.SANS, size,
                      C["ink"] if any(l > 0 for l, _ in bullets) else C["ink-soft"])
            else:
                c.bullet(p, "–", C["subtle"], 30, 34 * lvl)
                c.run(p, t, self.SANS, size - 2, C["ink-soft"])

    def table(self, c, rows, x, y, w, h):
        C = self.C
        nr, nc = len(rows), max(len(r) for r in rows)
        widths = _col_widths(rows, w)
        fs = _table_font(rows, widths, h, (24, 22, 20, 18, 16))
        rh = min(80, max(fs * 1.25 + 16, min(52, h / nr)))
        gf = c.s.shapes.add_table(nr, nc, c.E(x), c.E(y), c.E(w), c.E(rh * nr))
        _plain_table_style(gf)
        t = gf.table
        for ci, cw in enumerate(widths):
            t.columns[ci].width = c.E(cw)
        for ri in range(nr):
            t.rows[ri].height = c.E(rh)
            for ci in range(nc):
                cell = t.cell(ri, ci)
                cell.margin_left = cell.margin_right = c.E(20)
                cell.margin_top = cell.margin_bottom = c.E(8)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(C["teal"] if ri == 0 else (C["row-alt"] if ri % 2 == 0 else C["surface"]))
                tf = cell.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                txt = rows[ri][ci] if ci < len(rows[ri]) else ""
                cell.margin_left = cell.margin_right = c.E(14 if fs < 22 else 20)
                if ri == 0:
                    c.run(p, txt, self.SANS_B, fs, C["on-dark"], spacing=1)
                    _cell_border(cell, "B", C["brand-cyan"], c.E(4))
                else:
                    c.run(p, txt, self.SANS_B if ci == 0 else self.SANS, fs, C["teal"] if ci == 0 else C["ink-soft"])
                    _cell_border(cell, "B", C["hairline"], c.E(1.5))
                for sd_ in ("L", "R", "T"):
                    _cell_border(cell, sd_, None, 0)

    # ---- 마무리
    def _lay_closing(self, c):
        self.dark_ground(c, 0.38)
        tf = c.text(120, 300, 1600, 190)
        c.run(c.para(tf, True), "THANK YOU", self.DISPLAY, 168, grad=self.GRAD, spacing=-4)
        tf = c.text(120, 500, 1600, 110)
        c.run(c.para(tf, True), "감사합니다.", self.DISPLAY, 80, self.C["on-dark"], spacing=-2)
        r = c.rect(120, 760, 760, 2, "#FFFFFF")
        self._alpha(r, 0.2)
        self.logo(c, "white", 120, 940, 240)
        c.gradient(c.rect(0, 1068, 1920, 12), self.GRAD)

    def closing(self):
        c = self.on(self.L["closing"])
        tf = c.text(120, 784, 1000, 90)
        c.run(c.para(tf, True, line=1.5), "문의 · [부서명] [담당자명]", self.SANS, 24, self.C["muted-dark"])
        c.run(c.para(tf, line=1.5), "[이메일] · [전화번호]", self.SANS, 24, self.C["muted-dark"])

    def layouts(self, total):
        C = self.C
        self.L = {
            "cover": self.make_layout(0, "모던 · 표지", self._lay_cover,
                                      dict(x=120, y=300, w=1300, h=260, anchor="t", font=self.DISPLAY, size_px=96,
                                           color=C["on-dark"])),
            "contents": self.make_layout(1, "모던 · 목차", self._lay_contents),
            "content": self.make_layout(2, "모던 · 본문", lambda c: self._lay_content(c, total),
                                        dict(x=300, y=88, w=1476, h=72, anchor="ctr", font=self.DISPLAY, size_px=54,
                                             color=C["ink"])),
            "closing": self.make_layout(3, "모던 · 마무리", self._lay_closing)}
        self.drop_unused_layouts(list(self.L.values()))

    def build(self):
        slides = self.d.get("slides", [])
        has_toc = len(slides) >= 3
        self.layouts(len(slides) + (2 if has_toc else 1) + 1)
        self.cover()
        chapters = [ch for ch in (self.d.get("chapters") or []) if any(s.get("chapter") == ch for s in slides)]
        short = {ch: re.sub(r"^제\s*\d+\s*장\s*", "", ch) for ch in chapters}
        if has_toc:
            self.contents([short[ch] for ch in chapters] if chapters else [s.get("title", "") for s in slides])
        chap = self.d.get("title", "")
        chap = chap if len(chap) <= 24 else chap[:23] + "…"
        off = 2 if has_toc else 1
        total = len(slides) + off + 1
        for i, sd in enumerate(slides, 1):
            if sd.get("chapter") in short:                          # 원 소스 보고서 기반: 장별 위치 표시
                k = chapters.index(sd["chapter"])
                nm = short[sd["chapter"]]
                crumb = f"{ROMAN[k % 10]}. {nm if len(nm) <= 30 else nm[:29] + '…'}"
            else:
                crumb = f"{ROMAN[0]}. {chap}"
            self.content(i, total, sd, crumb, page=i + off)
        self.closing()
        out = io.BytesIO()
        self.prs.save(out)
        return out.getvalue()


# ======================================================================= 블루 (960×540)
class Blue(_Layouts):
    K, F = 12700, 1.0
    FONT = "Noto Sans KR"
    C = {"surface": "#F7FAFC", "surface-raised": "#FCFCFC", "surface-tint": "#E4F5FD", "surface-stripe": "#EFF8FC",
         "line": "#D1DBE3", "ink": "#081C39", "ink-body": "#27334A", "ink-muted": "#71767E", "accent-ink": "#166FB3",
         "brand-blue": "#1272C9", "brand-cyan": "#01BBED", "brand-navy": "#122D4F", "blue-deep": "#174273",
         "slate": "#778798", "on-brand": "#FFFFFF", "on-light": "#081C39", "cover-ground": "#091935",
         "on-dark-muted": "#BED2E2", "logo-band": "#F7FAFC", "band-ink": "#5A6577"}
    A = os.path.join(ASSET, "blue")

    def __init__(self, data):
        self.d = data
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Emu(960 * self.K), Emu(540 * self.K)

    def cv(self):
        return Canvas(self.prs, _blank(self.prs), self.K, self.F)

    def logo(self, c, x_right, y, h):
        p = os.path.join(self.A, "logo.png")
        if os.path.exists(p):
            from PIL import Image
            iw, ih = Image.open(p).size
            w = h * iw / ih
            c.picture(p, x_right - w, y, w, h)

    def _lay_cover(self, c):
        C = self.C
        c.rect(0, 0, 960, 540, C["cover-ground"])
        glow = c.rect(560, 250, 520, 360, shape=MSO_SHAPE.OVAL)      # 표지 우하단 시안 번짐 (허용된 유일한 그라데이션)
        glow.fill.gradient()
        glow.fill.gradient_angle = 0
        gs = glow.fill._xPr.find(qn("a:gradFill"))
        gs.find(qn("a:lin")) is not None and gs.remove(gs.find(qn("a:lin")))
        gl = gs.find(qn("a:gsLst"))
        for g in list(gl):
            gl.remove(g)
        for pos, a in ((0, 0.35), (1, 0.0)):
            g = etree.SubElement(gl, qn("a:gs"), pos=str(int(pos * 100000)))
            clr = etree.SubElement(g, qn("a:srgbClr"), val="01BBED")
            etree.SubElement(clr, qn("a:alpha"), val=str(int(a * 100000)))
        path = etree.SubElement(gs, qn("a:path"), path="circle")
        etree.SubElement(path, qn("a:fillToRect"), l="50000", t="50000", r="50000", b="50000")
        c.rect(40, 150, 6, 150, C["brand-cyan"])
        c.rect(64, 322, 120, 4, C["brand-cyan"])
        c.rect(0, 476, 960, 64, C["logo-band"])
        self.logo(c, 920, 494, 28)

    def cover(self):
        c = self.on(self.L["cover"])
        C = self.C
        tf = self.title_tf(c)
        c.run(c.para(tf, True, line=1.45), self.d.get("title") or "발표 자료", self.FONT, 38, "#FFFFFF", bold=True)
        if self.d.get("subtitle"):
            tf = c.text(64, 340, 760, 60)
            c.run(c.para(tf, True, line=1.4), self.d["subtitle"], self.FONT, 16, C["on-dark-muted"])
        tf = c.text(40, 476, 600, 64, MSO_ANCHOR.MIDDLE)
        c.run(c.para(tf, True), datetime.date.today().strftime("%Y. %m.") + " · 보고", self.FONT, 10, C["band-ink"])

    def _lay_content(self, c):
        C = self.C
        c.rect(0, 0, 960, 540, C["surface"])
        c.rect(40, 21, 880, 5, C["brand-blue"])
        _slide_num(c, 700, 506, 66, 20, self.FONT, 10, C["ink-muted"])
        self.logo(c, 920, 503, 24)

    def content(self, idx, total, sd):
        c = self.on(self.L["content"])
        C = self.C
        tf = self.title_tf(c)
        title = sd.get("title", "")
        c.run(c.para(tf, True), title, self.FONT, 28 if len(title) <= 34 else 23, C["ink"], bold=True)
        bullets = list(sd.get("bullets", []))
        tbl = sd.get("table")
        top, bottom = 104, 488
        callout = sd.get("keypoint")
        if callout:
            bottom -= 58
        if sd.get("mindmap"):                               # 마인드맵 장: 편집 가능한 도형으로 그림
            import mindmap
            mindmap.draw_pptx(c.s, c.E(40), c.E(top), c.E(880), c.E(bottom - top), sd["mindmap"], font=self.FONT)
        elif tbl or sd.get("image"):
            vx, vw = (386, 534) if bullets else (40, 880)
            if bullets:
                self.cards(c, _groups(bullets)[:3], 40, top, 330, bottom - top, cols=1)
            vy = top
            if sd.get("caption"):
                tf = c.text(vx, vy - 2, vw, 20, MSO_ANCHOR.MIDDLE)
                c.run(c.para(tf, True), sd["caption"], self.FONT, 11, C["accent-ink"], bold=True)
                vy += 22
            if sd.get("image"):
                c.rect(vx, vy, vw, bottom - vy, C["surface-raised"], C["line"], MSO_SHAPE.ROUNDED_RECTANGLE, radius=8)
                _figure(c, sd["image"], vx + 8, vy + 8, vw - 16, bottom - vy - 16)
            else:
                self.table(c, tbl, vx, vy, vw, bottom - vy)
        else:
            self.cards(c, _groups(bullets)[:6], 40, top, 880, bottom - top, cols=2)
        if callout:
            box = c.rect(40, bottom + 10, 880, 46, C["surface-tint"], shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=8)
            tf = c.text(56, bottom + 10, 848, 46, MSO_ANCHOR.MIDDLE)
            c.run(c.para(tf, True), callout, self.FONT, 19 if len(callout) <= 48 else 16, C["accent-ink"], bold=True)
        tf = c.text(40, 506, 700, 20, MSO_ANCHOR.MIDDLE)
        c.run(c.para(tf, True), f"출처: {sd['source']}" if sd.get("source") else "", self.FONT, 10, C["ink-muted"])
        if sd.get("notes"):
            c.s.notes_slide.notes_text_frame.text = sd["notes"]

    def cards(self, c, groups, x, y, w, h, cols=2):
        C = self.C
        if not groups:
            return
        rows = (len(groups) + cols - 1) // cols
        gap = 16
        icons = _pick_icons([hd + " " + " ".join(t for _, t in kd) for hd, kd in groups])
        cw = (w - gap * (cols - 1)) / cols
        ch = (h - gap * (rows - 1)) / rows
        for i, (head, kids) in enumerate(groups):
            cx, cy = x + (i % cols) * (cw + gap), y + (i // cols) * (ch + gap)
            card = c.rect(cx, cy, cw, ch, C["surface-raised"], shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=8)
            c.shadow(card, 8, 2, 0.08)
            # 아이콘: 브랜드 시안 원 + 진한 남색 선형 글리프 (못 찾으면 번호 배지)
            circ = c.rect(cx + 14, cy + 13, 30, 30, C["brand-cyan"], shape=MSO_SHAPE.OVAL)
            if not (icons and _icon(c, icons[i], C["on-light"], cx + 20, cy + 19, 18)):
                circ.fill.fore_color.rgb = rgb(C["brand-blue"])
                tf = c.text(cx + 14, cy + 13, 30, 30, MSO_ANCHOR.MIDDLE)
                c.run(c.para(tf, True, PP_ALIGN.CENTER), str(i + 1), self.FONT, 12, "#FFFFFF", bold=True)
            tf = c.text(cx + 54, cy + 14, cw - 70, 30, MSO_ANCHOR.MIDDLE)
            c.run(c.para(tf, True, line=1.3), head, self.FONT, 17 if len(head) <= 26 else 15, C["ink"], bold=True)
            if kids:
                tf = c.text(cx + 16, cy + 52, cw - 32, ch - 64)
                for j, (lvl, t) in enumerate(kids):
                    p = c.para(tf, j == 0, line=1.5, after=3)
                    c.bullet(p, "·", C["brand-blue"], 12, 12 * (lvl - 1))
                    c.run(p, t, self.FONT, max(10, min(14 if len(kids) <= 4 else 12.5, (ch - 60) / (len(kids) * 1.7))), C["ink-body"])

    def table(self, c, rows, x, y, w, h):
        C = self.C
        nr, nc = len(rows), max(len(r) for r in rows)
        widths = _col_widths(rows, w)
        fs = _table_font(rows, widths, h, (12, 11, 10, 9), pad=20, vpad=8)
        rh = min(34, max(fs * 1.25 + 8, min(24, h / nr)))
        gf = c.s.shapes.add_table(nr, nc, c.E(x), c.E(y), c.E(w), c.E(rh * nr))
        _plain_table_style(gf)
        t = gf.table
        for ci, cw in enumerate(widths):
            t.columns[ci].width = c.E(cw)
        heads = [C["brand-navy"]] + [C["brand-blue"]] * (nc - 1)
        for ri in range(nr):
            t.rows[ri].height = c.E(rh)
            for ci in range(nc):
                cell = t.cell(ri, ci)
                cell.margin_left = cell.margin_right = c.E(10)
                cell.margin_top = cell.margin_bottom = c.E(4)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(heads[ci] if ri == 0 else (C["surface-stripe"] if ri % 2 == 0 else C["surface-raised"]))
                txt = rows[ri][ci] if ci < len(rows[ri]) else ""
                p = cell.text_frame.paragraphs[0]
                cell.text_frame.word_wrap = True
                if ri == 0:
                    c.run(p, txt, self.FONT, fs, "#FFFFFF", bold=True)
                else:
                    c.run(p, txt, self.FONT, fs, C["ink"] if ci == 0 else C["ink-body"], bold=(ci == 0))
                _cell_border(cell, "B", C["line"], c.E(1))
                for sd_ in ("L", "R", "T"):
                    _cell_border(cell, sd_, None, 0)

    def _lay_closing(self, c):
        C = self.C
        c.rect(0, 0, 960, 540, C["cover-ground"])
        c.rect(40, 180, 6, 110, C["brand-cyan"])
        tf = c.text(64, 170, 760, 70, MSO_ANCHOR.MIDDLE)
        c.run(c.para(tf, True), "감사합니다.", self.FONT, 38, "#FFFFFF", bold=True)
        c.rect(0, 476, 960, 64, C["logo-band"])
        self.logo(c, 920, 494, 28)

    def closing(self):
        c = self.on(self.L["closing"])
        tf = c.text(64, 244, 760, 50)
        c.run(c.para(tf, True, line=1.5), "문의 · [부서명] [담당자명] · [이메일]", self.FONT, 14, self.C["on-dark-muted"])

    def build(self):
        slides = self.d.get("slides", [])
        C = self.C
        self.L = {
            "cover": self.make_layout(0, "블루 · 표지", self._lay_cover,
                                      dict(x=64, y=140, w=760, h=170, anchor="t", font=self.FONT, size_px=38,
                                           color="#FFFFFF", bold=True)),
            "content": self.make_layout(1, "블루 · 본문", self._lay_content,
                                        dict(x=40, y=40, w=880, h=48, anchor="ctr", font=self.FONT, size_px=28,
                                             color=C["ink"], bold=True)),
            "closing": self.make_layout(2, "블루 · 마무리", self._lay_closing)}
        self.drop_unused_layouts(list(self.L.values()))
        self.cover()
        for i, sd in enumerate(slides, 1):
            self.content(i, len(slides) + 2, sd)
        self.closing()
        out = io.BytesIO()
        self.prs.save(out)
        return out.getvalue()


def render(theme: str, data: dict) -> bytes:
    return {"modern": Modern, "blue": Blue}.get(theme, Modern)(data).build()
