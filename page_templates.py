"""웹페이지 틀(템플릿) — 페이지 종류를 먼저 고르면 구성·자료원·부품이 정해지고, AI는 칸 안의 내용만 채운다.

틀 6종
  topic   주제·작품 소개   (위키백과)        개요 카드 · 연표 · 인물 카드
  list    목록·비교        (웹 검색·사진)    3D 회전 갤러리 · 항목 카드 · 정렬 비교표 · 차트/3D 막대
  history 연표·역사        (위키백과)        연도 슬라이더 타임라인 · 주제별 펼침
  org     기관·사업 소개   (올린 문서)       핵심 수치 · 연혁 · 주요 사업 카드 · 거점 지구본 · 연락처
  report  보고서 요약      (올린 문서)       핵심 수치 · 장별 요약(펼침) · 원문 표(정렬) · 차트
  event   행사·안내        (입력한 내용)     카운트다운 · 프로그램 표 · 오시는 길 · 문의
모든 틀: 디자인 트렌드(design_trends) 적용, 표지 3D 배경 선택, 인터넷 없이 열리는 단일 HTML."""
import datetime
import html
import json
import re
import urllib.parse

import web_components as wc

TEMPLATES = {
    "topic": {"name": "주제·작품 소개", "icon": "📖", "src": "위키백과",
              "desc": "영화·소설·기술·인물 같은 하나의 주제를 개요·연표·인물 카드로 소개합니다.",
              "parts": "3D 표지 · 기울어지는 카드 · 연도 슬라이더 연표"},
    "list": {"name": "목록·비교", "icon": "🗂️", "src": "웹 검색 + 사진",
             "desc": "제품·영화·장소처럼 여러 항목을 찾아 사진·특징·비교표로 정리합니다.",
             "parts": "3D 회전 갤러리 · 정렬·검색 비교표 · 막대 차트 · 3D 막대"},
    "history": {"name": "연표·역사", "icon": "🕰️", "src": "위키백과",
                "desc": "사건·기관·기술의 흐름을 시간 순으로 보여 줍니다.",
                "parts": "연도 슬라이더 타임라인 · 주제별 펼침 목록"},
    "org": {"name": "기관·사업 소개", "icon": "🏢", "src": "올린 문서(또는 지식보관함)",
            "desc": "사업계획서·기관 소개 자료로 개요·성과 수치·연혁·주요 사업을 소개합니다.",
            "parts": "숫자가 올라가는 핵심 수치 · 3D 막대 · 연혁 · 거점 지구본"},
    "report": {"name": "보고서 요약", "icon": "📊", "src": "올린 문서",
               "desc": "보고서를 핵심 수치·장별 요약·원문 표·차트로 한 페이지에 요약합니다.",
               "parts": "핵심 수치 · 장별 펼침 · 정렬 표(탭) · 차트"},
    "event": {"name": "행사·안내", "icon": "📅", "src": "입력한 내용",
              "desc": "세미나·설명회 안내 페이지 — 일시·장소·프로그램·문의를 입력하면 만듭니다.",
              "parts": "카운트다운 · 프로그램 표 · 오시는 길 링크"},
}
HEROES = {"particles": "3D 입자 네트워크", "globe": "3D 점 지구본(거점 표시)", "theme": "디자인 트렌드 기본 배경", "none": "없음"}
DEFAULT_THEME = {"bg": "#F6F7FB", "bg2": "#EAEDF5", "surface": "#FFFFFF", "text": "#151A2D", "muted": "#5D6478",
                 "accent": "#2563EB", "accent2": "#06B6D4", "heading_font": "IBM Plex Sans KR", "body_font": "Noto Sans KR", "hero": "grid"}


def _e(s):
    return html.escape(str("" if s is None else s))


