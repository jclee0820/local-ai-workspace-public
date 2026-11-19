"""원 소스 보고서 → 발표 슬라이드 (장·절 구조를 따라 한 장씩 만듦).

예전 방식(보고서 요약 9천 자를 넣고 한 번에 15장 JSON 생성)은 8192 문맥에 출력이 잘려 앞 몇 장만 남거나,
요약이 뒤쪽 장만 남아 보고서 일부만 다루는 문제가 있었다. 여기서는
  1) 원문에서 장(제N장)·절(제N절)·소단원(1. …)·표([표 N-N] + 행)·그림([그림 N-N]) 을 코드로 찾고,
  2) 요청 장수만큼 장·절 경계를 지키며 원문 분량에 비례해 슬라이드를 배분한 뒤,
  3) 슬라이드마다 해당 부분 원문만 넣어 LLM 을 한 번씩 호출(출력이 짧아 잘리지 않음),
  4) 표는 원문 표를 그대로(행·열만 줄여) 쓰고, PDF 그림은 캡션 위 영역을 잘라 넣는다."""
import json
import re

import exporters
import llm_client
from md_parser import clean_inline, _extract_json

TAB_CAP = re.compile(r"^\s*[\[<]\s*표\s*([0-9]+(?:[-.][0-9]+)*)\s*[\]>]\s*(.*)$")
FIG_CAP = re.compile(r"^\s*[\[<]\s*그림\s*([0-9]+(?:[-.][0-9]+)*)\s*[\]>]\s*(.*)$")
CHAP = re.compile(r"^\s*제\s*(\d+)\s*장\s*(.*)$")
SECT = re.compile(r"^\s*제\s*(\d+)\s*절\s*(\S.{0,40})$")
SUB = re.compile(r"^\s*(\d{1,2})\.\s*(\S.{1,40})$")
PAGE_NO = re.compile(r"^\s*[-–]\s*\d+\s*[-–]\s*$")


