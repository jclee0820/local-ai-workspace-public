"""PDF 에서 그림·표를 캡션 기준으로 찾아 이미지로 잘라내고, 본문 언급 문장·표 데이터를 함께 수집한다.
설명은 Qwen 이 '원문 캡션 + 본문 언급 + 표 데이터'만 근거로 작성 (그림 내부 판독은 하지 않음)."""
import io
import json
import re

import fitz
fitz.TOOLS.mupdf_display_errors(False)     # 글꼴 정보가 불완전한 PDF의 경고가 터미널을 가득 채우지 않게 (본문 추출에는 영향 없음)
fitz.TOOLS.mupdf_display_warnings(False)

CAP = re.compile(r"^\s*[<\[(]?\s*(Figure|FIGURE|Fig\.|Table|TABLE|그림|표)\s*([A-Z]?\d+(?:[.\-]\d+)?)\s*[>\])]?"
                 r"\s*([-–—:.]\s*|\s+)(.{2,})$")
WATERMARK = re.compile(r"Downloaded from .{0,60} by |This document is licensed|Copyright ©|All rights reserved", re.I)


def _norm(s: str) -> str:
    """PDF 수식 글자 정리: 𝜹𝜹 → δ (수학용 기호 정규화 + PDF 추출 시 두 번 찍힌 그리스 문자 제거)."""
    from md_parser import fix_math_chars

    def undouble(m):                              # 𝟗𝟗𝟎𝟎 처럼 글자마다 두 번 찍힌 수식 → 𝟗𝟎
        t = m.group(0)
        return t[::2] if len(t) % 2 == 0 and t[::2] == t[1::2] else t
    s = re.sub("[\U0001D400-\U0001D7FF]{2,}", undouble, s)
    s = fix_math_chars(s)
    return re.sub(r"([α-ωΑ-Ω])\1", r"\1", s)


def _kind(word: str) -> str:
    return "table" if word.lower().startswith("tab") or word == "표" else "figure"


def _lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = _norm("".join(s["text"] for s in ln["spans"]).strip())
            if t:
                r = fitz.Rect(ln["bbox"])
                first = next((s for s in ln["spans"] if s["text"].strip()), None)
                if first:                         # 수식 기호 등으로 줄 높이가 부풀려지는 것 방지
                    fb = fitz.Rect(first["bbox"])
                    r = fitz.Rect(r.x0, fb.y0, r.x1, fb.y1)
                out.append((r, t))
    return out


def _is_caption(text: str):
    if "....." in text or re.search(r"\.{3,}\s*\d+\s*$", text):      # 목차 줄 제외
        return None
    m = CAP.match(text)
    if not m:
        return None
    sep = m.group(3).strip()
    word = m.group(1)
    korean = word in ("그림", "표")
    if not sep and not korean:                    # 영문은 'Figure 1 - 제목' 처럼 구분자가 있어야 캡션
        return None
    title = m.group(4).strip()
    if not korean and title[:1].islower():
        return None
    return _kind(word), m.group(2), title


def _graphics(page):
    W, H = page.rect.width, page.rect.height
    rects = []
    for i in page.get_image_info():
        r = fitz.Rect(i["bbox"])
        if r.width > 20 and r.height > 20:
            rects.append((r, True))
    text_lines = [r for r, _ in _lines(page)]
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.height < 2.5 and r.width < 260:       # 본문 하이퍼링크 밑줄(유색 가는 선) 제외
            col = d.get("color") or d.get("fill") or (0, 0, 0)
            colored = max(col) - min(col) > 0.25 if col else False
            near = any(abs(r.y0 - tl.y1) < 4 and r.x0 >= tl.x0 - 2 and r.x1 <= tl.x1 + 2 for tl in text_lines)
            if colored and near:
                continue
        if r.y1 < H * 0.06 or r.y0 > H * 0.94:   # 머리말/꼬리말 선 제외
            continue
        if r.width > W * 0.85 and r.height < 2:  # 페이지 가로 구분선 제외
            continue
        if r.width * r.height < 1 and r.width < 3 and r.height < 3:
            continue
        rects.append((r, False))
    return rects


def _cluster(cands, start_key, grow_ok):
    if not cands:
        return None
    cands = sorted(cands, key=start_key)
    u = fitz.Rect(cands[0])
    changed = True
    while changed:
        changed = False
        for g in cands:
            if not u.contains(g) and grow_ok(u, g):
                u |= g
                changed = True
    return u


