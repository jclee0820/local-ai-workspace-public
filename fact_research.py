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


def wiki_page(title, lang="ko"):
    try:
        d = _api(lang, action="query", prop="extracts", explaintext=1, titles=title, redirects=1)
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


def _title_score(t, request, qual):
    s = 3 if qual and qual in t else 0
    s -= 4 * sum(1 for m in MEDIA if m in t.lower() and m not in request)
    if "동음이의" in t or "disambiguation" in t.lower():
        s -= 5
    return s


def collect(request, ko_query, core, en_query="", qual="", progress=None, max_ko=7, max_en=2):
    """관련 위키 문서를 모아 [{'lang','title','url','sections':[(제목,본문)]}] 반환."""
    say = progress or (lambda m: None)
    ko, en = [], []
    pat = re.compile(rf"(^|[\s(:《『]){re.escape(core.lower())}($|[\s):》』,])")
    for q in dict.fromkeys([ko_query, f"{core} {qual}".strip(), core]):
        say(f"📚 위키백과 검색(ko): {q}")
        for t in wiki_search(q, "ko"):
            if t not in ko and pat.search(t.lower()):     # '랫팩듄' 처럼 단어 일부만 겹치는 문서 제외
                ko.append(t)
    ko = [t for t in sorted(ko, key=lambda t: -_title_score(t, request, qual)) if _title_score(t, request, qual) > -4]
    if en_query:
        say(f"📚 위키백과 검색(en): {en_query}")
        first = en_query.split()[0].lower()
        en = [t for t in wiki_search(en_query, "en") if first in t.lower()
              and _title_score(t, request, qual) > -4][:max_en]
    pages = []
    for lang, t in [("ko", t) for t in ko[:max_ko]] + [("en", t) for t in en]:
        title, text = wiki_page(t, lang)
        if text:
            pages.append({"lang": lang, "title": title, "sections": split_sections(text),
                          "url": f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"})
    return pages


def select(pages, focus, layout, budget=3800):
    """섹션 성격에 맞는 자료만 골라 텍스트로 반환."""
    words = FOCUS.get(focus, []) + FOCUS.get("세계관" if layout == "prose" else "", [])
    picks = []
    for p in pages:
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