# ================================================================== 공통 렌더러
BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0} html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--tx);font-family:var(--bf);line-height:1.7;font-size:16.5px;-webkit-font-smoothing:antialiased}
a{color:var(--ac)}
.nav{position:sticky;top:0;z-index:30;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:12px clamp(16px,5vw,56px);
 background:color-mix(in srgb,var(--bg) 78%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid color-mix(in srgb,var(--tx) 10%,transparent)}
.brand{font-family:var(--hf);font-weight:800;letter-spacing:.02em} .nav nav{display:flex;gap:clamp(10px,2.4vw,26px);flex-wrap:wrap}
.nav nav a{color:var(--mu);text-decoration:none;font-size:.93rem;font-weight:500} .nav nav a:hover{color:var(--ac)}
.hero{position:relative;min-height:78vh;display:grid;place-items:center;text-align:center;overflow:hidden;padding:110px 20px 120px;
 background:radial-gradient(900px 500px at 75% 10%,color-mix(in srgb,var(--ac2) 22%,transparent),transparent 60%),radial-gradient(800px 500px at 10% 100%,color-mix(in srgb,var(--ac) 20%,transparent),transparent 60%),var(--bg)}
.hero-art{position:absolute;inset:0;width:100%;height:100%;z-index:0}
.hero-inner{position:relative;z-index:2;max-width:980px}
.eyebrow{display:inline-block;font-size:.8rem;letter-spacing:.18em;color:var(--ac);border:1px solid color-mix(in srgb,var(--ac) 40%,transparent);padding:6px 14px;border-radius:999px;margin-bottom:22px;background:color-mix(in srgb,var(--sf) 70%,transparent)}
.hero h1{font-family:var(--hf);font-size:clamp(2.4rem,7vw,5.2rem);line-height:1.08;letter-spacing:-.02em;font-weight:900}
.tagline{font-size:clamp(1.05rem,2.2vw,1.35rem);margin-top:18px;color:var(--mu)}
.hero-globe{margin-top:26px}
main{max-width:1180px;margin:0 auto;padding:0 clamp(16px,5vw,44px)}
.sec{padding:clamp(56px,8vw,96px) 0;border-top:1px solid color-mix(in srgb,var(--tx) 8%,transparent)}
.sec-head{margin-bottom:34px;max-width:780px} .sec-no{color:var(--ac);font-weight:800;letter-spacing:.2em;font-size:.85rem}
.sec-head h2{font-family:var(--hf);font-size:clamp(1.7rem,3.6vw,2.6rem);line-height:1.2;margin-top:6px;letter-spacing:-.01em}
.sec-intro{color:var(--mu);margin-top:12px;font-size:1.05rem}
.lead{font-size:clamp(1.08rem,1.9vw,1.28rem);line-height:1.85;margin-bottom:26px;max-width:860px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:26px;align-items:start}
.info{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.info div{background:var(--sf);border-radius:16px;padding:20px 22px;border:1px solid color-mix(in srgb,var(--tx) 9%,transparent)}
.info b{display:block;color:var(--ac);font-size:.85rem;margin-bottom:4px} .info span{font-size:1.05rem;font-weight:600}
.btn{display:inline-block;margin-top:14px;padding:10px 18px;border-radius:999px;background:var(--ac);color:#fff;text-decoration:none;font-weight:600;margin-right:8px}
.btn.ghost{background:transparent;color:var(--ac);border:1px solid var(--ac)}
.note{font-size:.88rem;color:var(--mu);margin-top:14px}
footer{margin-top:30px;padding:44px clamp(16px,5vw,56px);background:var(--bg2);color:var(--mu);font-size:.88rem}
footer h4{color:var(--tx);margin-bottom:10px} footer ul{list-style:none;display:grid;gap:5px;margin-bottom:14px}
.reveal{opacity:0;transform:translateY(22px);transition:opacity .7s ease,transform .7s ease} .reveal.on{opacity:1;transform:none}
@media(max-width:760px){.nav nav{display:none}}
@media(prefers-reduced-motion:reduce){.reveal{opacity:1;transform:none;transition:none}}
"""


def theme_vars(trend):
    import design_trends as dt
    import web_builder as wb
    t = wb.fix_theme(dt.web_theme(dict(DEFAULT_THEME), trend) if trend and trend != "auto" else dict(DEFAULT_THEME))
    return t


def render(page, trend=None):
    """page = {'title','tagline','eyebrow','hero','hero_markers','hero_extra','sections':[{'nav','heading','intro','html'}],'sources','note'}"""
    import design_trends as dt
    import web_builder as wb
    t = theme_vars(trend)
    fams = "&".join(f"family={wb.FONTS[f]}" for f in {t["heading_font"], t["body_font"], "Noto Sans KR"} if f in wb.FONTS)
    hero = page.get("hero", "particles")
    if hero == "particles":
        art = wc.hero_particles()
    elif hero == "theme":
        art = wb._hero_bg(t)
    else:
        art = ""
    globe_html = f'<div class="hero-globe">{wc.globe(page.get("hero_markers") or [])}</div>' if hero == "globe" else ""
    secs = [s for s in page.get("sections", []) if s.get("html")]
    nav = "".join(f'<a href="#s{i}">{_e(s.get("nav") or s.get("heading"))}</a>' for i, s in enumerate(secs, 1))
    body = "".join(
        f'<section id="s{i}" class="sec"><header class="sec-head reveal"><span class="sec-no">{i:02d}</span><h2>{_e(s.get("heading"))}</h2>'
        + (f'<p class="sec-intro">{_e(s["intro"])}</p>' if s.get("intro") else "") + f'</header>{s["html"]}</section>'
        for i, s in enumerate(secs, 1))
    src = "".join(f'<li><a href="{_e(x["url"])}" target="_blank" rel="noopener">{_e(x["title"])}</a></li>' if x.get("url") else f"<li>{_e(x['title'])}</li>"
                  for x in page.get("sources", []))
    root = (f":root{{--bg:{t['bg']};--bg2:{t['bg2']};--sf:{t['surface']};--tx:{t['text']};--mu:{t['muted']};--ac:{t['accent']};--ac2:{t['accent2']};"
            f"--hf:'{t['heading_font']}','Noto Sans KR',sans-serif;--bf:'{t['body_font']}','Noto Sans KR',sans-serif}}")
    today = datetime.date.today().isoformat()
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(page.get('title'))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?{fams}&display=swap" rel="stylesheet">
<style>{root}{BASE_CSS}{wc.CSS}{dt.web_css(trend) if trend and trend != 'auto' else ''}</style></head><body>
<div class="nav"><span class="brand">{_e(page.get('title'))}</span><nav>{nav}</nav></div>
<section class="hero">{art}<div class="hero-inner"><span class="eyebrow">{_e(page.get('eyebrow') or today)}</span>
<h1>{_e(page.get('title'))}</h1>{f'<p class="tagline">{_e(page["tagline"])}</p>' if page.get('tagline') else ''}{page.get('hero_extra', '')}{globe_html}</div></section>
<main>{body}</main>
<footer>{('<h4>자료 출처</h4><ul>' + src + '</ul>') if src else ''}<p>{_e(page.get('note') or '')} 생성일 {today} · 로컬 AI 작업실</p></footer>
<script>const _io=new IntersectionObserver(es=>es.forEach(e=>{{if(e.isIntersecting){{e.target.classList.add('on');_io.unobserve(e.target)}}}}),{{threshold:.1}});
document.querySelectorAll('.reveal').forEach(el=>_io.observe(el));</script><script>{wc.RUNTIME_JS}</script></body></html>"""


# ================================================================== 틀 1·3: 주제 소개 / 연표 (위키백과)
def _wiki_sections(content, timeline_first=False):
    out, tl_items, keys = [], [], []
    for s in content.get("sections", []):
        lay, items = s.get("layout"), s.get("items", [])
        if lay == "timeline":
            tl_items += [{"year": it.get("tag"), "title": it.get("title"), "sub": it.get("subtitle"), "body": it.get("body")} for it in items]
            out.append({"nav": s.get("nav"), "heading": s.get("heading"), "intro": s.get("intro"), "html": wc.timeline(tl_items[-len(items):])})
        elif lay == "cards":
            out.append({"nav": s.get("nav"), "heading": s.get("heading"), "intro": s.get("intro"),
                        "html": wc.tilt_cards([{"title": it.get("title"), "sub": it.get("subtitle"), "body": it.get("body"), "tag": it.get("tag")} for it in items])})
        else:
            keys.append(s)
            items = [it for it in items if (it.get("title") or "").strip() and (it.get("body") or "").strip()]
            if not (s.get("intro") or "").strip() and len(items) < 2:
                continue                                                       # 내용이 거의 없는 섹션은 뺌
            body = (f'<p class="lead reveal">{_e(s.get("intro"))}</p>' if s.get("intro") else "")
            if items:
                body += wc.tilt_cards([{"title": it.get("title"), "body": it.get("body")} for it in items])
            out.append({"nav": s.get("nav"), "heading": s.get("heading"), "html": body})
    if timeline_first:
        out.sort(key=lambda s: 0 if 'data-wc="timeline"' in s["html"] else 1)
    return out


def build_topic(form, chat_fn, progress=None, history=False):
    import web_builder as wb
    topic = form["topic"].strip()
    req = f"{topic} — {form.get('focus') or ('역사와 주요 사건을 시간 순으로' if history else '개요, 전개, 주요 인물')}"
    res = wb.build(req, chat_fn, progress, core=topic, allow_product=False, extra_context=form.get("extra", ""))
    c = res["content"]
    page = {"title": c.get("title") or topic, "tagline": c.get("tagline"), "eyebrow": "TIMELINE" if history else "INTRODUCTION",
            "hero": form.get("hero", "particles"), "sections": _wiki_sections(c, timeline_first=history),
            "sources": res["sources"], "note": "본문은 위 자료를 근거로 로컬 AI가 정리했습니다(위키백과 본문: CC BY-SA 4.0). 근거가 확인되지 않은 항목은 뺐습니다."}
    return page, {"removed": res["removed"], "context": res["context"], "sources": res["sources"]}


# ================================================================== 틀 2: 목록·비교 (웹 검색)
LIST_SYS = """아래 [자료]는 '{cat}' 관련 웹 검색 결과이다. 자료에 '구체적인 이름'으로 등장하는 항목(제품·작품·장소·기관 등)을 찾아라.
- 자료에 글자 그대로 나온 이름만. 기억·추측 금지. 일반 명사·분류명은 항목이 아니다. 같은 대상의 변형(세대·색상)은 하나로.
- 여러 자료에 반복 등장하는 대표 항목 우선. 최대 {n}개.
- name 은 자료 표기 그대로, name_en 은 영어 이름(이미지 검색용, 모르면 ""), maker 는 만든 곳·주체(자료에 있을 때).
출력 JSON: {{"items":[{{"name":"","name_en":"","maker":""}}]}}"""

ITEM_SYS = """아래 [자료]만 근거로 '{name}' 의 정보를 JSON 으로 정리한다. 자료에 없으면 빈 문자열. 추측·기억 금지.
- attrs: 다음 비교 항목마다 값(자료 표기 그대로, 단위 포함)과 근거(자료에서 글자 그대로 복사한 10~40자): {attrs}
- summary: 한 줄 소개(40자 이내, 자료 근거). features: 특징 2~3개, 각 {{"text":"20~40자","evidence":"자료 원문 10~40자"}}
- kind: 한 단어 분류(자료에서 알 수 있을 때).
출력 JSON: {{"summary":"","kind":"","attrs":{{"항목명":{{"value":"","evidence":""}}}},"features":[{{"text":"","evidence":""}}]}}"""

PHOTO_Q = ("'{name}'({maker}) 를 대표하는 사진을 찾고 있다(제품이면 제품 사진, 영화·책이면 포스터·표지, 장소면 그 장소 사진).\n"
           "이 이미지가 그런 사진인가? 글자가 많은 광고·인포그래픽·로고만 있는 그림·다른 대상이면 no.\n형식: 한 줄 설명 | yes 또는 no")


def _item_photo(it, cat_en, chat_fn):
    import llm_client
    import product_builder as pb
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    q = it.get("name_en") or f"{it['name']} {cat_en}".strip()
    toks = [t for t in re.split(r"[\s()/,:-]+", q.lower()) if len(t) >= 2]
    vision = llm_client.supports_vision()
    try:
        with DDGS() as d:
            rows = d.images(q, max_results=15) or []
    except Exception:
        return
    tried = 0
    for r in rows:
        url, title = r.get("image") or "", (r.get("title") or "").lower()
        if not url or re.search(r"logo|icon|\.svg|\.gif|sprite", url.lower()):
            continue
        if toks and sum(t in title or t in url.lower() for t in toks) < max(1, len(toks) // 3):
            continue
        try:
            uri = pb._to_data_uri(url, r.get("url") or "")
        except Exception:
            uri = ""
        if not uri:
            continue
        tried += 1
        if vision:
            try:
                out = chat_fn([{"role": "user", "content": PHOTO_Q.format(name=it.get("name_en") or it["name"], maker=it.get("maker", "")),
                                "images": [uri.split(",", 1)[1]]}], {"temperature": 0, "num_predict": 60, "num_ctx": 4096})
                if not out.strip().lower().rstrip(".").endswith("yes"):
                    if tried >= 4:
                        return
                    continue
            except Exception:
                continue
        it["image"] = uri
        it["image_credit"] = re.sub(r"^www\.", "", urllib.parse.urlparse(r.get("url") or url).netloc)
        return


def build_list(form, chat_fn, progress=None):
    import product_builder as pb
    say = progress or (lambda f, m: None)
    cat = form["topic"].strip()
    attrs = [a.strip() for a in re.split(r"[,，/·]", form.get("attrs") or "") if a.strip()][:6] or ["특징"]
    n = int(form.get("n") or 6)
    year = datetime.date.today().year
    say(0.03, "🔑 검색어 만드는 중…")
    try:
        d = pb._json(chat_fn, pb.TOPIC_SYS.replace("제품 분야", "조사 대상(분야)"), f"{cat} — 비교 항목: {', '.join(attrs)}", num_predict=300, num_ctx=2048)
    except Exception:
        d = {}
    cat_en = (d.get("category_en") or "").strip()
    qs = [q for q in (d.get("queries") or []) if isinstance(q, str)][:3] or [f"{cat} {year}", f"{cat} 순위 비교", f"{cat} {' '.join(attrs[:2])}"]
    say(0.08, f"🔎 웹 검색: {', '.join(qs)}")
    docs = pb._search_docs(qs + [q for q in (d.get("queries_en") or []) if isinstance(q, str)][:2], n=6) + pb._search_docs(qs[:1], n=5, news=True)
    seen, pool = set(), []
    for x in docs:
        if x["url"] not in seen:
            seen.add(x["url"])
            pool.append(x)
    if not pool:
        raise RuntimeError("웹 검색 결과를 가져오지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.")
    say(0.2, f"📰 검색 결과 {len(pool)}건 — 항목 추리는 중…")
    blob = "\n\n".join(f"({x['source']}) {x['text'][:1100]}" for x in pool[:9])[:7500]
    try:
        li = pb._json(chat_fn, LIST_SYS.format(cat=cat, n=n + 2), f"[자료]\n{blob}", num_predict=600)
    except Exception:
        li = {}
    allsrc = pb._norm(" ".join(x["text"] for x in pool))
    items, keys = [], set()
    for it in li.get("items", []) or []:
        name = (it.get("name") or "").strip()
        k = pb._norm(name)
        if len(k) >= 2 and k not in keys and k in allsrc:
            keys.add(k)
            items.append({"name": name, "name_en": (it.get("name_en") or "").strip(), "maker": (it.get("maker") or "").strip()})
    ks = [pb._norm(i["name"]) for i in items]
    items = [i for i, k in zip(items, ks) if not any(o != k and o in k for o in ks)][:n]
    if not items:
        raise RuntimeError("검색 결과에서 구체적인 항목 이름을 찾지 못했습니다. 대상을 더 구체적으로 적어 주세요.")
    say(0.3, "📦 항목: " + ", ".join(i["name"] for i in items))
    sources = []
    for i, it in enumerate(items):
        say(0.3 + 0.6 * i / len(items), f"🧾 [{i + 1}/{len(items)}] {it['name']} 정보 확인 중…")
        dd = pb._search_docs([f"{it['name']} {' '.join(attrs[:3])}", f"{it['name']} {cat_en}".strip()], n=4)
        ctx, picked = pb._windows(dd + pool, [it["name"]], total=4200)
        it.update(attrs={}, features=[], summary="", kind="")
        if len(ctx) >= 120:
            try:
                r = pb._json(chat_fn, ITEM_SYS.format(name=it["name"], attrs=", ".join(attrs)), f"[자료]\n{ctx}", num_predict=800)
            except Exception:
                r = {}
            srcn = pb._norm(ctx)
            for a in attrs:
                v = (r.get("attrs") or {}).get(a) or next((vv for kk, vv in (r.get("attrs") or {}).items() if re.sub(r"\s", "", kk) == re.sub(r"\s", "", a)), None)
                if not isinstance(v, dict) or not str(v.get("value") or "").strip():
                    continue
                val = str(v["value"]).strip()[:60]
                ok = pb._price_ok(val, ctx) if re.search(r"\d", val) else pb._evidence_ok(v.get("evidence", ""), srcn)
                if ok:
                    it["attrs"][a] = val                                       # 숫자는 원문에 그 숫자가 있어야, 글은 근거 구절이 있어야 채택
            if pb._evidence_ok(r.get("summary", ""), srcn) or (r.get("summary") and len(r.get("features") or []) and any(
                    pb._evidence_ok(f.get("evidence", ""), srcn) for f in r.get("features") if isinstance(f, dict))):
                it["summary"] = str(r.get("summary") or "")[:60]
            it["features"] = [f["text"][:60] for f in (r.get("features") or []) if isinstance(f, dict) and f.get("text") and pb._evidence_ok(f.get("evidence", ""), srcn)][:3]
            it["kind"] = str(r.get("kind") or "")[:16]
            for p in picked[:2]:
                if p["url"] not in {s["url"] for s in sources}:
                    sources.append({"title": p["title"][:70] or p["source"], "url": p["url"]})
        if form.get("photos", True):
            say(0.3 + 0.6 * (i + 0.6) / len(items), f"📷 [{i + 1}/{len(items)}] {it['name']} 사진 찾는 중…")
            try:
                _item_photo(it, cat_en, chat_fn)
            except Exception:
                pass
    items = [it for it in items if it["attrs"] or it["features"] or it.get("image")]
    say(0.95, "🎨 페이지 구성 중…")
    secs = []
    cards = [{"title": it["name"], "sub": " · ".join(f"{a} {v}" for a, v in list(it["attrs"].items())[:2]) or it.get("maker"), "img": it.get("image")} for it in items]
    if form.get("carousel", True) and sum(1 for it in items if it.get("image")) >= 3:
        secs.append({"nav": "갤러리", "heading": "한눈에 보기", "intro": "좌우로 넘기거나 끌어서 돌려 보세요.", "html": wc.carousel3d(cards)})
    tc = []
    for it in items:
        body = (it["summary"] + " " if it["summary"] else "") + " · ".join(it["features"])
        tc.append({"title": it["name"], "sub": it.get("maker") or it.get("kind"), "tag": it.get("kind"), "img": it.get("image"),
                   "body": (body + (" | " if body and it["attrs"] else "") + " · ".join(f"{a}: {v}" for a, v in it["attrs"].items())).strip()})
    secs.append({"nav": "항목", "heading": f"{cat} — 항목별 소개", "intro": "자료에서 확인된 내용만 담았습니다. 카드에 마우스를 올려 보세요.", "html": wc.tilt_cards(tc)})
    rows = [["이름"] + attrs] + [[it["name"]] + [it["attrs"].get(a, "확인 안 됨") for a in attrs] for it in items]
    secs.append({"nav": "비교표", "heading": "비교표", "intro": "머리글을 누르면 정렬됩니다. 값은 자료 표기 그대로이며 '확인 안 됨'은 자료에서 찾지 못한 값입니다.",
                 "html": wc.table(rows)})
    DATE = re.compile(r"\d{4}\s*[.\-/년]|\d{1,2}\s*월|\d{1,2}\s*일")
    for a in attrs:                                                     # 숫자 비교 항목이면 차트(날짜·연도 항목은 제외)
        vals = [str(it["attrs"].get(a) or "") for it in items]
        if any(DATE.search(v) for v in vals) or re.search(r"일자|날짜|개봉|출시|연도|기간|일시", a):
            continue
        pts = [{"label": it["name"][:14], "value": it["attrs"].get(a)} for it in items if wc.num(it["attrs"].get(a)) is not None]
        if len(pts) >= 3:
            unit = re.sub(r"[\d,.\s~\-]+", "", str(items[0]["attrs"].get(a, "")))[:6]
            ch = wc.bars3d(pts, f"{a} 비교", unit) if form.get("bars3d", True) else wc.bar_chart(pts, f"{a} 비교", unit)
            secs.append({"nav": "차트", "heading": f"{a} 비교", "html": ch + (wc.bar_chart(pts, "", unit) if form.get("bars3d", True) else "")})
            break
    page = {"title": cat, "tagline": f"웹에서 확인한 {len(items)}개 항목을 사진·특징·비교표로 정리했습니다", "eyebrow": "COMPARE",
            "hero": form.get("hero", "particles"), "sections": secs, "sources": sources,
            "note": "웹 검색 자료를 근거로 로컬 AI가 정리했습니다. 수치는 자료에 그 숫자가 있을 때만 실었습니다. 사진 저작권은 각 출처에 있으며 내부 참고용입니다."}
    return page, {"removed": sum(1 for it in items for a in attrs if a not in it["attrs"]), "context": blob[:3000], "sources": sources}


# ================================================================== 틀 4·5: 기관·사업 소개 / 보고서 요약 (올린 문서)
ORG_SYS = """[자료]는 '{name}' 에 관한 문서이다. 기관·사업 소개 웹페이지에 넣을 내용을 [자료]만 근거로 JSON 으로 뽑는다. 없으면 빈 값. 추측 금지.
- tagline: 25자 이내 한 줄 소개. overview: 2~3문장 개요.
- keypoints: 핵심 특징 3~4개 {{"title","body"(40자 이내),"evidence"}}
- kpis: 성과·규모 수치 3~6개 {{"label","value"(숫자만),"unit","evidence"}} — 자료의 숫자 그대로
- history: 연혁·추진 경과 {{"year"(예: 2026 또는 '26.5),"title","body","evidence"}} 최대 8개
- projects: 주요 사업·과제 {{"title","sub","body","evidence"}} 최대 6개
- contacts: 연락처·담당 {{"label","value"}} (자료에 있을 때만)
evidence 는 [자료]에서 글자 그대로 복사한 10~40자.
출력 JSON: {{"tagline":"","overview":"","keypoints":[],"kpis":[],"history":[],"projects":[],"contacts":[]}}"""

REPORT_SYS = """[자료]는 보고서이다. 한 페이지 요약 웹페이지용 내용을 [자료]만 근거로 JSON 으로 뽑는다. 추측 금지.
- title: 보고서 제목(자료 표기). tagline: 30자 이내 핵심 메시지. summary: 3문장 요약.
- kpis: 보고서의 핵심 수치 3~6개 {{"label","value"(숫자만),"unit","evidence"}}
- chapters: 장(章)마다 {{"title","points":["핵심 2~4개, 각 60자 이내"]}} (목차 순서대로)
- conclusion: 결론·시사점 2~4개(각 60자 이내)
evidence 는 [자료]에서 글자 그대로 복사한 10~40자.
출력 JSON: {{"title":"","tagline":"","summary":"","kpis":[],"chapters":[],"conclusion":[]}}"""


def _ok_ev(ev, srcn):
    import product_builder as pb
    return pb._evidence_ok(ev or "", srcn)


def _kpis_checked(kpis, src):
    import fact_check
    out = []
    for k in kpis or []:
        if not isinstance(k, dict) or wc.num(k.get("value")) is None:
            continue
        if fact_check.check(f"{k['value']}{k.get('unit') or ''}", src)["missing"]:
            continue                                                           # 원문에 없는 숫자는 버림
        out.append({"label": str(k.get("label") or "")[:24], "value": str(k["value"]), "unit": str(k.get("unit") or "")[:6]})
    return out[:6]


def _md_tables(text, limit=3):
    """원문 속 마크다운 표(문서 읽기 단계에서 표는 | a | b | 형태로 나옴)를 골라 반환."""
    tabs, cur = [], []
    for l in text.split("\n") + [""]:
        if l.strip().startswith("|"):
            if not re.match(r"^\|?\s*:?-{2,}", l.strip().strip("|").strip()):
                cells = [re.sub(r"^(-?\d+)\s+(\d+)\s*\.$", r"\1.\2", c.strip()) for c in l.strip().strip("|").split("|")]   # PDF 표의 '27 6 .' → '27.6'
                cur.append(cells)
        elif cur:
            if len(cur) >= 3 and max(len(r) for r in cur) >= 2:
                tabs.append(cur)
            cur = []
    tabs.sort(key=lambda t: -len(t) * max(len(r) for r in t))
    return tabs[:limit]


def _chart_from_table(tb):
    """첫 열=이름, 숫자가 많은 첫 열=값 → 차트 데이터"""
    if len(tb) < 4:
        return None
    w = max(len(r) for r in tb)
    for k in range(1, w):
        pts = [{"label": r[0][:14], "value": r[k]} for r in tb[1:] if k < len(r) and wc.num(r[k]) is not None and r[0]]
        if len(pts) >= 3:
            return tb[0][k] if k < len(tb[0]) else "", pts
    return None


def _src_text(form):
    return form.get("source_text") or ""


def build_org(form, chat_fn, progress=None):
    import form_fill as ff
    import product_builder as pb
    say = progress or (lambda f, m: None)
    name, src = form["topic"].strip(), _src_text(form)
    if len(src) < 200:
        raise RuntimeError("기관·사업 소개는 원 소스 문서가 필요합니다. 사업계획서·소개 자료를 올리거나 지식보관함을 켜 주세요.")
    say(0.2, "📑 문서에서 소개 내용 뽑는 중…")
    d = pb._json(chat_fn, ORG_SYS.format(name=name), f"[자료]\n{ff.digest(src, 7000)}", num_predict=1800)
    srcn = pb._norm(src)
    keyp = [k for k in d.get("keypoints") or [] if isinstance(k, dict) and _ok_ev(k.get("evidence"), srcn)]
    hist = [h for h in d.get("history") or [] if isinstance(h, dict) and _ok_ev(h.get("evidence"), srcn)]
    proj = [p for p in d.get("projects") or [] if isinstance(p, dict) and _ok_ev(p.get("evidence"), srcn)]
    kp = _kpis_checked(d.get("kpis"), src)
    secs = [{"nav": "개요", "heading": f"{name} 개요", "html": (f'<p class="lead reveal">{_e(d.get("overview"))}</p>' if d.get("overview") else "")
             + wc.tilt_cards([{"title": k.get("title"), "body": k.get("body")} for k in keyp])}]
    if kp:
        units = [k["unit"] for k in kp]
        same = max(set(units), key=units.count) if units else ""
        b3 = [{"label": k["label"], "value": k["value"]} for k in kp if k["unit"] == same]
        secs.append({"nav": "성과", "heading": "핵심 수치", "intro": "문서에 적힌 숫자만 실었습니다.",
                     "html": wc.kpis(kp) + (wc.bars3d(b3, f"단위: {same}", same) if form.get("bars3d", True) and len(b3) >= 3 else "")})
    if hist:
        secs.append({"nav": "연혁", "heading": "추진 경과", "html": wc.timeline([{"year": h.get("year"), "title": h.get("title"), "body": h.get("body")} for h in hist])})
    if proj:
        secs.append({"nav": "사업", "heading": "주요 사업", "html": wc.tilt_cards([{"title": p.get("title"), "sub": p.get("sub"), "body": p.get("body")} for p in proj])})
    if form.get("markers"):
        secs.append({"nav": "거점", "heading": "거점·대상 지역", "html": wc.globe(form["markers"])})
    cts = [c for c in d.get("contacts") or [] if isinstance(c, dict) and c.get("value") and pb._norm(str(c["value"])) in srcn]
    if cts:
        secs.append({"nav": "연락처", "heading": "문의", "html": '<div class="info">' + "".join(
            f'<div><b>{_e(c.get("label"))}</b><span>{_e(c.get("value"))}</span></div>' for c in cts) + "</div>"})
    page = {"title": name, "tagline": d.get("tagline"), "eyebrow": "ABOUT", "hero": form.get("hero", "particles"),
            "hero_markers": form.get("markers"), "sections": secs, "sources": [{"title": n} for n in form.get("source_names", [])],
            "note": "올린 문서를 근거로 로컬 AI가 정리했습니다. 문서에서 근거를 찾지 못한 내용과 숫자는 뺐습니다."}
    return page, {"removed": len(d.get("keypoints") or []) - len(keyp) + len(d.get("history") or []) - len(hist), "context": src[:3000], "sources": []}


def build_report(form, chat_fn, progress=None):
    import form_fill as ff
    import product_builder as pb
    say = progress or (lambda f, m: None)
    src = _src_text(form)
    if len(src) < 200:
        raise RuntimeError("보고서 요약은 원 소스 문서가 필요합니다. 보고서를 올려 주세요.")
    say(0.2, "📑 보고서에서 요약·수치 뽑는 중…")
    d = pb._json(chat_fn, REPORT_SYS, f"[자료]\n{ff.digest(src, 7000)}", num_predict=2000)
    kp = _kpis_checked(d.get("kpis"), src)
    secs = []
    if d.get("summary") or kp:
        secs.append({"nav": "요약", "heading": "한눈에 보기", "html": (f'<p class="lead reveal">{_e(d.get("summary"))}</p>' if d.get("summary") else "") + wc.kpis(kp)})
    chs = [c for c in d.get("chapters") or [] if isinstance(c, dict) and c.get("title")]
    if chs:
        secs.append({"nav": "장별 요약", "heading": "장별 요약", "intro": "제목을 누르면 펼쳐집니다.",
                     "html": wc.accordion([(c["title"], "<ul>" + "".join(f"<li>{_e(p)}</li>" for p in (c.get("points") or [])[:5]) + "</ul>") for c in chs])})
    tbs = _md_tables(src, 3)
    if tbs:
        panels = [(f"표 {i + 1} — {' · '.join(t[0][:3])[:24]}", wc.table(t)) for i, t in enumerate(tbs)]
        secs.append({"nav": "원문 표", "heading": "원문 주요 표", "intro": "보고서에 있는 표를 그대로 옮겼습니다. 머리글을 누르면 정렬됩니다.", "html": wc.tabs(panels)})
        for t in tbs:
            ch = _chart_from_table(t)
            if ch:
                lab, pts = ch
                is_time = all(re.search(r"\d{2,4}", p["label"]) for p in pts)
                secs.append({"nav": "차트", "heading": f"{lab or '수치'} 차트", "html": (wc.line_chart if is_time else wc.bar_chart)(pts, lab)})
                break
    if d.get("conclusion"):
        secs.append({"nav": "결론", "heading": "결론·시사점", "html": wc.tilt_cards([{"title": f"시사점 {i + 1}", "body": c} for i, c in enumerate(d["conclusion"][:4])])})
    names = form.get("source_names", [])
    page = {"title": d.get("title") or (names[0].rsplit(".", 1)[0] if names else "보고서 요약"), "tagline": d.get("tagline"), "eyebrow": "REPORT SUMMARY",
            "hero": form.get("hero", "particles"), "sections": secs, "sources": [{"title": n} for n in names],
            "note": "올린 보고서를 근거로 로컬 AI가 요약했습니다. 핵심 수치는 원문에 있는 숫자만 실었습니다."}
    return page, {"removed": 0, "context": src[:3000], "sources": []}


# ================================================================== 틀 6: 행사·안내 (입력값)
EVENT_SYS = """행사 안내 웹페이지의 소개 문구를 다듬는다. [입력]에 있는 사실만 쓰고 새 사실(날짜·장소·인물·수치)을 더하지 않는다.
출력 JSON: {"tagline":"20자 이내 한 줄","intro":"2~3문장 소개"}"""


def build_event(form, chat_fn=None, progress=None):
    say = progress or (lambda f, m: None)
    name = form["topic"].strip()
    when = form.get("when")                                                 # datetime 또는 None
    intro, tagline = (form.get("intro") or "").strip(), form.get("tagline") or ""
    if chat_fn and form.get("polish") and intro:
        say(0.3, "✍️ 소개 문구 다듬는 중…")
        try:
            d = json.loads(chat_fn([{"role": "system", "content": EVENT_SYS}, {"role": "user", "content": f"[입력] 행사명: {name}\n소개: {intro}"}],
                                   {"temperature": 0.3, "num_ctx": 2048, "num_predict": 300}, fmt="json"))
            tagline, intro = d.get("tagline") or tagline, d.get("intro") or intro
        except Exception:
            pass
    info = [("일시", when.strftime("%Y년 %m월 %d일 %H:%M") if when else form.get("when_text", "")), ("장소", form.get("place")),
            ("대상", form.get("audience")), ("참가비", form.get("fee"))]
    secs = [{"nav": "개요", "heading": "행사 개요", "html": (f'<p class="lead reveal">{_e(intro)}</p>' if intro else "")
             + '<div class="info">' + "".join(f'<div><b>{k}</b><span>{_e(v)}</span></div>' for k, v in info if v) + "</div>"
             + (f'<a class="btn" href="{_e(form["apply"])}" target="_blank" rel="noopener">참가 신청</a>' if form.get("apply") else "")}]
    prog = [[c.strip() for c in re.split(r"\s*\|\s*", l)] for l in (form.get("program") or "").splitlines() if l.strip()]
    if prog:
        w = max(len(r) for r in prog)
        head = ["시간", "내용", "발표·담당", "비고"][:w]
        secs.append({"nav": "프로그램", "heading": "프로그램", "html": wc.table([head] + prog, search=False)})
    if form.get("address"):
        q = urllib.parse.quote(form["address"])
        secs.append({"nav": "오시는 길", "heading": "오시는 길", "html": f'<div class="info"><div><b>주소</b><span>{_e(form["address"])}</span></div></div>'
                     f'<a class="btn" href="https://map.naver.com/p/search/{q}" target="_blank" rel="noopener">네이버 지도</a>'
                     f'<a class="btn ghost" href="https://map.kakao.com/?q={q}" target="_blank" rel="noopener">카카오맵</a>'
                     '<p class="note">지도는 인터넷 연결 시 새 창에서 열립니다.</p>'})
    if form.get("contact"):
        secs.append({"nav": "문의", "heading": "문의", "html": '<div class="info">' + "".join(
            f'<div><b>문의</b><span>{_e(l)}</span></div>' for l in form["contact"].splitlines() if l.strip()) + "</div>"})
    page = {"title": name, "tagline": tagline, "eyebrow": "EVENT", "hero": form.get("hero", "particles"), "sections": secs,
            "hero_extra": wc.countdown(when.isoformat(), "행사까지") if when and when > datetime.datetime.now() else "",
            "note": "입력한 내용으로 만든 안내 페이지입니다."}
    return page, {"removed": 0, "context": "", "sources": []}


BUILDERS = {"topic": lambda f, c, p: build_topic(f, c, p), "history": lambda f, c, p: build_topic(f, c, p, history=True),
            "list": build_list, "org": build_org, "report": build_report, "event": build_event}


def build(kind, form, chat_fn, progress=None, trend=None):
    """반환: {'html','page','meta'} — page 를 보관하면 디자인 트렌드만 바꿔 즉시 다시 그릴 수 있다."""
    page, meta = BUILDERS[kind](form, chat_fn, progress)
    if not page.get("sections"):
        raise RuntimeError("자료에서 페이지에 넣을 내용을 찾지 못했습니다. 입력을 바꾸거나 자료를 추가해 주세요.")
    return {"html": render(page, trend), "page": page, "meta": meta, "kind": kind}
