"""HWPX 생성기 — 한컴오피스가 직접 저장한 빈 문서(assets/base.hwpx)를 바탕으로
글자/문단/테두리 모양을 '복제·수정'해 추가하므로 한컴 규격과 어긋나지 않는다.
제목, 개조식(□ ㅇ - ※), 표, 그림(BinData)을 지원한다."""
import copy
import io
import threading
import os
import struct
import zipfile
from xml.sax.saxutils import escape

from lxml import etree

from md_parser import parse_blocks

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "base.hwpx")
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"
Q = lambda ns, t: f"{{{ns}}}{t}"
NS = ('xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
      'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"')
SYM = {"box": "□ ", "circle": "ㅇ ", "dash": "- ", "note": "※ "}

_pid = [100]                         # template_injector 가 양식의 기존 번호와 겹치지 않게 시작값을 직접 맞춤(_pid[0] = 900000)
_pid_lock = threading.Lock()         # 여러 사용자가 동시에 문서를 만들어도 번호가 겹치지 않게


def _nid():
    with _pid_lock:
        _pid[0] += 1
        return _pid[0]


# ------------------------------------------------------------------ XML 조각 (템플릿 주입기와 공용)
def para_xml(text: str, para_id: int, char_id: int) -> str:
    return (f'<hp:p id="{_nid()}" paraPrIDRef="{para_id}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{char_id}"><hp:t>{escape(text)}</hp:t></hp:run></hp:p>')


def col_widths(rows, total_w):
    """열 너비를 내용 길이에 비례해 배분 (짧은 열은 최소 폭 보장, 긴 열이 독식하지 않게 제곱근 가중)."""
    ncol = max(len(r) for r in rows)
    lens = []
    for c in range(ncol):
        L = [len(r[c]) if c < len(r) else 0 for r in rows]
        lens.append(max(3.0, (sum(L) / len(L) + max(L)) / 2) ** 0.75)
    tot = sum(lens)
    frac = [max(l / tot, 0.11) for l in lens]       # 최소 11% 보장 후 다시 합계 100%로 정규화
    s = sum(frac)
    w = [int(total_w * f / s) for f in frac]
    w[-1] += total_w - sum(w)
    return w


