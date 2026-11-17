"""R&D 보고서 정밀 검토 — 기계적으로 가능한 점검은 코드가, 판단·문장은 로컬 LLM이.

1) 쪽 단위 추출: PDF 쪽마다 본문과 '인쇄 쪽번호'(- N -)를 읽고, 번호 없는 간지는 앞뒤로 보간
2) 규칙 점검(AI 없음): 참조 무결성, 표 제목 중복, 총계 수치 불일치, 목적·시나리오-결과 대응, 목차-본문 제목,
   가중합 재계산, 등급 일관성·건수, 약어 오기, 문단 중복, 미확정 표현
3) LLM 검토: 장 단위 + 목차·규칙 점검 결과를 함께 주고, 의견마다 원문 인용·쪽수를 요구
4) 인용 검증: 인용이 원문에 없으면 폐기, 쪽수가 틀리면 원문 위치로 교정, 보고서가 이미 밝힌 내용을 '없다'고 한 지적은 폐기
5) 교차 확인: 온도를 달리해 여러 번 실행, 2회 이상 나온 지적만 채택(규칙 점검은 그대로 채택)
6) 문장 정리: 칸마다 3~4개, 어미 규칙(검토의견 ~함/~음/~임, 개선사항 ~필요), 끝에 (p.N)
모든 결과는 JSON 으로 남겨 무엇이 왜 빠졌는지 확인할 수 있게 한다."""
import json
import re
from collections import Counter, defaultdict

# ================================================================== 1) 쪽 단위 추출
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
TOC_LINE = re.compile(r"[·.…]{6,}\s*\d*\s*$")


def load_pages(pdf_bytes: bytes):
    """[{'pdf':1, 'printed':N|None, 'text':..., 'toc':bool}] — 인쇄 쪽번호 기준, 번호 없는 쪽은 앞뒤로 보간."""
    import fitz
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for i, pg in enumerate(doc, 1):
        t = CTRL.sub("", pg.get_text())
        m = re.findall(r"(?m)^\s*-\s*(\d{1,3})\s*-\s*$", t)
        toc = sum(1 for l in t.split("\n") if TOC_LINE.search(l)) >= 3
        pages.append({"pdf": i, "printed": int(m[-1]) if m else None, "text": t, "toc": toc, "interp": False})
    known = [(i, p["printed"]) for i, p in enumerate(pages) if p["printed"] is not None]
    for i, p in enumerate(pages):                                  # 간지: 앞 번호 + 거리 (뒤 번호와 모순 없을 때만)
        if p["printed"] is not None or p["toc"]:
            continue
        prev = [(j, n) for j, n in known if j < i]
        nxt = [(j, n) for j, n in known if j > i]
        if prev:
            j, n = prev[-1]
            guess = n + (i - j)
            if not nxt or guess < nxt[0][1]:
                p["printed"], p["interp"] = guess, True
        elif nxt and nxt[0][1] - (nxt[0][0] - i) >= 1:
            p["printed"], p["interp"] = nxt[0][1] - (nxt[0][0] - i), True
    return pages


def _flat(s):
    return re.sub(r"\s+", " ", s)


def body_pages(pages):
    return [p for p in pages if not p["toc"] and p["printed"] is not None]


def pno(p):
    return p["printed"] if p["printed"] is not None else f"PDF{p['pdf']}"


# ================================================================== 2) 규칙 점검
CAP = re.compile(r"\[(표|그림)\s*(\d+(?:[-.]\d+)?)\]\s*([^\n\[]{2,60})")
REF = re.compile(r"(?<![\[가-힣])(표|그림)\s*(\d+(?:[-.]\d+)?)(?![\]\d%배점개])")   # '목표 2배', '지표 17' 제외
REF_B = re.compile(r"\[(표|그림)\s*(\d+(?:[-.]\d+)?)\]")


def _f(kind, text, pages, cite="", **kw):
    pages = sorted({x for x in pages if x is not None}, key=lambda v: (isinstance(v, str), v))
    return {"유형": kind, "내용": text, "쪽": pages, "근거": cite[:160], **kw}


def check_refs(pages):
    """본문이 언급한 표·그림·부록이 실제로 있는지."""
    out, caps = [], {}
    bp = body_pages(pages)
    for p in bp:
        for m in CAP.finditer(p["text"]):
            caps.setdefault((m.group(1), m.group(2)), []).append((pno(p), m.group(3).strip()))
    seen = defaultdict(list)
    norm = lambda n: n.replace(".", "-")
    capn = {(k, norm(n)) for k, n in caps}
    for p in bp:
        t = p["text"]
        for m in REF.finditer(t):
            seen[(m.group(1), norm(m.group(2)))].append(pno(p))
    for k, pgs in seen.items():
        if k not in capn and len(caps) >= 3 and any(c[0] == k[0] for c in caps):
            out.append(_f("참조 무결성", f"본문이 언급한 {k[0]} {k[1]}이(가) 보고서에 없음", pgs[:3]))
    # 부록: '(부록 B)' 처럼 언급만 있고 '부록 B' 제목(줄 맨 앞)이 없으면 누락
    apx_ref, apx_head = defaultdict(list), set()
    for p in pages:
        for m in re.finditer(r"부록\s*([A-ZＡ-Ｚ]|\d+|[가-하](?=[\s)]))", p["text"]):
            apx_ref[m.group(1)].append(pno(p))
        for m in re.finditer(r"(?m)^\s*\[?\s*부록\s*([A-ZＡ-Ｚ]|\d+|[가-하])[\]\s.]", p["text"]):
            if not p["toc"]:
                apx_head.add(m.group(1))
    for k, pgs in apx_ref.items():
        if k not in apx_head:
            cite = next((_flat(p["text"])[max(0, _flat(p["text"]).find("부록") - 60): _flat(p["text"]).find("부록") + 20]
                         for p in pages if "부록" in p["text"] and pno(p) == pgs[0]), "")
            out.append(_f("참조 무결성", f"본문이 참조한 부록 {k}이(가) 보고서에 없음", pgs[:3], cite))
    return out, caps