def _region(page, cap_rect, kind, lim_top, lim_bot, claimed=()):
    W = page.rect.width
    allg = [(g, im) for g, im in _graphics(page)    # 다른 그림·표가 이미 차지한 영역은 제외
            if not any((g & c).get_area() > 0.3 * max(g.get_area(), 1) for c in claimed)]

    def pick(cands, seed_key):
        """가장 가까운 것을 씨앗으로 삼고, 표가 선(도형)으로 시작하면 그림 이미지는 합치지 않음."""
        if not cands:
            return None
        seed = sorted(cands, key=lambda x: seed_key(x[0]))[0]
        if kind == "table" and not seed[1]:
            return [g for g, im in cands if not im]
        return [g for g, _ in cands]

    def above():
        allc = [(g, im) for g, im in allg if g.y1 <= cap_rect.y0 + 4 and g.y0 >= lim_top - 2]
        if not any(cap_rect.y0 - g.y1 < 90 for g, _ in allc):
            return None
        rs = pick(allc, lambda g: -g.y1) if kind == "table" else [g for g, _ in allc]
        return _cluster(rs, lambda g: -g.y1, lambda u, g: g.y1 >= u.y0 - 18 and g.y0 < u.y1)

    def below():
        allc = [(g, im) for g, im in allg if g.y0 >= cap_rect.y1 - 4 and g.y1 <= lim_bot + 2]
        near = [x for x in allc if x[0].y0 - cap_rect.y1 < 60]
        if not near:
            return None
        rs = pick(allc, lambda g: g.y0) if kind == "table" else [g for g, _ in allc]
        return _cluster(rs, lambda g: g.y0, lambda u, g: g.y0 <= u.y1 + 18 and g.y1 > u.y0)

    r = (above() or below()) if kind == "figure" else (below() or above())
    if r is None or r.height < 15 or r.width < 30:
        return None
    r = fitz.Rect(max(r.x0 - 4, 0), max(r.y0 - 4, 0), min(r.x1 + 4, W), min(r.y1 + 4, page.rect.height))
    return r


def _png(page, rect, dpi=150) -> bytes:
    pix = page.get_pixmap(clip=rect, dpi=dpi)
    data = pix.tobytes("png")
    if len(data) > 600_000:                       # 사진류는 JPEG 로 용량 절감
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        data = buf.getvalue()
    return data


def _table_rows(page, rect):
    try:
        for t in page.find_tables().tables:
            if fitz.Rect(t.bbox).intersects(rect):
                rows = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in t.extract()]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2:
                    return rows[:25]
    except Exception:
        pass
    return None


def full_text(doc) -> str:
    out = []
    for p in doc:
        out.extend(l for l in p.get_text().splitlines() if not WATERMARK.search(l))
    return _norm("\n".join(out))


def _context(text: str, word: str, num: str, caption: str, limit=3):
    words = {"figure": r"(?:Figure|Fig\.|그림)", "table": r"(?:Table|표)"}[word]
    flat = re.sub(r"\s+", " ", text)
    sents = re.split(r"(?<=[.!?。])\s+", flat)
    out = []
    for s in sents:
        if re.search(rf"\b{words}\s*{re.escape(num)}(?![\d.]\d)", s) and caption[:25] not in s:
            if "....." in s:
                continue
            out.append(s.strip()[:350])
            if len(out) >= limit:
                break
    return out


