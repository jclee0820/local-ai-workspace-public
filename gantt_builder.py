"""연구개발계획서·제안서·과업지시서 → WBS(작업분류체계) → 간트 차트(엑셀).

흐름
  1) 문서에서 일정·과업 관련 부분만 골라냄 (키워드·표 점수, 긴 문서도 8K 문맥 안에서 처리)
  2) 로컬 LLM이 WBS 항목(코드·작업명·기간·담당·산출물·근거 구절)을 JSON으로 추출 (분석 깊이만큼 나눠서 반복)
  3) 파이썬이 병합·번호 정리·날짜 환산(개월차·차년도·실제 날짜)·상위 기간 집계·근거 대조
  4) 엑셀: 날짜를 고치면 막대가 따라 움직이는 간트 (조건부 서식), 진척률 반영, 마일스톤 ◆, 오늘 표시, 단계 접기
"""
import calendar
import datetime as dt
import io
import json
import re

# ------------------------------------------------------------------ 1. 문서 → 관련 부분 선택
KEYS = {  # 일정·WBS 와 관련 깊은 말 (가중치)
    r"추진\s*일정|수행\s*일정|세부\s*일정|연구\s*일정|사업\s*일정|일정\s*계획|추진\s*계획|간트|gantt|WBS|작업\s*분류": 6,
    r"마일스톤|milestone|착수|중간\s*보고|최종\s*보고|완료\s*보고|납품|검수|준공|종료\s*보고": 4,
    r"\d\s*차\s*년도|\d+\s*개월|\d+\s*월|\d{4}\s*[.\-년]\s*\d{1,2}|분기|상반기|하반기|M\+?\d+": 2,
    r"단계|과업|세부\s*과제|세부\s*내용|연구\s*내용|수행\s*내용|추진\s*내용|업무\s*범위|산출물|성과물|담당|책임": 2,
    r"설계|개발|구축|시험|실증|검증|분석|조사|평가|운영|교육|보고서": 1,
}
MARK = re.compile(r"[●■◆▲○□◇★▶■█▓]|━|─{2,}")
PERIOD_LINE = re.compile(r"(사업|연구|과제|수행|용역|개발|계약|협약)\s*(기간|기한)|착수일|완료일|총\s*\d+\s*개월")


def windows(text: str, size: int = 1400):
    """줄 단위로 묶은 창(window) 리스트: [(index, text, score)]."""
    lines = [l.rstrip() for l in text.replace("\r", "").split("\n") if l.strip()]
    out, buf = [], []
    for l in lines:
        buf.append(l)
        if sum(len(x) for x in buf) >= size:
            out.append("\n".join(buf))
            buf = []
    if buf:
        out.append("\n".join(buf))
    res = []
    for i, w in enumerate(out):
        s = sum(len(re.findall(p, w, re.I)) * wt for p, wt in KEYS.items())
        s += 3 * sum(1 for l in w.split("\n") if l.startswith("|") and (MARK.search(l) or re.search(r"\|\s*\d{1,2}\s*\|", l)))
        res.append((i, w, s))
    return res


def period_lines(text: str, limit: int = 8):
    seen, out = set(), []
    for l in text.split("\n"):
        l = l.strip()
        if PERIOD_LINE.search(l) and l not in seen and len(l) < 200:
            seen.add(l)
            out.append(l)
        if len(out) >= limit:
            break
    return out


def plan_calls(text: str, depth: int = 2, budget: int = 5200):
    """LLM 호출별 원문 묶음. 1회차=일정 밀도가 가장 높은 부분, 2회차 이후=다음 순위(세부 내용)."""
    ws = windows(text)
    ranked = [w for w in sorted(ws, key=lambda x: -x[2]) if w[2] > 0]
    head = text[:900]
    calls, used = [], set()
    for k in range(depth):
        pick, n = [], 0
        for w in ranked:
            if w[0] in used or n + len(w[1]) > budget:
                continue
            pick.append(w)
            used.add(w[0])
            n += len(w[1])
        if not pick:
            break
        body = "\n…\n".join(w[1] for w in sorted(pick))
        calls.append((head if k == 0 else "") + "\n…\n" + body)
    if not calls:                                        # 키워드가 없는 짧은 문서
        calls = [text[:budget]]
    return calls


# ------------------------------------------------------------------ 1-b. 일정표(●·■ 표시) 직접 해석
CELL_MARK = re.compile(r"[●■◆▲◎★█▓▶━]|^\s*[oOvV✓✔]\s*$")


def _col_period(h: str, k: int, state: dict):
    """일정표 머리글 한 칸 → (시작 표기, 끝 표기). 예: '4~6월차'→('M4','M6'), '2분기'→순서대로, '2026.04'→실제 날짜."""
    raw = h or ""
    h = re.sub(r"\s+", "", raw)
    if re.search(r"월차|개월", re.sub(r"[~\-]", "", h)) and not re.match(r"^M?\d+[~\-]M?\d+", h, re.I):
        nums = re.findall(r"\d+", raw)                 # PDF 칸 줄바꿈으로 '13 15 ~ 월차'처럼 섞인 머리글
        if len(nums) == 2:
            return f"M{nums[0]}", f"M{nums[1]}"
    m = re.match(r"^'?(\d{2,4})[.\-/년](\d{1,2})월?$", h)
    if m:
        y = int(m.group(1))
        y = y + 2000 if y < 100 else y
        return f"{y}-{int(m.group(2)):02d}", f"{y}-{int(m.group(2)):02d}"
    m = re.match(r"^M?(\d+)[~\-](?:M)?(\d+)(개?월차?|개월|M)?$", h, re.I)
    if m and (m.group(3) or h.upper().startswith("M")):
        return f"M{m.group(1)}", f"M{m.group(2)}"
    m = re.match(r"^(\d+)(개?월차|개월차)$", h) or re.match(r"^M(\d+)$", h, re.I)
    if m:
        return f"M{m.group(1)}", f"M{m.group(1)}"
    m = re.match(r"^(\d)차?년?도?(\d)분기$", h)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        return f"Y{y}-M{3 * q - 2}", f"Y{y}-M{3 * q}"
    m = re.match(r"^(\d)/?4?분기$|^Q(\d)$", h, re.I)
    if m:
        state["q"] = state.get("q", 0) + 1                  # 분기 칸은 순서대로 이어짐 (2차년도면 5번째 칸 = 13~15개월)
        n = state["q"]
        return f"M{3 * n - 2}", f"M{3 * n}"
    m = re.match(r"^(\d)차?년도?$|^(\d)년차$", h)
    if m:
        y = int(m.group(1) or m.group(2))
        return f"Y{y}", f"Y{y}"
    m = re.match(r"^(\d{1,2})월$", h)
    if m:
        mo = int(m.group(1))
        if not 1 <= mo <= 12:
            return None
        base = state.get("base")
        if base:                                            # 달력상의 월 → 사업 시작연도 기준 실제 날짜
            y = state.setdefault("y", base.year if mo >= base.month else base.year + 1)
            if state.get("last") and mo < state["last"]:
                y = state["y"] = y + 1
            state["last"] = mo
            return f"{y}-{mo:02d}", f"{y}-{mo:02d}"
        state["n"] = state.get("n", 0) + 1
        return f"M{state['n']}", f"M{state['n']}"
    return None


