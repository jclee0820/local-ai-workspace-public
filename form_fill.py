"""HWPX 서식 채우기: '각 보고서에 대한 자문의견서를 ○○.hwpx 양식대로' 같은 요청용.

문제였던 방식: 서식까지 포함한 모든 파일을 한 문서로 이어 붙여 75조각 요약 → 하나의 종합 보고서(요청·서식 무시, 수 시간 소요).
이 모듈의 방식:
1) 올린 HWPX 중 채울 칸('O'·'ㅇ'·'○' 같은 빈 글머리 줄)이 있는 것을 서식으로 인식하고 원문에서 뺀다.
2) 서식 표에서 [보고서 칸] → [항목명(주요 검토의견·보완 개선사항 …)] → [빈 줄 개수]를 읽는다.
3) 서식의 보고서 번호·제목과 올린 원문 파일을 짝짓는다(③ 와 3 은 같은 번호로 봄).
4) 보고서마다 목차 구조를 따라 핵심만 골라(AI 없이) 한 번에 의견을 쓴다 — 보고서당 AI 호출 1회(+수치 오류 시 1회).
5) 서식의 빈 줄 개수에 맞춰 같은 글자 모양으로 채워 넣고, 나머지 서식은 손대지 않는다."""
import copy
import io
import json
import re
import zipfile

