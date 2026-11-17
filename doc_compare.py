"""문서 비교(신구대조표): 두 판의 문서를 맞대어 수정·신설·삭제를 찾고 바뀐 글자를 표시한다.
- 대조 자체는 AI 없이 글자 비교로 하므로 빠르고, 없는 차이를 지어내지 않음
- '제N조' 가 3개 이상이면 조문 단위로, 아니면 문단(줄) 단위로 맞춤
- AI 는 찾은 차이를 읽고 '주요 변경 요약'을 쓸 때만 사용"""
import difflib
import io
import re

ART = re.compile(r"^\s*(제\s*\d+\s*조(?:\s*의\s*\d+)?)")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def split_units(text: str):
    """반환: ([(열쇠 또는 None, 표시 이름, 본문)], '조문'|'문단')"""
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n")]
    lines = [l for l in lines if l]
    if sum(bool(ART.match(l)) for l in lines) >= 3:
        units, cur = [], None
        for l in lines:
            m = ART.match(l)
            if m:
                key = _norm(m.group(1))
                cur = [key, key, [l]]
                units.append(cur)
            elif cur:
                cur[2].append(l)
            else:
                units.append([None, "", [l]])                   # 첫 조문 앞의 머리말
        seen, out = {}, []
        for key, label, body in units:
            if key:                                              # 부칙 등에서 같은 조 번호가 다시 나오면 구분
                seen[key] = seen.get(key, 0) + 1
                if seen[key] > 1:
                    key, label = f"{key}#{seen[key]}", f"{label}({seen[key]}번째)"
            out.append((key, label, "\n".join(body)))
        return out, "조문"
    return [(None, "", l) for l in lines], "문단"


def _segments(old: str, new: str):
    """글자 단위 차이 → (현행 조각[(글, 지워짐)], 개정 조각[(글, 새로 들어옴)])"""
    tok = re.compile(r"\d[\d,.]*\d|\d|[A-Za-z]+|\s+|.", re.S)      # 숫자·영문 낱말은 통째로 (12억→15억 에서 '2→5'가 아니라 '12→15')
    ta, tb = tok.findall(old), tok.findall(new)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    a, b = [], []

    def push(lst, text, flag):
        if lst and lst[-1][1] == flag:
            lst[-1] = (lst[-1][0] + text, flag)
        else:
            lst.append((text, flag))

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if i2 > i1:
            push(a, "".join(ta[i1:i2]), tag != "equal")
        if j2 > j1:
            push(b, "".join(tb[j1:j2]), tag != "equal")
    return a, b


def _row(kind, label, old, new):
    if kind == "수정":
        a, b = _segments(old, new)
    else:
        a, b = ([(old, True)] if old else []), ([(new, True)] if new else [])
    return {"kind": kind, "label": label, "old": old, "new": new, "old_seg": a, "new_seg": b}


def _pair_block(olds, news, rows):
    """서로 다른 구간 안에서 닮은 문단끼리 짝지음 (순서 유지). 닮은 게 없으면 삭제·신설로 처리."""
    i = 0
    for n in news:
        best, bi = 0.0, -1
        for k in range(i, min(len(olds), i + 8)):
            r = difflib.SequenceMatcher(None, _norm(olds[k]), _norm(n), autojunk=False).ratio()
            if r > best:
                best, bi = r, k
        if best >= 0.5:
            for o in olds[i:bi]:
                rows.append(_row("삭제", "", o, ""))
            rows.append(_row("수정", "", olds[bi], n))
            i = bi + 1
        else:
            rows.append(_row("신설", "", "", n))
    for o in olds[i:]:
        rows.append(_row("삭제", "", o, ""))


