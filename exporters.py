"""생성 결과(마크다운) → MD / PDF / DOCX / HWPX / PPTX 변환기."""
import io
import os
import re

from md_parser import parse_blocks, parse_slides, SYM_CHAR

def _find_font():
    """PDF용 한글 TTF 찾기: 환경변수 → 작업실 assets/fonts → Windows 맑은 고딕 → 리눅스 나눔/Noto."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [(os.environ.get("LAI_FONT_REG"), os.environ.get("LAI_FONT_BOLD")),
             (os.path.join(here, "assets", "fonts", "NanumGothic.ttf"), os.path.join(here, "assets", "fonts", "NanumGothicBold.ttf")),
             (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
             ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
             ("/usr/share/fonts/nanum/NanumGothic.ttf", "/usr/share/fonts/nanum/NanumGothicBold.ttf"),
             ("/usr/share/fonts/naver-nanum/NanumGothic.ttf", "/usr/share/fonts/naver-nanum/NanumGothicBold.ttf"),
             ("/usr/share/fonts/google-nanum-fonts/NanumGothic.ttf", "/usr/share/fonts/google-nanum-fonts/NanumGothicBold.ttf")]
    for reg, bold in cands:
        if reg and os.path.exists(reg):
            return reg, (bold if bold and os.path.exists(bold) else reg)
    return cands[2]                                    # 없으면 PDF 저장 시 글꼴 오류로 안내됨


FONT_REG, FONT_BOLD = _find_font()
NAVY = (0x1F, 0x38, 0x64)
DGRAY = (0x40, 0x40, 0x40)


def strip_non_korean_cjk(text: str) -> str:
    """중국어 한자(CJK 통합 한자) 잔여물 제거 + 중국어 문장부호(。，：；！？)를 일반 부호로 교체."""
    text = text.translate(str.maketrans({"。": ".", "，": ",", "：": ":", "；": ";", "！": "!", "？": "?", "、": ","}))
    return re.sub(r"[\u4e00-\u9fff]", "", text)


def _set_jong(ch: str, jong: int) -> str:
    code = ord(ch) - 0xAC00
    if not (0 <= code < 11172):
        return ch
    return chr(0xAC00 + (code // 28) * 28 + jong)


_END = r"(?=[.\s,:;)\]|]|$)"


def to_gaejosik(text: str) -> str:
    """서술형 종결(~합니다/~입니다/~습니다)을 개조식(~함/~임/~음)으로 기계적으로 교정.
    예) 포함합니다→포함함, 적용됩니다→적용됨, 따릅니다→따름, 있습니다→있음, 했습니다→했음"""
    text = re.sub(r"([가-힣])습니다" + _END, r"\1음", text, flags=re.M)
    text = re.sub(r"([가-힣])니다" + _END,
                  lambda m: _set_jong(m.group(1), 16) if (ord(m.group(1)) - 0xAC00) % 28 == 17 else m.group(0),
                  text, flags=re.M)
    # 평서형 '~다.'(문장 끝) → 개조식: 보여준다→보여줌, 된다→됨, 이다→임, 있다→있음, 먹는다→먹음
    end_da = r"다(?=\.?\s*$|\.\s)"

    def da(m):
        ch = m.group(1)
        jong = (ord(ch) - 0xAC00) % 28
        if jong == 4:                 # ㄴ받침: 한다→함, 된다→됨, 준다→줌
            return _set_jong(ch, 16)
        if jong == 0:                 # 받침 없음: 이다→임, 크다→큼
            return _set_jong(ch, 16)
        return ch + "음"              # 기타 받침: 있다→있음, 했다→했음, 같다→같음

    text = re.sub(r"([가-힣])는" + end_da, r"\1음", text, flags=re.M)
    text = re.sub(r"([가-힣])" + end_da, da, text, flags=re.M)
    return text


def narrative_count(text: str) -> int:
    return len(re.findall(r"[가-힣]니다" + _END, text, flags=re.M))


# ---------------------------------------------------------------- MD
def to_md(text: str, images: dict = None) -> bytes:
    if images:                                            # 그림은 MD 안에 직접 포함(data URI)
        import base64

        def emb(m):
            data = images.get(m.group(2))
            if data is None:
                return m.group(0)
            mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
            return f"![{m.group(1)}](data:{mime};base64,{base64.b64encode(data).decode()})"
        text = re.sub(r"!\[([^\]]*)\]\(img:([^)]+)\)", emb, text)
    return text.encode("utf-8")


# ---------------------------------------------------------------- PDF
def _heading_icon(text, used):
    """문서 소제목 아이콘(남색 선형 PNG 경로). 사이드바 설정이 꺼져 있거나 못 찾으면 None."""
    try:
        import icon_library as il
        return il.heading_icon(text, "#1F3864", used)
    except Exception:
        return None


def to_pdf(text: str, images: dict = None) -> bytes:
    from fpdf import FPDF
    from fpdf.fonts import FontFace
    pdf = FPDF(format="A4")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(True, 18)
    pdf.add_font("Malgun", "", FONT_REG)
    pdf.add_font("Malgun", "B", FONT_BOLD)
    pdf.add_page()
    lm = pdf.l_margin
    usable = pdf.w - pdf.l_margin - pdf.r_margin

    def hanging(sym, txt, indent, symw, bold=False, size=10.5, lh=6.2):
        pdf.set_font("Malgun", "B" if bold else "", size)
        pdf.set_left_margin(lm)
        y = pdf.get_y()
        if y + lh > pdf.h - 18:
            pdf.add_page()
            y = pdf.get_y()
        pdf.set_xy(lm + indent, y)
        pdf.cell(symw, lh, sym)
        pdf.set_left_margin(lm + indent + symw)
        pdf.set_xy(lm + indent + symw, y)
        pdf.multi_cell(0, lh, txt, new_x="LMARGIN", new_y="NEXT")
        pdf.set_left_margin(lm)

    used = []
    for b in parse_blocks(text):
        pdf.set_left_margin(lm)
        pdf.set_x(lm)
        if b[0] == "h":
            if b[1] == 1:
                pdf.set_font("Malgun", "B", 18)
                pdf.set_text_color(*NAVY)
                pdf.multi_cell(0, 10, b[2], align="C", new_x="LMARGIN", new_y="NEXT")
                pdf.set_draw_color(*NAVY)
                pdf.line(lm, pdf.get_y() + 1, lm + usable, pdf.get_y() + 1)
                pdf.ln(5)
            else:
                if pdf.get_y() > pdf.h - 70:      # 제목이 쪽 끝에 홀로 남지 않게 다음 쪽으로
                    pdf.add_page()
                pdf.ln(2)
                pdf.set_font("Malgun", "B", 14 if b[1] == 2 else 12)
                pdf.set_text_color(*NAVY)
                ic = _heading_icon(b[2], used) if b[1] == 2 else None
                if ic:                                # 소제목 앞 선형 아이콘 (5.5mm)
                    y = pdf.get_y()
                    pdf.image(ic, x=lm, y=y + 1.25, w=5.5, h=5.5)
                    pdf.set_left_margin(lm + 7.5)
                    pdf.set_xy(lm + 7.5, y)
                pdf.multi_cell(0, 8, b[2], new_x="LMARGIN", new_y="NEXT")
                pdf.set_left_margin(lm)
                pdf.ln(1)
            pdf.set_text_color(0, 0, 0)
        elif b[0] == "sym":
            k = b[1]
            sym = SYM_CHAR[k]
            if k == "box":
                pdf.ln(1.5)
                hanging(sym, b[2], 0, 7, True, 11.5)
            elif k == "circle":
                hanging(sym, b[2], 6, 6)
            elif k == "dash":
                hanging(sym, b[2], 12, 5, size=10)
            else:
                hanging(sym, b[2], 12, 6, size=9.5)
        elif b[0] == "p":
            pdf.set_font("Malgun", "", 10.5)
            pdf.multi_cell(0, 6.2, b[1], new_x="LMARGIN", new_y="NEXT")
        elif b[0] == "img" and images and b[1] in images:
            from hwpx_builder import image_size
            pw, ph = image_size(images[b[1]])
            w = min(usable * 0.95, pw * 25.4 / 96 * 1.0)          # mm, 원본 96dpi 기준 크기 이하
            h = w * ph / pw
            max_h = pdf.h - pdf.t_margin - 18 - 12
            if h > max_h:
                h = max_h
                w = h * pw / ph
            if pdf.get_y() + h + 10 > pdf.h - 18:
                pdf.add_page()
            pdf.ln(2)
            pdf.image(io.BytesIO(images[b[1]]), x=lm + (usable - w) / 2, w=w, h=h)
            if b[2]:
                pdf.set_font("Malgun", "B", 9.5)
                pdf.set_text_color(*NAVY)
                pdf.multi_cell(0, 5.5, b[2], align="C", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
        elif b[0] == "table":
            rows = b[1]
            pdf.set_font("Malgun", "", 9.5)
            pdf.ln(1)
            from hwpx_builder import col_widths
            with pdf.table(col_widths=tuple(col_widths(rows, 1000)),
                           headings_style=FontFace(emphasis="BOLD", fill_color=(217, 226, 243)),
                           line_height=5.8, text_align="LEFT", borders_layout="ALL",
                           first_row_as_headings=True) as t:
                for r in rows:
                    row = t.row()
                    for c in r:
                        row.cell(c)
            pdf.ln(3)
    out = pdf.output()
    return bytes(out)


# ---------------------------------------------------------------- DOCX
def _set_font(run, size=None, bold=None, color=None):
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    run.font.name = "맑은 고딕"
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        from docx.oxml import OxmlElement
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    rf.set(qn("w:eastAsia"), "맑은 고딕")
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)


def _shade(cell, hex_fill):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def to_docx(text: str, images: dict = None) -> bytes:
    import docx
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    d = docx.Document()
    sec = d.sections[0]
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = sec.bottom_margin = Cm(2.2)
    st = d.styles["Normal"]
    st.font.name = "맑은 고딕"
    st.font.size = Pt(10.5)
    from docx.oxml.ns import qn
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")

    used = []
    for b in parse_blocks(text):
        if b[0] == "h":
            lvl = min(b[1], 3)
            p = d.add_heading(level=lvl if lvl > 1 else 0 if False else lvl)
            ic = _heading_icon(b[2], used) if lvl == 2 else None
            if ic:                                    # 소제목 앞 선형 아이콘 (글자처럼 인라인)
                p.add_run().add_picture(ic, width=Pt(14), height=Pt(14))
                p.add_run(" ")
            r = p.add_run(b[2])
            _set_font(r, {1: 18, 2: 14, 3: 12}[lvl], True, NAVY)
            if lvl == 1:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif b[0] == "sym":
            k = b[1]
            p = d.add_paragraph()
            pf = p.paragraph_format
            cfg = {"box": (0, 0.6, 11.5, True), "circle": (0.5, 0.5, 10.5, False),
                   "dash": (1.0, 0.45, 10, False), "note": (1.0, 0.5, 9.5, False)}[k]
            pf.left_indent = Cm(cfg[0] + cfg[1])
            pf.first_line_indent = Cm(-cfg[1])
            pf.space_after = Pt(2)
            pf.space_before = Pt(5 if k == "box" else 0)
            r = p.add_run(f"{SYM_CHAR[k]} {b[2]}")
            _set_font(r, cfg[2], cfg[3])
        elif b[0] == "p":
            p = d.add_paragraph()
            _set_font(p.add_run(b[1]), 10.5)
        elif b[0] == "img" and images and b[1] in images:
            from hwpx_builder import image_size
            pw, ph = image_size(images[b[1]])
            w_cm = min(16.0, pw / 96 * 2.54)
            if w_cm * ph / pw > 20:
                w_cm = 20 * pw / ph
            p = d.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(io.BytesIO(images[b[1]]), width=Cm(w_cm))
            if b[2]:
                cp = d.add_paragraph()
                cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _set_font(cp.add_run(b[2]), 9.5, True, NAVY)
        elif b[0] == "table":
            rows = b[1]
            t = d.add_table(rows=len(rows), cols=len(rows[0]))
            t.style = "Table Grid"
            t.autofit = False
            from hwpx_builder import col_widths
            for ci, w in enumerate(col_widths(rows, 16000)):          # 16.0cm 를 내용 길이에 맞게 배분
                for cell in t.columns[ci].cells:
                    cell.width = Cm(w / 1000)
            for ri, row in enumerate(rows):
                for ci, val in enumerate(row):
                    c = t.cell(ri, ci)
                    c.text = ""
                    r = c.paragraphs[0].add_run(val)
                    _set_font(r, 9.5, ri == 0)
                    if ri == 0:
                        _shade(c, "D9E2F3")
            d.add_paragraph()
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- HWPX
def to_hwpx(text: str, title: str = "문서", images: dict = None) -> bytes:
    from hwpx_builder import markdown_to_hwpx
    return markdown_to_hwpx(text, title, images)


# ---------------------------------------------------------------- PPTX (기본 비즈니스 테마)
def to_pptx(text_or_struct) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

    data = text_or_struct if isinstance(text_or_struct, dict) else parse_slides(text_or_struct)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    navy, gray = RGBColor(*NAVY), RGBColor(*DGRAY)

    def font(run, size, bold=False, color=gray):
        run.font.name = "맑은 고딕"
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color

    # 표지
    s = prs.slides.add_slide(blank)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb = navy; bg.line.fill.background()
    tb = s.shapes.add_textbox(Inches(1), Inches(2.5), Inches(11.3), Inches(1.6))
    tf = tb.text_frame; tf.word_wrap = True
    r = tf.paragraphs[0].add_run(); r.text = data.get("title") or "발표 자료"
    font(r, 38, True, RGBColor(255, 255, 255))
    if data.get("subtitle"):
        p = tf.add_paragraph(); r = p.add_run(); r.text = data["subtitle"]
        font(r, 20, False, RGBColor(0xD9, 0xE2, 0xF3))

    sym = ["□ ", "ㅇ ", "- "]
    for sd in data.get("slides", []):
        s = prs.slides.add_slide(blank)
        bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(1.1))
        bar.fill.solid(); bar.fill.fore_color.rgb = navy; bar.line.fill.background()
        acc = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(1.1), prs.slide_width, Inches(0.06))
        acc.fill.solid(); acc.fill.fore_color.rgb = gray; acc.line.fill.background()
        t = s.shapes.add_textbox(Inches(0.6), Inches(0.15), Inches(12.1), Inches(0.8))
        t.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        r = t.text_frame.paragraphs[0].add_run(); r.text = sd["title"]
        font(r, 28, True, RGBColor(255, 255, 255))

        has_tbl = bool(sd.get("table"))
        bullets = sd.get("bullets", [])
        if has_tbl:
            bullets = bullets[:3]
        body_h = Inches(1.9) if has_tbl else Inches(5.6)
        if bullets:
            bx = s.shapes.add_textbox(Inches(0.7), Inches(1.45), Inches(11.9), body_h)
            tf = bx.text_frame; tf.word_wrap = True
            first = True
            for lvl, txt in bullets:
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                first = False
                lvl = max(0, min(lvl, 2))
                p.level = lvl
                p.space_after = Pt(6)
                r = p.add_run(); r.text = sym[lvl] + txt
                font(r, [20, 18, 16][lvl], lvl == 0)
        if has_tbl:
            rows = sd["table"]
            nr, nc = len(rows), max(len(x) for x in rows)
            top = Inches(3.5) if bullets else Inches(1.5)
            gt = s.shapes.add_table(nr, nc, Inches(0.7), top, Inches(11.9), Inches(0.45) * nr)
            tbl = gt.table
            for ri, row in enumerate(rows):
                for ci in range(nc):
                    cell = tbl.cell(ri, ci)
                    cell.text = ""
                    r = cell.text_frame.paragraphs[0].add_run()
                    r.text = row[ci] if ci < len(row) else ""
                    font(r, 14, ri == 0, RGBColor(255, 255, 255) if ri == 0 else gray)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = navy if ri == 0 else RGBColor(0xF2, 0xF2, 0xF2) if ri % 2 == 0 else RGBColor(255, 255, 255)
        if sd.get("notes"):
            s.notes_slide.notes_text_frame.text = sd["notes"]
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def export(fmt: str, text: str, title: str = "문서", images: dict = None) -> bytes:
    text = strip_non_korean_cjk(text)
    return {"md": lambda t: to_md(t, images), "pdf": lambda t: to_pdf(t, images),
            "docx": lambda t: to_docx(t, images), "hwpx": lambda t: to_hwpx(t, title, images)}[fmt](text)
