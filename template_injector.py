"""내 업무용 HWPX 양식 / PPTX 템플릿 서식 100% 상속 주입 엔진."""
import io
import os
import re
import zipfile
from collections import Counter

from lxml import etree

import hwpx_builder as hb
from md_parser import parse_blocks, parse_slides, SYM_CHAR

BASE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(BASE, "templates")
HWPX_DIR = os.path.join(TPL_DIR, "hwpx")
PPTX_DIR = os.path.join(TPL_DIR, "pptx")
for _d in (HWPX_DIR, PPTX_DIR):
    os.makedirs(_d, exist_ok=True)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
Q = lambda ns, t: f"{{{ns}}}{t}"


def list_templates(kind: str):
    d = HWPX_DIR if kind == "hwpx" else PPTX_DIR
    exts = (".hwpx",) if kind == "hwpx" else (".pptx", ".pdf")   # 슬라이드 템플릿은 PPTX 또는 PDF
    return sorted(f for f in os.listdir(d) if f.lower().endswith(exts))


def save_template(kind: str, name: str, data: bytes) -> str:
    d = HWPX_DIR if kind == "hwpx" else PPTX_DIR
    path = os.path.join(d, os.path.basename(name))
    with open(path, "wb") as f:
        f.write(data)
    return path


# ===================================================================== HWPX
def _ptext(p) -> str:
    return "".join(t.text or "" for t in p.iter(Q(HP, "t")))


def _first_ids(p):
    run = p.find(Q(HP, "run"))
    for r in p.iter(Q(HP, "run")):
        if r.find(Q(HP, "t")) is not None:
            run = r
            break
    return p.get("paraPrIDRef", "0"), (run.get("charPrIDRef", "0") if run is not None else "0")


def _merge_placeholders(root):
    """{{...}} 가 여러 run 으로 쪼개진 문단을 첫 run 의 t 로 병합."""
    n = 0
    for p in root.iter(Q(HP, "p")):
        full = _ptext(p)
        if "{{" in full and "}}" in full:
            ts = [t for t in p.iter(Q(HP, "t"))]
            if len(ts) > 1:
                ts[0].text = full
                for t in ts[1:]:
                    t.text = ""
                n += 1
    return n


def _char_heights(header_root):
    h = {}
    for c in header_root.iter(Q(HH, "charPr")):
        h[c.get("id")] = int(c.get("height", "1000"))
    return h


def _top_paras(sec):
    return [p for p in sec if p.tag == Q(HP, "p")]


def analyze_hwpx_bytes(data: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(data))
    sec = etree.fromstring(z.read("Contents/section0.xml"))
    hdr = etree.fromstring(z.read("Contents/header.xml"))
    return _analyze(sec, hdr)


