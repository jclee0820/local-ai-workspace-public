"""PDF 슬라이드 템플릿 → PPTX. 페이지 유형을 자동 판별하고(표지/본문/마무리) 사용자가 페이지를 직접 지정할 수도 있다."""
import io
import math

import fitz
from PIL import Image

from md_parser import parse_slides

DARK = (0x26, 0x26, 0x26)
NAVY = (0x1F, 0x38, 0x64)


# ------------------------------------------------------------------ 유틸
def _lum(rgb):
    r, g, b = [c / 255 for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _rgb(c: int):
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


def _union(rects):
    r = fitz.Rect(rects[0])
    for x in rects[1:]:
        r |= fitz.Rect(x)
    return r


def _readable(color, bg):
    if color and abs(_lum(color) - _lum(bg)) >= 0.35:
        return color
    return DARK if _lum(bg) > 0.5 else (255, 255, 255)


def _fit_size(items, width_pt, height_pt, base, minimum=11):
    size = base
    while size > minimum:
        lines = 0
        for lvl, txt in items:
            cpl = max(8, (width_pt - lvl * 20) / (size * 0.62))
            lines += math.ceil(max(len(txt), 1) / cpl)
        if lines * size * 1.5 <= height_pt:
            break
        size -= 1
    return size


def _spans(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                if s["text"].strip():
                    out.append({"size": s["size"], "color": _rgb(s["color"]), "rect": fitz.Rect(s["bbox"]),
                                "text": s["text"].strip()})
    return out


def _title_spans(spans, H, top_limit=None):
    """제목 후보: 장식용 초대형 글자(숫자·따옴표 등)와 짧은 글자(2자 이하)는 제외하고 가장 큰 글자."""
    cand = [s for s in spans if 0.03 * H <= s["size"] <= 0.17 * H and len(s["text"]) >= 4
            and (top_limit is None or s["rect"].y0 < top_limit)]
    if not cand:
        return []
    mx = max(s["size"] for s in cand)
    sel = [s for s in cand if s["size"] >= mx * 0.9]
    first = min(sel, key=lambda s: s["rect"].y0)
    return [s for s in sel if s["rect"].y0 - first["rect"].y0 < mx * 3.2]


# ------------------------------------------------------------------ 페이지 유형 자동 판별
def auto_pages(doc):
    """(표지, 본문, 마무리) 페이지 번호(0부터). 마무리는 없으면 None."""
    n = len(doc)
    cover = 0
    content = 0 if n == 1 else 1
    if n > 1:
        found = None
        for limit in (0.15, 0.25):
            for i in range(1, n - 1 if n > 2 else n):
                pg = doc[i]
                ts = _title_spans(_spans(pg), pg.rect.height, pg.rect.height * limit)
                if ts and _union([s["rect"] for s in ts]).y1 < pg.rect.height * (limit + 0.07):
                    found = i
                    break
            if found is not None:
                break
        content = found if found is not None else 1
    end = None
    if n > 2:
        for i in (n - 1, n - 2):
            txt = doc[i].get_text().upper()
            if i > content and any(k in txt for k in ("THANK", "감사", "Q&A", "THE END")):
                end = i
                break
    return cover, content, end


def page_thumbnails(path: str, max_pages: int = 12, dpi: int = 30):
    doc = fitz.open(path)
    return [doc[i].get_pixmap(dpi=dpi).tobytes("png") for i in range(min(max_pages, len(doc)))]


def page_count(path: str) -> int:
    return len(fitz.open(path))


# ------------------------------------------------------------------ 페이지 분석 + 글자 제거 배경
def _background(page, W, H):
    tmp = fitz.open()
    tmp.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
    p = tmp[0]
    for b in p.get_text("blocks"):
        if b[6] == 0:
            p.add_redact_annot(fitz.Rect(b[:4]), fill=False)
    try:
        p.apply_redactions(images=0, graphics=0)
    except TypeError:
        p.apply_redactions()
    dpi = int(1920 / (W / 72))
    png = p.get_pixmap(dpi=dpi).tobytes("png")
    tmp.close()
    if _is_raster(page):          # 페이지 전체가 그림인 PDF: 글자 위치를 찾아 배경으로 메워 지움
        png = _inpaint_text(png, page, W, H)
    return png


def _is_raster(page) -> bool:
    area = page.rect.width * page.rect.height
    try:
        imgs = page.get_image_info()
    except Exception:
        return False
    return any(fitz.Rect(i["bbox"]).get_area() >= 0.6 * area for i in imgs)


def _inpaint_text(png: bytes, page, W, H) -> bytes:
    """텍스트 층이 가리키는 영역 안에서 '배경과 다른 픽셀(글자)'만 골라 주변 색으로 복원."""
    import cv2
    import numpy as np
    arr = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    sx, sy = arr.shape[1] / W, arr.shape[0] / H
    mask = np.zeros(arr.shape[:2], np.uint8)
    pad = 3
    for s in _spans(page):
        r = s["rect"]
        x0, y0 = max(int(r.x0 * sx) - pad, 0), max(int(r.y0 * sy) - pad, 0)
        x1, y1 = min(int(r.x1 * sx) + pad, arr.shape[1]), min(int(r.y1 * sy) + pad, arr.shape[0])
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        roi = arr[y0:y1, x0:x1].astype(np.int16)
        bg = np.median(roi.reshape(-1, 3), axis=0)
        diff = np.abs(roi - bg).sum(axis=2)
        mask[y0:y1, x0:x1] |= ((diff > 60).astype(np.uint8) * 255)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
    out = cv2.inpaint(arr, mask, 4, cv2.INPAINT_TELEA)
    return cv2.imencode(".png", out)[1].tobytes()


def _paint_blank(png: bytes, W, H, rect) -> bytes:
    """rect(pt) 영역을 왼쪽 여백 띠의 배경색으로 칠해 비운다. 여백 색이 균일하지 않으면 그대로 둔다."""
    import numpy as np
    img = Image.open(io.BytesIO(png)).convert("RGB")
    sx, sy = img.width / W, img.height / H
    y0, y1 = int(rect.y0 * sy), min(int(rect.y1 * sy), img.height)
    strip = np.asarray(img.crop((int(0.006 * W * sx), y0, max(int(0.03 * W * sx), int(0.006 * W * sx) + 2), y1)))
    flat = strip.reshape(-1, 3)
    if flat.std(axis=0).max() > 25:
        return png
    color = tuple(int(v) for v in np.median(flat, axis=0))
    from PIL import ImageDraw
    ImageDraw.Draw(img).rectangle([int(rect.x0 * sx), y0, int(rect.x1 * sx), y1], fill=color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def analyze(page, mode: str, clean_body: bool = False):
    """mode: 'cover'(표지·마무리) | 'content'(본문). 반환: 배경 PNG + 제목/본문 박스(pt) + 색."""
    W, H = page.rect.width, page.rect.height
    spans = _spans(page)
    png = _background(page, W, H)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    sx, sy = img.width / W, img.height / H

    def bg_at(r):
        x0, y0 = int(max(r.x0, 0) * sx), int(max(r.y0, 0) * sy)
        x1, y1 = max(int(r.x1 * sx), x0 + 1), max(int(r.y1 * sy), y0 + 1)
        return img.crop((x0, y0, min(x1, img.width), min(y1, img.height))).resize((1, 1), Image.BOX).getpixel((0, 0))

    ts = _title_spans(spans, H, H * 0.25 if mode == "content" else None)
    margin = 0.07 * W
    if ts:
        tr = _union([s["rect"] for s in ts])
        tsize, tcolor = max(s["size"] for s in ts), ts[0]["color"]
        left = tr.x0 if tr.x0 < 0.4 * W else margin
        title_box = fitz.Rect(left, tr.y0, W - margin, max(tr.y1, tr.y0 + 0.07 * H))
    else:
        tr, tsize, tcolor = None, 32, None
        left = margin
        title_box = fitz.Rect(left, 0.06 * H, W - margin, 0.2 * H)
    res = {"png": png, "W": W, "H": H, "title_box": title_box, "tsize": tsize, "tcolor": tcolor,
           "title_bg": bg_at(title_box)}

    others = [s for s in spans if s not in ts and s["size"] <= 0.17 * H]
    if mode == "cover":
        below = [s for s in others if s["rect"].y0 >= title_box.y1 - 2 and len(s["text"]) >= 2]
        if below:
            sz = max(s["size"] for s in below)
            sub = [s for s in below if s["size"] >= sz * 0.9]
            sr = _union([s["rect"] for s in sub])
            res["sub_box"] = fitz.Rect(left, sr.y0, W - margin, max(sr.y1, sr.y0 + 0.06 * H))
            res["sub_color"] = sub[0]["color"]
        else:
            res["sub_box"] = fitz.Rect(left, title_box.y1 + 0.03 * H, W - margin, title_box.y1 + 0.12 * H)
            res["sub_color"] = None
        res["sub_bg"] = bg_at(res["sub_box"])
    else:
        top_zone = [s for s in spans if s["rect"].y0 < 0.25 * H and s["size"] <= 0.17 * H]
        top = max([s["rect"].y1 for s in top_zone] + [title_box.y1]) + 0.03 * H
        if top > 0.45 * H:
            top = title_box.y1 + 0.05 * H
        body_left = left if left < 0.3 * W else margin
        right = max(body_left, 0.1 * W) if clean_body else body_left
        res["body_box"] = fitz.Rect(body_left, top, W - right, 0.93 * H)
        if clean_body:   # 샘플 카드·박스 등 본문 영역의 장식을 지우고 머리말/꼬리말만 남김
            res["png"] = png = _paint_blank(png, W, H, fitz.Rect(0.035 * W, top - 0.005 * H, 0.94 * W, 0.915 * H))
            img = Image.open(io.BytesIO(png)).convert("RGB")
        body_sp = [s for s in others if s["rect"].y0 >= top]
        colors = [s["color"] for s in body_sp if len(s["text"]) >= 3]
        res["body_color"] = max(set(colors), key=colors.count) if colors else None
        res["body_bg"] = bg_at(res["body_box"])
    return res


def status(path: str) -> str:
    try:
        doc = fitz.open(path)
        c, b, e = auto_pages(doc)
        endtxt = f", 마무리 {e + 1}쪽" if e is not None else ""
        return (f"✅ PDF 템플릿 분석 완료: 총 {len(doc)}쪽 / 자동 선택 → 표지 {c + 1}쪽, 본문 {b + 1}쪽{endtxt} "
                f"(아래에서 바꿀 수 있음) / 원본 글자는 제거하고 배경·로고·도형·색상·제목 위치만 활용")
    except Exception as e:
        return f"⚠️ PDF 템플릿 분석 실패: {e}"


# ------------------------------------------------------------------ PPTX 생성
def build(pdf_path: str, text_or_struct, cover=None, content=None, end="auto", clean_body=True) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Pt

    data = text_or_struct if isinstance(text_or_struct, dict) else parse_slides(text_or_struct)
    doc = fitz.open(pdf_path)
    ac, ab, ae = auto_pages(doc)
    cover = ac if cover is None else cover
    content = ab if content is None else content
    end = ae if end == "auto" else end

    cv = analyze(doc[cover], "cover")
    ct = analyze(doc[content], "content", clean_body)
    prs = Presentation()
    SW = 12192000
    prs.slide_width = SW
    prs.slide_height = int(SW * cv["H"] / cv["W"])
    SH = prs.slide_height
    blank = prs.slide_layouts[6]
    PTW = 960.0

    def emu(a, r):
        kx, ky = SW / a["W"], SH / a["H"]
        return (int(r.x0 * kx), int(r.y0 * ky), int(r.width * kx), int(r.height * ky))

    def background(slide, a):
        pic = slide.shapes.add_picture(io.BytesIO(a["png"]), 0, 0, SW, SH)
        el = pic._element
        tree = el.getparent()
        tree.remove(el)
        tree.insert(2, el)

    def tbox(slide, rect, anchor):
        tb = slide.shapes.add_textbox(*rect)
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        return tf

    def style(run, size, rgb, bold=False):
        run.font.name = "맑은 고딕"
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor(*rgb)

    def title_slide(a, title, subtitle=""):
        s = prs.slides.add_slide(blank)
        background(s, a)
        rect = emu(a, a["title_box"])
        col = _readable(a["tcolor"], a["title_bg"])
        base = max(28, min(52, a["tsize"] * PTW / a["W"]))
        tf = tbox(s, rect, MSO_ANCHOR.MIDDLE)
        r = tf.paragraphs[0].add_run()
        r.text = title
        style(r, _fit_size([(0, title)], rect[2] / 12700, rect[3] / 12700, base, 22), col, True)
        if subtitle:
            sr = emu(a, a["sub_box"])
            tf2 = tbox(s, sr, MSO_ANCHOR.TOP)
            r = tf2.paragraphs[0].add_run()
            r.text = subtitle
            style(r, _fit_size([(0, subtitle)], sr[2] / 12700, sr[3] / 12700, 24, 14),
                  _readable(a["sub_color"] or a["tcolor"], a["sub_bg"]))
        return s

    title_slide(cv, data.get("title") or "발표 자료", data.get("subtitle", ""))

    sym = ["□ ", "ㅇ ", "- "]
    for sd in data.get("slides", []):
        s = prs.slides.add_slide(blank)
        background(s, ct)
        trect = emu(ct, ct["title_box"])
        tcol = _readable(ct["tcolor"], ct["title_bg"])
        tf = tbox(s, trect, MSO_ANCHOR.MIDDLE)
        r = tf.paragraphs[0].add_run()
        r.text = sd["title"]
        base = max(24, min(38, ct["tsize"] * PTW / ct["W"]))
        style(r, _fit_size([(0, sd["title"])], trect[2] / 12700, trect[3] / 12700, base, 18), tcol, True)

        bl, bt, bw, bh = emu(ct, ct["body_box"])
        bcol = _readable(ct["body_color"], ct["body_bg"])
        bullets = sd.get("bullets", [])
        tbl = sd.get("table")
        if tbl:
            bullets = bullets[:3]
        bul_h = int(bh * 0.40) if (tbl and bullets) else bh
        if bullets:
            tf = tbox(s, (bl, bt, bw, bul_h), MSO_ANCHOR.TOP)
            size = _fit_size(bullets, bw / 12700, bul_h / 12700, 20)
            for i, (lvl, txt) in enumerate(bullets):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                lvl = max(0, min(lvl, 2))
                p.space_after = Pt(5)
                r = p.add_run()
                r.text = "    " * lvl + sym[lvl] + txt
                style(r, size - lvl * 2, bcol, lvl == 0)
        if tbl:
            nr, nc = len(tbl), max(len(x) for x in tbl)
            top = bt + (bul_h + int(SH * .02) if bullets else 0)
            avail = SH - top - int(SH * .06)
            rh = min(int(SH * .07), max(int(avail / nr), int(SH * .035)))
            gt = s.shapes.add_table(nr, nc, bl, top, bw, rh * nr)
            tbg = ct["title_bg"]
            hdr = tbg if _lum(tbg) < 0.6 else (tcol if _lum(tcol) < 0.6 else NAVY)
            for ri, row in enumerate(tbl):
                for ci in range(nc):
                    c = gt.table.cell(ri, ci)
                    c.text = ""
                    r = c.text_frame.paragraphs[0].add_run()
                    r.text = row[ci] if ci < len(row) else ""
                    style(r, 14 if nr <= 6 else 12, (255, 255, 255) if ri == 0 else DARK, ri == 0)
                    c.fill.solid()
                    c.fill.fore_color.rgb = RGBColor(*hdr) if ri == 0 else (
                        RGBColor(0xF2, 0xF2, 0xF2) if ri % 2 == 0 else RGBColor(255, 255, 255))
        if sd.get("notes"):
            s.notes_slide.notes_text_frame.text = sd["notes"]

    if end is not None:
        title_slide(analyze(doc[end], "cover"), "감사합니다")

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