def check_dup_titles(caps):
    out, by_title = [], defaultdict(list)
    for (kind, num), lst in caps.items():
        for pg, title in lst:
            key = re.sub(r"\s+", "", title)
            if len(key) >= 4:
                by_title[(kind, key)].append((num, pg, title))
    for (kind, _), lst in by_title.items():
        nums = sorted({n for n, _, _ in lst})
        if len(nums) >= 2:
            out.append(_f("표 제목 중복", f"서로 다른 {kind}({', '.join(f'{kind} {n}' for n in nums)})에 같은 제목 '{lst[0][2]}'이 붙음",
                          [pg for _, pg, _ in lst], f"[{kind} {nums[0]}] {lst[0][2]}"))
    return out


ENT = r"(차로|지점|검지기|장비|구간|링크|건|개소|노드|기관|지자체|대)"


def check_totals(pages):
    """같은 대상의 '전체 개수'가 절마다 다른지 (예: 차로 합계 120개 vs 118개 차로 중)."""
    tot = defaultdict(list)
    pats = [re.compile(r"(차로|지점|검지기|장비|구간|링크|노드)\s*(?:의\s*)?(?:합계|총계|총|전체)\s*(?:는|은|가|이)?\s*(\d[\d,]*)\s*개"),
            re.compile(r"(\d[\d,]*)\s*개\s*(차로|지점|검지기|장비|구간|링크|노드)\s*중"),
            re.compile(r"(차로|지점|검지기|장비|구간|링크|노드)\s*\d[\d,]*\s*개\s*\(\s*(\d[\d,]*)\s*개\s*중\)")]
    for p in body_pages(pages):
        t = _flat(p["text"])
        for i, pat in enumerate(pats):
            for m in pat.finditer(t):
                ent, n = (m.group(1), m.group(2)) if i != 1 else (m.group(2), m.group(1))
                tot[ent].append((int(n.replace(",", "")), pno(p), t[max(0, m.start() - 30): m.end() + 20]))
    out = []
    for ent, lst in tot.items():
        vals = sorted({v for v, _, _ in lst})
        if len(vals) >= 2:
            desc = " / ".join(f"{v}개(p.{', '.join(str(x) for x in sorted({pg for vv, pg, _ in lst if vv == v}))})" for v in vals)
            out.append(_f("수치 불일치", f"전체 {ent} 수가 절마다 다름: {desc}", [pg for _, pg, _ in lst], lst[0][2], 값=vals))
    return out


def check_codes(pages):
    """시나리오·단계 코드(S1, S01 …): 정의 표에 있는데 이후 본문에 없거나, 본문에 있는데 정의 표에 없는 코드."""
    out = []
    bp = body_pages(pages)
    fam = defaultdict(lambda: defaultdict(set))                      # 접두어 → 코드 → 쪽
    for p in bp:
        for m in re.finditer(r"(?<![A-Za-z0-9])S(\d{1,2})(?![\d-])", p["text"]):
            fam["S"][m.group(0)].add(p["pdf"])
    for pre, codes in fam.items():
        if len(codes) < 3:
            continue
        per_page = Counter(pg for c in codes.values() for pg in c)
        defpg = per_page.most_common(1)[0][0]
        def_codes = {c for c, pgs in codes.items() if defpg in pgs or defpg + 1 in pgs and per_page[defpg + 1] >= 3}
        if len(def_codes) < 3:
            continue
        num = lambda c: int(c[1:])
        pad = Counter(len(c) for c in def_codes).most_common(1)[0][0]
        printed = {p["pdf"]: pno(p) for p in pages}
        txt = {p["pdf"]: _flat(p["text"]) for p in pages}
        for c, pgs in codes.items():
            if c not in def_codes and len(c) == pad and num(c) == max(num(x) for x in def_codes) + 1:
                cite_pg = min(pgs)
                pos = txt[cite_pg].find(c)
                out.append(_f("목록-본문 불일치", f"정의 표({min(def_codes, key=num)}~{max(def_codes, key=num)})에 없는 {c}가 본문에 나옴",
                              [printed[defpg]] + [printed[x] for x in pgs], txt[cite_pg][max(0, pos - 10): pos + 50]))
        later = [p["pdf"] for p in bp if p["pdf"] > defpg + 1]
        used_later = [c for c in def_codes if codes[c] & set(later)]
        if not used_later:                                        # 결과 장이 코드를 아예 안 쓰면 코드로는 판단 불가(장 예고 대조가 대신 봄)
            continue
        for c in sorted(def_codes, key=num):
            if later and not (codes[c] & set(later)):
                pos = txt[defpg].find(c)
                out.append(_f("목적-결과 대응", f"분석 시나리오 {c}가 정의 표 이후 결과 장에서 다뤄지지 않음",
                              [printed[defpg]], txt[defpg][max(0, pos - 5): pos + 60]))
    return out


def chapter_ranges(pages):
    """{장번호: (시작 PDF쪽, 끝 PDF쪽)} — 본문(목차 제외)의 '제N장' 첫 등장 기준."""
    starts = {}
    for p in pages:
        if p["toc"]:
            continue
        for m in re.finditer(r"(?m)^\s*제\s*(\d+)\s*장", p["text"]):
            starts.setdefault(int(m.group(1)), p["pdf"])
    order = sorted(starts.items(), key=lambda x: x[1])
    last = max(p["pdf"] for p in pages)
    return {n: (s, (order[i + 1][1] - 1) if i + 1 < len(order) else last) for i, (n, s) in enumerate(order)}


def check_roadmap(pages):
    """1장의 'N장은 X로/으로 …검증함' 예고와 실제 N장 내용 대조: 방법(X)이 그 장에 한 번도 나오지 않으면 목적-결과 불일치."""
    rng = chapter_ranges(pages)
    txt = {p["pdf"]: _flat(p["text"]) for p in pages}
    out = []
    for p in body_pages(pages)[:12]:
        t = _flat(p["text"])
        for m in re.finditer(r"(\d)\s*장(?:은|는|에서는)\s*([가-힣A-Za-z0-9 ·]{2,20}?)\s*(?:으로|로|를\s*통해|을\s*통해|을\s*활용하여|를\s*활용하여)\s*([^.()]{4,50}?(?:검증|평가|분석|확인|제시))", t):
            n, method = int(m.group(1)), m.group(2).strip()
            if n not in rng or len(re.sub(r"\s", "", method)) < 3:
                continue
            a, b = rng[n]
            body = " ".join(txt[i] for i in range(a, b + 1) if i in txt)
            key = re.sub(r"\s+", r"\\s*", re.escape(method).replace(r"\ ", " "))
            if not re.search(key, body):
                out.append(_f("목적-결과 대응", f"1장에서 '{n}장은 {method}(으)로 {m.group(3).strip()}'라고 했으나 {n}장에 '{method}' 내용이 없음",
                              [pno(p)], t[max(0, m.start() - 10): m.end() + 5]))
    return out