def doc_start(text: str):
    """'연구개발기간: 2026년 4월 1일 ~ …' 등에서 사업 시작일."""
    for l in period_lines(text, 12):
        m = re.search(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]?\s*(\d{1,2})?", l)
        if m and 1 <= int(m.group(2)) <= 12:
            return dt.date(int(m.group(1)), int(m.group(2)), 1)
    return None


def table_schedule(text: str):
    """마크다운식 표(| a | b |) 중 일정표를 찾아 [(작업명, 시작표기, 끝표기, 담당)] 반환."""
    rows_all, cur = [], []
    for l in text.split("\n") + [""]:
        if l.strip().startswith("|"):
            cur.append([c.strip() for c in l.strip().strip("|").split("|")])
        elif cur:
            rows_all.append(cur)
            cur = []
    base = doc_start(text)
    out = []
    for tbl in rows_all:
        for hi, head in enumerate(tbl[:3]):               # 머리글은 표 위쪽 3행 안
            state = {"base": base}
            per = {k: _col_period(h, k, state) for k, h in enumerate(head)}
            pcols = [k for k, v in per.items() if v]
            if len(pcols) < 3:
                continue
            for r in tbl[hi + 1:]:
                marks = [k for k in pcols if k < len(r) and CELL_MARK.search(r[k] or "")]
                names = [c for k, c in enumerate(r) if k not in pcols and c and not CELL_MARK.search(c)]
                if not marks or not names:
                    continue
                owner = names[1] if len(names) > 1 and len(names[1]) <= 20 else ""
                out.append((names[0], per[marks[0]][0], per[marks[-1]][1], owner))
            break
    return out


def _sim(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    ga, gb = {a[i:i + 2] for i in range(len(a) - 1)}, {b[i:i + 2] for i in range(len(b) - 1)}
    return len(ga & gb) / max(len(ga | gb), 1)


# ------------------------------------------------------------------ 2. LLM 추출
SYS = """너는 공공 연구개발·정보화 사업의 PMO(사업관리) 전문가다. 주어진 문서(연구개발계획서, 제안서, 과업지시서 등) 발췌에서
WBS(작업분류체계)와 일정을 추출해 JSON만 출력한다.
규칙:
- 계층: 1수준=단계·연차·주요 과업, 2수준=세부 과업, 3수준=세부 활동. wbs 코드는 "1", "1.2", "1.2.3" 형식. 최대 3수준.
- 문서에 있는 과업만 쓴다. 문서에 없는 과업을 지어내지 않는다.
- 연구 필요성·국내외 동향·배경·기대효과·예산 설명은 과업이 아니므로 넣지 않는다.
- start/end 표기: 실제 날짜가 있으면 "2026-04" 또는 "2026-04-15", 개월차면 "M1"(1개월차)~"M36", 연차만 있으면 "Y1"(1차년도 전체)·"Y2",
  연차 안의 개월이면 "Y2-M3". 분기는 해당 개월로 바꾼다(예: 1차년도 2분기 → start "Y1-M4", end "Y1-M6").
- 기간이 문서에 없으면 start/end 를 "" 로 두고 지어내지 않는다.
- 착수보고·중간보고·최종보고·납품·검수·평가 같은 시점은 ms=true, start=end.
- owner=담당 기관·팀(문서에 있을 때만), output=산출물(문서에 있을 때만).
- src=근거가 되는 원문 구절을 그대로 옮긴 30자 이내 문자열.
출력 형식:
{"project":{"name":"사업(과제)명","start":"전체 시작(문서에 있을 때)","end":"전체 종료","months":총개월수 또는 null},
 "tasks":[{"wbs":"1","name":"작업명","start":"M1","end":"M6","owner":"","output":"","ms":false,"src":"원문 구절"}]}"""


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    s = m.group(0)
    for cand in (s, re.sub(r",\s*([}\]])", r"\1", s)):
        try:
            return json.loads(cand)
        except Exception:
            continue
    return None


def extract(text: str, chat_fn, depth: int = 2, request: str = "", progress=None):
    """문서 텍스트 → {'project':{...}, 'tasks':[...] (병합 전 원본 목록)}"""
    calls = plan_calls(text, depth)
    periods = period_lines(text)
    sched = table_schedule(text)
    project, tasks = {}, []
    for k, chunk in enumerate(calls):
        if progress:
            progress(k / len(calls), f"WBS 추출 중 ({k + 1}/{len(calls)}회차)…")
        user = ""
        if request:
            user += f"[사용자 요청] {request}\n"
        if periods:
            user += "[사업 기간 관련 원문]\n" + "\n".join(periods) + "\n"
        if sched:
            user += ("[일정표에서 자동 계산한 기간 — 이 과업들의 start/end 는 이 값을 그대로 쓸 것]\n"
                     + "\n".join(f"- {n}: {s} ~ {e}" + (f" (담당 {o})" if o else "") for n, s, e, o in sched[:40]) + "\n")
        if tasks:
            have = "\n".join(f'{t.get("wbs","")} {t.get("name","")} ({t.get("start","")}~{t.get("end","")})'
                             for t in tasks[:70])
            user += ("[지금까지 정리된 WBS]\n" + have + "\n위 WBS 를 유지하면서, 아래 발췌에서 빠진 과업·활동·마일스톤만 추가하거나 "
                     "기간·담당·산출물이 비어 있던 항목을 보완하라. 기존 항목과 같은 과업이면 같은 wbs 코드를 쓴다.\n")
        user += "[문서 발췌]\n" + chunk
        out = chat_fn([{"role": "system", "content": SYS}, {"role": "user", "content": user}],
                      {"temperature": 0.1, "num_predict": 3000}, fmt="json")
        d = _json(out) or {}
        for key, v in (d.get("project") or {}).items():
            if v and not project.get(key):
                project[key] = v
        tasks.extend(t for t in (d.get("tasks") or []) if isinstance(t, dict) and str(t.get("name", "")).strip())
    if progress:
        progress(1.0, "WBS 정리 중…")
    return {"project": project, "tasks": tasks, "schedule": sched}


# ------------------------------------------------------------------ 3. 날짜 환산 · 병합
def _add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, 1)


