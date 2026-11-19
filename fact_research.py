"""사실 자료 수집기: 위키백과(한국어·영어). API 키 불필요.
문서를 섹션 단위로 모아 두고, 웹페이지의 섹션 성격(세계관/전개/인물…)에 맞는 부분만 골라 준다."""
import re

import requests

UA = {"User-Agent": "LocalAIWorkspace/1.0 (personal research tool)"}
FOCUS = {  # 섹션 초점 → 위키 섹션 제목에서 찾을 단어
    "세계관": ["설정", "세계관", "배경", "세계", "개요", "setting", "premise", "universe", "overview", "synopsis"],
    "전개": ["작품", "시리즈", "영화", "소설", "개봉", "films", "novels", "adaptations", "series", "release"],
    "인물": ["등장 인물", "등장인물", "출연", "캐스팅", "인물", "cast", "characters"],
    "줄거리": ["줄거리", "plot", "synopsis"],
    "역사": ["역사", "연혁", "history"],
    "특징": ["특징", "개요", "features", "overview"],
    "평가": ["반응", "평가", "수상", "reception", "accolades"],
}
SKIP = ("각주", "외부 링크", "같이 보기", "참고 문헌", "references", "external links", "see also", "notes",
        "further reading", "bibliography")
MEDIA = ("게임", "배틀", "보드", "만화", "드라마", "애니메이션", "음반", "앨범", "game", "board")


_S = requests.Session()
_S.headers.update(UA)


def _api(lang, **params):
    """위키백과 API 호출. 일시적 요청 제한(429 등)에 대비해 최대 4회 재시도."""
    import time
    params.update({"format": "json", "maxlag": 5})
    last = None
    for i in range(4):
        try:
            r = _S.get(f"https://{lang}.wikipedia.org/w/api.php", params=params, timeout=10)
            if r.status_code == 200:
                d = r.json()
                if "error" not in d:
                    return d
                last = d["error"]
            else:
                last = r.status_code
        except Exception as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"위키백과 응답 실패: {last}")


def wiki_search(query, lang="ko", n=8):
    try:
        return [x["title"] for x in _api(lang, action="query", list="search", srsearch=query, srlimit=n)["query"]["search"]]
    except Exception:
        return []


def wiki_page(title, lang="ko", intro_only=False):
    """intro_only: 첫 단락만(작품·인물 후보 확인용 — 문서 전체보다 훨씬 빠르고 요청 제한에도 덜 걸림)."""
    try:
        extra = {"exintro": 1} if intro_only else {}
        d = _api(lang, action="query", prop="extracts", explaintext=1, titles=title, redirects=1, **extra)
        page = list(d["query"]["pages"].values())[0]
        return page.get("title", title), page.get("extract", "")
    except Exception:
        return title, ""


def split_sections(text):
    parts = re.split(r"^(==+)\s*(.+?)\s*\1\s*$", text, flags=re.M)
    out = [("개요", parts[0].strip())]
    for i in range(1, len(parts) - 2, 3):
        out.append((parts[i + 1].strip(), parts[i + 2].strip()))
    return [(t, b) for t, b in out if b and not any(s in t.lower() for s in SKIP)]


def wiki_image(title, lang="ko", size=500):
    """위키백과 문서의 대표 그림(정보상자 포스터·인물 사진) 주소. 한국어 문서에 없으면 영어판 같은 문서에서
    (영화 포스터는 대개 영어판에만 있음 — pilicense=any 로 비자유 이미지 포함)."""
    try:
        d = _api(lang, action="query", prop="pageimages|langlinks", titles=title, redirects=1, pithumbsize=size,
                 pilicense="any", lllang="en")
        pg = list(d["query"]["pages"].values())[0]
        if pg.get("thumbnail", {}).get("source"):
            return pg["thumbnail"]["source"]
        en = (pg.get("langlinks") or [{}])[0].get("*") if lang != "en" else None
        if en:
            d = _api("en", action="query", prop="pageimages", titles=en, redirects=1, pithumbsize=size, pilicense="any")
            pg = list(d["query"]["pages"].values())[0]
            return pg.get("thumbnail", {}).get("source") or ""
    except Exception:
        pass
    return ""