def check_toc(pages):
    """목차의 장 제목과 본문의 장 제목이 다른지."""
    toc, body = {}, {}
    for p in pages:
        for m in re.finditer(r"(?m)^\s*제\s*(\d+)\s*장\s*([^\n·.…]{2,40})", p["text"]):
            title = m.group(2).strip()
            (toc if p["toc"] else body).setdefault(int(m.group(1)), (title, pno(p)))
    out = []
    for n, (t, _) in toc.items():
        if n in body and re.sub(r"\s+", "", t) != re.sub(r"\s+", "", body[n][0]):
            out.append(_f("목차-본문 불일치", f"제{n}장 제목이 목차('{t}')와 본문('{body[n][0]}')에서 다름", [body[n][1]]))
    return out


def check_weights(pages):
    """가중치(%)와 항목 점수가 있는 표: 종합점수를 다시 계산해 차이 보고 + 같은 점수에 다른 등급 + 등급별 건수."""
    out = []
    bp = body_pages(pages)
    alltext = [( pno(p), _flat(p["text"])) for p in bp]
    for pg, t in alltext:
        for hm in re.finditer(r"((?:[가-힣A-Za-z]{1,6}\s*\d{1,2}\s*%\s*){4,8})(?:종합|합계|총점)", t):
            w = [int(x) for x in re.findall(r"(\d{1,2})\s*%", hm.group(1))]
            if abs(sum(w) - 100) > 1:
                continue
            k = len(w)
            row = re.compile(r"([A-Z]\d+-\d+)\s+(.{2,40}?)\s+((?:[1-5]\s+){%d})(\d\.\d{1,2})\s*([ABCDS](?:/[ABCDS])?)?" % k)
            rows = []
            for pg2, t2 in alltext:                                   # 표가 다음 쪽으로 이어질 수 있음
                if not (pg2 == pg or (isinstance(pg2, int) and isinstance(pg, int) and 0 < pg2 - pg <= 2)):
                    continue
                for m in row.finditer(t2):
                    sc = [int(x) for x in m.group(3).split()]
                    calc = round(sum(a * b for a, b in zip(sc, w)) / 100, 2)
                    rows.append({"code": m.group(1), "name": m.group(2).strip(), "scores": sc, "stated": float(m.group(4)),
                                 "calc": calc, "grade": m.group(5) or "", "page": pg2})
            seen, uniq = set(), []
            for r in rows:
                if r["code"] not in seen:
                    seen.add(r["code"])
                    uniq.append(r)
            bad = [r for r in uniq if abs(r["calc"] - r["stated"]) >= 0.015]
            if bad:
                ex = ", ".join(f"{r['code']} 표기 {r['stated']:.2f} 대 재계산 {r['calc']:.2f}" for r in bad[:4])
                out.append(_f("가중치 재계산", f"가중치({'·'.join(map(str, w))}%)로 다시 계산한 종합점수가 표 값과 다름 {len(bad)}건(예: {ex})",
                              [r["page"] for r in bad], hm.group(0)[:80], 행=[{k2: r[k2] for k2 in ("code", "stated", "calc", "grade")} for r in bad]))
            by_score = defaultdict(set)
            for r in uniq:
                if r["grade"]:
                    by_score[r["stated"]].add(r["grade"])
            mixed = {s: g for s, g in by_score.items() if len(g) > 1}
            if mixed:
                out.append(_f("등급 일관성", "같은 종합점수에 다른 등급: " + ", ".join(f"{s:.2f}→{'/'.join(sorted(g))}" for s, g in mixed.items()),
                              [pg]))
            for pg4, t4 in alltext:                                   # 'N개 세부기술' 서술과 표의 실제 행 수
                for m in re.finditer(r"(\d{1,3})\s*개\s*(세부\s*기술|세부기술|평가\s*대상|항목)", t4):
                    n = int(m.group(1))
                    if abs(n - len(uniq)) >= 1 and len(uniq) >= 8 and re.search(r"표|평가|점수", t4[max(0, m.start() - 30): m.end() + 30]) \
                            and n > 6 and n != k:
                        out.append(_f("수치 불일치", f"본문은 {n}개 {m.group(2)}라고 했으나 가중치 표에는 {len(uniq)}개 행이 있음",
                                      [pg4], t4[max(0, m.start() - 30): m.end() + 20]))
                        break
            cnt = Counter(r["grade"] for r in uniq if r["grade"])
            if cnt:
                claims = []
                for pg3, t3 in alltext:
                    for m in re.finditer(r"(?:A\s*등급\s*(?:은|는|이|가)?\s*(?:총\s*)?(\d{1,2})\s*(?:건|개))|(?:(\d{1,2})\s*(?:건|개)\s*(?:이|가)?\s*A\s*등급)", t3):
                        pre = t3[max(0, m.start() - 14): m.start()]
                        if re.search(r"T\d\s*\(|평균|,\s*$", pre) or t3[m.end(): m.end() + 1] == ")":
                            continue                                     # 'T4(4.15, 2건)' 같은 기술군별 부분 건수는 제외
                        claims.append((int(m.group(1) or m.group(2)), pg3, t3[max(0, m.start() - 40): m.end() + 10]))
                vals = sorted({c[0] for c in claims} | {cnt.get("A", 0)})
                if claims and len(vals) > 1:
                    desc = f"표의 A등급 {cnt.get('A', 0)}건" + "".join(f", p.{c[1]} 서술 {c[0]}건" for c in claims)
                    out.append(_f("등급 건수 불일치", f"A등급 건수가 서로 다름: {desc}", [c[1] for c in claims] + [pg], claims[0][2]))
    return out


KNOWN_ACR = {"RNN", "KNN", "CNN", "GNN", "MLP", "PCA", "PCT", "FNO", "EMS", "SSA", "SLA", "API", "GPS", "VDS", "VMS", "DSRC", "LSTM",
             "GRU", "ITS", "TCS", "CCTV", "AWS", "GPU", "CPU", "SQL", "XML", "JSON", "OCR", "LLM", "RAG", "MCP", "KPI", "TRL",
             "ISO", "CEN", "IEC", "KS", "TTA", "AHP", "BIS", "BMS", "DTG", "RSE", "OBU", "VDE", "HDM", "IDF"}