def extract(pdf_bytes: bytes, progress=None) -> dict:
    """반환: {'items': [...], 'n_pages': int}. item: id, kind, label, num, caption, page, image, rows, context"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = full_text(doc)
    items, seen = [], set()
    for pi, page in enumerate(doc):
        if progress:
            progress(pi / len(doc), f"🔍 그림·표 찾는 중... {pi + 1}/{len(doc)}쪽")
        lines = _lines(page)
        caps = []
        for r, t in lines:
            c = _is_caption(t)
            if c and not WATERMARK.search(t):
                caps.append((r, t, c))
        H = page.rect.height
        caps.sort(key=lambda c: c[0].y0)
        claimed, page_items = [], []
        # 표(캡션 아래)를 먼저 확정한 뒤 그림(캡션 위)을 찾아 서로 영역을 침범하지 않게 함
        order = sorted(range(len(caps)), key=lambda i: 0 if caps[i][2][0] == "table" else 1)
        for ci in order:
            r, t, (kind, num, title) = caps[ci]
            key = (kind, num)
            if key in seen:                       # 같은 번호가 다시 나오면(계속 표 등) 건너뜀
                continue
            lim_top = max([c[0].y1 for c in caps[:ci]] + [H * 0.06])
            lim_bot = min([c[0].y0 for c in caps[ci + 1:]] + [H * 0.94])
            rect = _region(page, r, kind, lim_top, lim_bot, claimed)
            if rect is None:
                continue
            claimed.append(rect)
            seen.add(key)
            word = "Figure" if kind == "figure" else "Table"
            if re.match(r"^\s*[<\[(]?\s*(그림|표)", t):
                word = "그림" if kind == "figure" else "표"
            items.append({
                "id": ("F" if kind == "figure" else "T") + num, "kind": kind, "num": num,
                "label": f"{word} {num}", "caption": t.strip(), "title": title, "page": pi + 1, "y": r.y0,
                "image": _png(page, rect), "rows": _table_rows(page, rect) if kind == "table" else None,
                "context": _context(text, kind, num, title)})
    items.sort(key=lambda it: (it["page"], it["y"]))
    return {"items": items, "n_pages": len(doc)}


# ------------------------------------------------------------------ 설명 생성 (Qwen)
DESC_SYS = """당신은 기술 표준 문서 분석가이다. 각 그림/표에 대해 국문 제목과 개조식 설명을 작성한다.
규칙:
- 근거는 제공된 '원문 캡션', '본문 언급 문장', '표 데이터'(그리고 이미지가 첨부된 경우 그 이미지)뿐임.
  이미지가 없으면 그림 내부를 볼 수 없으므로 색·모양·배치 등 시각 요소를 지어내지 말 것.