def _analyze(sec, hdr) -> dict:
    heights = _char_heights(hdr)
    tops = _top_paras(sec)
    info = {"placeholders": sorted(set(re.findall(r"\{\{([^{}]+)\}\}", "".join(_ptext(p) for p in tops) +
                                                  "".join(t.text or "" for t in sec.iter(Q(HP, "t")))))),
            "para": {}, "char": {}}
    kinds = {}
    body_ids = Counter()
    first_tbl_idx = None
    for i, p in enumerate(tops):
        if first_tbl_idx is None and any(True for _ in p.iter(Q(HP, "tbl"))):
            first_tbl_idx = i
        if any(True for _ in p.iter(Q(HP, "tbl"))) or p.find(".//" + Q(HP, "secPr")) is not None:
            continue
        txt = _ptext(p).strip()
        if not txt:
            continue
        ids = _first_ids(p)
        body_ids[ids] += 1
        c0 = txt[0]
        k = {"□": "box", "ㅇ": "circle", "○": "circle", "-": "dash", "※": "note", "•": "dash"}.get(c0)
        if k and k not in kinds:
            kinds[k] = ids
    # 제목
    title_ids = None
    for p in tops:
        if "{{제목}}" in _ptext(p):
            title_ids = _first_ids(p)
            break
    if title_ids is None:
        best, bh = None, -1
        for p in tops:
            if any(True for _ in p.iter(Q(HP, "tbl"))) or not _ptext(p).strip():
                continue
            ids = _first_ids(p)
            if heights.get(ids[1], 0) > bh:
                best, bh = ids, heights.get(ids[1], 0)
        title_ids = best
    common = body_ids.most_common(1)[0][0] if body_ids else ("0", "0")
    order = ["box", "circle", "dash", "note"]
    for i, k in enumerate(order):
        if k not in kinds:
            # 가장 가까운 상위 위계로 대체
            for kk in reversed(order[:i]):
                if kk in kinds:
                    kinds[k] = kinds[kk]
                    break
            else:
                kinds[k] = common
    kinds["body"] = common
    kinds["title"] = title_ids or common
    kinds["h2"] = kinds["box"]
    kinds["h3"] = kinds["circle"]
    for k, (pp, cc) in kinds.items():
        info["para"][k], info["char"][k] = pp, cc
    info["style_count"] = len({v for v in kinds.values()})
    info["has_header_table"] = first_tbl_idx is not None and first_tbl_idx < 6
    # 표 서식
    bf_head = bf_body = None
    cell_ids = None
    for tbl in sec.iter(Q(HP, "tbl")):
        rows = tbl.findall(Q(HP, "tr"))
        if len(rows) >= 2:
            tc0 = rows[0].find(Q(HP, "tc"))
            tc1 = rows[1].find(Q(HP, "tc"))
            if tc0 is not None and tc1 is not None:
                bf_head, bf_body = tc0.get("borderFillIDRef"), tc1.get("borderFillIDRef")
                cp = tc1.find(".//" + Q(HP, "p"))
                if cp is not None:
                    cell_ids = _first_ids(cp)
                break
    info["bf_head"], info["bf_body"], info["cell_ids"] = bf_head, bf_body, cell_ids
    return info


def _page_text_width(sec):
    pp = sec.find(".//" + Q(HP, "pagePr"))
    m = pp.find(Q(HP, "margin")) if pp is not None else None
    if pp is None or m is None:
        return 42520
    return int(pp.get("width")) - int(m.get("left", 0)) - int(m.get("right", 0))


def _strip_lineseg(sec):
    for el in list(sec.iter(Q(HP, "linesegarray"))):
        el.getparent().remove(el)