def check_acronyms(pages):
    """드물게 나온 약어가 자주 쓰인 약어와 한 글자만 다르고, 쓰인 문맥(앞뒤 단어)까지 그 약어와 같으면 오기 의심 (예: FRO ↔ FTO)."""
    cnt, where, ctx = Counter(), defaultdict(list), defaultdict(set)
    for p in body_pages(pages):
        t = _flat(p["text"])
        for m in re.finditer(r"(?<![A-Za-z])([A-Z]{3,5})(?![A-Za-z])", t):
            a = m.group(1)
            cnt[a] += 1
            around = t[max(0, m.start() - 30): m.end() + 30]
            where[a].append((pno(p), around))
            ctx[a] |= set(re.findall(r"[가-힣]{2,}", around))
    out = []
    for a, n in cnt.items():
        if n > 2 or a in KNOWN_ACR:
            continue
        mine = set().union(*[set(re.findall(r"[가-힣]{2,}", w[1])) for w in where[a]]) or {"_"}
        for b, nb in cnt.items():
            if nb >= 5 and len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1:
                if len(mine & ctx[b]) / len(mine) >= 0.5:
                    out.append(_f("오기 의심", f"'{a}'({n}회)는 같은 문맥에 쓰인 '{b}'({nb}회)의 오기로 보임", [w[0] for w in where[a]], where[a][0][1]))
                    break
    return out


def check_dup_paras(pages):
    """같은 문장(60자 이상)이 두 번 이상 나오면 중복 기술."""
    seen, out = defaultdict(list), []
    for p in body_pages(pages):
        for s in re.split(r"(?<=[다함음임])\s*[.]?\s*\n|¡|\n-\s", p["text"]):
            k = re.sub(r"\s+", "", s)
            if len(k) >= 60 and not CAP.search(s):
                seen[k].append((pno(p), _flat(s).strip()))
    groups = [v for v in seen.values() if len({x[0] for x in v}) >= 1 and len(v) >= 2]
    if groups:
        pgs = sorted({x[0] for v in groups for x in v}, key=str)
        out.append(_f("내용 중복", f"같은 문장이 반복 기술됨 {len(groups)}건", pgs, groups[0][0][1][:100]))
    return out


def check_pending(pages):
    """'확인 필요', '추후 확정' 같은 미확정 표현이 남아 있는지 (판정 기준값 유보 포함)."""
    out = []
    pend = []
    for p in body_pages(pages):
        t = _flat(p["text"])
        for m in re.finditer(r"(확인\s*필요|검토\s*필요|미확인|TBD|추후\s*(?:확정|결정|협의))", t):
            pend.append((pno(p), t[max(0, m.start() - 40): m.end() + 5]))
    if len(pend) >= 3:
        out.append(_f("미확정 항목", f"'확인 필요·미확인' 등 미확정으로 남은 서술 {len(pend)}곳", [x[0] for x in pend], pend[0][1]))
    for p in body_pages(pages):
        t = _flat(p["text"])
        for m in re.finditer(r"(임계값|판정\s*기준|기준값)[^.]{0,40}(확정하지\s*않|협의[^.]{0,20}(?:합의|확정)|후\s*확정|추후)", t):
            out.append(_f("기준값 미확정", "판정 임계값·기준값이 확정되지 않고 협의 후로 유보됨", [pno(p)], t[max(0, m.start() - 10): m.end() + 30]))
            break
    return out


def check_label_dates(pages):
    """'권역·지방청·지역·기관' 열인데 행 이름이 날짜('26.7.)로 들어간 표."""
    out = []
    for p in body_pages(pages):
        t = _flat(p["text"])
        for m in re.finditer(r"(권역|지방청|지역|기관)\s+[가-힣A-Za-z()]+\(km\)", t):
            seg = t[m.start(): m.start() + 400]
            dates = re.findall(r"[‘'’]\d{2}\.\d{1,2}\.?(?:~\d{1,2})?", seg)
            if len(dates) >= 3:
                cap = CAP.search(t[m.start():])
                out.append(_f("표 내용 오류", f"'{m.group(1)}' 열에 {m.group(1)} 이름 대신 일자({', '.join(dates[:3])} …)가 기재됨"
                              + (f" — [{cap.group(1)} {cap.group(2)}]" if cap else ""), [pno(p)], seg[:120]))
    return out


def rule_checks(pages):
    refs, caps = check_refs(pages)
    res = refs + check_dup_titles(caps) + check_totals(pages) + check_codes(pages) + check_roadmap(pages) + check_toc(pages) + \
        check_weights(pages) + check_acronyms(pages) + check_dup_paras(pages) + check_pending(pages) + check_label_dates(pages)
    return res


# ================================================================== 3~5) LLM 검토 + 인용 검증 + 교차 확인
REVIEW_SYS = """당신은 교통·ITS·데이터 분야 기술보고서 자문위원이다. 아래 [보고서 일부]를 점검표에 따라 검토한다.
[점검표] ① 목적·범위 대비 결과 충족 ② 정량 근거의 출처(직접 분석인지 타 자료 인용인지) ③ 판정 기준값의 근거·확정 여부
④ 검증 방법·기준자료의 독립성 ⑤ 연계 성과물 간 정합(코드·키·집계 단위) ⑥ 운영 현실성(센터 운영 실태, 환경 변화 대응)
[규칙]
- [이미 지적된 사항]은 따로 반영되므로 다시 쓰지 않는다. 그 밖의 문제를 찾는다.
- 요약·칭찬 금지. 문제점·한계·보완점 위주로, 보고서에 실제로 있는 내용만 근거로 한다.
- 보고서가 이미 스스로 밝힌 원칙·한계·제외 사항을 '없다'고 지적하지 않는다.
- 각 항목에 근거_인용: [보고서 일부]에서 글자 그대로 복사한 30~80자. 쪽수: 그 인용이 있는 [p.N] 표시의 N.
- 특허·코드·표 번호를 다른 대상과 연결할 때는 같은 문장 안에서 직접 연결된 경우만 쓴다.
- 최대 4개. 해당 없으면 빈 목록. 오늘 날짜는 {today} 이다(이전 연도·올해 날짜를 미래라고 하지 않는다).
출력 JSON: {{"items":[{{"구분":"검토의견|개선사항","점검":"①~⑦","내용":"","근거_인용":"","쪽수":0}}]}}"""