def table_xml(rows, para_id, head_char, body_char, bf_head, bf_body, total_w, bf_table=None) -> str:
    ncol = max(len(r) for r in rows)
    widths = col_widths(rows, total_w)
    cw = total_w // ncol
    rh = 1600
    out = (f'<hp:p id="{_nid()}" paraPrIDRef="{para_id}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
           f'<hp:run charPrIDRef="{body_char}"><hp:tbl id="{_nid()}" zOrder="0" numberingType="TABLE" '
           f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" '
           f'repeatHeader="1" rowCnt="{len(rows)}" colCnt="{ncol}" cellSpacing="0" '
           f'borderFillIDRef="{bf_table or bf_body}" noAdjust="0">'
           f'<hp:sz width="{sum(widths)}" widthRelTo="ABSOLUTE" height="{rh * len(rows)}" heightRelTo="ABSOLUTE" protect="0"/>'
           f'<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
           f'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           f'<hp:outMargin left="283" right="283" top="283" bottom="283"/>'
           f'<hp:inMargin left="141" right="141" top="141" bottom="141"/>')
    for ri, row in enumerate(rows):
        out += "<hp:tr>"
        for ci in range(ncol):
            txt = row[ci] if ci < len(row) else ""
            out += (f'<hp:tc name="" header="{1 if ri == 0 else 0}" hasMargin="0" protect="0" editable="0" dirty="0" '
                    f'borderFillIDRef="{bf_head if ri == 0 else bf_body}">'
                    f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
                    f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                    f'{para_xml(txt, para_id, head_char if ri == 0 else body_char)}</hp:subList>'
                    f'<hp:cellAddr colAddr="{ci}" rowAddr="{ri}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                    f'<hp:cellSz width="{widths[ci]}" height="{rh}"/>'
                    f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>')
        out += "</hp:tr>"
    return out + "</hp:tbl></hp:run></hp:p>"


def image_size(data: bytes):
    """PNG/JPEG 픽셀 크기."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    try:
        from PIL import Image
        return Image.open(io.BytesIO(data)).size
    except Exception:
        return (800, 600)


def pic_xml(item_id: str, data: bytes, para_id: int, char_id: int, max_w: int, max_h: int = 52000) -> str:
    """본문에 '글자처럼 취급'되는 그림 문단. 크기는 HWPUNIT(1px@96dpi = 75)."""
    return (f'<hp:p id="{_nid()}" paraPrIDRef="{para_id}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            + pic_run(item_id, data, char_id, max_w, max_h) + '</hp:p>')


def icon_heading_xml(item_id: str, data: bytes, text: str, para_id: int, char_id: int, size: int = 1200) -> str:
    """'아이콘 + 제목' 한 문단 (아이콘은 글자처럼 취급, 기본 약 4.2mm)."""
    return (f'<hp:p id="{_nid()}" paraPrIDRef="{para_id}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            + pic_run(item_id, data, char_id, size, size)
            + f'<hp:run charPrIDRef="{char_id}"><hp:t> {escape(text)}</hp:t></hp:run></hp:p>')


def pic_run(item_id: str, data: bytes, char_id: int, max_w: int, max_h: int = 52000) -> str:
    pw, ph = image_size(data)
    ow, oh = pw * 75, ph * 75
    scale = min(1.0, max_w / ow, max_h / oh)
    cw, ch = max(int(ow * scale), 1), max(int(oh * scale), 1)
    sx, sy = cw / ow, ch / oh
    i = _nid()
    return (f'<hp:run charPrIDRef="{char_id}"><hp:pic id="{i}" zOrder="{i % 1000}" numberingType="PICTURE" '
            f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" '
            f'instid="{i + 7}" reverse="0">'
            f'<hp:offset x="0" y="0"/><hp:orgSz width="{ow}" height="{oh}"/><hp:curSz width="{cw}" height="{ch}"/>'
            f'<hp:flip horizontal="0" vertical="0"/><hp:rotationInfo angle="0" centerX="{cw // 2}" centerY="{ch // 2}" rotateimage="1"/>'
            f'<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            f'<hc:scaMatrix e1="{sx:.6f}" e2="0" e3="0" e4="0" e5="{sy:.6f}" e6="0"/>'
            f'<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
            f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{ow}" y="0"/><hc:pt2 x="{ow}" y="{oh}"/><hc:pt3 x="0" y="{oh}"/></hp:imgRect>'
            f'<hp:imgClip left="0" right="{ow}" top="0" bottom="{oh}"/>'
            f'<hp:inMargin left="0" right="0" top="0" bottom="0"/><hp:imgDim dimwidth="{ow}" dimheight="{oh}"/>'
            f'<hc:img binaryItemIDRef="{item_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/><hp:effects/>'
            f'<hp:sz width="{cw}" widthRelTo="ABSOLUTE" height="{ch}" heightRelTo="ABSOLUTE" protect="0"/>'
            f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            f'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            f'<hp:outMargin left="0" right="0" top="0" bottom="0"/></hp:pic></hp:run>')


def frag(xml: str):
    return list(etree.fromstring(f"<r {NS}>{xml}</r>"))


def add_binaries(files: dict, images: list):
    """images: [(item_id, bytes)] → BinData/ 저장 + content.hpf manifest 등록."""
    if not images:
        return
    hpf = etree.fromstring(files["Contents/content.hpf"])
    man = hpf.find(".//" + Q(OPF, "manifest"))
    for item_id, data in images:
        ext = "png" if data[:4] == b"\x89PNG" else "jpg"
        href = f"BinData/{item_id}.{ext}"
        files[href] = data
        el = etree.SubElement(man, Q(OPF, "item"))
        el.set("id", item_id)
        el.set("href", href)
        el.set("media-type", f"image/{ext}")
        el.set("isEmbeded", "1")
    files["Contents/content.hpf"] = etree.tostring(hpf, xml_declaration=True, encoding="UTF-8", standalone=True)


def write_zip(order: list, files: dict) -> bytes:
    out = io.BytesIO()
    names = list(order) + [n for n in files if n not in order]
    with zipfile.ZipFile(out, "w") as z:
        for n in names:
            ct = zipfile.ZIP_STORED if n == "mimetype" or n.startswith("BinData/") else zipfile.ZIP_DEFLATED
            z.writestr(zipfile.ZipInfo(n, date_time=(2026, 1, 1, 0, 0, 0)), files[n], compress_type=ct)
    return out.getvalue()


# ------------------------------------------------------------------ 스타일 북 (header.xml 복제 편집)
class StyleBook:
    def __init__(self, hdr_root):
        self.h = hdr_root
        self.font = self._ensure_font("맑은 고딕")

    def _ensure_font(self, face):
        ids = None
        for ff in self.h.iter(Q(HH, "fontface")):
            fonts = ff.findall(Q(HH, "font"))
            for f in fonts:
                if f.get("face") == face:
                    ids = f.get("id")
                    break
            else:
                new = copy.deepcopy(fonts[0])
                for ch in list(new):
                    new.remove(ch)
                nid = str(max(int(f.get("id")) for f in fonts) + 1)
                new.set("id", nid)
                new.set("face", face)
                new.set("type", "TTF")
                ff.append(new)
                ff.set("fontCnt", str(len(ff.findall(Q(HH, "font")))))
                ids = nid
        return ids or "0"

    def _next_id(self, parent, tag):
        return str(max(int(e.get("id")) for e in parent.findall(Q(HH, tag))) + 1)

    def char(self, size_pt, bold=False, color="#000000"):
        cont = self.h.find(".//" + Q(HH, "charProperties"))
        src = cont.find(Q(HH, "charPr"))
        e = copy.deepcopy(src)
        e.set("id", self._next_id(cont, "charPr"))
        e.set("height", str(int(size_pt * 100)))
        e.set("textColor", color)
        fr = e.find(Q(HH, "fontRef"))
        for k in fr.attrib:
            fr.set(k, self.font)
        for b in e.findall(Q(HH, "bold")):
            e.remove(b)
        if bold:
            off = e.find(Q(HH, "offset"))
            off.addnext(etree.Element(Q(HH, "bold")))
        cont.append(e)
        cont.set("itemCnt", str(len(cont.findall(Q(HH, "charPr")))))
        return int(e.get("id"))

    def para(self, align="JUSTIFY", left=0, intent=0, prev=0, nxt=0, line=160, keep_next=False):
        cont = self.h.find(".//" + Q(HH, "paraProperties"))
        src = cont.find(Q(HH, "paraPr"))
        e = copy.deepcopy(src)
        e.set("id", self._next_id(cont, "paraPr"))
        e.find(Q(HH, "align")).set("horizontal", align)
        bs = e.find(Q(HH, "breakSetting"))
        if bs is not None:
            bs.set("keepWithNext", "1" if keep_next else "0")      # 제목이 쪽 끝에 홀로 남지 않게
        vals = {"intent": intent, "left": left, "right": 0, "prev": prev, "next": nxt}
        for el in e.iter():
            ln = etree.QName(el).localname
            if ln in vals and el.getparent() is not None and etree.QName(el.getparent()).localname == "margin":
                el.set("value", str(vals[ln]))
            elif ln == "lineSpacing":
                el.set("value", str(line))
        cont.append(e)
        cont.set("itemCnt", str(len(cont.findall(Q(HH, "paraPr")))))
        return int(e.get("id"))

    def border(self, solid=True, fill=None):
        cont = self.h.find(".//" + Q(HH, "borderFills"))
        src = cont.findall(Q(HH, "borderFill"))[-1]
        e = copy.deepcopy(src)
        e.set("id", self._next_id(cont, "borderFill"))
        for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
            b = e.find(Q(HH, side))
            b.set("type", "SOLID" if solid else "NONE")
            b.set("width", "0.12 mm")
            b.set("color", "#000000")
        wb = e.find(".//" + Q(HC, "winBrush"))
        if wb is None:
            fb = etree.SubElement(e, Q(HC, "fillBrush"))
            wb = etree.SubElement(fb, Q(HC, "winBrush"))
            wb.set("hatchColor", "#999999")
            wb.set("alpha", "0")
        wb.set("faceColor", fill or "none")
        cont.append(e)
        cont.set("itemCnt", str(len(cont.findall(Q(HH, "borderFill")))))
        return int(e.get("id"))


def standard_ids(sb: StyleBook) -> dict:
    """기본 보고서 스타일(맑은 고딕) 일괄 등록."""
    C = {"body": sb.char(10.5), "title": sb.char(17, True, "#1F3864"), "h2": sb.char(13, True, "#1F3864"),
         "h3": sb.char(11.5, True), "box": sb.char(11.5, True), "th": sb.char(10, True), "cell": sb.char(10),
         "caption": sb.char(10, True, "#1F3864"), "small": sb.char(9, False, "#595959")}
    P = {"body": sb.para("JUSTIFY", 0, 0, 0, 200), "title": sb.para("CENTER", 0, 0, 0, 900, keep_next=True),
         "h2": sb.para("LEFT", 0, 0, 1000, 300, keep_next=True), "h3": sb.para("LEFT", 0, 0, 600, 200, keep_next=True),
         "pic": sb.para("CENTER", 0, 0, 300, 60, 100, keep_next=True),
         "box": sb.para("JUSTIFY", 1700, -1700, 500, 150), "circle": sb.para("JUSTIFY", 2900, -1200, 100, 100),
         "dash": sb.para("JUSTIFY", 3900, -1000, 0, 80), "note": sb.para("JUSTIFY", 3900, -1100, 0, 80),
         "cell": sb.para("LEFT", 0, 0, 0, 0, 130), "center": sb.para("CENTER", 0, 0, 300, 100, 130)}
    return {"char": C, "para": P, "bf_head": sb.border(True, "#D9E2F3"), "bf_body": sb.border(True)}


def _heading_icon(text, used):
    """소제목 아이콘 PNG bytes (설정에서 꺼져 있거나 못 찾으면 None)."""
    try:
        import icon_library as il
        p = il.heading_icon(text, "#1F3864", used)
        return open(p, "rb").read() if p else None
    except Exception:
        return None


def blocks_to_xml(blocks, ids, text_w, images=None, img_list=None) -> str:
    """블록 → section 본문 XML. images: {key: bytes}, img_list: 등록할 (item_id, bytes) 누적 리스트."""
    P = lambda k: ids["para"].get(k, ids["para"].get("body", 0))
    C = lambda k: ids["char"].get(k, ids["char"].get("body", 0))
    out, used = [], []
    for b in blocks:
        kind = b[0]
        if kind == "h":
            k = {1: "title", 2: "h2"}.get(b[1], "h3")
            ic = _heading_icon(b[2], used) if (k == "h2" and img_list is not None) else None
            if ic:
                item_id = f"image{len(img_list) + 1}"
                img_list.append((item_id, ic))
                out.append(icon_heading_xml(item_id, ic, b[2], P(k), C(k)))
            else:
                out.append(para_xml(b[2], P(k), C(k)))
        elif kind == "sym":
            out.append(para_xml(SYM[b[1]] + b[2], P(b[1]), C("box") if b[1] == "box" else C("body")))
        elif kind == "p":
            out.append(para_xml(b[1], P("body"), C("body")))
        elif kind == "table":
            out.append(table_xml(b[1], P("cell"), C("th"), C("cell"), ids.get("bf_head", 1), ids.get("bf_body", 1),
                                 int(text_w * 0.98)))
            out.append(para_xml("", P("body"), C("body")))
        elif kind == "img":
            data = (images or {}).get(b[1])
            if data is None:
                continue
            item_id = f"image{len(img_list) + 1}"
            img_list.append((item_id, data))
            out.append(pic_xml(item_id, data, ids["para"].get("pic", P("center")), C("body"), int(text_w * 0.95)))
            if b[2]:
                out.append(para_xml(b[2], P("center"), C("caption")))
    return "".join(out)


def _text_width(sec) -> int:
    pp = sec.find(".//" + Q(HP, "pagePr"))
    m = pp.find(Q(HP, "margin"))
    return int(pp.get("width")) - int(m.get("left")) - int(m.get("right"))


def markdown_to_hwpx(md: str, title: str = "문서", images: dict = None) -> bytes:
    with zipfile.ZipFile(BASE) as z:
        order = z.namelist()
        files = {n: z.read(n) for n in order}
    hdr = etree.fromstring(files["Contents/header.xml"])
    sec = etree.fromstring(files["Contents/section0.xml"])
    ids = standard_ids(StyleBook(hdr))
    img_list = []
    body = blocks_to_xml(parse_blocks(md), ids, _text_width(sec), images, img_list)
    for n in frag(body):
        sec.append(n)
    files["Contents/header.xml"] = etree.tostring(hdr, xml_declaration=True, encoding="UTF-8", standalone=True)
    files["Contents/section0.xml"] = etree.tostring(sec, xml_declaration=True, encoding="UTF-8", standalone=True)
    add_binaries(files, img_list)
    return write_zip(order, files)