from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
NS = {"hp": HP, "hh": HH, "hc": HC}
HANG = 950            # 'O ' 폭(10pt 기준, HWPUNIT) — 줄이 넘어가면 이 위치에 맞춤(내어쓰기)
BULLET = re.compile(r"^\s*(?:O|o|ㅇ|○|◦|●|•|-|□|■|※)?\s*$")
CIRCLED = {c: str(i) for i, c in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳", 1)}
FORM_WORD = re.compile(r"양식|서식|형식|틀|준수|채워|작성\s*칸")
EACH_WORD = re.compile(r"각각|각\s*(보고서|문서|자료|파일)|(보고서|문서|자료|파일)\s*(별|마다)|건별|개별")


# ------------------------------------------------------------------ 서식 읽기
def _t(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def _para_text(p):
    return "".join(t.text or "" for t in p.iter(f"{{{HP}}}t"))


def _cells(tbl):
    out = []
    for tc in tbl.iter(f"{{{HP}}}tc"):
        if tc.getparent().getparent() is not tbl:          # 중첩 표 제외
            continue
        a, s = tc.find("hp:cellAddr", NS), tc.find("hp:cellSpan", NS)
        sub = tc.find("hp:subList", NS)
        paras = sub.findall("hp:p", NS) if sub is not None else []
        out.append({"el": tc, "col": int(a.get("colAddr")), "row": int(a.get("rowAddr")),
                    "rspan": int(s.get("rowSpan", "1")) if s is not None else 1,
                    "paras": paras, "text": "\n".join(_para_text(p).strip() for p in paras).strip()})
    return out


def _is_slot(c):
    return c["paras"] and all(BULLET.match(_para_text(p)) for p in c["paras"]) and \
        any(_para_text(p).strip() for p in c["paras"])


def parse_form(data: bytes) -> dict:
    """반환: {'slots':[{'section','label','count','bullet','cell'}], 'root', 'zipdata'} — 채울 칸이 없으면 slots 빈 목록."""
    z = zipfile.ZipFile(io.BytesIO(data))
    root = etree.fromstring(z.read("Contents/section0.xml"))
    slots = []
    for tbl in root.iter(f"{{{HP}}}tbl"):
        cells = _cells(tbl)
        by_pos = {(c["col"], c["row"]): c for c in cells}
        for c in cells:
            if not _is_slot(c):
                continue
            label = ""
            for dc in range(c["col"] - 1, -1, -1):                       # 같은 줄 왼쪽의 항목명
                lc = by_pos.get((dc, c["row"]))
                if lc and lc["text"] and not _is_slot(lc):
                    label = lc["text"]
                    break
            sec = ""
            for s in cells:                                                # 이 줄을 덮는 맨 왼쪽(보고서) 칸
                if s["col"] == 0 and s["row"] <= c["row"] < s["row"] + s["rspan"] and s["text"] and s["text"] != label:
                    sec = s["text"]
            sym = _para_text(c["paras"][0]).strip() or "O"
            slots.append({"section": sec, "label": label, "count": sum(1 for p in c["paras"] if _para_text(p).strip()) or 1,
                          "bullet": sym, "cell": c, "tbl": tbl})
    return {"slots": slots, "root": root, "zipdata": data, "header": etree.fromstring(z.read("Contents/header.xml"))}


def is_form(name: str, data: bytes) -> bool:
    if not name.lower().endswith(".hwpx"):
        return False
    try:
        return len(parse_form(data)["slots"]) >= 1
    except Exception:
        return False


def find_form(files, instr: str):
    """올린 파일 [(name, bytes)] 중 서식 1개를 고른다. 요청에 양식·서식 말이 있거나 파일 이름이 요청에 나올 때만."""
    if not instr:
        return None
    flat = re.sub(r"\s+", "", instr)
    cands = [(n, d) for n, d in files if is_form(n, d)]
    named = [(n, d) for n, d in cands if re.sub(r"\s+", "", n.rsplit(".", 1)[0]) in flat]
    if named:
        return named[0]
    if cands and FORM_WORD.search(instr):
        return cands[0]
    return None


def wants_each(instr: str) -> bool:
    return bool(EACH_WORD.search(instr or ""))


# ------------------------------------------------------------------ 보고서 ↔ 원문 짝짓기
def _code(s):
    m = re.search(r"\[([^\]]{3,20})\]", s or "")
    if not m:
        return ""
    return "".join(CIRCLED.get(ch, ch) for ch in m.group(1) if CIRCLED.get(ch, ch).isalnum())


def _grams(s):
    s = re.sub(r"[\s\W_]+", "", (s or "").lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def match_sources(sections, sources):
    """sections: 서식의 보고서 칸 글자 목록, sources: [(파일명, 본문)] → {section: (파일명, 본문)}"""
    out, used = {}, set()
    for sec in sections:
        best, score = None, 0.0
        for n, t in sources:
            if n in used:
                continue
            sc = 0.0
            if _code(sec) and _code(sec) == _code(n):
                sc += 1.0
            a, b = _grams(re.sub(r"\[[^\]]*\]", "", sec)), _grams(re.sub(r"\[[^\]]*\]|\.\w+$", "", n))
            if a and b:
                sc += len(a & b) / len(a)
            if sc > score:
                best, score = (n, t), sc
        if best and score >= 0.45:
            out[sec] = best
            used.add(best[0])
    return out


# ------------------------------------------------------------------ 보고서 요점 추리기 (AI 없이)
HEAD = re.compile(r"(?m)^\s*(제\s*\d+\s*장[^\n]*|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.\s*[^\n]*|\d{1,2}\.(?:\d{1,2}\.?)?\s+[가-힣A-Za-z][^\n]{0,60})$")
CONCL = re.compile(r"결론|요약|시사점|종합|향후|제언|맺음|한계|개선\s*방향|추진\s*방안")


def digest(text: str, budget: int = 7000) -> str:
    """보고서 전체 흐름을 한 번에 볼 수 있는 요점본 (AI 없이).
    ① 목차(장·절 제목)를 개요로 모으고 ② 본문 절마다 길이에 비례해 앞부분을 담고 ③ 결론·시사점 절은 더 담는다.
    표지의 깨진 글자(글꼴 정보 없는 PDF)와 점선 목차 줄은 버린다."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    lines = [l for l in text.split("\n") if not re.search(r"[·.…]{6,}\s*\d*\s*$", l) and not re.match(r"^\s*-\s*[ivx\d]+\s*-\s*$", l)]
    body = "\n".join(lines)
    marks = [m.start() for m in HEAD.finditer(body)]
    if len(marks) < 3:
        return re.sub(r"[ \t]+", " ", body)[:budget]
    marks = [0] + marks
    secs = [body[a:b].strip() for a, b in zip(marks, marks[1:] + [len(body)]) if body[a:b].strip()]
    outline = list(dict.fromkeys(re.sub(r"\s+", " ", s.split("\n", 1)[0]).strip()[:40] for s in secs[1:]))
    outline_txt = "[목차] " + " / ".join(outline)[:900]
    big = [s for s in secs if len(s) >= 200]                         # 목차 조각(제목만 있는 짧은 덩어리)은 본문에서 제외
    room = max(budget - len(outline_txt), 2000)
    weight = [len(s) ** 0.5 * (1.8 if CONCL.search(s.split("\n", 1)[0]) else 1.0) for s in big]
    tot = sum(weight) or 1
    out = [outline_txt]
    for s, w in zip(big, weight):
        head, _, rest = s.partition("\n")
        n = max(180, int(room * w / tot))
        out.append(head.strip()[:70] + "\n" + re.sub(r"\s+", " ", rest).strip()[:n])
    return "\n\n".join(out)[:budget + 300]


# ------------------------------------------------------------------ 의견 작성
SYS = """당신은 해당 분야의 자문위원이다. 기술보고서를 검토하고 자문의견서 칸을 채운다.
[작성 원칙]
- 각 문장은 보고서의 실제 내용(장·절, 방법, 수치, 결론)을 짚어서 쓴다. 보고서에 없는 사실·수치를 만들지 않는다.
- 요약이 아니라 '평가'를 쓴다: 주요 검토의견 = 타당성·충실성·논리 일관성·활용성에 대한 판단, 보완 개선사항 = 구체적으로 무엇을 어떻게 보완할지.
- 칭찬·과장 없이 객관적으로. 한 항목은 1~2문장, 120자 안팎. 개조식 명사형 어미(~함, ~필요, ~바람직).
- 글머리 기호(O, -, 번호)는 쓰지 않는다(서식에 이미 있음).
{user_rule}
출력 JSON: {{{schema}}}"""


def _schema(labels):
    return ", ".join(f'"{l}": ["…" × {n}개]' for l, n in labels)


def write_opinions(chat_fn, sec_title, src_name, text, labels, user_instr="", check=True):
    """labels: [(항목명, 줄 수)] → {항목명: [문장…]}"""
    import fact_check
    dg = digest(text)
    rule = f"- 사용자 지시: {user_instr.strip()[:400]}" if user_instr else ""
    msgs = [{"role": "system", "content": SYS.format(user_rule=rule, schema=_schema(labels))},
            {"role": "user", "content": f"[검토 대상] {sec_title.replace(chr(10), ' ')}\n(원문 파일: {src_name})\n"
                                        f"[보고서 요점 — 목차 순서]\n{dg}\n\n"
                                        "항목별 개수를 정확히 지켜 JSON 으로만 답하라."}]
    opts = {"temperature": 0.2, "num_ctx": 8192, "num_predict": 900}
    res, note = {}, ""
    for attempt in range(2):
        m = msgs if not note else msgs + [{"role": "user", "content": note}]
        try:
            d = json.loads(chat_fn(m, opts, fmt="json"))
        except Exception:
            d = {}
        res = {}
        for l, n in labels:
            v = d.get(l) or next((d[k] for k in d if re.sub(r"\s", "", k) == re.sub(r"\s", "", l)), [])
            v = [re.sub(r"^\s*(?:O|ㅇ|○|-|•|\d+[.)])\s*", "", str(x)).strip().rstrip(".。") for x in (v if isinstance(v, list) else [v])
                 if str(x).strip()]                              # 개조식: 문장 끝 마침표 통일(없음)
            res[l] = v[:n]
        if not check:
            break
        fc = fact_check.check("\n".join(sum(res.values(), [])), text)
        if not fc["missing"] or attempt:
            res["_numcheck"] = fc
            break
        note = ("다음 수치는 보고서 원문에서 찾을 수 없다. 이 수치를 빼거나 원문 수치로 고쳐 다시 써라: "
                + ", ".join(x["num"] for x in fc["missing"][:8]))
    return res


# ------------------------------------------------------------------ 서식에 써 넣기
def _set_para(p, text):
    ts = list(p.iter(f"{{{HP}}}t"))
    if ts:
        ts[0].text = text
        for t in ts[1:]:
            t.text = ""
    for lsa in p.findall("hp:linesegarray", NS):                 # 줄 배치 정보는 지우면 한글이 다시 계산
        p.remove(lsa)


def _text_units(s):
    """글자 폭 합(한글·전각 1, 영문·숫자·공백 약 0.55) — 줄 수 추정용"""
    return sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in s)


def _grow_row(s, need):
    """채운 글이 칸 높이를 넘으면 그 줄의 칸·이 줄을 덮는 병합 칸·표 전체 높이를 함께 늘린다(한글은 고정 높이를 그대로 써서 글이 테두리에 겹침)."""
    cell, tbl = s["cell"], s["tbl"]
    sz = cell["el"].find("hp:cellSz", NS)
    cur = int(sz.get("height", "0"))
    if need <= cur:
        return
    delta = need - cur
    for c in _cells(tbl):
        csz = c["el"].find("hp:cellSz", NS)
        if c["row"] == cell["row"] and c["rspan"] == 1:
            csz.set("height", str(need))
        elif c["row"] <= cell["row"] < c["row"] + c["rspan"]:
            csz.set("height", str(int(csz.get("height", "0")) + delta))
    tsz = tbl.find("hp:sz", NS)
    if tsz is not None:
        tsz.set("height", str(int(tsz.get("height", "0")) + delta))


def _need_height(cell_el, lines_text, font=1000, spacing=1.6, indent=0):
    sz, mg = cell_el.find("hp:cellSz", NS), cell_el.find("hp:cellMargin", NS)
    width = int(sz.get("width", "28000")) - (int(mg.get("left", "510")) + int(mg.get("right", "510")) if mg is not None else 1020)
    per_line = max(10.0, width / font * 1.03)                      # 한글 실측 보정(공백·문장부호가 좁음). 겹치는 것보다 약간 넉넉한 쪽을 택함
    rest = max(10.0, (width - indent) / font * 1.03)               # 내어쓰기한 둘째 줄부터는 폭이 좁음
    lines = sum(1 + max(0, -(-(_text_units(t) - per_line) // rest)) for t in lines_text)
    pad = (int(mg.get("top", "141")) + int(mg.get("bottom", "141")) if mg is not None else 282) + 450
    return int(lines * font * spacing + pad)


def _hang_para_pr(header, base_id, hang=HANG):
    """기존 문단 모양(base_id)을 복사해 내어쓰기(첫 줄 0, 다음 줄부터 hang)를 준 새 문단 모양을 추가하고 id 반환."""
    props = header.find(".//hh:paraProperties", NS)
    base = next((p for p in props.findall("hh:paraPr", NS) if p.get("id") == str(base_id)), None)
    if base is None:
        return base_id
    new = copy.deepcopy(base)
    nid = max(int(p.get("id")) for p in props.findall("hh:paraPr", NS)) + 1
    new.set("id", str(nid))
    for mg in new.iter(f"{{{HH}}}margin"):
        for tag, val in (("intent", -hang), ("left", hang)):
            el = mg.find(f"hc:{tag}", NS)
            if el is not None:
                el.set("value", str(val))
    props.append(new)
    props.set("itemCnt", str(len(props.findall("hh:paraPr", NS))))
    return nid


def _new_para(proto, text, para_pr=None):
    """문단을 단일 run/t 로 새로 만든다(글자 모양은 원래 첫 run 것, 줄 배치 정보 없음 → 한글이 다시 계산)."""
    p = etree.Element(proto.tag, dict(proto.attrib))
    if para_pr is not None:
        p.set("paraPrIDRef", str(para_pr))
    r0 = proto.find("hp:run", NS)
    run = etree.SubElement(p, f"{{{HP}}}run", {"charPrIDRef": r0.get("charPrIDRef", "0") if r0 is not None else "0"})
    etree.SubElement(run, f"{{{HP}}}t").text = text
    return p


def fill(form: dict, answers: dict, hang: bool = True) -> bytes:
    """answers: {(section, label): [문장…]} → 채운 HWPX 바이트. hang: 줄이 넘어가면 'O ' 다음 글자 위치에 맞춤."""
    hang_ids = {}
    for s in form["slots"]:
        items = answers.get((s["section"], s["label"]))
        if not items:
            continue
        cell = s["cell"]
        sub = cell["el"].find("hp:subList", NS)
        proto = next(p for p in cell["paras"] if _para_text(p).strip())
        base = proto.get("paraPrIDRef", "0")
        pp = None
        if hang:
            if base not in hang_ids:
                hang_ids[base] = _hang_para_pr(form["header"], base)
            pp = hang_ids[base]
        for p in list(sub.findall("hp:p", NS)):
            sub.remove(p)
        lines = []
        for it in items:
            sub.append(_new_para(proto, f"{s['bullet']} {it}", pp))
            lines.append(f"{s['bullet']} {it}")
        _grow_row(s, _need_height(cell["el"], lines, indent=HANG if hang else 0))
    xml = etree.tostring(form["root"], xml_declaration=True, encoding="UTF-8", standalone=True)
    hxml = etree.tostring(form["header"], xml_declaration=True, encoding="UTF-8", standalone=True)
    zi = zipfile.ZipFile(io.BytesIO(form["zipdata"]))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zo:
        for info in zi.infolist():                                # 순서·압축 방식 그대로(mimetype 맨 앞 무압축)
            data = {"Contents/section0.xml": xml, "Contents/header.xml": hxml}.get(info.filename) or zi.read(info.filename)
            if info.filename == "Preview/PrvText.txt":
                continue
            zo.writestr(info, data, compress_type=info.compress_type)
    return buf.getvalue()


# ------------------------------------------------------------------ 전체
def _label_kind(label):
    return "개선사항" if re.search(r"개선|보완|요구|조치", label or "") else "검토의견"


def run(form_name, form_data, sources, chat_fn, instr="", progress=None, raw=None, precise=False):
    """sources: [(파일명, 본문)] (서식 제외), raw: {파일명: 원본 바이트}.
    precise=True 이면 PDF 원문에 대해 report_review(규칙 점검 + 장 단위 AI 검토 + 인용 검증 + 교차 확인)로 작성.
    반환: {'hwpx','markdown','matched','unmatched','numcheck','evidence'}"""
    if precise:
        return _run_precise(form_name, form_data, sources, chat_fn, progress, raw or {})
    say = progress or (lambda f, m: None)
    form = parse_form(form_data)
    order = []
    for s in form["slots"]:
        if s["section"] not in order:
            order.append(s["section"])
    real = [x for x in order if x]
    match = match_sources(real, sources) if real else {}
    if not real and len(sources) == 1:                            # 보고서 칸이 없는 단일 서식 → 원문 1개에 대해 작성
        match = {"": sources[0]}
    answers, md, numck = {}, [f"# {form_name.rsplit('.', 1)[0].strip()} (작성 결과)"], {}
    todo = [s for s in order if s in match]
    for i, sec in enumerate(todo):
        name, text = match[sec]
        labels = [(s["label"] or "의견", s["count"]) for s in form["slots"] if s["section"] == sec]
        title = sec.replace("\n", " ") or name
        say(0.05 + 0.9 * i / max(len(todo), 1), f"✍️ [{i + 1}/{len(todo)}] {title[:40]} 의견 작성 중...")
        res = write_opinions(chat_fn, sec or name, name, text, labels, instr)
        numck[title] = res.pop("_numcheck", None)
        md.append(f"\n## {title}\n")
        for l, _ in labels:
            answers[(sec, l if l != "의견" else "")] = res.get(l, [])
            md.append(f"**{l}**\n" + "\n".join(f"- {x}" for x in res.get(l, [])) + "\n")
    say(1.0, "✅ 서식 채우기 완료")
    unmatched = [s.replace("\n", " ") for s in real if s not in match]
    return {"hwpx": fill(form, answers), "markdown": "\n".join(md), "matched": {k.replace("\n", " "): v[0] for k, v in match.items()},
            "unmatched": unmatched, "numcheck": numck, "evidence": None}


def _run_precise(form_name, form_data, sources, chat_fn, progress, raw):
    import report_review as rr
    say = progress or (lambda f, m: None)
    form = parse_form(form_data)
    order = list(dict.fromkeys(s["section"] for s in form["slots"]))
    real = [x for x in order if x]
    match = match_sources(real, sources) if real else ({"": sources[0]} if len(sources) == 1 else {})
    todo = [s for s in order if s in match]
    answers, md, ev = {}, [f"# {form_name.rsplit('.', 1)[0].strip()} (정밀 검토 결과)"], {"자동점검": {}, "LLM검토_원본": {}, "폐기항목": {}, "채택근거": {}}
    numck = {}
    for i, sec in enumerate(todo):
        name, text = match[sec]
        title = sec.replace("\n", " ").strip() or name
        base = 0.02 + 0.96 * i / max(len(todo), 1)
        say(base, f"🔎 [{i + 1}/{len(todo)}] {title[:40]} — 규칙 점검·AI 검토 시작")
        data = raw.get(name)
        if not data or not name.lower().endswith(".pdf"):           # PDF 가 아니면 쪽 정보가 없어 빠른 방식으로
            res = write_opinions(chat_fn, sec or name, name, text, [(s["label"] or "의견", s["count"]) for s in form["slots"] if s["section"] == sec])
            res.pop("_numcheck", None)
            out = {_label_kind(l): v for l, v in res.items()}
        else:
            r = rr.review_report(chat_fn, title, data, say=lambda m, b=base: say(b, f"🔎 [{i + 1}/{len(todo)}] {m}"))
            out = r["text"]
            ev["자동점검"][title] = r["rules"]
            ev["LLM검토_원본"][title] = r["llm_raw"]
            ev["폐기항목"][title] = r["dropped"]
            ev["채택근거"][title] = r["findings"]
        md.append(f"\n## {title}\n")
        for s in form["slots"]:
            if s["section"] != sec:
                continue
            items = out.get(_label_kind(s["label"]), [])
            answers[(sec, s["label"])] = items
            md.append(f"**{s['label'] or '의견'}**\n" + "\n".join(f"- {x}" for x in items) + "\n")
    say(1.0, "✅ 정밀 검토 완료")
    return {"hwpx": fill(form, answers), "markdown": "\n".join(md), "matched": {k.replace("\n", " "): v[0] for k, v in match.items()},
            "unmatched": [s.replace("\n", " ") for s in real if s not in match], "numcheck": numck, "evidence": ev}