def _title_score(t, request, qual):
    s = 3 if qual and qual in t else 0
    s -= 4 * sum(1 for m in MEDIA if m in t.lower() and m not in request)
    if "동음이의" in t or "disambiguation" in t.lower():
        s -= 5
    return s


def collect(request, ko_query, core, en_query="", qual="", progress=None, max_ko=7, max_en=2, en_core="", candidates=None):
    """관련 위키 문서를 모아 [{'lang','title','url','sections':[(제목,본문)]}] 반환.
    en_core(주제의 영어 이름)가 있으면 영어 문서는 제목에 그 이름이 '통째로' 들어 있어야 채택
    (예전엔 검색어 첫 단어만 봐서 'Star Wars' 요청에 'Timeline of Star Trek' 이 들어왔음)."""
    say = progress or (lambda m: None)
    ko, en = [], []
    pat = re.compile(rf"(^|[\s(:《『]){re.escape(core.lower())}($|[\s):》』,])")
    for q in dict.fromkeys([ko_query, f"{core} {qual}".strip(), core]):
        say(f"📚 위키백과 검색(ko): {q}")
        for t in wiki_search(q, "ko"):
            if t not in ko and pat.search(t.lower()):     # '랫팩듄' 처럼 단어 일부만 겹치는 문서 제외
                ko.append(t)
    if re.search(r"시리즈|영화|드라마|애니메이션|작품|연대|연표|순서|에피소드", request):   # 작품 목록형 요청: 매체별로 더 찾음
        for suf in ("에피소드", "영화", "드라마", "애니메이션", "시리즈"):
            q = f"{core} {suf}"
            say(f"📚 위키백과 검색(ko): {q}")
            for t in wiki_search(q, "ko", n=12):
                if t not in ko and pat.search(t.lower()) and "동음이의" not in t:
                    ko.append(t)
        max_ko = max(max_ko, 16)
    if not ko and " " in core.strip():                     # 주제어에 수식어가 붙어 제목과 안 맞으면 첫 단어로 다시
        core1 = core.split()[0]
        pat1 = re.compile(rf"(^|[\s(:《『]){re.escape(core1.lower())}($|[\s):》』,])")
        say(f"📚 위키백과 검색(ko): {core1}")
        ko = [t for t in wiki_search(core1, "ko") if pat1.search(t.lower())]
    ko = [t for t in sorted(ko, key=lambda t: -_title_score(t, request, qual)) if _title_score(t, request, qual) > -4]
    if en_query:
        say(f"📚 위키백과 검색(en): {en_query}")
        if en_core:
            ep = re.compile(rf"(^|[\s(:]){re.escape(en_core.lower())}($|[\s):,'])")
            ok = lambda t: bool(ep.search(t.lower()))
        else:
            first = en_query.split()[0].lower()
            ok = lambda t: first in t.lower()
        en = [t for t in wiki_search(en_query, "en") if ok(t) and _title_score(t, request, qual) > -4][:max_en]
    people = []
    if re.search(r"주인공|등장\s*인물|인물|캐릭터", request):     # 인물 요청: 등장인물 문서(제목에 주제어가 없어도 본문 첫 단락에 있으면)
        for q in (f"{core} 등장인물", f"{core} 주인공", f"{core} 캐릭터"):
            say(f"📚 위키백과 검색(ko): {q}")
            for t in wiki_search(q, "ko", n=10):
                if t not in ko and t not in people and "동음이의" not in t and "목록" not in t:
                    people.append(t)
    cand = candidates or {}
    c_works = [str(t).strip() for t in (cand.get("works") or []) if str(t).strip()][:16]
    c_people = [str(t).strip() for t in (cand.get("people") or []) if str(t).strip()][:8]
    base = ko[:max_ko]
    jobs = [("ko", t, "") for t in base] + [("en", t, "") for t in en]
    jobs += [("ko", t, "work") for t in c_works if t not in base]          # 제목에 주제어가 없는 작품(제국의 역습 등)
    jobs += [("ko", t, "person") for t in c_people + [p for p in people if p not in c_people][:4]]
    if core not in base:                                      # 주제 대표 문서(예: '스타워즈')는 항상 포함 — 한 줄 소개의 근거
        jobs.insert(0, ("ko", core, ""))
    uniq, jobs0 = set(), jobs
    jobs = []
    for j in jobs0:
        if (j[0], j[1]) not in uniq:
            uniq.add((j[0], j[1]))
            jobs.append(j)
    if c_works or c_people:
        say(f"📚 위키백과 문서 {len(jobs)}개 받는 중 (후보 작품 {len(c_works)}·인물 {len(c_people)} 포함)")
    from concurrent.futures import ThreadPoolExecutor
    def fetch(j):                                             # 후보 작품·인물은 첫 단락만 받음
        return wiki_page(j[1], j[0], intro_only=j[2] in ("work", "person"))
    with ThreadPoolExecutor(2) as ex:                         # 동시에 2개씩 (4개씩 받으면 위키백과 요청 제한으로 일부가 조용히 빠졌음)
        got = list(ex.map(lambda j: (j, fetch(j)), jobs))
    got = [(j, r if r[1] else fetch(j)) for j, r in got]      # 실패한 문서는 한 번 더(순서대로)
    names = [n for n in (core, en_core) if n]
    pages, seen, n_person = [], set(), 0
    for (lang, asked, kind), (title, text) in got:
        if not text or (lang, title) in seen:
            continue
        secs = split_sections(text)
        intro = secs[0][1][:600] if secs else ""
        if kind == "work":                                    # 후보 작품: 첫 단락에 주제어와 연도가 있는 영화·드라마·애니메이션이어야
            if not any(n in intro for n in names) or not re.search(r"\d{4}년", intro) \
                    or not re.search(r"영화|드라마|시리즈|애니메이션|작품", intro[:250]) or "동음이의" in title:
                continue
        elif kind == "person":                                # 등장인물: 주제어가 있고, 가상 인물이며, 배우·감독 문서가 아니어야
            head = intro[:250]
            if not any(n in intro for n in names) or n_person >= 8 \
                    or not re.search(r"등장\s*인물|가상의|캐릭터|주인공|인물이다|인물로", head) \
                    or re.search(r"배우|성우|감독|가수|작곡가|각본가|코미디언|이다\.\s*$", head[:80]) \
                    or re.search(r"(영화|드라마|소설|게임|애니메이션)이다", head[:120]):
                continue
            n_person += 1
        seen.add((lang, title))
        pages.append({"lang": lang, "title": title, "sections": secs, "kind": kind,
                      "url": f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"})
    return pages


def select(pages, focus, layout, budget=3800):
    """섹션 성격에 맞는 자료만 골라 텍스트로 반환."""
    words = FOCUS.get(focus, []) + FOCUS.get("세계관" if layout == "prose" else "", [])
    picks = []
    for p in pages:
        if p.get("kind") == "person":                         # 인물 문서: 인물 섹션에만, 첫 단락으로
            if focus == "인물" and p["sections"]:
                picks.append((5, f"[출처: {p['title']} ({p['lang']})] {p['title']}\n{p['sections'][0][1][:500]}"))
            continue
        for i, (st, body) in enumerate(p["sections"]):
            s = 0
            if layout == "timeline" and i == 0:
                s, body = 5, body[:450]                    # 작품별 첫 단락(개봉 연도·감독 등)
            elif any(w.lower() in st.lower() for w in words):
                s = 4
                body = body[:1500 if layout == "cards" else 1000]
            elif i == 0 and layout == "prose":
                s, body = 2, body[:700]
            if s:
                picks.append((s, f"[출처: {p['title']} ({p['lang']})] {st}\n{body}"))
    picks.sort(key=lambda x: -x[0])
    out, used = [], 0
    for _, c in picks:
        if used + len(c) > budget:
            c = c[: budget - used]
        if len(c) < 150:
            break
        out.append(c)
        used += len(c)
    return "\n\n".join(out)
