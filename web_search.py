"""무료 실시간 웹/뉴스 검색 (API 키 불필요): DuckDuckGo → Google News RSS 자동 우회."""
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

PER_PAGE_MAX = 1200
TOTAL_MAX = 4500
FETCH_TIMEOUT = 3
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def extract_keywords(question: str, use_llm: bool = True) -> str:
    """긴 문장에서 핵심 검색 키워드 1~2개 구문 추출 (Qwen 사용, 실패 시 규칙 기반)."""
    fallback = _rule_keywords(question)
    if not use_llm or len(question) < 12:
        return fallback
    try:
        import llm_client
        out = llm_client.chat([
            {"role": "system", "content": "사용자 문장에서 웹 검색에 쓸 핵심 키워드만 한 줄로 출력한다. "
                                          "공백으로 구분된 2~6개 단어, 설명·따옴표·문장부호 금지. 한국어만."},
            {"role": "user", "content": question[:500]}],
            options={"temperature": 0.1, "num_predict": 40})
        kw = re.sub(r"[\"'`\n].*", "", out.strip().split("\n")[0]).strip()
        kw = re.sub(r"[一-鿿]", "", kw).replace(",", " ")
        kw = " ".join(x for x in kw.split() if x not in ("보고서", "작성", "최신", "조사", "관련"))
        return kw if 2 <= len(kw) <= 80 else fallback
    except Exception:
        return fallback


def _rule_keywords(q: str) -> str:
    stop = ["조사해서", "조사해", "보고서로", "보고서", "써줘", "작성해줘", "작성해", "알려줘", "요약해줘", "요약해",
            "만들어줘", "만들어", "최근", "관련", "대한", "에서", "해주세요", "해줘", "를", "을", "과", "와", "및"]
    t = q
    for s in stop:
        t = t.replace(s, " ")
    t = re.sub(r"[^\w\s]", " ", t)
    words = [w for w in t.split() if len(w) > 1]
    return " ".join(words[:6]) or q[:40]


def _ddg(query, mode, n):
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    items = []
    with DDGS() as d:
        if mode in ("general", "both"):
            for r in d.text(query, region="kr-kr", max_results=n) or []:
                items.append({"title": r.get("title", ""), "url": r.get("href") or r.get("url", ""),
                              "snippet": r.get("body", ""), "source": urlparse(r.get("href", "")).netloc})
        if mode in ("news", "both"):
            for r in d.news(query, region="kr-kr", max_results=n) or []:
                items.append({"title": r.get("title", ""), "url": r.get("url", ""),
                              "snippet": r.get("body", ""), "source": r.get("source", "") or urlparse(r.get("url", "")).netloc})
    return items


def _google_news_rss(query, n):
    import feedparser
    url = (f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}"
           f"&hl=ko&gl=KR&ceid=KR:ko")
    resp = requests.get(url, headers=UA, timeout=8)
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries[:n]:
        summ = re.sub(r"<[^>]+>", " ", e.get("summary", ""))
        src = e.get("source", {}).get("title", "") if isinstance(e.get("source"), dict) else ""
        link = e.get("link", "")
        try:  # 구글 뉴스 리다이렉트 링크 → 실제 기사 URL
            from googlenewsdecoder import gnewsdecoder
            d = gnewsdecoder(link, interval=0.5)
            link = d.get("decoded_url") or link
        except Exception:
            pass
        items.append({"title": e.get("title", ""), "url": link,
                      "snippet": re.sub(r"\s+", " ", summ).strip(), "source": src or "Google News"})
    return items


def fetch_body(url: str) -> str:
    """trafilatura로 본문만 추출 (URL당 3초 타임아웃)."""
    try:
        import trafilatura
        r = requests.get(url, headers=UA, timeout=FETCH_TIMEOUT)
        if r.status_code != 200:
            return ""
        txt = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
        return re.sub(r"\n{2,}", "\n", txt).strip()
    except Exception:
        return ""


def search(question: str, mode: str = "both", n: int = 3, use_llm_keywords: bool = True) -> dict:
    """mode: 'both'(일반 웹+뉴스) | 'news'(최신 뉴스 전용). 반환: dict(keywords, engine, results, context)"""
    n = max(1, min(n, 5))
    kw = extract_keywords(question, use_llm_keywords)
    engine, items, err = "DuckDuckGo", [], ""
    try:
        items = _ddg(kw, "news" if mode == "news" else "both", n)
    except Exception as e:  # RateLimit, 네트워크 오류 등 전부 우회
        err = f"{type(e).__name__}: {e}"
    if not items:
        engine = "Google News RSS (우회)"
        try:
            items = _google_news_rss(kw, n)
        except Exception as e:
            err += f" / RSS: {type(e).__name__}: {e}"
    # 중복 URL 제거 후 n개
    seen, uniq = set(), []
    for it in items:
        if it["url"] and it["url"] not in seen:
            seen.add(it["url"])
            uniq.append(it)
    uniq = uniq[:n]

    with ThreadPoolExecutor(max_workers=5) as ex:
        bodies = list(ex.map(lambda it: fetch_body(it["url"]), uniq))
    total, results = 0, []
    for it, body in zip(uniq, bodies):
        text = (body or it["snippet"] or it["title"])[:PER_PAGE_MAX]
        if total + len(text) > TOTAL_MAX:
            text = text[: max(0, TOTAL_MAX - total)]
        if not text:
            continue
        total += len(text)
        it["text"] = text
        it["full_body"] = bool(body)
        results.append(it)
    ctx = "\n\n".join(f"[웹검색: {r['source'] or urlparse(r['url']).netloc}] {r['title']}\n{r['text']}"
                      for r in results)
    return {"keywords": kw, "engine": engine, "results": results, "context": ctx, "error": err}