def inject_hwpx(template_path: str, md: str, title: str = "", extra: dict = None, images: dict = None) -> bytes:
    """양식 ZIP 을 통째로 복제하고 section0.xml 의 본문만 교체한다. images: 그림 {키: bytes}"""
    extra = extra or {}
    with zipfile.ZipFile(template_path) as zin:
        order = zin.namelist()
        files = {n: zin.read(n) for n in order}
    sec = etree.fromstring(files["Contents/section0.xml"])
    hdr = etree.fromstring(files["Contents/header.xml"])
    _merge_placeholders(sec)
    info = _analyze(sec, hdr)
    blocks = parse_blocks(md)
    doc_title = title
    if blocks and blocks[0][0] == "h" and blocks[0][1] == 1:
        doc_title = doc_title or blocks[0][2]
    ids = {"para": {k: int(v) for k, v in info["para"].items()},
           "char": {k: int(v) for k, v in info["char"].items()}}
    if info["cell_ids"]:
        ids["para"]["cell"] = int(info["cell_ids"][0])
        ids["char"]["th"] = ids["char"]["cell"] = int(info["cell_ids"][1])
    sb = None
    if info["bf_head"] and info["bf_body"]:
        ids["bf_head"], ids["bf_body"] = int(info["bf_head"]), int(info["bf_body"])
    else:                                     # 양식에 표가 없으면 표 테두리를 양식 header 에 추가
        sb = hb.StyleBook(hdr)
        ids["bf_head"], ids["bf_body"] = sb.border(True, "#D9E2F3"), sb.border(True)
    if images:                                # 그림용 가운데 정렬 문단·캡션 글자
        sb = sb or hb.StyleBook(hdr)
        ids["para"]["center"] = sb.para("CENTER", 0, 0, 300, 100, 130)
        ids["char"]["caption"] = ids["char"].get("bold", ids["char"]["body"])
    tw = _page_text_width(sec)
    hb._pid[0] = 900000
    img_list = []

    values = {"제목": doc_title, "일자": extra.get("일자", ""), "작성자": extra.get("작성자", ""),
              "부서": extra.get("부서", "")}
    anchor = None
    for p in sec.iter(Q(HP, "p")):
        if "{{본문}}" in _ptext(p):
            anchor = p
            break
    has_title_ph = "제목" in info["placeholders"]
    body_blocks = blocks[1:] if (has_title_ph and blocks and blocks[0][0] == "h" and blocks[0][1] == 1) else blocks
    new_nodes = hb.frag(hb.blocks_to_xml(body_blocks, ids, tw, images, img_list))

    if anchor is not None:
        parent = anchor.getparent()
        idx = parent.index(anchor)
        parent.remove(anchor)
        for j, n in enumerate(new_nodes):
            parent.insert(idx + j, n)
    else:
        tops = _top_paras(sec)
        keep_until = 0
        if info["has_header_table"]:
            for i, p in enumerate(tops):
                if any(True for _ in p.iter(Q(HP, "tbl"))):
                    keep_until = i
                    break
        for p in tops[keep_until + 1:]:       # secPr 문단과 상단 헤더 표는 보존, 이후 본문 교체
            sec.remove(p)
        for n in new_nodes:
            sec.append(n)
    for t in sec.iter(Q(HP, "t")):
        if t.text and "{{" in t.text:
            t.text = re.sub(r"\{\{([^{}]+)\}\}",
                            lambda m: values.get(m.group(1).strip(), extra.get(m.group(1).strip(), "")), t.text)
    _strip_lineseg(sec)
    files["Contents/section0.xml"] = etree.tostring(sec, xml_declaration=True, encoding="UTF-8", standalone=True)
    files["Contents/header.xml"] = etree.tostring(hdr, xml_declaration=True, encoding="UTF-8", standalone=True)
    hb.add_binaries(files, _rename_items(sec, files, img_list) if img_list else [])
    return hb.write_zip(order, files)


def _rename_items(sec, files, img_list):
    """양식에 이미 image1.. 이 있을 수 있으므로 새 그림 ID 를 aiimgN 으로 바꿔 충돌 방지."""
    out = []
    for i, (old, data) in enumerate(img_list, 1):
        new = f"aiimg{i}"
        for img in sec.iter(Q(HC, "img")):
            if img.get("binaryItemIDRef") == old:
                img.set("binaryItemIDRef", new)
        out.append((new, data))
    files["Contents/section0.xml"] = etree.tostring(sec, xml_declaration=True, encoding="UTF-8", standalone=True)
    return out


def hwpx_status(path: str) -> str:
    try:
        with open(path, "rb") as f:
            info = analyze_hwpx_bytes(f.read())
        hdr = "상단 헤더 보존됨" if info["has_header_table"] else "상단 헤더 없음(본문 전체 교체)"
        ph = f" / 치환자 {len(info['placeholders'])}개({', '.join(info['placeholders'][:4])})" if info["placeholders"] else ""
        return f"✅ HWPX 양식 분석 완료: {hdr} / 문단 스타일 {info['style_count']}종 매핑됨{ph}"
    except Exception as e:
        return f"⚠️ HWPX 양식 분석 실패: {e}"


# ===================================================================== PPTX
def _find_layouts(prs):
    from pptx.enum.shapes import PP_PLACEHOLDER as PH
    title_l = content_l = None
    for l in prs.slide_layouts:
        types = [ph.placeholder_format.type for ph in l.placeholders]
        has_ctr = PH.CENTER_TITLE in types
        has_sub = PH.SUBTITLE in types
        has_title = PH.TITLE in types
        has_body = any(t in (PH.BODY, PH.OBJECT) for t in types)
        if title_l is None and (has_ctr or (has_title and has_sub)) :
            title_l = l
        if content_l is None and has_title and has_body and not has_sub:
            nm = l.name.lower()
            if "content" in nm or "내용" in nm:
                content_l = l
    if content_l is None:
        for l in prs.slide_layouts:
            types = [ph.placeholder_format.type for ph in l.placeholders]
            if PH.TITLE in types and any(t in (PH.BODY, PH.OBJECT) for t in types):
                content_l = l
                break
    layouts = list(prs.slide_layouts)
    return title_l or layouts[0], content_l or layouts[min(1, len(layouts) - 1)]