- 근거가 부족하면 설명을 1문장으로 짧게 쓸 것(캡션 내용을 풀어 쓰는 수준). 근거에 없는 센서 종류·수치·기능을 덧붙이지 말 것.
- 수치·표준번호·약어(RSU, RV, HV, CP, V2X, IoU, CDF 등)는 원문 그대로 유지.
- 국문 제목은 자연스러운 한국어로: "Illustration of X" → "X 개념도", "Example of X" → "X 예시", "Relationship between A and B" → "A와 B의 관계". 직역투(일러스트레이션 등) 금지.
- 설명은 2~4개 문장, 각 문장은 ~함/~임/~음/~됨 으로 끝나는 개조식 한국어. 중국어 한자 금지.
- 반드시 JSON 객체만 출력: {"items":[{"id":"F1","title_ko":"국문 제목","desc":["설명1","설명2"]}]}"""


def _payload(it):
    d = {"id": it["id"], "구분": "그림" if it["kind"] == "figure" else "표", "원문 캡션": it["caption"],
         "본문 언급": it["context"][:3]}
    if it.get("rows"):
        d["표 데이터"] = "\n".join(" | ".join(r) for r in it["rows"][:12])[:900]
    return d


VISION_RULE = """
[그림 이미지 첨부됨] 메시지에 첨부된 이미지는 items 순서와 같은 순서임(첫 번째 이미지 = 첫 번째 item).
- 이 경우 그림·표에 실제로 보이는 요소(구성 요소 이름, 축·범례, 화살표 관계, 표의 열과 대표 값)를 근거로 설명할 것.
- 이미지에 보이지 않거나 글자가 흐려 읽을 수 없는 내용은 추측하지 말 것."""


def _small_b64(data: bytes, max_side=896) -> str:
    """비전 입력용 축소 이미지(base64). 토큰·메모리 절약."""
    import base64
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def describe(items, chat_fn, doc_name="", mode="detail", progress=None, batch=4, vision=False):
    """mode: detail(설명+제목) | title(국문 제목만) | none. vision=True 면 그림 이미지를 함께 보냄.
    items 에 title_ko, desc 를 채운다."""
    if mode == "none":
        for it in items:
            it["title_ko"], it["desc"] = it["title"], []
        return items
    vision = vision and mode == "detail"
    size = (3 if vision else batch) if mode == "detail" else 12
    for bi in range(0, len(items), size):
        group = items[bi: bi + size]
        if progress:
            progress(bi / max(len(items), 1), f"✍️ 설명 작성 중... {bi + 1}~{bi + len(group)} / {len(items)}")
        req = [_payload(it) for it in group]
        if mode == "title":
            for r in req:
                r.pop("본문 언급", None)
                r.pop("표 데이터", None)
        instr = ("각 항목의 국문 제목(title_ko)만 작성하고 desc 는 빈 배열로 둘 것." if mode == "title"
                 else "각 항목의 국문 제목(title_ko)과 설명(desc)을 작성할 것.")
        by_id = {it["id"]: it for it in group}

        def ask(reqs):
            msg = f"대상 문서: {doc_name}\n{instr}\n\n" + json.dumps(reqs, ensure_ascii=False)
            user = {"role": "user", "content": msg}
            sys_prompt = DESC_SYS
            if vision:
                user["images"] = [_small_b64(by_id[r["id"]]["image"]) for r in reqs]
                sys_prompt = DESC_SYS + VISION_RULE
            for attempt in range(2):
                try:
                    out = chat_fn([{"role": "system", "content": sys_prompt}, user],
                                  {"temperature": 0.2 + 0.1 * attempt, "num_ctx": 8192, "num_predict": 1800},
                                  fmt="json")
                    data = json.loads(out)
                    res = {str(x.get("id")): x for x in data.get("items", []) if isinstance(x, dict)}
                    if res:
                        return res
                except Exception:
                    continue
            return {}

        got = ask(req)
        missing = [r for r in req if r["id"] not in got]
        for r in missing:                          # 묶음 응답이 실패한 항목은 하나씩 다시 요청
            got.update(ask([r]))
        for it in group:
            g = got.get(it["id"], {})
            it["title_ko"] = (g.get("title_ko") or it["title"]).strip()
            it["desc"] = [str(x).strip() for x in g.get("desc", []) if str(x).strip()][:4]
    if progress:
        progress(1.0, "✅ 설명 작성 완료")
    return items


def to_markdown(items, doc_name: str, vision: bool = False):
    """문서(마크다운) + 그림 사전 {키: bytes} 반환."""
    figs = [i for i in items if i["kind"] == "figure"]
    tabs = [i for i in items if i["kind"] == "table"]
    images = {it["id"]: it["image"] for it in items}
    md = [f"# {doc_name} 그림·표 정리", "",
          f"□ (대상 문서) {doc_name}",
          f"  ㅇ (추출 결과) 그림 {len(figs)}개, 표 {len(tabs)}개 추출함",
          ("    ※ 설명은 그림 이미지와 원문 캡션·본문 언급 문장·표 데이터를 근거로 AI가 작성함 (검토 필요)" if vision else
           "    ※ 설명은 원문 캡션과 본문 언급 문장, 표 데이터를 근거로 작성됨 (그림 내부를 직접 판독한 것은 아님)"), "",
          "## 1. 그림·표 목록", "", "| 번호 | 국문 제목 | 원문 제목 | 쪽 |", "|---|---|---|---|"]
    for it in figs + tabs:
        ko_label = ("그림 " if it["kind"] == "figure" else "표 ") + it["num"]
        md.append(f"| {ko_label} | {it.get('title_ko', '').replace('|', '/')} | {it['title'].replace('|', '/')} | {it['page']} |")
    for sec_no, (name, group) in enumerate((("그림", figs), ("표", tabs)), 2):
        if not group:
            continue
        md += ["", f"## {sec_no}. {name}", ""]
        for it in group:
            ko_label = ("그림 " if it["kind"] == "figure" else "표 ") + it["num"]
            md += [f"### {ko_label}. {it.get('title_ko') or it['title']}", "",
                   f"![{it['caption']} (원문 {it['page']}쪽)](img:{it['id']})", ""]
            for j, d in enumerate(it.get("desc") or []):
                md.append(("□ " if j == 0 else "  ㅇ ") + d)
            if not it.get("desc"):
                md.append("  ㅇ (원문 캡션) " + it["caption"])
            if it.get("context"):
                c = it["context"][0]
                md.append(f"    ※ 본문 언급(원문): {c[:220]}{'…' if len(c) > 220 else ''}")
            md.append("")
    return "\n".join(md), images