def outline(pages):
    heads = []
    for p in body_pages(pages):
        for m in re.finditer(r"(?m)^\s*(제\s*\d+\s*장[^\n]{0,40}|\d{1,2}\.\d{1,2}\s+[^\n]{2,40})$", p["text"]):
            h = _flat(m.group(1)).strip()
            if h not in heads:
                heads.append(h)
    return " / ".join(heads)[:1500]


def chunks(pages, size=5200):
    """장 경계를 우선해 [p.N] 표시를 붙인 조각으로 나눈다."""
    out, cur = [], ""
    for p in body_pages(pages):
        t = re.sub(r"[ \t]+", " ", "\n".join(l for l in p["text"].split("\n") if not TOC_LINE.search(l)))
        block = f"[p.{pno(p)}]\n{t.strip()}\n"
        new_ch = re.search(r"(?m)^\s*제\s*\d+\s*장", t)
        if cur and (len(cur) + len(block) > size or (new_ch and len(cur) > size * 0.45)):
            out.append(cur)
            cur = ""
        while len(block) > size:
            out.append(block[:size])
            block = f"[p.{pno(p)}]\n" + block[size:]
        cur += block
    if cur.strip():
        out.append(cur)
    return out


GENERIC = {"검토", "분석", "검증", "제시", "필요", "보완", "구체", "명확", "확보", "고려", "반영", "수행", "활용", "정의", "설정", "적용",
           "산출", "평가", "구축", "개선", "확인", "정리", "기술", "작성", "설명", "기재", "포함", "연계", "운영", "관리", "추진"}


def _nows(s):
    return re.sub(r"[\s\"'“”‘’]", "", s or "")


def post_filter(it):
    """인용과 무관하게 버려야 할 지적: 올해 이하 연도를 '미래 시점'이라고 한 것(모델의 학습 시점 착오). 반환: 폐기 사유 또는 None"""
    import datetime
    c = it.get("내용", "")
    nums = set(re.findall(r"(\d[\d,.]*)\s*(?:건|개|곳|명|km|%)", c))
    if len(nums) >= 2 and re.search(r"불일치|일치하지|다름|다르게|차이|상이", c):
        return "건수·수치 불일치 주장은 AI가 표 범위를 잘못 읽는 경우가 많아 규칙 점검 결과만 인정"
    if re.search(r"미래|아직\s*오지|도래하지", c):
        years = [int(y) for y in re.findall(r"(20\d{2})", (it.get("근거_인용") or "") + it.get("내용", ""))]
        if not years or max(years) <= datetime.date.today().year:
            return "올해 이하 연도를 미래 시점으로 잘못 판단함"
    return None


def verify(items, pages, rule_text=""):
    """인용 검증 + 이미 밝힌 내용 지적 제거. 반환: (채택, 폐기[사유 포함])"""
    flat = {pno(p): _nows(p["text"]) for p in pages}
    full = _flat(" ".join(p["text"] for p in pages))
    ok, drop = [], []
    for it in items:
        why = post_filter(it)
        if why:
            drop.append({**it, "폐기사유": why})
            continue
        q = _nows(it.get("근거_인용"))
        if len(q) < 15:
            drop.append({**it, "폐기사유": "근거 인용이 없거나 너무 짧음"})
            continue
        hit = [pg for pg, t in flat.items() if q in t] or [pg for pg, t in flat.items() if q[:25] in t]
        if not hit:
            drop.append({**it, "폐기사유": "근거 인용이 원문에 없음"})
            continue
        if it.get("쪽수") not in hit:
            it = {**it, "쪽수_원래": it.get("쪽수"), "쪽수": hit[0]}       # 쪽수만 틀린 경우 원문 위치로 교정
        claim_absent = re.search(r"없|부재|누락|미흡|부족|제시되지|고려되지|방지|구분", it.get("내용", ""))
        if claim_absent:                                          # 지적한 행위를 보고서가 이미 '하지 않음/금지/제외/구분'으로 밝혔으면 폐기
            for w in re.findall(r"([가-힣]{2,6})(?:화|하는|할|함|하여)", it.get("내용", "")):
                if w in GENERIC or len(w) < 2:
                    continue
                m = re.search(re.escape(w) + r"[가-힣]{0,3}\s*(?:하지\s*않|하지\s*아니|을\s*금지|를\s*금지|은\s*제외|는\s*제외|과\s*구분|와\s*구분)", full)
                if m:
                    it = {**it, "폐기사유": f"보고서가 이미 명시함: …{full[max(0, m.start() - 20): m.end() + 10]}…"}
                    break
            if it.get("폐기사유"):
                drop.append(it)
                continue
        ok.append(it)
    return ok, drop


def _tok(s):
    return set(re.findall(r"[가-힣A-Za-z0-9]{2,}", s or ""))


def _same_spot(a, b):
    """두 인용이 원문의 같은 자리를 가리키는지: 한쪽이 다른 쪽을 포함하거나 앞 15자가 같음."""
    qa, qb = _nows(a), _nows(b)
    return bool(qa and qb) and (qa[:15] == qb[:15] or qa[:20] in qb or qb[:20] in qa)


def vote(runs, need=2):
    """여러 실행의 지적을 묶어 need 회 이상 나온 것만 채택.
    같은 지적 = (같은 원문 자리를 인용) 또는 (쪽수 ±1 이고 내용 단어 25% 이상 겹침) 또는 (내용 단어 40% 이상 겹침). 구분(검토/개선)은 따지지 않음."""
    clusters = []
    for ri, items in enumerate(runs):
        for it in items:
            tk = _tok(it["내용"]) | _tok(it.get("근거_인용"))
            for c in clusters:
                ov = len(tk & c["tok"]) / max(1, min(len(tk), len(c["tok"])))
                near = isinstance(it.get("쪽수"), int) and any(isinstance(p, int) and abs(p - it["쪽수"]) <= 1 for p in c["pages"])
                same = _same_spot(it.get("근거_인용"), c["rep"].get("근거_인용")) or (near and ov >= 0.25) or ov >= 0.4
                if same:
                    c["runs"].add(ri)
                    c["tok"] |= tk
                    c["pages"].add(it.get("쪽수"))
                    break
            else:
                clusters.append({"구분": it["구분"], "rep": it, "tok": tk, "runs": {ri}, "pages": {it.get("쪽수")}})
    keep = [dict(c["rep"], 채택횟수=len(c["runs"])) for c in clusters if len(c["runs"]) >= need]
    drop = [dict(c["rep"], 채택횟수=len(c["runs"]), 폐기사유=f"{len(runs)}회 중 {len(c['runs'])}회만 나옴") for c in clusters if len(c["runs"]) < need]
    return keep, drop