def _month_end(d: dt.date) -> dt.date:
    return dt.date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def parse_when(s, base: dt.date):
    """표기 하나 → (시작일, 종료일). 해석 못 하면 None."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]?\s*(\d{1,2})?\s*일?$", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            return None
        if m.group(3):
            d = dt.date(y, mo, min(int(m.group(3)), calendar.monthrange(y, mo)[1]))
            return d, d
        d = dt.date(y, mo, 1)
        return d, _month_end(d)
    m = re.match(r"^(\d{4})\s*년?$", s)
    if m:
        return dt.date(int(m.group(1)), 1, 1), dt.date(int(m.group(1)), 12, 31)
    m = re.match(r"^Y\s*(\d+)\s*[-\s]?\s*M\s*(\d+)$", s, re.I) or re.match(r"^(\d+)\s*차\s*년도\s*(\d+)\s*개?월", s)
    if m:
        n = (int(m.group(1)) - 1) * 12 + int(m.group(2))
        d = _add_months(base, n - 1)
        return d, _month_end(d)
    m = re.match(r"^Y\s*(\d+)$", s, re.I) or re.match(r"^(\d+)\s*차\s*년도$", s)
    if m:
        a = _add_months(base, (int(m.group(1)) - 1) * 12)
        return a, _month_end(_add_months(a, 11))
    m = re.match(r"^M\s*\+?\s*(\d+)$", s, re.I) or re.match(r"^(\d+)\s*개?월\s*차?$", s) or re.match(r"^(\d+)$", s)
    if m:
        d = _add_months(base, int(m.group(1)) - 1)
        return d, _month_end(d)
    m = re.match(r"^W\s*(\d+)$", s, re.I) or re.match(r"^(\d+)\s*주\s*차?$", s)
    if m:
        a = base + dt.timedelta(weeks=int(m.group(1)) - 1)
        return a, a + dt.timedelta(days=6)
    return None


def guess_base(project: dict, tasks: list, user_start: dt.date = None) -> dt.date:
    if user_start:
        return user_start
    for v in (project.get("start"),) + tuple(t.get("start") for t in tasks):
        r = parse_when(v, dt.date(2000, 1, 1))
        if r and re.match(r"^\d{4}", str(v).strip()):
            return dt.date(r[0].year, r[0].month, 1)
    t = dt.date.today()
    return _add_months(dt.date(t.year, t.month, 1), 1)


def _norm(s):
    return re.sub(r"[\s\W_]+", "", str(s or "")).lower()


def _code(s):
    s = re.sub(r"[^\d.]", "", str(s or "")).strip(".")
    return s if re.match(r"^\d+(\.\d+){0,3}$", s) else ""


def _key(code):
    return tuple(int(x) for x in code.split("."))


def verify_src(src: str, doc_norm: str) -> bool:
    """근거 구절이 원문에 실제로 있는지 (띄어쓰기 무시, 2글자 조각 70% 이상 일치)."""
    n = _norm(src)
    if len(n) < 4:
        return False
    if n in doc_norm:
        return True
    grams = {n[i:i + 2] for i in range(len(n) - 1)}
    hit = sum(1 for g in grams if g in doc_norm)
    return hit / max(len(grams), 1) >= 0.7 and _norm(n[:6]) in doc_norm


EFFORT_SYS = """너는 공공 연구용역·정보화 사업의 PMO(사업관리) 전문가다. 사업 기간과 WBS 를 보고,
날짜가 정해지지 않은 작업마다 표준 공수에 근거한 소요 기간(주)과 선행 작업을 추정해 JSON만 출력한다.
규칙:
- weeks: 그 작업에 실제로 필요한 기간(주, 정수 1 이상). 작업 범위·난이도와 사업 전체 길이에 비례하게 정한다.
  (예: 1년 이하 연구용역이면 조사 4~8주·분석 6~12주·정책제언 3~6주, 다년도 기술개발이면 설계 12~26주·개발 26~52주·실증 26~52주)
  같은 묶음 안 작업이라도 범위가 다르면 기간도 다르게 준다. 모든 작업을 사업 전체 기간으로 두지 않는다.
- after: 이 작업을 시작하기 전에 끝나야 하는 작업의 wbs 목록. 일반적 흐름은 조사·요구분석·설계 → 개발·분석 → 통합·시험 → 실증·검증 → 최적화·표준화·정책제언.
  병렬로 할 수 있으면 [] 로 둔다. 자기 자신이나 뒤에 나오는 작업끼리 서로 선행이 되지 않게 한다.
- stage: 사업 전체 흐름에서 이 작업이 놓이는 시점(0.0=맨 처음, 0.5=가운데, 1.0=맨 끝). 설계·기능정의는 0~0.2, 개발 0.2~0.6,
  통합·시험 0.5~0.7, 실증·성능검증 0.6~0.9, 최적화·표준화·매뉴얼·정책제언 0.8~1.0 처럼 작업 성격에 맞게 정한다.