def _clear_slides(prs):
    lst = prs.slides._sldIdLst
    for sldId in list(lst):
        prs.part.drop_rel(sldId.rId)
        lst.remove(sldId)


def inject_pptx(template_path: str, text_or_struct) -> bytes:
    from pptx import Presentation
    from pptx.util import Pt, Emu
    from pptx.enum.shapes import PP_PLACEHOLDER as PH

    data = text_or_struct if isinstance(text_or_struct, dict) else parse_slides(text_or_struct)
    prs = Presentation(template_path)
    title_l, content_l = _find_layouts(prs)
    _clear_slides(prs)
    sw, sh = prs.slide_width, prs.slide_height

    # 표지
    s = prs.slides.add_slide(title_l)
    for ph in s.placeholders:
        t = ph.placeholder_format.type
        if t in (PH.CENTER_TITLE, PH.TITLE):
            ph.text_frame.text = data.get("title") or "발표 자료"
        elif t == PH.SUBTITLE:
            ph.text_frame.text = data.get("subtitle") or ""

    for sd in data.get("slides", []):
        s = prs.slides.add_slide(content_l)
        body = None
        for ph in s.placeholders:
            t = ph.placeholder_format.type
            if t in (PH.TITLE, PH.CENTER_TITLE):
                ph.text_frame.text = sd["title"]
            elif body is None and t in (PH.BODY, PH.OBJECT):
                body = ph
        bullets = sd.get("bullets", [])
        tbl = sd.get("table")
        if tbl:
            bullets = bullets[:3]
        if body is not None:
            if bullets:
                tf = body.text_frame
                for i, (lvl, txt) in enumerate(bullets):
                    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    p.text = txt
                    p.level = max(0, min(lvl, 2))
            else:
                if tbl:
                    body._element.getparent().remove(body._element)
                    body = None
        if tbl:
            nr, nc = len(tbl), max(len(r) for r in tbl)
            left = body.left if body is not None else int(sw * 0.07)
            width = body.width if body is not None else int(sw * 0.86)
            if body is not None:
                top0, full_h = body.top, body.height
                new_h = min(full_h, int(sh * 0.28)) if bullets else full_h
                body.height = new_h
                top = top0 + new_h + int(sh * 0.02)
            else:
                top = int(sh * 0.22)
            avail = sh - top - int(sh * 0.06)
            row_h = min(int(sh * 0.07), max(int(avail / nr), int(sh * 0.035)))
            gt = s.shapes.add_table(nr, nc, left, top, width, row_h * nr)
            for ri, row in enumerate(tbl):
                for ci in range(nc):
                    c = gt.table.cell(ri, ci)
                    c.text = row[ci] if ci < len(row) else ""
                    for p in c.text_frame.paragraphs:
                        for r in p.runs:
                            r.font.size = Pt(14 if nr <= 6 else 12)
        if sd.get("notes"):
            s.notes_slide.notes_text_frame.text = sd["notes"]
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def build_slides(template_path, data, pages=None) -> bytes:
    """템플릿 종류(.pptx/.pdf)에 따라 알맞은 주입 방식 선택. pages: PDF용 {'cover','content','end'}(0부터)."""
    if template_path.lower().endswith(".pdf"):
        import pdf_template
        pages = pages or {}
        return pdf_template.build(template_path, data, pages.get("cover"), pages.get("content"),
                                  pages.get("end", "auto"), pages.get("clean_body", True))
    return inject_pptx(template_path, data)


def pptx_status(path: str) -> str:
    if path.lower().endswith(".pdf"):
        import pdf_template
        return pdf_template.status(path)
    try:
        from pptx import Presentation
        prs = Presentation(path)
        return f"✅ PPTX 템플릿 분석 완료: 총 {len(prs.slide_layouts)}개의 슬라이드 레이아웃 감지됨"
    except Exception as e:
        return f"⚠️ PPTX 템플릿 분석 실패: {e}"