SCOPE_SYS = """당신은 기술보고서 자문위원이다. 보고서 제목과 1장(목적·범위)에 비춰, [전체 목차]에 빠진 핵심 내용을 찾는다.
- 제목·목적이 약속한 작업(예: '공모 설계'면 공모 기준·절차·평가, '유통 표준'이면 이용조건·접근·인증 등)이 목차와 본문에 실제로 있는지 본다.
- 목적에 적힌 검증·시나리오가 결과 장에 대응되는지 본다.
- 목차에 이미 있는 내용을 없다고 하지 않는다. 확실한 것만, 최대 3개.
- 근거_인용: [1장 목적·범위]에서 글자 그대로 복사한 30~80자, 쪽수: 그 [p.N].
출력 JSON: {"items":[{"구분":"검토의견","점검":"①","내용":"","근거_인용":"","쪽수":0}]}"""


def scope_review(chat_fn, title, pages, temps):
    """제목·목적 대비 목차 검토(빠진 핵심 내용) — 조각 단위 검토로는 '없는 것'을 볼 수 없어서 따로 함."""
    rng = chapter_ranges(pages)
    a, b = rng.get(1, (1, 6))
    ch1 = "\n".join(f"[p.{pno(p)}]\n" + p["text"] for p in pages if a <= p["pdf"] <= b and not p["toc"])[:4500]
    heads = []
    for p in body_pages(pages):
        for m in re.finditer(r"(?m)^\s*(제\s*\d+\s*장[^\n]{0,40}|\d{1,2}\.\d{1,2}\s+[^\n]{2,40}|\d\)\s+[^\n]{2,40})$", p["text"]):
            h = _flat(m.group(1)).strip()
            if h not in heads:
                heads.append(h)
    msg = [{"role": "system", "content": SCOPE_SYS},
           {"role": "user", "content": f"[보고서 제목] {title}\n[전체 목차]\n" + "\n".join(heads)[:2500] + f"\n\n[1장 목적·범위]\n{ch1}"}]
    runs = []
    for temp in (0.0, 0.15, 0.3)[:len(temps)]:                   # 목차 검토는 온도가 높으면 회차마다 다른 걸 짚어 낮게 고정
        try:
            d = json.loads(chat_fn(msg, {"temperature": temp, "num_ctx": 8192, "num_predict": 700}, fmt="json"))
        except Exception:
            d = {}
        items = []
        for it in d.get("items") or []:
            if isinstance(it, dict) and it.get("내용"):
                it["구분"] = "검토의견"
                try:
                    it["쪽수"] = int(re.sub(r"\D", "", str(it.get("쪽수"))) or 0)
                except ValueError:
                    it["쪽수"] = 0
                items.append(it)
        runs.append(items)
    return runs


def llm_review(chat_fn, title, pages, rules, temps=(0.1, 0.3, 0.5), say=None):
    say = say or (lambda m: None)
    ol = outline(pages)
    rule_txt = "\n".join(f"- {r['유형']}: {r['내용']} (p.{', '.join(map(str, r['쪽'][:3]))})" for r in rules) or "- 없음"
    parts = chunks(pages)
    runs, raw = [], []
    say(f"{title[:24]} — 제목·목적 대비 목차 검토")
    scope = scope_review(chat_fn, title, pages, temps)
    for ti, temp in enumerate(temps):
        items = list(scope[ti]) if ti < len(scope) else []
        for ci, ch in enumerate(parts):
            say(f"{title[:24]} — {ti + 1}/{len(temps)}회차 {ci + 1}/{len(parts)}조각")
            import datetime
            msg = [{"role": "system", "content": REVIEW_SYS.format(today=datetime.date.today().isoformat())},
                   {"role": "user", "content": f"[보고서] {title}\n[목차] {ol}\n[이미 지적된 사항]\n{rule_txt}\n\n[보고서 일부]\n{ch}"}]
            try:
                d = json.loads(chat_fn(msg, {"temperature": temp, "num_ctx": 8192, "num_predict": 900}, fmt="json"))
            except Exception:
                d = {}
            for it in (d.get("items") or []):
                if isinstance(it, dict) and it.get("내용"):
                    it["구분"] = "개선사항" if "개선" in str(it.get("구분")) else "검토의견"
                    try:
                        it["쪽수"] = int(re.sub(r"\D", "", str(it.get("쪽수"))) or 0)
                    except ValueError:
                        it["쪽수"] = 0
                    it["회차"] = ti + 1
                    items.append(it)
        raw.append(items)
        ok, drop = verify(items, pages)
        runs.append(ok)
        raw[-1] = {"채택": ok, "폐기": drop}
    keep, vdrop = vote(runs, need=2 if len(temps) >= 3 else 1)
    # 로컬 모델은 회차마다 다른 주제를 짚는 경향이 커서 2회 이상 채택분만으로는 칸을 못 채움 →
    # 인용 검증을 통과한 1회 지적을 '보조'로 보관(칸이 부족할 때만 문장 정리에 씀, JSON 에 1회로 표시)
    spare = [dict(d, 폐기사유=None, 보조=True) for d in vdrop]
    return keep, raw, spare


# ================================================================== 6) 문장 정리
WRITE_SYS = """자문의견서 칸에 들어갈 문장을 쓴다. [지적 목록]만 근거로, 목록에 없는 내용은 만들지 않는다.
- 칸: 주요 검토의견 3~4개, 보완 개선사항 3~4개. 한 항목은 1~2줄(60~110자). 비슷한 지적은 하나로 합친다.
- 주요 검토의견은 '~함/~음/~임'으로, 보완 개선사항은 '~필요'로 끝낸다. '바람', '권고함', '바람직함' 금지.
- 영문 병기·전문용어는 최소화, 과장·미사여구 금지. 쪽수·지적 번호는 text 에 쓰지 않는다(따로 붙임). 글머리 기호 금지.
- 서로 다른 주제의 지적을 한 항목에 섞지 않는다. 각 항목에 사용한 지적 번호(ids)를 ids 에 적는다.
- [규칙] 표시 지적(표·수치·참조 오류)은 개선사항으로, 목적·근거·방법론 판단은 검토의견으로 쓴다.
- 검토의견은 점검 항목(① 목적 대비 결과, ② 정량 근거의 출처, ③ 기준값 확정, ④ 검증 독립성, ⑤ 성과물 간 정합, ⑥ 운영 현실성)이
  서로 다른 것으로 고루 담는다. 같은 점검 항목의 지적만 여러 개 고르지 않는다.
- '(보조)' 표시 지적은 다른 지적으로 칸이 채워지지 않을 때만 쓴다.
출력 JSON: {"검토의견":[{"text":"","ids":[1]}], "개선사항":[{"text":"","ids":[2]}]}"""