- 목록에 있는 작업만, wbs 코드를 그대로 쓴다.
출력 형식: {"tasks":[{"wbs":"1.1","weeks":6,"after":[],"stage":0.0},{"wbs":"1.2","weeks":8,"after":["1.1"],"stage":0.3}]}"""


def _report_point(name, p_start, p_end):
    """날짜 없는 보고 마일스톤의 관례적 시점."""
    if re.search(r"착수|킥오프|kick", name, re.I):
        return p_start
    if re.search(r"중간", name):
        return p_start + (p_end - p_start) / 2
    if re.search(r"최종|완료|납품|검수|결과\s*보고", name):
        return p_end
    return None


def schedule_undated(by_code, codes, p_start, p_end, chat_fn=None, request="", progress=None):
    """날짜 없는 말단 작업에 기간을 붙임(제자리 수정).
    창(window) = 날짜가 문서에 있는 가장 가까운 상위 작업의 기간, 없으면 사업 기간.
    LLM 이 작업별 소요 주·선행 작업·단계(stage 0~1)를 추정 → 선행이 끝난 뒤, 단계 위치(창 안의 비율) 이후에 시작.
    병렬 작업을 창 전체로 늘리지 않음(늘리면 모든 막대가 같아짐): 가장 긴 흐름이 창보다 길면 줄이고, 짧으면 최대 1.5배까지만 늘림.
    LLM 이 없거나 실패하면 같은 1수준 묶음은 순서대로, 1수준 묶음끼리는 차례로(앞 묶음 끝나면 다음) 배치해 창을 채움."""
    kids = {c: [k for k in codes if k.startswith(c + ".")] for c in codes}
    for c in codes:                                          # 날짜 없는 보고 마일스톤: 착수=시작, 중간=가운데, 최종=끝
        t = by_code[c]
        if t.get("ms") and not t["s"]:
            d = _report_point(t["name"], p_start, p_end)
            if d:
                t["s"] = t["e"] = d
                t["basis"] = "추정(보고 시점)"
    leaves = [c for c in codes if not kids[c] and not by_code[c]["s"] and not by_code[c].get("ms")]
    if not leaves:
        return

    # 최종보고(결과보고·납품) 시점이 사업 기간 안에 있으면 실제 작업은 그때까지 끝나야 함
    finals = [by_code[c]["s"] for c in codes if by_code[c].get("ms") and by_code[c]["s"]
              and re.search(r"최종|결과\s*보고|납품|완료\s*보고", by_code[c]["name"])]
    w_end = max(finals) if finals and p_start + dt.timedelta(days=28) < max(finals) < p_end else p_end

    def window(c):
        while "." in c:
            c = c.rsplit(".", 1)[0]
            p = by_code.get(c)
            if p and p["s"] and str(p.get("basis", "")).startswith("문서"):
                return p["s"], p["e"]
        return p_start, w_end

    est = {}
    if chat_fn:
        if progress:
            progress(0.97, f"날짜 없는 작업 {len(leaves)}개의 공수·순서 추정 중…")
        weeks = max(1, round((p_end - p_start).days / 7))
        lines = []
        for c in codes:
            t = by_code[c]
            mark = (f"{t['s']:%Y-%m-%d}~{t['e']:%Y-%m-%d} (확정)" if t["s"] else ("← 추정 대상" if c in leaves else ""))
            lines.append(f"{'  ' * c.count('.')}{c} {t['name']} {mark}".rstrip())
        user = (f"[사업 기간] {p_start:%Y-%m-%d} ~ {p_end:%Y-%m-%d} (약 {weeks}주)\n"
                + (f"[사용자 요청] {request}\n" if request else "")
                + "[WBS]\n" + "\n".join(lines) + "\n\n'← 추정 대상' 작업만 weeks·after·stage 를 추정하라.")
        try:
            d = _json(chat_fn([{"role": "system", "content": EFFORT_SYS}, {"role": "user", "content": user}],
                              {"temperature": 0.1, "num_predict": 2500}, fmt="json")) or {}
            for x in d.get("tasks") or []:
                c = _code(x.get("wbs"))
                if c in leaves:
                    try:
                        w = max(1, min(int(float(x.get("weeks") or 0)), 260))
                    except Exception:
                        w = 0
                    aft = [_code(a) for a in (x.get("after") or []) if _code(a)]
                    try:
                        stg = min(max(float(x.get("stage")), 0.0), 1.0)
                    except Exception:
                        stg = None
                    est[c] = {"weeks": w or None, "after": aft, "stage": stg}
        except Exception:
            est = {}
    ai = bool(est)
    tops = [c for c in codes if "." not in c]
    for c in leaves:                                          # 추정이 빠진 작업 기본값
        e = est.setdefault(c, {"weeks": None, "after": [], "stage": None})
        if not e["weeks"]:
            e["weeks"] = 4
        if not ai:                                            # 규칙 기반: 같은 묶음 안은 순서대로, 묶음끼리도 차례로
            sib = [k for k in leaves if k.split(".")[0] == c.split(".")[0]]
            i = sib.index(c)
            if i:
                e["after"] = [sib[i - 1]]
            else:
                ti = tops.index(c.split(".")[0]) if c.split(".")[0] in tops else 0
                prev = [k for k in leaves if tops.index(k.split(".")[0]) < ti] if ti else []
                e["after"] = [prev[-1]] if prev else []
    groups = {}
    for c in leaves:
        groups.setdefault(window(c), []).append(c)
    for (ws, we), mem in groups.items():
        span_days = max(7, (we - ws).days + 1)
        order = sorted(mem, key=_key)
        for i, c in enumerate(order):                         # 단계가 빠진 작업: WBS 순서로 앞→뒤 고르게
            if est[c].get("stage") is None:
                est[c]["stage"] = 0.8 * i / max(len(order) - 1, 1)

        def lay(scale, use_stage=False):
            out = {}
            for c in order:
                dur = min(max(3, round(est[c]["weeks"] * 7 * scale)), span_days)
                latest = we - dt.timedelta(days=dur - 1)              # 창 안에 끝나려면 이때까지는 시작해야 함
                st0 = ws
                for a in est[c]["after"]:
                    if a == c or _key(a) >= _key(c) and a in mem:   # 순환 방지: 앞선 작업만 선행으로 인정
                        continue
                    if a in out:                                     # 같이 배치 중인 작업
                        pe_ = out[a][1]
                    elif a in by_code and by_code[a]["s"] and not kids[a]:   # 문서에 날짜가 있는 말단 작업
                        pe_ = by_code[a]["e"]
                    else:                                            # 묶음(상위 코드): 그 아래에서 새로 배치한 작업들의 끝만 봄
                        ends = [out[k][1] for k in out if k.startswith(a + ".")]   # (전 기간 요약 행의 끝을 쓰면 모두 맨 끝으로 밀림)
                        if not ends:
                            continue
                        pe_ = max(ends)
                    cand = pe_ + dt.timedelta(days=1)
                    if cand <= latest:                               # 지킬 수 없는 선행(창 끝에 몰리게 함)은 무시
                        st0 = max(st0, cand)
                if use_stage:                                       # 단계 위치: 창 안에서 (창 길이 - 작업 길이) × stage 지점 이후
                    st0 = max(st0, ws + dt.timedelta(days=round(est[c]["stage"] * (span_days - dur))))
                st0 = min(st0, max(ws, latest))
                out[c] = (st0, st0 + dt.timedelta(days=dur - 1))
            return out

        first = lay(1.0)
        used = (max(e for _, e in first.values()) - ws).days + 1
        if ai:                                                       # 긴 흐름이 넘치면 줄이고, 모자라면 1.5배까지만 늘린 뒤 단계 위치로 펼침
            res = lay(span_days / used if used > span_days else min(span_days / used, 1.5), use_stage=True)
        else:                                                        # 규칙 기반(순차 사슬): 사슬이 창을 꽉 채우도록 비례 조정
            res = lay(span_days / used) if used != span_days else first
        for c, (s, e) in res.items():
            e = min(e, we)
            s = min(s, e)
            t = by_code[c]
            t["s"], t["e"] = s, e
            t["basis"] = (f"추정(공수 {est[c]['weeks']}주" + (", AI" if ai else ", 순차")
                          + (", 원문 기간 불명확" if t.get("weak") else "") + ")")
    # 묶음 행 = 하위 기간 합 (새로 배치된 작업 반영)
    for c in sorted(codes, key=lambda c: -c.count(".")):
        ks = [by_code[k] for k in codes if k.startswith(c + ".") and k.count(".") == c.count(".") + 1 and by_code[k]["s"]]
        p = by_code[c]
        if ks and p.get("basis") != "마일스톤 묶음":
            lo, hi = min(k["s"] for k in ks), max(k["e"] for k in ks)
            if not p["s"]:
                p["s"], p["e"], p["basis"] = lo, hi, "하위 합산"
            else:
                p["s"], p["e"] = min(p["s"], lo), max(p["e"], hi)


WEAK_KEEP = re.compile(r"(과업|사업|프로젝트|연구)\s*관리|진도|보고|회의|자문|PMO|운영위원|품질\s*보증")


def drop_weak_dates(by_code, codes, project, base):
    """AI 가 문서에 없는 기간 대신 '사업 전체 기간'이나 '상위 작업과 똑같은 기간'을 채워 넣은 말단 작업의 날짜를 지움.
    (이런 날짜는 정보가 없고, 그대로 두면 모든 막대가 같은 길이·같은 위치가 됨.) 일정표(●·■)에서 계산한 기간과
    과업관리·보고·자문처럼 원래 전 기간에 걸치는 작업은 그대로 둠. 지운 작업은 schedule_undated 가 공수로 다시 배치."""
    dated = [by_code[c] for c in codes if by_code[c]["s"]]
    if not dated:
        return
    ps, pe = parse_when(project.get("start"), base), parse_when(project.get("end"), base)
    lo = min([t["s"] for t in dated] + ([ps[0]] if ps else []))
    hi = max([t["e"] for t in dated] + ([pe[1]] if pe else []))
    P = (hi - lo).days + 1
    if P < 120:
        return
    kids = {c: [k for k in codes if k.startswith(c + ".") and k.count(".") == c.count(".") + 1] for c in codes}
    for c in codes:
        t = by_code[c]
        if kids[c] or not t["s"] or t.get("ms") or t.get("basis") != "문서" or WEAK_KEEP.search(t["name"]):
            continue
        span = (t["e"] - t["s"]).days + 1
        par = by_code.get(c.rsplit(".", 1)[0]) if "." in c else None
        same_as_parent = False
        if par and par["s"] and (t["s"], t["e"]) == (par["s"], par["e"]):
            same = [k for k in kids[c.rsplit(".", 1)[0]] if (by_code[k]["s"], by_code[k]["e"]) == (t["s"], t["e"])]
            same_as_parent = len(same) >= 2
        if span >= 0.9 * P or same_as_parent:
            t["s"] = t["e"] = None
            t["basis"] = ""
            t["weak"] = True


def build(raw: dict, doc_text: str, user_start: dt.date = None, user_end: dt.date = None, chat_fn=None,
          request: str = "", progress=None):
    """LLM 원본 → 정리된 WBS. 반환 {'project':{name,start,end}, 'tasks':[...] }
    user_start/user_end: 사용자가 정한 사업 기간(우선). chat_fn: 날짜 없는 작업의 공수 추정용(없으면 규칙 기반 배치)."""
    project, items = raw.get("project") or {}, raw.get("tasks") or []
    base = guess_base(project, items, user_start or doc_start(doc_text))
    by_code, by_name, order = {}, {}, []

    def fill(dst, src):
        for k in ("start", "end", "owner", "output", "src"):
            if not dst.get(k) and src.get(k):
                dst[k] = src[k]
        dst["ms"] = dst.get("ms") or bool(src.get("ms"))

    for t in items:
        t = {k: (str(v).strip() if isinstance(v, str) else v) for k, v in t.items()}
        name = re.sub(r"^\s*[\d.]+\s*[).]?\s+", "", t.get("name", "")).strip() or t.get("name", "")
        t["name"] = name
        nk = _norm(name)
        code = _code(t.get("wbs"))
        if nk in by_name:                                   # 같은 과업 → 보완
            fill(by_name[nk], t)
            continue
        if code and code in by_code and _norm(by_code[code]["name"]) != nk:
            parent = code.rsplit(".", 1)[0] if "." in code else ""
            sib = [c for c in by_code if (c.rsplit(".", 1)[0] if "." in c else "") == parent and c.count(".") == code.count(".")]
            last = max((_key(c)[-1] for c in sib), default=0)
            code = (parent + "." if parent else "") + str(last + 1)
        if not code:
            tops = [c for c in by_code if "." not in c]
            code = str(max((int(c) for c in tops), default=0) + 1)
        t["wbs"] = code
        by_code[code] = t
        by_name[nk] = t
        order.append(code)

    # 날짜 환산
    for t in by_code.values():
        a, b = parse_when(t.get("start"), base), parse_when(t.get("end") or t.get("start"), base)
        if a and not b:
            b = a
        if b and not a:
            a = b
        t["s"], t["e"] = (a[0], b[1]) if a and b else (None, None)
        if t["s"] and t["e"] and t["e"] < t["s"]:
            t["s"], t["e"] = t["e"], t["s"]
        if t.get("ms") and t["s"]:                          # 마일스톤 = 한 시점 (착수는 월초, 그 밖은 월말)
            t["s"] = t["e"] = t["s"] if re.search(r"착수|킥오프|kick", t.get("name", ""), re.I) else t["e"]
        t["basis"] = "문서" if t["s"] else ""

    # 일정표(●·■)에서 직접 계산한 기간이 우선 (LLM 환산 오류 방지). 표에만 있는 과업은 새 항목으로 추가
    for n, s0, e0, owner in raw.get("schedule") or []:
        a, b = parse_when(s0, base), parse_when(e0, base)
        if not (a and b):
            continue
        best = max(by_code.values(), key=lambda t: (round(_sim(t["name"], n), 2), t["wbs"].count(".")), default=None)
        if best is not None and _sim(best["name"], n) >= 0.5 and not best.get("ms"):
            best["s"], best["e"], best["basis"] = a[0], b[1], "문서(일정표)"
            if owner and not best.get("owner"):
                best["owner"] = owner
        else:
            tops = [c for c in by_code if "." not in c]
            code = str(max((int(c) for c in tops), default=0) + 1)
            by_code[code] = {"wbs": code, "name": n, "owner": owner, "s": a[0], "e": b[1], "basis": "문서(일정표)",
                             "src": n, "ms": False}

    codes = sorted(by_code, key=_key)
    drop_weak_dates(by_code, codes, project, base)
    for c in codes:                                         # 하위 작업이 있는 묶음 행은 마일스톤이 아님
        if by_code[c].get("ms") and any(k.startswith(c + ".") for k in codes):
            by_code[c]["ms"] = False
    # 상위 기간 = 하위 기간을 모두 포함 (아래에서 위로)
    for c in sorted(codes, key=lambda c: -c.count(".")):
        kids = [by_code[k] for k in codes if k.startswith(c + ".") and k.count(".") == c.count(".") + 1 and by_code[k]["s"]]
        if kids:
            p = by_code[c]
            lo, hi = min(k["s"] for k in kids), max(k["e"] for k in kids)
            if not p["s"]:
                p["s"], p["e"], p["basis"] = lo, hi, "하위 합산"
            else:
                p["s"], p["e"] = min(p["s"], lo), max(p["e"], hi)
    # 하위가 모두 마일스톤인 묶음(예: '주요 마일스톤')은 막대를 그리지 않음 (전체 기간 막대가 과업처럼 보이지 않게)
    for c in codes:
        kids = [by_code[k] for k in codes if k.startswith(c + ".")]
        if kids and all(k.get("ms") for k in kids):
            by_code[c]["s"] = by_code[c]["e"] = None
            by_code[c]["basis"] = "마일스톤 묶음"
    dated = [by_code[c] for c in codes if by_code[c]["s"]]
    ps = parse_when(project.get("start"), base)
    pe = parse_when(project.get("end"), base)
    p_start = min([d["s"] for d in dated] + ([ps[0]] if ps else [])) if (dated or ps) else base
    p_end = max([d["e"] for d in dated] + ([pe[1]] if pe else [])) if (dated or pe) else _month_end(_add_months(base, 11))
    if not pe and project.get("months"):
        try:
            p_end = max(p_end, _month_end(_add_months(base, int(project["months"]) - 1)))
        except Exception:
            pass
    if user_start:                                          # 사용자가 정한 사업 기간이 우선
        p_start = user_start
    if user_end and user_end > p_start:
        p_end = user_end
    # 기간이 없는 작업 → 공수(소요 주) 추정 후 사업 기간(또는 날짜 있는 상위 작업 기간) 안에 배치
    schedule_undated(by_code, codes, p_start, p_end, chat_fn, request, progress)
    doc_norm = _norm(doc_text)
    tasks = []
    for c in codes:
        t = by_code[c]
        tasks.append({"wbs": c, "level": c.count(".") + 1, "name": t["name"], "owner": t.get("owner", "") or "",
                      "start": t["s"], "end": t["e"], "output": t.get("output", "") or "", "milestone": bool(t.get("ms")),
                      "basis": t["basis"] or "기간 없음", "src": t.get("src", "") or "",
                      "verified": verify_src(t.get("src", ""), doc_norm)})
    return {"project": {"name": project.get("name") or "사업 일정", "start": p_start, "end": p_end}, "tasks": tasks}


def auto_unit(start: dt.date, end: dt.date) -> str:
    return "week" if (end - start).days <= 190 else "month"


# ------------------------------------------------------------------ 4. 엑셀 간트
LEVEL_COLORS = {1: "#1F3864", 2: "#2E75B6", 3: "#9DC3E6", 4: "#BDD7EE"}
DONE = "#00B050"
MS_COLOR = "#E46C0A"


def to_excel(plan: dict, unit: str = "auto", source_name: str = "", spare_rows: int = 25) -> bytes:
    import xlsxwriter
    pj, tasks = plan["project"], plan["tasks"]
    start, end = pj["start"], pj["end"]
    if unit == "auto":
        unit = auto_unit(start, end)
    # 타임라인 칸
    if unit == "week":
        t0 = start - dt.timedelta(days=start.weekday())
        cols = []
        while t0 <= end:
            cols.append(t0)
            t0 += dt.timedelta(days=7)
        period_end = "{c}$5+6"
    else:
        t0, cols = dt.date(start.year, start.month, 1), []
        while t0 <= end:
            cols.append(t0)
            t0 = _add_months(t0, 1)
        period_end = "EOMONTH({c}$5,0)"

    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {"in_memory": True})
    font = "맑은 고딕"
    F = lambda **k: wb.add_format({"font_name": font, "font_size": 10, "valign": "vcenter", **k})
    f_title = F(bold=True, font_size=16, font_color="#1F3864")
    f_info = F(font_color="#595959")
    f_head = F(bold=True, font_color="#FFFFFF", bg_color="#1F3864", align="center", border=1, border_color="#BFBFBF", text_wrap=True)
    f_tl_grp = F(bold=True, font_color="#1F3864", bg_color="#D9E2F3", align="center", border=1, border_color="#BFBFBF")
    f_tl = F(font_size=9, font_color="#1F3864", bg_color="#EEF3FA", align="center", border=1, border_color="#BFBFBF",
             num_format='m"월"' if unit == "month" else "d")
    f_cell = {lv: F(border=1, border_color="#D9D9D9", bold=lv == 1, bg_color="#F2F5FA" if lv == 1 else "#FFFFFF")
              for lv in (1, 2, 3, 4)}
    f_name = {lv: F(border=1, border_color="#D9D9D9", bold=lv == 1, indent=lv - 1, text_wrap=True,
                    bg_color="#F2F5FA" if lv == 1 else "#FFFFFF") for lv in (1, 2, 3, 4)}
    f_date = {lv: F(border=1, border_color="#D9D9D9", num_format="yyyy-mm-dd", align="center", bold=lv == 1,
                    bg_color="#F2F5FA" if lv == 1 else "#FFFFFF") for lv in (1, 2, 3, 4)}
    f_num = F(border=1, border_color="#D9D9D9", align="center")
    f_pct = F(border=1, border_color="#D9D9D9", align="center", num_format="0%")
    f_grid = F(border=1, border_color="#E7E7E7", align="center", font_color=MS_COLOR, bold=True)
    f_warn = F(border=1, border_color="#D9D9D9", font_color="#C00000", align="center")
    f_ok = F(border=1, border_color="#D9D9D9", font_color="#548235", align="center")

    ws = wb.add_worksheet("간트 차트")
    heads = ["수준", "WBS", "작업명", "담당", "시작일", "종료일", "기간(일)", "진척률", "산출물", "일정 근거"]
    widths = [5, 7, 38, 12, 11, 11, 7, 7, 18, 11]
    for i, w in enumerate(widths):
        ws.set_column(i, i, w)
    C0 = len(heads)                                   # 타임라인 시작 열 (K)
    ws.set_column(C0, C0 + len(cols) - 1, 4.3 if unit == "month" else 3.6)
    last_col = C0 + len(cols) - 1
    ws.merge_range(0, 0, 0, max(last_col, 9), f"{pj['name']} — WBS 일정표", f_title)
    ws.write(1, 0, f"사업 기간 {start:%Y-%m-%d} ~ {end:%Y-%m-%d} · 작성 {dt.date.today():%Y-%m-%d}"
                   + (f" · 원문: {source_name}" if source_name else "")
                   + " · 시작일·종료일·진척률을 고치면 막대가 자동으로 바뀝니다.", f_info)
    parts = ["범례  "]
    for lab, colr in (("1수준", LEVEL_COLORS[1]), ("2수준", LEVEL_COLORS[2]), ("3수준", LEVEL_COLORS[3]),
                      ("진척(완료분)", DONE), ("마일스톤", None), ("오늘", "#C00000")):
        parts += [F(font_color=colr or MS_COLOR, font_size=12), "◆ " if colr is None else "■ ", f_info, lab + "    "]
    ws.write_rich_string(2, 0, *parts, f_info)
    # 머리글 (4~5행 = index 3,4)
    for i, h in enumerate(heads):
        ws.merge_range(3, i, 4, i, h, f_head)
    groups = {}
    for j, d in enumerate(cols):
        g = f"{d.year}년" if unit == "month" else f"{d:%y}.{d.month}월"
        groups.setdefault(g, []).append(j)
        ws.write_datetime(4, C0 + j, dt.datetime(d.year, d.month, d.day), f_tl)
    for g, js in groups.items():
        if len(js) > 1:
            ws.merge_range(3, C0 + js[0], 3, C0 + js[-1], g, f_tl_grp)
        else:
            ws.write(3, C0 + js[0], g, f_tl_grp)
    ws.set_row(3, 18)
    ws.set_row(4, 18)

    first = 5                                         # 데이터 첫 행 index (엑셀 6행)
    n_rows = len(tasks) + spare_rows
    for i in range(n_rows):
        r = first + i
        t = tasks[i] if i < len(tasks) else None
        lv = min(t["level"], 4) if t else 3
        R = r + 1
        if t:
            ws.write_number(r, 0, t["level"], f_num)
            ws.write_string(r, 1, t["wbs"], f_cell[lv])
            ws.write_string(r, 2, ("◆ " if t["milestone"] else "") + t["name"], f_name[lv])
            ws.write_string(r, 3, t["owner"], f_cell[lv])
            for ci, key in ((4, "start"), (5, "end")):
                if t[key]:
                    ws.write_datetime(r, ci, dt.datetime(t[key].year, t[key].month, t[key].day), f_date[lv])
                else:
                    ws.write_blank(r, ci, None, f_date[lv])
            ws.write_number(r, 7, 0, f_pct)
            ws.write_string(r, 8, t["output"], f_cell[lv])
            ws.write_string(r, 9, t["basis"], f_warn if t["basis"].startswith(("추정", "기간 없음")) else f_cell[lv])
            lines = max(1, -(-(len(t["name"]) + 2 * (lv - 1)) // 22))     # 작업명 칸(폭 38)에 들어가는 줄 수
            h = max(20 if t["level"] >= 2 else 22, 15 * lines + 5)
            ws.set_row(r, h, None, {"level": min(t["level"] - 1, 7)} if t["level"] >= 2 else None)
        else:
            for ci in (0, 1, 2, 3, 8, 9):
                ws.write_blank(r, ci, None, f_cell[3])
            ws.write_blank(r, 4, None, f_date[3])
            ws.write_blank(r, 5, None, f_date[3])
            ws.write_blank(r, 7, None, f_pct)
        ws.write_formula(r, 6, f'=IF(AND(E{R}<>"",F{R}<>""),F{R}-E{R}+1,"")', f_num)
        for j in range(len(cols)):
            c = xlsxwriter.utility.xl_col_to_name(C0 + j)
            pe = period_end.format(c=c)
            ws.write_formula(r, C0 + j, f'=IF(AND($E{R}<>"",$E{R}=$F{R},{c}$5<=$F{R},{pe}>=$E{R}),"◆","")', f_grid)
    rng_last = first + n_rows - 1
    if cols:
        c = xlsxwriter.utility.xl_col_to_name(C0)
        pe = period_end.format(c=c)
        span = f'$E6<>"",$F6<>"",$E6<>$F6,{c}$5<=$F6,{pe}>=$E6'
        area = (first, C0, rng_last, last_col)
        ws.conditional_format(*area, {"type": "formula", "criteria": f"=AND({span},$H6>0,{c}$5<=$E6+($F6-$E6)*$H6)",
                                      "format": wb.add_format({"bg_color": DONE}), "stop_if_true": True})
        for lv, colr in LEVEL_COLORS.items():
            crit = f"=AND({span},$A6={lv})" if lv < 4 else f"=AND({span},OR($A6>=4,$A6=\"\"))"
            ws.conditional_format(*area, {"type": "formula", "criteria": crit,
                                          "format": wb.add_format({"bg_color": colr}), "stop_if_true": True})
        today_rule = f"=AND(TODAY()>={c}$5,TODAY()<={pe})"
        ws.conditional_format(4, C0, 4, last_col, {"type": "formula", "criteria": today_rule,
                                                   "format": wb.add_format({"bg_color": "#C00000", "font_color": "#FFFFFF"})})
        ws.conditional_format(*area, {"type": "formula", "criteria": today_rule,
                                      "format": wb.add_format({"left": 2, "left_color": "#C00000"})})
    ws.data_validation(first, 7, rng_last, 7, {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 1,
                                               "input_title": "진척률", "input_message": "0%~100% (예: 50%)"})
    ws.data_validation(first, 4, rng_last, 5, {"validate": "date", "criteria": ">", "value": dt.date(2000, 1, 1),
                                               "input_title": "날짜", "input_message": "예: 2026-04-01"})
    ws.freeze_panes(first, 3)
    ws.outline_settings(True, False, True, False)
    ws.set_landscape()
    ws.set_paper(8 if len(cols) > 30 else 9)          # A3 / A4
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(3, 4)
    ws.print_area(0, 0, rng_last, max(last_col, 9))
    ws.hide_gridlines(2)
    ws.activate()

    # 근거 시트
    w2 = wb.add_worksheet("원문 근거")
    for i, (h, w) in enumerate((("WBS", 8), ("작업명", 40), ("일정 근거", 14), ("원문 구절", 50), ("원문 확인", 12))):
        w2.set_column(i, i, w)
        w2.write(0, i, h, f_head)
    for i, t in enumerate(tasks, 1):
        w2.write(i, 0, t["wbs"], f_cell[3])
        w2.write(i, 1, t["name"], f_name[min(t["level"], 4)])
        w2.write(i, 2, t["basis"], f_cell[3])
        w2.write(i, 3, t["src"], f_cell[3])
        w2.write(i, 4, "원문 일치" if t["verified"] else "확인 필요", f_ok if t["verified"] else f_warn)
    w2.freeze_panes(1, 0)
    # 안내 시트
    w3 = wb.add_worksheet("사용 안내")
    w3.set_column(0, 0, 100)
    tips = ["이 간트 차트는 로컬 AI가 문서에서 WBS와 일정을 뽑아 만든 초안입니다. 반드시 원문과 대조하세요.",
            "'간트 차트' 시트의 시작일·종료일을 고치면 막대가 자동으로 다시 그려집니다.",
            "진척률(예: 50%)을 넣으면 막대의 앞부분이 초록색(완료분)으로 바뀝니다.",
            "시작일과 종료일이 같은 행은 마일스톤(◆)으로 표시됩니다.",
            "새 작업은 표 아래 빈 행에 수준·WBS·작업명·날짜를 적으면 막대가 생깁니다.",
            "왼쪽 위 숫자 단추(1·2·3)로 하위 작업을 접고 펼칠 수 있습니다.",
            "'일정 근거'가 빨간 글씨인 행은 문서에 기간이 없어 상위 기간을 물려받았거나 기간이 비어 있는 항목입니다.",
            "'원문 근거' 시트에서 각 항목의 근거 구절이 실제 원문에 있는지(원문 일치/확인 필요) 볼 수 있습니다.",
            "오늘 날짜가 속한 칸은 머리글이 빨간색으로 표시됩니다."]
    w3.write(0, 0, "사용 안내", f_title)
    for i, s in enumerate(tips, 2):
        w3.write(i, 0, "• " + s, F(text_wrap=True))
    wb.close()
    return out.getvalue()


# ------------------------------------------------------------------ 표 ↔ 계획 변환 (화면 편집용)
def to_rows(plan):
    return [{"WBS": t["wbs"], "작업명": t["name"], "담당": t["owner"], "시작일": t["start"], "종료일": t["end"],
             "마일스톤": t["milestone"], "산출물": t["output"], "일정 근거": t["basis"],
             "원문 확인": "원문 일치" if t["verified"] else "확인 필요", "근거 구절": t["src"]} for t in plan["tasks"]]


def from_rows(rows, name, old=None):
    """화면에서 고친 표 → 계획. 날짜가 있는 행만 기간 계산에 사용."""
    def d(v):
        if v is None or v != v:          # None / NaN
            return None
        if isinstance(v, dt.datetime):
            return v.date()
        if isinstance(v, dt.date):
            return v
        try:
            return dt.date.fromisoformat(str(v)[:10])
        except Exception:
            return None
    def s_(v):
        return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()

    tasks, used = [], set()
    for r in rows:
        code, nm = _code(r.get("WBS")), s_(r.get("작업명"))
        if not nm:
            continue
        if not code or code in used:                       # 비었거나 겹치는 코드 → 새 1수준 번호
            code = str(max([int(c.split(".")[0]) for c in used] + [0]) + 1)
        used.add(code)
        s, e = d(r.get("시작일")), d(r.get("종료일"))
        if s and not e:
            e = s
        if e and not s:
            s = e
        if s and e and e < s:
            s, e = e, s
        ms = r.get("마일스톤")
        ms = bool(ms) and not (isinstance(ms, float) and ms != ms)
        tasks.append({"wbs": code, "level": code.count(".") + 1, "name": nm, "owner": s_(r.get("담당")),
                      "start": s, "end": e, "output": s_(r.get("산출물")), "milestone": ms,
                      "basis": s_(r.get("일정 근거")) or ("직접 입력" if s else "기간 없음"),
                      "src": s_(r.get("근거 구절")), "verified": r.get("원문 확인") == "원문 일치"})
        if ms and s:
            tasks[-1]["start"] = tasks[-1]["end"]           # 마일스톤 = 한 시점
    tasks.sort(key=lambda t: _key(t["wbs"]))
    dated = [t for t in tasks if t["start"]]
    if dated:
        s, e = min(t["start"] for t in dated), max(t["end"] for t in dated)
    else:
        s = (old or {}).get("start") or dt.date.today()
        e = (old or {}).get("end") or _month_end(_add_months(s, 11))
    return {"project": {"name": name, "start": s, "end": e}, "tasks": tasks}