def compare(old_text: str, new_text: str) -> dict:
    """반환: {'rows':[{kind,label,old,new,old_seg,new_seg}], 'mode', 'stats':{수정,신설,삭제,동일}, 'similarity'}"""
    ctrl = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")   # 깨진 글꼴 PDF의 제어문자: 워드·엑셀 저장을 막음
    old_text, new_text = ctrl.sub("", old_text or ""), ctrl.sub("", new_text or "")
    ua, ma = split_units(old_text)
    ub, mb = split_units(new_text)
    rows, same = [], 0
    if ma == mb == "조문":
        mode = "조문"
        amap = {k: (lab, body) for k, lab, body in ua if k}
        bkeys = {k for k, _, _ in ub if k}
        # 머리말(조문 앞 부분)은 문단 비교
        pre_a = [body for k, _, body in ua if not k]
        pre_b = [body for k, _, body in ub if not k]
        if pre_a != pre_b:
            _pair_block([p for p in pre_a if p not in pre_b], [p for p in pre_b if p not in pre_a], rows)
        same += len(set(pre_a) & set(pre_b))
        order_a = [k for k, _, _ in ua if k]
        done = set()
        for k, lab, body in ub:
            if not k:
                continue
            # 이 조문보다 앞에 있던 삭제 조문을 제자리에 끼움
            if k in amap:
                pos = order_a.index(k)
                for g in order_a[:pos]:
                    if g not in bkeys and g not in done:
                        rows.append(_row("삭제", amap[g][0], amap[g][1], ""))
                        done.add(g)
                if _norm(amap[k][1]) == _norm(body):
                    same += 1
                else:
                    rows.append(_row("수정", lab, amap[k][1], body))
            else:
                rows.append(_row("신설", lab, "", body))
        for g in order_a:
            if g not in bkeys and g not in done:
                rows.append(_row("삭제", amap[g][0], amap[g][1], ""))
    else:
        mode = "문단"
        A = [body for _, _, body in ua]
        B = [body for _, _, body in ub]
        sm = difflib.SequenceMatcher(None, [_norm(x) for x in A], [_norm(x) for x in B], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                same += i2 - i1
            elif tag == "delete":
                rows += [_row("삭제", "", o, "") for o in A[i1:i2]]
            elif tag == "insert":
                rows += [_row("신설", "", "", n) for n in B[j1:j2]]
            else:
                _pair_block(A[i1:i2], B[j1:j2], rows)
    stats = {k: sum(r["kind"] == k for r in rows) for k in ("수정", "신설", "삭제")}
    stats["동일"] = same
    sim = difflib.SequenceMatcher(None, _norm(old_text)[:200000], _norm(new_text)[:200000], autojunk=True).quick_ratio()
    return {"rows": rows, "mode": mode, "stats": stats, "similarity": round(sim * 100, 1)}


# ---------------------------------------------------------------- 출력
def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def to_html(res: dict, old_name="현행", new_name="개정안", limit: int = 400) -> str:
    """화면 미리보기용 표 (지워진 글자 빨간 취소선, 새 글자 파란 밑줄)."""
    def cell(segs, cls):
        return "".join(f'<span class="{cls}">{_esc(t)}</span>' if f else _esc(t) for t, f in segs)
    trs = "".join(
        f'<tr><td class="k k{("수정", "신설", "삭제").index(r["kind"])}">{r["kind"]}'
        + (f'<div class="lab">{_esc(r["label"])}</div>' if r["label"] else "")
        + f'</td><td>{cell(r["old_seg"], "del")}</td><td>{cell(r["new_seg"], "ins")}</td></tr>'
        for r in res["rows"][:limit])
    more = (f'<p class="more">차이 {len(res["rows"])}건 중 앞 {limit}건만 표시했습니다. 전체는 내려받은 파일에 있습니다.</p>'
            if len(res["rows"]) > limit else "")
    return f"""<style>
.cmp{{width:100%;border-collapse:collapse;font-size:14px;line-height:1.65;table-layout:fixed;font-family:'Malgun Gothic','Noto Sans KR',sans-serif}}
.cmp th{{background:#1F3864;color:#fff;padding:8px;border:1px solid #1F3864}}
.cmp td{{padding:8px 10px;border:1px solid #c9ced6;vertical-align:top;word-break:break-all;background:#fff;color:#1b1f24}}
.cmp td.k{{width:76px;text-align:center;font-weight:600}} .cmp th:first-child{{width:76px}}
.cmp .k0{{color:#9a5b0e}} .cmp .k1{{color:#0b6b3a}} .cmp .k2{{color:#b3261e}}
.cmp .lab{{font-weight:400;font-size:12px;color:#555;margin-top:2px}}
.cmp .del{{color:#b3261e;text-decoration:line-through;background:#fdecea}}
.cmp .ins{{color:#0b57d0;text-decoration:underline;background:#e8f0fe;font-weight:600}}
.more{{font:13px 'Malgun Gothic',sans-serif;color:#666}}
</style><table class="cmp"><tr><th>구분</th><th>{_esc(old_name)}</th><th>{_esc(new_name)}</th></tr>{trs}</table>{more}"""


def to_markdown(res: dict, old_name="현행", new_name="개정안") -> str:
    """글자 표시 없는 단순 표 (HWPX·PDF 내보내기와 보관함 저장용)."""
    def c(s):
        return s.replace("|", "｜").replace("\n", " ") or "-"
    st = res["stats"]
    out = ["# 신구대조표", "",
           f"- 대상: {old_name} → {new_name}", f"- 차이: 수정 {st['수정']}건, 신설 {st['신설']}건, 삭제 {st['삭제']}건 (동일 {st['동일']}건)", "",
           f"| 구분 | 현행 | 개정안 |", "|---|---|---|"]
    for r in res["rows"]:
        out.append(f"| {r['kind']}{(' ' + r['label']) if r['label'] else ''} | {c(r['old'])} | {c(r['new'])} |")
    return "\n".join(out)


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")


def _clean_res(res):
    """저장 직전 한 번 더: 표의 모든 글자에서 제어문자 제거(워드·엑셀은 제어문자가 있으면 저장 실패)."""
    rows = []
    for r in res.get("rows", []):
        r = dict(r)
        for k in ("label", "old", "new"):
            r[k] = _CTRL.sub("", r.get(k) or "")
        for k in ("old_seg", "new_seg"):
            r[k] = [(_CTRL.sub("", t), f) for t, f in (r.get(k) or [])]
        rows.append(r)
    return {**res, "rows": rows}


def to_docx(res: dict, old_name="현행", new_name="개정안", summary: str = "") -> bytes:
    """가로 A4 신구대조표. 개정안의 바뀐 글자는 굵은 밑줄(파랑), 현행의 지워진 글자는 취소선(빨강)."""
    res, summary = _clean_res(res), _CTRL.sub("", summary or "")
    old_name, new_name = _CTRL.sub("", old_name), _CTRL.sub("", new_name)
    import docx
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    d = docx.Document()
    sec = d.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Mm(297), Mm(210)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Mm(15))

    def font(run, size=10, bold=False, color=None, underline=False, strike=False):
        run.font.name = "맑은 고딕"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
        run.font.size, run.font.bold, run.font.underline, run.font.strike = Pt(size), bold, underline, strike
        if color:
            run.font.color.rgb = RGBColor(*color)

    def shade(cell, hex_):
        tcPr = cell._element.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_)
        tcPr.append(shd)

    p = d.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    font(p.add_run("신 구 대 조 표"), 18, True)
    st = res["stats"]
    font(d.add_paragraph().add_run(f"{old_name}  →  {new_name}    (수정 {st['수정']}건 · 신설 {st['신설']}건 · 삭제 {st['삭제']}건)"), 9,
         color=(0x55, 0x55, 0x55))
    if summary.strip():
        font(d.add_paragraph().add_run("주요 변경 요약"), 11, True)
        for line in summary.strip().split("\n"):
            if line.strip():
                font(d.add_paragraph().add_run(re.sub(r"^#+\s*", "", line)), 10)
    t = d.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    t.autofit = False
    widths = (Mm(22), Mm(122), Mm(122))
    for i, (cell, name) in enumerate(zip(t.rows[0].cells, ("구분", old_name, new_name))):
        cell.width = widths[i]
        shade(cell, "1F3864")
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        font(cell.paragraphs[0].add_run(name), 10, True, (0xFF, 0xFF, 0xFF))
    for r in res["rows"]:
        cells = t.add_row().cells
        for i, c in enumerate(cells):
            c.width = widths[i]
        cells[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        font(cells[0].paragraphs[0].add_run(r["kind"] + (("\n" + r["label"]) if r["label"] else "")), 9, True)
        for cell, segs, style in ((cells[1], r["old_seg"], dict(color=(0xB3, 0x26, 0x1E), strike=True)),
                                  (cells[2], r["new_seg"], dict(color=(0x0B, 0x57, 0xD0), underline=True, bold=True))):
            para = cell.paragraphs[0]
            for txt, flag in segs:
                font(para.add_run(txt), 9.5, **(style if flag else {}))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_xlsx(res: dict, old_name="현행", new_name="개정안") -> bytes:
    res = _clean_res(res)
    old_name, new_name = _CTRL.sub("", old_name), _CTRL.sub("", new_name)
    import xlsxwriter
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("신구대조표")
    base = {"font_name": "맑은 고딕", "font_size": 10}
    f_head = wb.add_format({**base, "bold": True, "font_color": "#FFFFFF", "bg_color": "#1F3864", "align": "center", "border": 1})
    f_cell = wb.add_format({**base, "text_wrap": True, "valign": "top", "border": 1})
    f_kind = wb.add_format({**base, "bold": True, "align": "center", "valign": "top", "border": 1, "text_wrap": True})
    f_del = wb.add_format({**base, "font_color": "#B3261E", "font_strikeout": True})
    f_ins = wb.add_format({**base, "font_color": "#0B57D0", "bold": True, "underline": 1})
    f_norm = wb.add_format(base)
    ws.set_column(0, 0, 12)
    ws.set_column(1, 2, 62)
    ws.freeze_panes(1, 0)
    for c, name in enumerate(("구분", old_name, new_name)):
        ws.write(0, c, name, f_head)

    def rich(row, col, segs, fmt):
        segs = [(t[:8000], f) for t, f in segs if t]
        if not segs:
            ws.write_blank(row, col, None, f_cell)
        elif len(segs) == 1:
            ws.write_string(row, col, segs[0][0], wb.add_format({**base, "text_wrap": True, "valign": "top", "border": 1,
                                                               **({"font_color": "#B3261E", "font_strikeout": True} if segs[0][1] and fmt is f_del else
                                                                  {"font_color": "#0B57D0", "bold": True} if segs[0][1] else {})}))
        else:
            parts = []
            for t, f in segs:
                parts += [fmt if f else f_norm, t]
            if ws.write_rich_string(row, col, *parts, f_cell) != 0:      # 조각이 너무 많으면 일반 글자로
                ws.write_string(row, col, "".join(t for t, _ in segs), f_cell)

    for i, r in enumerate(res["rows"], 1):
        ws.write(i, 0, r["kind"] + (("\n" + r["label"]) if r["label"] else ""), f_kind)
        rich(i, 1, r["old_seg"], f_del)
        rich(i, 2, r["new_seg"], f_ins)
    wb.close()
    return buf.getvalue()


# ---------------------------------------------------------------- AI 요약
SYS = """너는 공공기관 문서의 개정 내용을 검토하는 담당자다. [차이 목록]에 있는 내용만 근거로 한국어 개조식으로 정리한다.
- 형식: `## 주요 변경 사항` 아래 중요한 순서로 3~8개 (□ 항목, 필요하면 - 하위). 이어서 `## 확인이 필요한 사항` 1~4개.
- 수치·기한·금액·주체·의무 수준(해야 한다/할 수 있다)이 바뀌었으면 '전 → 후' 값을 그대로 적는다.
- 조문 번호나 항목 이름이 있으면 앞에 밝힌다. 단순 오탈자·띄어쓰기 수정은 한 줄로 묶는다.
- 목록에 없는 배경·이유·효과를 지어내지 않는다. ~함/~임 어미."""


def digest(res: dict, budget: int = 5600):
    """AI 에 줄 차이 목록 (변화가 큰 것부터 예산만큼). 반환: (텍스트, 포함 건수)"""
    def size(r):
        return sum(len(t) for t, f in r["old_seg"] + r["new_seg"] if f)
    items, used = [], 0
    for r in sorted(res["rows"], key=size, reverse=True):
        if r["kind"] == "수정":
            chg_a = " / ".join(t for t, f in r["old_seg"] if f)[:160]
            chg_b = " / ".join(t for t, f in r["new_seg"] if f)[:160]
            s = f"[수정] {r['label']} (현행) {r['old'][:230]} → (개정) {r['new'][:230]} | 바뀐 글자: '{chg_a}' → '{chg_b}'"
        else:
            s = f"[{r['kind']}] {r['label']} {(r['new'] or r['old'])[:330]}"
        if used + len(s) > budget:
            break
        items.append((res["rows"].index(r), s))
        used += len(s)
    return "\n".join(s for _, s in sorted(items)), len(items)


def summarize(res: dict, chat_fn, old_name="현행", new_name="개정안", stream_callback=None) -> str:
    text, n = digest(res)
    note = "" if n >= len(res["rows"]) else f"\n(차이 {len(res['rows'])}건 중 변화가 큰 {n}건만 제시됨. 이 사실을 첫 줄에 밝힐 것.)"
    out = chat_fn([{"role": "system", "content": SYS},
                   {"role": "user", "content": f"[문서] {old_name} → {new_name}{note}\n\n[차이 목록]\n{text}"}],
                  {"temperature": 0.2}, stream_callback=stream_callback)
    return out.strip()