def _pages_mark(pgs):
    pgs = sorted({p for p in pgs if isinstance(p, int) and p > 0})
    if not pgs:
        return ""
    if len(pgs) == 1:
        return f" (p.{pgs[0]})"
    return f" (p.{pgs[0]}, {', '.join(map(str, pgs[1:4]))})" if len(pgs) <= 4 else f" (p.{pgs[0]}~{pgs[-1]})"


def _ending(text, kind):
    """어미 규칙: 검토의견 ~함/~음/~임, 개선사항 ~필요. '바람·권고함·바람직함' 제거. 문장 속 지적 번호 '(1, 2)'·쪽 표시 제거."""
    t = re.sub(r"\s*\(p\.[^)]*\)", "", text.strip())
    t = re.sub(r"\s*\(\s*\d+(?:\s*,\s*\d+)*\s*\)", "", t).strip().rstrip(" .。")
    t = re.sub(r"\s*(?:것을\s*|것이\s*)?(?:권고함|바람직함|바람|요망됨|요망함|권장함)$", " 필요", t).strip()
    if kind == "개선사항":
        t = re.sub(r"필요(?:함|하다|합니다|가\s*있음)$", "필요", t)
        t = re.sub(r"(\S+?)(?:해야|하여야)\s*함$", r"\1 필요", t)              # '보완해야 함' → '보완 필요'
        t = re.sub(r"\s+(?:해야|하여야)\s*함$", " 하는 것이 필요", t)          # '명확히 해야 함' → '명확히 하는 것이 필요'
        t = re.sub(r"(\S+?)할\s*것$", r"\1 필요", t)
        if not t.endswith("필요"):                                    # '~작성됨' 같은 문제 서술 → '~작성된 점 보완 필요'(뜻이 뒤집히지 않게)
            t = re.sub(r"없음$", "없는", re.sub(r"있음$", "있는", t))
            last = t[-1:]
            if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 == 16:
                t = t[:-1] + chr(ord(last) - 16 + 4)                  # 받침 ㅁ → ㄴ (됨→된, 함→한, 임→인, 음→은)
            t = t + " 점 보완 필요" if re.search(r"(된|한|인|은|운|는)$", t) else t + " 보완 필요"
    else:
        t = re.sub(r"하다$", "함", t)
        t = re.sub(r"(?:이다|있다|없다|다)$", lambda m: {"있다": "있음", "없다": "없음"}.get(m.group(0), "임"), t)
        last = t[-1:] if t else ""
        if not ("가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 == 16):     # 끝 글자 받침이 'ㅁ'(함·음·임·움·짐…)이 아니면
            t += "함"
    return re.sub(r"\s{2,}", " ", t)


def _times(f):
    m = re.search(r"(\d)회", f.get("출처", ""))
    return int(m.group(1)) if m else 1


def _merge(group, kind):
    pgs = []
    for f in group:
        pgs += f.get("쪽") or ([f["쪽수"]] if f.get("쪽수") else [])
    return {"구분": kind, "내용": " / ".join(f["내용"] for f in group), "쪽": pgs, "출처": "규칙"}


CHECK_KW = {"①": r"목적|범위|시나리오|결과|대응|누락", "②": r"인용|출처|직접|참고|문헌|가상|합성|자체",
            "③": r"기준값|임계|확정|유보|판정", "④": r"독립|기준자료|검증\s*방법|비교\s*대상",
            "⑤": r"정합|코드|키|단위|식별자|매핑", "⑥": r"운영|센터|현실|실태|변화"}


def select_findings(findings, n=4):
    """칸에 넣을 지적을 코드가 고른다(AI가 고르면 회차마다 달라짐).
    - 규칙 점검: 검토의견용은 1개로, 개선사항용은 최대 2개로 묶어 맨 앞에
    - AI 지적: 점검 항목(①~⑥)이 서로 다른 것부터, 채택 횟수가 많은 순(보조는 맨 뒤)"""
    rules_ = [f for f in findings if f.get("출처") == "규칙"]
    rtok = [_tok(f["내용"]) for f in rules_]
    llm = [f for f in findings if f.get("출처") != "규칙" and not post_filter(f)
           and not any(len(_tok(f["내용"]) & t) / max(1, len(t)) >= 0.5 for t in rtok)]   # 규칙 지적과 같은 내용이면 뺌
    out = {}
    for kind in ("검토의견", "개선사항"):
        rg = [f for f in rules_ if f["구분"] == kind]
        pre = []
        if rg:
            if kind == "검토의견" or len(rg) <= 2:
                pre = [_merge(rg, kind)] if kind == "검토의견" else [_merge([g], kind) for g in rg]
            else:
                half = (len(rg) + 1) // 2
                pre = [_merge(rg[:half], kind), _merge(rg[half:], kind)]
        cand = sorted([f for f in llm if f["구분"] == kind], key=lambda f: (bool(f.get("보조")), -_times(f)))
        sel = list(pre)
        for c in "①②③④⑤⑥⑦":                                   # 점검 항목 순서대로 하나씩: 채택 횟수 → 그 항목 핵심어가 많은 것
            if len(sel) >= n:
                break
            pool = [f for f in cand if (f.get("점검") or "").startswith(c) and not f.get("보조")]
            if pool:
                kw = CHECK_KW.get(c, "")
                sel.append(max(pool, key=lambda f: (_times(f), len(re.findall(kw, f["내용"])) if kw else 0)))
        for f in cand:
            if len(sel) >= n:
                break
            if f not in sel:
                sel.append(f)
        out[kind] = sel[:n]
    return out


REWRITE_SYS = """자문의견서 칸에 들어갈 문장으로 [항목]을 하나씩 다듬는다. 항목마다 정확히 1문장, 60~110자.
- 내용을 바꾸거나 새 사실을 더하지 않는다. 수치·표 번호·부록 기호·코드(예: 120개, 표 6, 부록 B, S11, 4.80)는 그대로 남긴다.
- 항목의 핵심 용어(작은따옴표 안 용어, '인용', '직접 분석', '유통', '공모' 같은 쟁점 단어)는 지우지 않는다.
- 여러 오류가 '/'로 묶인 항목은 핵심만 나열해 한 문장으로 줄인다.
- 검토의견 항목은 '~함/~음/~임', 개선사항 항목은 '~필요'로 끝낸다. '바람', '권고함', '바람직함' 금지.
- 영문 병기·전문용어 최소화, 과장 금지, 쪽수·번호·글머리 기호를 text 에 쓰지 않는다.
출력 JSON: {"items":[{"id":1,"text":""}]}"""


def _rewrite(chat_fn, title, items):
    lst = "\n".join(f"{i}. [{f['구분']}] {f['내용'][:300]}" for i, f in enumerate(items, 1))
    try:
        d = json.loads(chat_fn([{"role": "system", "content": REWRITE_SYS},
                                {"role": "user", "content": f"[보고서] {title}\n[항목]\n{lst}"}],
                               {"temperature": 0.1, "num_ctx": 8192, "num_predict": 1600}, fmt="json"))
        return {int(x["id"]): x["text"] for x in d.get("items", []) if isinstance(x, dict) and x.get("text") and str(x.get("id", "")).isdigit()}
    except Exception:
        return {}


def _compose_call(chat_fn, title, findings):
    lst = "\n".join(f"{i}. [{f['구분']}][{f.get('출처', '')}]{'[' + f['점검'] + ']' if f.get('점검') else ''}"
                    f"{'(보조)' if f.get('보조') else ''} {f['내용'][:180]}" for i, f in enumerate(findings, 1))
    try:
        d = json.loads(chat_fn([{"role": "system", "content": WRITE_SYS},
                                {"role": "user", "content": f"[보고서] {title}\n[지적 목록]\n{lst}"}],
                               {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1800}, fmt="json"))
        return d if isinstance(d, dict) and (d.get("검토의견") or d.get("개선사항")) else {}
    except Exception:
        return {}


def compose(chat_fn, title, findings):
    """findings → {'검토의견':[문장], '개선사항':[문장]}. 고르기는 코드(select_findings), 다듬기만 AI.
    AI 응답이 깨지면 그 항목은 지적 원문을 줄여 씀(칸을 비우지 않음)."""
    sel = select_findings(findings)
    flat = sel["검토의견"] + sel["개선사항"]
    texts = _rewrite(chat_fn, title, flat) if flat else {}
    res, i = {}, 0
    for kind in ("검토의견", "개선사항"):
        out = []
        for f in sel[kind]:
            i += 1
            t = texts.get(i) or re.sub(r"^[^:/]{2,12}:\s*", "", f["내용"].split(" / ")[0])[:110]
            pgs = f.get("쪽") or ([f["쪽수"]] if f.get("쪽수") else [])
            out.append(_ending(t, kind) + _pages_mark(pgs))
        res[kind] = out
    return res


def compose_free(chat_fn, title, findings):
    """(이전 방식) AI가 지적을 골라 합쳐 쓰기 — 회차마다 고르는 지적이 달라 회귀 테스트가 흔들려 쓰지 않음."""
    d = _compose_call(chat_fn, title, findings)
    if not d:
        core = [f for f in findings if not f.get("보조")]
        d = _compose_call(chat_fn, title, core)
        if d:
            findings = core
    if not d:
        d = {k: [{"text": re.sub(r"^[^:]{2,12}:\s*", "", f["내용"])[:110], "ids": [i]}
                 for i, f in enumerate(findings, 1) if f["구분"] == k and not f.get("보조")][:4] for k in ("검토의견", "개선사항")}
    res = {}
    for kind in ("검토의견", "개선사항"):
        out = []
        for it in (d.get(kind) or [])[:4]:
            if not isinstance(it, dict) or not it.get("text"):
                continue
            ids = [i for i in it.get("ids") or [] if isinstance(i, int) and 1 <= i <= len(findings)]
            pgs = []
            for i in ids:
                f = findings[i - 1]
                pgs += f.get("쪽") or ([f["쪽수"]] if f.get("쪽수") else [])
            out.append(_ending(it["text"], kind) + _pages_mark(pgs))
        res[kind] = out
    return res


# ================================================================== 전체 (보고서 1건)
RULE_KIND = {"참조 무결성": "개선사항", "표 제목 중복": "개선사항", "수치 불일치": "개선사항", "목록-본문 불일치": "개선사항",
             "목적-결과 대응": "검토의견", "목차-본문 불일치": "개선사항", "가중치 재계산": "개선사항", "등급 일관성": "개선사항",
             "등급 건수 불일치": "개선사항", "오기 의심": "개선사항", "내용 중복": "개선사항", "미확정 항목": "검토의견",
             "기준값 미확정": "검토의견", "표 내용 오류": "개선사항"}


def review_report(chat_fn, title, pdf_bytes, temps=(0.2, 0.5, 0.8), say=None):
    pages = load_pages(pdf_bytes)
    rules = rule_checks(pages)
    keep, raw, spare = llm_review(chat_fn, title, pages, rules, temps, say)
    findings = [{"구분": RULE_KIND.get(r["유형"], "개선사항"), "내용": f"{r['유형']}: {r['내용']}", "쪽": r["쪽"], "출처": "규칙"} for r in rules]
    findings += [{"구분": k["구분"], "내용": k["내용"], "쪽수": k["쪽수"], "출처": f"LLM {k['채택횟수']}회", "점검": str(k.get("점검", ""))[:2]}
                 for k in keep]
    findings += [{"구분": k["구분"], "내용": k["내용"], "쪽수": k["쪽수"], "출처": "LLM 1회", "보조": True, "점검": str(k.get("점검", ""))[:2]}
                 for k in spare[:8]]
    text = compose(chat_fn, title, findings)
    return {"pages": len(pages), "rules": rules, "llm_raw": raw, "llm_keep": keep, "llm_spare": spare,
            "dropped": [d for r in raw for d in r["폐기"]], "findings": findings, "text": text}