# ------------------------------------------------------------------ 원문 구조
def _clean_cell(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    s = re.sub(r"(?:\s[.,·])+(?=\s|$)", "", s)                     # PDF 표에서 떨어져 나온 ' . ,' 부스러기
    s = re.sub(r"\s+-\s+-(?=\s|$)", "", s)
    return s.strip(" ,")


def _rows(lines):
    rows = []
    for ln in lines:
        cells = [c for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in cells):
            continue
        rows.append([_clean_cell(c) for c in cells])
    return rows


def parse(text: str):
    """→ (chapters, units). unit: {chap, sect, sub, text, tables:[{num,caption,rows}], figures:[{num,caption}]}"""
    lines = text.splitlines()
    freq = {}
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("|"):
            freq[s] = freq.get(s, 0) + 1
    running = {s for s, n in freq.items() if n >= 4 and len(s) > 12}          # 쪽마다 반복되는 머리말·꼬리말
    chap_title, best = {}, {}
    for s, k in freq.items():                                              # 장 제목: 가장 자주 나오는 '제N장 제목' 줄
        m = CHAP.match(s)
        if m and m.group(2).strip() and (k, len(s)) > best.get(m.group(1), (0, 0)):
            best[m.group(1)], chap_title[m.group(1)] = (k, len(s)), m.group(2).strip()
    units, cur = [], None
    chap = sect = ""
    sub_no = chap_no = 0

    def new(sub=""):
        nonlocal cur
        cur = {"chap": chap, "sect": sect, "sub": sub, "lines": [], "tables": [], "figures": []}
        units.append(cur)

    i = 0
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if not s or PAGE_NO.match(s) or s in running:
            continue
        m = CHAP.match(s)
        if m and len(s) < 60 and int(m.group(1)) >= chap_no and (
                not m.group(2).strip() or best.get(m.group(1), (0,))[0] >= 2):     # 본문 속 '제2장 …' 문장 제외
            n = m.group(1)
            chap_no = int(n)
            t = chap_title.get(n) or m.group(2).strip()
            if not m.group(2).strip() and i < len(lines) and lines[i].strip() and not t:
                t = lines[i].strip()
            new_chap = f"제{n}장 {t}".strip()
            if new_chap != chap:
                chap, sect, sub_no = new_chap, "", 0
                cur = None
            if not m.group(2).strip() and i < len(lines) and lines[i].strip() == t:
                i += 1                                                     # '제4장' 다음 줄의 장 제목
            continue
        m = SECT.match(s)
        if m and chap and not s.endswith(("함", "음", "임", "됨", "다.")):
            sect, sub_no = f"제{m.group(1)}절 {m.group(2).strip()}", 0
            new()
            continue
        if re.fullmatch(r"제\s*\d+\s*[장절]", s):                          # 목차의 번호만 있는 줄
            continue
        m = SUB.match(s)
        if m and sect and int(m.group(1)) == sub_no + 1 and not re.search(r"(다\.|함|음|임|됨)$", s):
            sub_no += 1
            new(f"{m.group(1)}. {m.group(2).strip()}")
            continue
        if cur is None:
            if not chap:
                continue
            new()
        m = TAB_CAP.match(s)
        if m:
            tl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tl.append(lines[i])
                i += 1
            rows = _rows(tl)
            if len(rows) >= 2:
                cur["tables"].append({"num": m.group(1), "caption": m.group(2).strip(), "rows": rows})
            cur["lines"].append(f"[표 {m.group(1)}] {m.group(2).strip()}")
            continue
        m = FIG_CAP.match(s)
        if m:
            cur["figures"].append({"num": m.group(1), "caption": m.group(2).strip()})
            cur["lines"].append(s)
            continue
        if s.startswith("|"):                                               # 캡션 없는 표
            tl = [lines[i - 1]]
            while i < len(lines) and lines[i].strip().startswith("|"):
                tl.append(lines[i])
                i += 1
            rows = _rows(tl)
            if len(rows) >= 2:
                cur["tables"].append({"num": "", "caption": "", "rows": rows})
            continue
        cur["lines"].append(s)
    for u in units:
        u["text"] = "\n".join(u.pop("lines"))
    units = [u for u in units if len(u["text"]) > 40 or u["tables"] or u["figures"]]
    chapters = []
    for u in units:
        if u["chap"] not in chapters:
            chapters.append(u["chap"])
    return chapters, units


def _size(u):
    return len(u["text"]) + 300 * len(u["tables"]) + 300 * len(u["figures"])


def _partition(items, k, key=_size, brk=None):
    """순서를 지킨 채 k 묶음으로 나눔: 묶음 크기가 고르게, brk(i)=True 인 경계(절 바뀜)에서 끊는 것을 선호."""
    n = len(items)
    k = max(1, min(k, n))
    sz = [key(x) for x in items]
    tot = sum(sz) or 1
    target = tot / k
    pre = [0]
    for v in sz:
        pre.append(pre[-1] + v)
    INF = float("inf")
    dp = [[INF] * (n + 1) for _ in range(k + 1)]
    cut = [[0] * (n + 1) for _ in range(k + 1)]
    dp[0][0] = 0
    for g in range(1, k + 1):
        for j in range(g, n + 1):
            for i in range(g - 1, j):
                if dp[g - 1][i] == INF:
                    continue
                c = ((pre[j] - pre[i]) - target) ** 2
                if brk and 0 < i < n and not brk(i):
                    c += (target * 0.35) ** 2                              # 절 중간에서 끊으면 벌점
                if dp[g - 1][i] + c < dp[g][j]:
                    dp[g][j], cut[g][j] = dp[g - 1][i] + c, i
    out, j = [], n
    for g in range(k, 0, -1):
        i = cut[g][j]
        out.append(items[i:j])
        j = i
    return out[::-1]


def plan(chapters, units, n):
    """n 장을 장별 분량에 비례해 배분(장마다 최소 1장) → 장 안에서 절 경계를 살려 나눔. → [[unit…]…]"""
    n = max(1, n)
    by = [[u for u in units if u["chap"] == c] for c in chapters]
    if n < len(by):                                                        # 장 수보다 적으면 장끼리 묶음
        return [sum(g, []) for g in _partition(by, n, key=lambda us: sum(_size(u) for u in us))]
    sizes = [sum(_size(u) for u in us) for us in by]
    tot = sum(sizes) or 1
    alloc = [1] * len(by)
    for _ in range(n - len(by)):                                           # 남은 장수: 1장당 분량이 가장 큰 장에 하나씩
        j = max(range(len(by)), key=lambda c: sizes[c] / alloc[c] if alloc[c] < len(by[c]) else -1)
        if alloc[j] >= len(by[j]):
            break
        alloc[j] += 1
    groups = []
    for us, k in zip(by, alloc):
        groups += _partition(us, k, brk=lambda i, us=us: us[i]["sect"] != us[i - 1]["sect"])
    return groups


# ------------------------------------------------------------------ PDF 그림 잘라내기
def pdf_figures(pdf_bytes: bytes, dpi=160):
    """캡션 '[그림 N-N]' 바로 위의 그림 영역을 PNG 로. → {num: png bytes}. 60쪽 기준 1초 안쪽."""
    import pymupdf as fitz
    out = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for pg in doc:
        W, H = pg.rect.width, pg.rect.height
        blocks = [b for b in pg.get_text("blocks") if b[6] == 0]
        draws = imgs = None
        for b in blocks:
            m = FIG_CAP.match(b[4].strip())
            if not m or m.group(1) in out:
                continue
            if draws is None:
                draws = [fitz.Rect(d["rect"]) for d in pg.get_drawings()]
                imgs = [fitz.Rect(x["bbox"]) for x in pg.get_image_info()]
            cy = b[1]
            top = H * 0.07
            for o in blocks:                                               # 위쪽 본문 글(긴 줄)·다른 캡션 아래부터
                t = o[4].strip()
                if o[3] <= cy - 2 and ((len(t) > 45 and o[2] - o[0] > W * 0.55) or TAB_CAP.match(t) or FIG_CAP.match(t)):
                    top = max(top, o[3])
            els = [r for r in draws + imgs if r.y0 >= top - 1 and r.y1 <= cy + 1 and r.height < H * 0.8
                   and not (r.height < 3 and r.width > W * 0.6)]               # 머리말 가로줄 제외
            if els:
                r = fitz.Rect(els[0])
                for e in els[1:]:
                    r |= e
                r = fitz.Rect(max(r.x0 - 4, 0), max(r.y0 - 4, top), min(r.x1 + 4, W), cy - 2)
            else:
                r = fitz.Rect(W * 0.08, top, W * 0.92, cy - 2)
            if r.height < 40 or r.width < 60:
                continue
            out[m.group(1)] = pg.get_pixmap(clip=r, dpi=dpi).tobytes("png")
    return out


# ------------------------------------------------------------------ 슬라이드 한 장씩 생성
ONE = """JSON 객체 하나만 출력하라. 형식:
{"title":"슬라이드 제목(25자 이내)","icon":"영어 단어 1개","keypoint":"핵심 메시지 한 문장(45자 이내)",
 "bullets":["대항목","  하위 항목","  하위 항목","대항목","  하위 항목", …],
 "visual":"표 4-1" 또는 "그림 4-2" 또는 "새 표" 또는 "없음",
 "table":[["구분","항목","내용"],["…","…","…"]] 또는 null,
 "notes":"발표자 노트 2~3문장"}
규칙:
- bullets: 대항목 3개, 대항목마다 하위 항목 1~2개(앞에 공백 2칸). 기호(□ ㅇ -) 붙이지 말 것. 한 줄 40자 이내.
- 원문에 있는 수치·기간·금액·표준번호·고유명사를 적극적으로 넣는다. 원문에 없는 내용·수치는 절대 만들지 않는다.
- visual: [이 부분의 표·그림] 목록에서 이 슬라이드를 가장 잘 보여 주는 것 1개의 번호를 그대로 적는다(예: "표 4-3").
  목록이 비었거나 맞는 것이 없으면 "새 표"로 하고 table 에 원문 내용으로 비교·정리 표(3~6행, 3~4열, 칸당 20자 이내)를 만든다.
  visual 이 표·그림 번호면 table 은 null."""


def _brief_tables(u, limit=6):
    out = []
    for t in u["tables"][:limit]:
        if not t["num"]:
            continue
        head = " | ".join(t["rows"][0])[:80]
        out.append(f"- 표 {t['num']} {t['caption']} (열: {head}; {len(t['rows']) - 1}행)")
    for f in u["figures"]:
        out.append(f"- 그림 {f['num']} {f['caption']}")
    return out


def _fit_table(rows, max_rows=8, max_cols=5, cell=42):
    rows = [r[:max_cols] for r in rows if any(c.strip() for c in r)]
    nc = max(len(r) for r in rows)
    rows = [r + [""] * (nc - len(r)) for r in rows]
    if nc >= 2:                                                            # 첫 열이 위 행과 같으면 비움(병합 셀 효과)
        for j in range(len(rows) - 1, 1, -1):
            if rows[j][0] and rows[j][0] == rows[j - 1][0]:
                rows[j][0] = ""
    body = rows[1:max_rows]
    return [[(c if len(c) <= cell else c[:cell - 1] + "…") for c in r] for r in [rows[0]] + body]


def _gae(s, narrative):
    s = exporters.strip_non_korean_cjk(clean_inline(str(s)))
    return s if narrative else exporters.to_gaejosik(s).strip()


def _trim_groups(bl, max_lines=11):
    """대항목 단위로 잘라 하위 항목 없는 대항목이 끝에 덩그러니 남지 않게."""
    out, grp = [], []
    for b in bl + [(0, None)]:
        if b[0] == 0 and grp:
            if len(out) + len(grp) > max_lines:
                break
            out += grp
            grp = []
        if b[1] is not None:
            grp.append(b)
    return out or bl[:max_lines]


def build_slide(group, focus, src_name, system, options, budget, style_rule="", narrative=False, figures=None,
                fig=None, used_titles=()):
    """fig: 이 장에 꼭 쓸 그림 번호(덱 전체에서 그림이 고르게 들어가도록 build 가 정함)."""
    figures = figures or {}
    chap = group[0]["chap"]
    sects = []
    for u in group:
        lab = " ".join(x for x in (u["sect"], u["sub"]) if x)
        if lab and lab not in sects:
            sects.append(lab)
    body = "\n\n".join((f"## {u['sect']} {u['sub']}".strip() + "\n" + u["text"]) for u in group)
    if len(body) > budget:
        import form_fill
        body = form_fill.digest(body, budget)
    vis = [v for u in group for v in _brief_tables(u)]
    figs = {f["num"]: f for u in group for f in u["figures"]}
    fixed = ""
    if fig and fig in figs:
        fixed = (f"\n- 이 슬라이드의 시각자료는 「그림 {fig} {figs[fig]['caption']}」로 정해져 있다. visual 은 \"그림 {fig}\", "
                 "table 은 null. bullets 는 그림이 보여 주는 구조·흐름·수치를 원문 근거로 풀어 설명한다.")
    dup = ("\n- 앞 슬라이드에서 이미 쓴 제목과 겹치지 않게, 이 부분만의 내용을 드러내는 제목을 쓴다: "
           + " / ".join(used_titles[-6:])) if used_titles else ""
    ask = (f"[발표 초점] {focus}\n" if focus else "") + \
          f"아래는 보고서 「{chap}」 중 {', '.join(sects[:4]) or '일부'} 부분 원문이다. 이 부분으로 발표 슬라이드 1장을 만든다.\n" + \
          (f"[문체] {style_rule}\n" if style_rule else "") + ONE + fixed + dup + \
          "\n\n[이 부분의 표·그림]\n" + ("\n".join(vis) if vis else "(없음)") + "\n\n[원문]\n" + body
    raw = llm_client.chat([{"role": "system", "content": system}, {"role": "user", "content": ask}],
                          {**options, "num_predict": 1400}, fmt="json")
    d = _extract_json(raw) or {}
    if not isinstance(d, dict):
        d = {}
    bl = []
    for b in d.get("bullets") or []:
        s = str(b)
        if not s.strip():
            continue
        lvl = min((len(s) - len(s.lstrip())) // 2, 2)
        bl.append((lvl, _gae(s.strip().lstrip("□ㅇ○-•▪· "), narrative)))
    tables = {t["num"]: t for u in group for t in u["tables"] if t["num"]}
    v = str(d.get("visual") or "")
    m = re.search(r"(표|그림)\s*([0-9]+(?:[-.][0-9]+)*)", v)
    table = image = caption = None
    if fig and fig in figs and fig in figures:
        image, caption = figures[fig], f"[그림 {fig}] {figs[fig]['caption']}"
    elif m and m.group(1) == "표" and m.group(2) in tables:
        t = tables[m.group(2)]
        table, caption = _fit_table(t["rows"]), f"[표 {t['num']}] {t['caption']}"
    elif m and m.group(1) == "그림" and m.group(2) in figs and m.group(2) in figures:
        image, caption = figures[m.group(2)], f"[그림 {m.group(2)}] {figs[m.group(2)]['caption']}"
    elif isinstance(d.get("table"), list) and len(d["table"]) >= 2 and all(isinstance(r, list) for r in d["table"]):
        table = _fit_table([[_gae(c, True) for c in r] for r in d["table"]])
    if table is None and image is None:                                      # LLM 이 고르지 않았으면 코드가 고름
        if tables:
            t = max(tables.values(), key=lambda t: min(len(t["rows"]), 8) * min(len(t["rows"][0]), 4))
            table, caption = _fit_table(t["rows"]), f"[표 {t['num']}] {t['caption']}"
        else:
            hit = [k for k in figs if k in figures]
            if hit:
                image, caption = figures[hit[0]], f"[그림 {hit[0]}] {figs[hit[0]]['caption']}"
    title = _gae(d.get("title") or (group[0]["sub"] or group[0]["sect"] or chap), True)
    title = re.sub(r"^\d+\.\s*", "", title)
    if title in used_titles:                                                   # 앞 장과 같은 제목 → 이 장의 표·그림·소단원 이름으로
        cands = [re.sub(r"\s*\([^)]*\)\s*$", "", re.sub(r"^\[(표|그림)\s*[\d.-]+\]\s*", "", caption or "")).strip(),
                 re.sub(r"^\d+\.\s*", "", next((u["sub"] for u in group if u["sub"]), "")),
                 re.sub(r"^제\s*\d+\s*절\s*", "", group[0]["sect"]), f"{title} ({len(used_titles) + 1})"]
        title = next(a for a in cands if a and a not in used_titles)
    src = f"{src_name} {chap.split(' ')[0]} {group[0]['sect'].split(' ')[0]}".strip()
    return {"title": title, "keypoint": _gae(d.get("keypoint") or "", narrative), "bullets": _trim_groups(bl, 9 if (table or image) else 12),
            "table": table, "image": image, "caption": caption, "icon": str(d.get("icon") or "").strip(),
            "notes": str(d.get("notes") or ""), "source": src, "chapter": chap}


def deck_title(chapters, focus, names, system, options):
    ask = ("아래 보고서의 발표 자료 표지 제목과 부제를 정하라. JSON 만: {\"title\":\"30자 이내\",\"subtitle\":\"40자 이내\"}\n"
           f"[파일] {names}\n[장 구성] " + " / ".join(chapters) + (f"\n[발표 요청] {focus}" if focus else ""))
    d = _extract_json(llm_client.chat([{"role": "system", "content": system}, {"role": "user", "content": ask}],
                                      {**options, "num_predict": 200}, fmt="json")) or {}
    return clean_inline(str(d.get("title") or names)), clean_inline(str(d.get("subtitle") or ""))


def build(sources, n, focus="", system="", options=None, style_rule="", narrative=False, careful=True, progress=None):
    """sources: [(파일명, 텍스트, 원본 bytes)] → parse_slides 와 같은 모양의 dict (+ chapter·image·caption)."""
    options = dict(options or {})
    chapters, units, figures = [], [], {}
    for name, text, data in sources:
        ch, us = parse(text)
        if not us:                                                           # 장·절이 안 잡히는 문서: 문단 덩어리로
            paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()] or [text]
            us = [{"chap": name, "sect": "", "sub": "", "text": p, "tables": [], "figures": []} for p in paras]
            ch = [name]
        for u in us:
            u["src"] = name
        chapters += [c for c in ch if c not in chapters]
        units += us
        if data and name.lower().endswith(".pdf"):
            try:
                figures.update(pdf_figures(data))
            except Exception:
                pass
    groups = plan(chapters, units, n)
    budget = 5200 if careful else 2600
    names = ", ".join(nm for nm, _, _ in sources)
    if progress:
        progress(0.02, f"📑 장 {len(chapters)}개 · 단원 {len(units)}개 · 표 {sum(len(u['tables']) for u in units)}개 · "
                       f"그림 {len(figures)}개 확인 → 슬라이드 {len(groups)}장 배분")
    title, subtitle = deck_title(chapters, focus, names, system, options)
    # 그림 배정: 그림이 있는 장 중 약 1/3 장수까지, 표가 적은(그림이 더 핵심인) 장부터. 장마다 첫 그림.
    cand = []
    for k, g in enumerate(groups):
        fs = [f["num"] for u in g for f in u["figures"] if f["num"] in figures]
        if fs:
            cand.append((sum(len(u["tables"]) for u in g), k, fs[0]))
    quota = max(1, -(-len(groups) // 3)) if cand else 0
    fig_of = {k: f for _, k, f in sorted(cand)[:quota]}
    slides = []
    for k, g in enumerate(groups):
        if progress:
            progress((k + 1) / (len(groups) + 1), f"✍️ 슬라이드 {k + 1}/{len(groups)} 작성 중 — {g[0]['chap'][:30]}")
        src_name = re.sub(r"\.[A-Za-z0-9]+$", "", g[0]["src"])
        try:
            slides.append(build_slide(g, focus, src_name, system, options, budget, style_rule, narrative, figures,
                                      fig_of.get(k), [s["title"] for s in slides]))
        except Exception as e:                                               # 한 장 실패해도 나머지는 계속
            slides.append({"title": g[0]["sub"] or g[0]["sect"] or g[0]["chap"], "keypoint": "", "chapter": g[0]["chap"],
                           "bullets": [(0, f"생성 실패: {e}")], "table": None, "image": None, "notes": "", "source": ""})
    return {"title": title, "subtitle": subtitle, "slides": slides, "chapters": chapters}
