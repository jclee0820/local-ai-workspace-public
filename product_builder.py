"""제품 조사 웹페이지 엔진 — '현재 판매 중인 ○○의 종류·특징·가격·사진' 같은 요청용.

위키백과에는 현재 판매 제품·가격이 없으므로 실시간 웹 검색을 쓴다.
1) 웹 검색으로 제품 목록 발견(이름이 검색 결과 본문에 실제로 있는 것만)
2) 제품별로 다시 검색해 가격·출시·특징을 추출(가격 숫자가 자료에 있어야 인정, 없으면 '확인 안 됨')
3) 제품 사진을 이미지 검색으로 받아 축소해 페이지에 포함(제품명이 맞는 결과만, 못 찾으면 비워 둠)
4) 제품 카드·비교표 전용 디자인으로 렌더링
확인되지 않은 정보는 만들지 않는 것이 원칙이다."""
import base64
import datetime
import html
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

import design_trends as dt
import web_search as ws

UA = ws.UA
PRODUCT_RE = re.compile(r"(판매\s*(중|되)|시판|출시(된|한)|제품|모델|기종|상품).{0,30}(종류|가격|사양|특징|사진|비교|정리|추천)|"
                        r"(종류|가격|사양|특징|사진|비교|정리|추천).{0,30}(판매\s*(중|되)|시판|제품|모델|기종)|"
                        r"(가격|얼마).{0,20}(사진|이미지|실물)|실물\s*사진")


def is_product_request(request: str) -> bool:
    return bool(PRODUCT_RE.search(request or ""))


# ------------------------------------------------------------------ 공통
def _norm(s):
    return re.sub(r"[\s\"'“”‘’()\[\],.·:;!?\-_/]", "", (s or "").lower())


def _evidence_ok(ev, src_norm):
    ev = _norm(ev)
    if len(ev) < 6:
        return False
    if ev in src_norm:
        return True
    pieces = [ev[i:i + 6] for i in range(0, max(len(ev) - 5, 1), 3)]
    return sum(p in src_norm for p in pieces) / max(len(pieces), 1) >= 0.85


def _e(s):
    return html.escape(str(s or ""))


def _json(chat_fn, system, user, num_predict=900, num_ctx=8192):
    out = chat_fn([{"role": "system", "content": system}, {"role": "user", "content": user}],
                  {"temperature": 0.1, "num_ctx": num_ctx, "num_predict": num_predict}, fmt="json")
    return json.loads(out)


# ------------------------------------------------------------------ 검색
def _search_docs(queries, n=6, news=False):
    """검색어 여러 개 → 본문까지 읽은 문서 목록 [{url,title,source,text}] (중복 URL 제거)."""
    items, seen = [], set()
    for q in queries:
        for attempt in range(2):
            try:
                rows = ws._ddg(q, "news" if news else "general", n)
                break
            except Exception:
                rows = []
        for r in rows:
            if r["url"] and r["url"] not in seen:
                seen.add(r["url"])
                items.append(r)
    with ThreadPoolExecutor(max_workers=6) as ex:
        bodies = list(ex.map(lambda it: ws.fetch_body(it["url"]), items))
    docs = []
    for it, body in zip(items, bodies):
        text = (body or "") if len(body or "") > len(it.get("snippet", "")) else (it.get("snippet", "") or "")
        text = re.sub(r"\s+", " ", f"{it.get('title', '')}. {text}").strip()
        if len(text) > 60:
            docs.append({"url": it["url"], "title": it.get("title", ""), "source": it.get("source") or urlparse(it["url"]).netloc,
                         "text": text[:6000]})
    return docs


def _windows(docs, names, per_doc=900, total=4200):
    """제품 이름이 언급된 주변 글만 골라 번호 붙여 반환 → (자료 텍스트, 번호별 문서)"""
    keys = []
    for n in names:
        n = n.strip().lower()
        if n:
            keys.append(n)
            ws2 = n.split()
            if len(ws2) >= 2:
                keys.append(" ".join(ws2[-2:]))
    picked, out, used = [], [], 0
    for d in docs:
        low = d["text"].lower()
        pos = [low.find(k) for k in keys if low.find(k) >= 0]
        if not pos:
            continue
        p = min(pos)
        seg = d["text"][max(0, p - 250): p + per_doc - 250]
        if used + len(seg) > total:
            break
        picked.append(d)
        out.append(f"[{len(picked)}] ({d['source']}) {seg}")
        used += len(seg)
    return "\n\n".join(out), picked


# ------------------------------------------------------------------ 1단계: 주제·제품 목록
TOPIC_SYS = """사용자의 요청에서 조사할 '제품 분야'를 뽑아 웹 검색어를 만든다. 제작 지시 단어(웹페이지, 만들어줘 등)는 뺀다.
출력 JSON: {"category":"제품 분야 한국어 2~4단어(예: AI 스마트 글래스)","category_en":"English product category (예: AI smart glasses)",
"queries":["한국어 검색어 3개 (제품 종류·가격·출시를 각각 겨냥, 연도 2026 포함 가능)"],
"queries_en":["English search queries 2 (best/lineup/price)"]}"""

LIST_SYS = """아래 [자료]는 '{cat}' 관련 웹 검색 결과이다. 자료에 '실제 제품 이름'으로 등장하는 현재 판매·출시 제품을 찾아라.
- 자료에 글자 그대로 나온 제품명만 쓴다. 기억이나 추측으로 추가 금지.
- 제조사 이름만 있거나 일반 용어(예: '스마트 글래스')는 제품이 아니다. 구체적 모델명(예: 레이밴 메타 Gen 2)만.
- 여러 자료에 반복 등장하는 대표 제품을 우선. 서로 다른 제조사가 고루 포함되면 좋다. 최대 {n}개.
- 같은 제품군의 세대·색상·사이즈 변형(예: 'Gen 2', '헤드라이너')은 따로 세지 말고 대표 이름 1개만. 서로 다른 제품 라인만 나열한다.
- name 은 자료 표기 그대로, maker 는 제조사(자료에 있을 때), name_en 은 그 제품의 영어 공식 이름(이미지 검색용, 모르면 "").
출력 JSON: {{"products":[{{"name":"","name_en":"","maker":""}}]}}"""

PRODUCT_SYS = """아래 [자료]만 근거로 제품 '{name}' 의 정보를 JSON 으로 정리한다. 자료에 없으면 빈 문자열/빈 목록으로 둔다. 추측·기억 금지.
- price: 판매 가격(자료에 적힌 표기 그대로, 통화·지역 포함. 예: "$299 (미국)", "449,000원"). 여러 개면 가장 대표적인 1~2개. 없으면 "".
- price_src: price 가 나온 자료 번호(숫자). released: 출시 시기(자료에 있을 때).
- features: 이 제품의 특징 3~4개. 각 항목은 {{"text":"한국어 20~40자 요약","evidence":"[자료]에서 글자 그대로 복사한 구절 10~40자"}}.
- kind: 한 줄 분류(예: 카메라형, 디스플레이형, 오디오형) — 자료에서 알 수 있을 때만.
한국어로 쓰되 제품명·기술 용어는 원문 표기 유지.
출력 JSON: {{"price":"","price_src":0,"released":"","kind":"","features":[{{"text":"","evidence":""}}]}}"""


def _topic(request, chat_fn):
    today = datetime.date.today().year
    core = re.sub(r"(현재|지금|요즘|판매\s*중인|판매되는|시판|출시된|종류|특징|판매\s*가격|가격|실물\s*사진|사진|에 대한|에 대해|"
                  r"웹\s*페이지|웹사이트|페이지|만들어\s*줘|만들어\s*달라고\s*했는데|해줘|보여주는|정리|및|,|\.)", " ", request)
    core = re.sub(r"\s+", " ", core).strip()[:30] or request[:20]
    t = {"category": core, "category_en": "", "queries": [f"{core} 제품 종류 가격 {today}", f"{core} 비교 추천 출시",
                                                         f"{core} 가격 얼마"], "queries_en": []}
    try:
        d = _json(chat_fn, TOPIC_SYS, request, num_predict=300, num_ctx=2048)
        if d.get("category"):
            t["category"] = d["category"].strip()[:30]
        t["category_en"] = (d.get("category_en") or "").strip()
        qs = [q for q in (d.get("queries") or []) if isinstance(q, str) and q.strip()][:3]
        if qs:
            t["queries"] = qs
        t["queries_en"] = [q for q in (d.get("queries_en") or []) if isinstance(q, str) and q.strip()][:2]
    except Exception:
        pass
    return t


def _discover(topic, docs, chat_fn, n=6):
    """검색 결과에서 제품 이름 추출 → 이름이 자료 본문에 실제로 있는 것만."""
    blob = "\n\n".join(f"({d['source']}) {d['text'][:1100]}" for d in docs[:9])[:7500]
    try:
        d = _json(chat_fn, LIST_SYS.format(cat=topic["category"], n=n + 2), f"[자료]\n{blob}", num_predict=500)
    except Exception:
        return []
    allsrc = _norm(" ".join(x["text"] for x in docs))
    out, seen = [], set()
    for p in d.get("products", []) or []:
        name = (p.get("name") or "").strip()
        key = _norm(name)
        if len(key) < 4 or key in seen or key not in allsrc:
            continue
        if _norm(topic["category"]) == key or len(name.split()) < 1:
            continue
        seen.add(key)
        out.append({"name": name, "name_en": (p.get("name_en") or "").strip(), "maker": (p.get("maker") or "").strip()})
    keys = [_norm(p["name"]) for p in out]            # '레이밴 메타' 와 '레이밴 메타 Gen 2' 처럼 한쪽이 다른 쪽을 포함하면 같은 제품군 → 짧은 쪽만
    out = [p for p, k in zip(out, keys) if not any(o != k and o in k for o in keys)]
    return out[:n]


# ------------------------------------------------------------------ 2단계: 제품별 정보
def _price_ok(price, ctx):
    nums = re.findall(r"\d[\d,.]*", price or "")
    flat = re.sub(r"(?<=\d),(?=\d{3})", "", ctx)
    return bool(nums) and all(re.sub(r"(?<=\d),(?=\d{3})", "", n).rstrip(".,") in flat for n in nums)


def _enrich(prod, topic, pool, chat_fn):
    name = prod["name"]
    docs = _search_docs([f"{name} 가격 출시 특징", f"{name} price release specs"], n=5)
    ctx, picked = _windows(docs + pool, [name], total=4200)
    prod.update({"price": "", "released": "", "kind": "", "features": [], "sources": [], "price_src": ""})
    if len(ctx) < 120:
        return prod
    try:
        d = _json(chat_fn, PRODUCT_SYS.format(name=name), f"[자료]\n{ctx}", num_predict=700)
    except Exception:
        return prod
    src = _norm(ctx)
    price = (d.get("price") or "").strip()
    if price and _price_ok(price, ctx):
        prod["price"] = price[:60]
        try:
            i = int(d.get("price_src") or 0)
        except (TypeError, ValueError):
            i = 0
        if 1 <= i <= len(picked) and _price_ok(price, picked[i - 1]["text"]):
            prod["price_src"] = picked[i - 1]["url"]
    rel = (d.get("released") or "").strip()[:30]
    prod["released"] = rel if rel and _price_ok(rel, ctx) else ""          # 출시 시기 숫자(연·월)가 자료에 있어야 인정
    prod["kind"] = (d.get("kind") or "").strip()[:20]
    for f in d.get("features", []) or []:
        if isinstance(f, dict) and f.get("text") and _evidence_ok(f.get("evidence", ""), src):
            prod["features"].append(f["text"].strip()[:60])
    prod["features"] = prod["features"][:4]
    prod["sources"] = [{"title": p["title"][:70] or p["source"], "url": p["url"]} for p in picked[:3]]
    return prod


# ------------------------------------------------------------------ 3단계: 사진
def _to_data_uri(url, referer=""):
    from PIL import Image
    r = requests.get(url, headers={**UA, "Referer": referer} if referer else UA, timeout=7, stream=True)
    if r.status_code != 200 or "image" not in r.headers.get("content-type", ""):
        return ""
    raw = r.raw.read(4_000_000, decode_content=True)
    im = Image.open(io.BytesIO(raw))
    if min(im.size) < 200:
        return ""
    im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
    if im.mode == "RGBA":                                   # 투명 배경은 흰색으로
        bg = Image.new("RGB", im.size, "#ffffff")
        bg.paste(im, mask=im.split()[3])
        im = bg
    im.thumbnail((720, 720))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


VISION_Q = ("제품 '{name}'({maker}) 의 사진을 찾고 있다. 이 이미지가 그 제품 자체를 깨끗하게 보여 주는 제품 사진인가?\n"
            "no 로 답할 경우: 글자가 많은 광고·인포그래픽·스크린샷, 사람 얼굴 위주, 다른 종류 제품, 제품이 작게만 보이는 경우, 로고만 있는 경우.\n"
            "형식: 한 줄 설명 | yes 또는 no")


def _vision_ok(chat_fn, b64, prod):
    try:
        out = chat_fn([{"role": "user", "content": VISION_Q.format(name=prod.get("name_en") or prod["name"], maker=prod.get("maker", "")),
                        "images": [b64]}], {"temperature": 0, "num_predict": 60, "num_ctx": 4096})
        return out.strip().lower().rstrip(".").endswith("yes")
    except Exception:
        return False


def _photo(prod, topic, chat_fn=None):
    """이미지 검색 결과 중 (1) 제목·주소에 제품명이 들어 있고 (2) 모델이 직접 보고 제품 사진이라고 확인한 것만 채택.
    엉뚱한 사진을 넣느니 빈칸이 낫다. 비전 모델이 아니면 제품명 일치만 엄격하게 본다."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    import llm_client
    vision = bool(chat_fn) and llm_client.supports_vision()
    q = prod.get("name_en") or f"{prod['name']} {topic.get('category_en', '')}"
    toks = [t for t in re.split(r"[\s()/,-]+", q.lower()) if len(t) >= 2 and t not in ("gen", "the", "smart", "glasses", "ai")]
    need = max(1, -(-len(toks) * (1 if vision else 2) // 3))
    try:
        with DDGS() as d:
            rows = d.images(q, max_results=15) or []
    except Exception:
        return
    tried = 0
    for r in rows:
        url, title = r.get("image") or "", (r.get("title") or "").lower()
        if not url or re.search(r"logo|icon|\.svg|\.gif|banner|sprite", url.lower()):
            continue
        if toks and sum(t in title or t in url.lower() for t in toks) < need:
            continue
        try:
            uri = _to_data_uri(url, r.get("url") or "")
        except Exception:
            uri = ""
        if not uri:
            continue
        tried += 1
        if vision and not _vision_ok(chat_fn, uri.split(",", 1)[1], prod):
            if tried >= 4:
                return
            continue
        prod["image"] = uri
        prod["image_credit"] = {"name": urlparse(r.get("url") or url).netloc, "url": r.get("url") or ""}
        return


# ------------------------------------------------------------------ 렌더링
CSS = """
:root{--ink:#0F172A;--mu:#64748B;--line:#E2E8F0;--bg:#F5F7FA;--card:#fff;--ac:#2563EB;--ac2:#06B6D4;--hero1:#0B1220;--hero2:#16213E}
*{box-sizing:border-box;margin:0;padding:0} html{scroll-behavior:smooth}
body{font-family:'Noto Sans KR','Pretendard',sans-serif;background:var(--bg);color:var(--ink);line-height:1.65;font-size:16px;-webkit-font-smoothing:antialiased}
a{color:var(--ac)}
.top{position:sticky;top:0;z-index:30;background:var(--topbg,rgba(255,255,255,.86));backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.top div{max-width:1200px;margin:0 auto;padding:13px 24px;display:flex;justify-content:space-between;align-items:center;gap:16px}
.top b{font-weight:800;letter-spacing:-.01em} .top nav{display:flex;gap:22px} .top nav a{color:var(--mu);text-decoration:none;font-size:.93rem;font-weight:500} .top nav a:hover{color:var(--ac)}
.hero{background:radial-gradient(900px 420px at 80% -10%,rgba(6,182,212,.35),transparent 60%),radial-gradient(700px 400px at 10% 110%,rgba(37,99,235,.45),transparent 60%),linear-gradient(135deg,var(--hero1),var(--hero2));
color:#fff;padding:clamp(64px,10vw,120px) 24px clamp(56px,8vw,96px);text-align:center}
.hero .in{max-width:860px;margin:0 auto} .tag{display:inline-block;font-size:.8rem;letter-spacing:.14em;padding:6px 14px;border:1px solid rgba(255,255,255,.28);border-radius:999px;color:#BAE6FD;margin-bottom:22px}
.hero h1{font-size:clamp(2.1rem,6vw,3.8rem);line-height:1.15;letter-spacing:-.02em;font-weight:900}
.hero p{margin-top:18px;color:#CBD5E1;font-size:clamp(1rem,2vw,1.2rem)}
.stats{display:flex;justify-content:center;gap:clamp(18px,5vw,56px);margin-top:38px;flex-wrap:wrap}
.stats div{text-align:center} .stats strong{display:block;font-size:2rem;font-weight:800;color:#fff} .stats span{font-size:.85rem;color:#94A3B8}
main{max-width:1200px;margin:0 auto;padding:0 24px}
.sec{padding:clamp(48px,7vw,84px) 0} .sec h2{font-size:clamp(1.5rem,3vw,2.1rem);font-weight:800;letter-spacing:-.02em}
.sec .lead{color:var(--mu);margin:8px 0 30px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:26px}
.pc{background:var(--card);border:1px solid var(--line);border-radius:20px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 1px 2px rgba(15,23,42,.04);transition:transform .25s,box-shadow .25s}
.pc:hover{transform:translateY(-5px);box-shadow:0 18px 40px rgba(15,23,42,.12)}
.ph{aspect-ratio:4/3;background:#fff;display:grid;place-items:center;border-bottom:1px solid var(--line);position:relative}
.ph img{width:100%;height:100%;object-fit:contain;padding:14px} .ph.none{background:linear-gradient(135deg,#EEF2FF,#ECFEFF);color:#94A3B8;font-size:.9rem}
.ph.none svg{width:64px;height:64px;opacity:.55}
.cr{position:absolute;right:8px;bottom:6px;font-size:.68rem;color:#94A3B8;background:rgba(255,255,255,.85);padding:1px 6px;border-radius:6px}
.pb{padding:22px 24px 24px;display:flex;flex-direction:column;gap:10px;flex:1}
.mk{font-size:.8rem;font-weight:700;color:var(--ac);letter-spacing:.04em;text-transform:uppercase}
.pb h3{font-size:1.3rem;line-height:1.3;letter-spacing:-.01em}
.kind{display:inline-block;align-self:flex-start;font-size:.78rem;padding:3px 10px;border-radius:999px;background:var(--kindbg,#EFF6FF);color:var(--ac);font-weight:600}
.price{font-size:1.55rem;font-weight:800;letter-spacing:-.02em;color:var(--ink)} .price small{display:block;font-size:.78rem;font-weight:500;color:var(--mu);letter-spacing:0}
.price.na{font-size:1rem;font-weight:600;color:#94A3B8}
.pb ul{list-style:none;display:grid;gap:7px;margin-top:2px} .pb li{padding-left:22px;position:relative;font-size:.94rem;color:var(--li,#334155)}
.pb li:before{content:"";position:absolute;left:0;top:.5em;width:12px;height:12px;border-radius:50%;background:linear-gradient(135deg,var(--ac),var(--ac2))}
.meta{margin-top:auto;padding-top:12px;border-top:1px dashed var(--line);font-size:.8rem;color:var(--mu);display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:18px}
table{width:100%;border-collapse:collapse;min-width:640px} th{background:var(--thbg,#F8FAFC);text-align:left;font-size:.82rem;color:var(--mu);letter-spacing:.04em;padding:14px 18px;border-bottom:1px solid var(--line)}
td{padding:16px 18px;border-bottom:1px solid var(--line);font-size:.95rem;vertical-align:top} tr:last-child td{border-bottom:0} td b{font-weight:700}
td.pr{font-weight:800;white-space:nowrap} td.na{color:#94A3B8}
.note{background:#FFFBEB;border:1px solid #FDE68A;color:#92400E;border-radius:14px;padding:16px 20px;font-size:.9rem;margin-top:22px}
footer{background:var(--hero1);color:#94A3B8;padding:44px 24px;font-size:.86rem} footer .in{max-width:1200px;margin:0 auto}
footer h4{color:#E2E8F0;margin-bottom:10px} footer ul{list-style:none;columns:2;column-gap:32px;margin-bottom:16px} footer li{break-inside:avoid;margin-bottom:5px} footer a{color:#7DD3FC}
.rv{opacity:0;transform:translateY(20px);transition:opacity .7s ease,transform .7s ease} .rv.on{opacity:1;transform:none}
@media(max-width:720px){.top nav{display:none} .grid{grid-template-columns:1fr} footer ul{columns:1}}
@media(prefers-reduced-motion:reduce){.rv{opacity:1;transform:none;transition:none}*{animation:none!important}}
"""
PLACEHOLDER = ('<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
               '<rect x="4" y="22" width="22" height="18" rx="8"/><rect x="38" y="22" width="22" height="18" rx="8"/><path d="M26 29h12M4 29l-1-6M60 29l1-6"/></svg>')


def _card(p):
    if p.get("image"):
        cr = p.get("image_credit") or {}
        ph = (f'<div class="ph"><img src="{p["image"]}" alt="{_e(p["name"])}" loading="lazy">'
              + (f'<span class="cr">사진: {_e(cr.get("name"))}</span>' if cr.get("name") else "") + "</div>")
    else:
        ph = f'<div class="ph none">{PLACEHOLDER}</div>'
    if p.get("price"):
        link = f' <a href="{_e(p["price_src"])}" target="_blank" rel="noopener">출처</a>' if p.get("price_src") else ""
        price = f'<div class="price">{_e(p["price"])}<small>자료에 표시된 가격{link}</small></div>'
    else:
        price = '<div class="price na">가격 정보를 확인하지 못했습니다</div>'
    feats = "<ul>" + "".join(f"<li>{_e(f)}</li>" for f in p["features"]) + "</ul>" if p["features"] else ""
    src = p.get("sources") or []
    meta = (f'<span>{_e(p["released"])} 출시</span>' if p.get("released") else "<span></span>") + \
           (f'<a href="{_e(src[0]["url"])}" target="_blank" rel="noopener">자세히 보기 ↗</a>' if src else "")
    return (f'<article class="pc rv">{ph}<div class="pb">' + (f'<span class="mk">{_e(p["maker"])}</span>' if p.get("maker") else "")
            + f'<h3>{_e(p["name"])}</h3>' + (f'<span class="kind">{_e(p["kind"])}</span>' if p.get("kind") else "")
            + f"{price}{feats}<div class=\"meta\">{meta}</div></div></article>")


def render(topic, products, sources, trend=None):
    n, priced, photo = len(products), sum(1 for p in products if p.get("price")), sum(1 for p in products if p.get("image"))
    today = datetime.date.today().isoformat()
    rows = "".join(
        f'<tr><td><b>{_e(p["name"])}</b><br><span style="color:var(--mu);font-size:.82rem">{_e(p.get("maker"))}</span></td>'
        f'<td>{_e(p.get("kind")) or "-"}</td>'
        + (f'<td class="pr">{_e(p["price"])}</td>' if p.get("price") else '<td class="na">확인 안 됨</td>')
        + f'<td>{_e(p.get("released")) or "-"}</td><td>{_e(p["features"][0]) if p["features"] else "-"}</td></tr>' for p in products)
    src = "".join(f'<li><a href="{_e(s["url"])}" target="_blank" rel="noopener">{_e(s["title"])}</a></li>' for s in sources)
    cat = _e(topic["category"])
    _f, _u = dt.font_param(trend)
    fam = f"&family={_u}" if _u else ""
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{cat} 제품 가이드</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800;900{fam}&display=swap" rel="stylesheet"><style>{CSS}{dt.product_css(trend)}</style></head><body>
<div class="top"><div><b>{cat}</b><nav><a href="#products">제품</a><a href="#compare">비교표</a><a href="#sources">출처</a></nav></div></div>
<section class="hero"><div class="in"><span class="tag">PRODUCT GUIDE · {today}</span>
<h1>{cat},<br>지금 살 수 있는 제품</h1><p>웹에서 확인한 제품의 특징과 가격, 실물 사진을 한 번에 비교해 보세요.</p>
<div class="stats"><div><strong>{n}</strong><span>조사한 제품</span></div><div><strong>{priced}</strong><span>가격 확인</span></div><div><strong>{photo}</strong><span>실물 사진</span></div></div></div></section>
<main>
<section class="sec" id="products"><h2>제품 한눈에 보기</h2><p class="lead">검색 결과에 실제로 나온 제품만 담았습니다.</p><div class="grid">{"".join(_card(p) for p in products)}</div></section>
<section class="sec" id="compare"><h2>제품 비교표</h2><p class="lead">가격은 자료에 표시된 값 그대로이며, 지역·환율·시기에 따라 달라질 수 있습니다.</p>
<div class="tw rv"><table><thead><tr><th>제품</th><th>유형</th><th>가격</th><th>출시</th><th>대표 특징</th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="note">⚠ 가격·사양은 검색 시점({today})의 웹 자료 기준입니다. 구매 전 공식 판매처에서 다시 확인하세요. 사진의 저작권은 각 출처에 있으며 내부 참고용으로만 사용하세요.</div></section>
</main>
<footer id="sources"><div class="in"><h4>자료 출처</h4><ul>{src}</ul><p>본문은 위 웹 자료를 근거로 로컬 AI가 정리했습니다. 자료에서 확인되지 않은 가격·특징은 싣지 않았습니다. 생성일 {today}</p></div></footer>
<script>const io=new IntersectionObserver(es=>es.forEach(e=>{{if(e.isIntersecting){{e.target.classList.add('on');io.unobserve(e.target)}}}}),{{threshold:.1}});
document.querySelectorAll('.rv').forEach(el=>io.observe(el));</script></body></html>"""


# ------------------------------------------------------------------ 전체 파이프라인
def build(request, chat_fn, progress=None, max_products=6, trend=None):
    say = progress or (lambda f, m: None)
    say(0.03, "🔑 조사할 제품 분야 파악 중...")
    topic = _topic(request, chat_fn)
    say(0.08, f"🔎 웹 검색: {topic['category']}")
    docs = _search_docs(topic["queries"] + topic["queries_en"], n=6) + _search_docs(topic["queries"][:1], n=5, news=True)
    seen, uniq = set(), []
    for d in docs:
        if d["url"] not in seen:
            seen.add(d["url"])
            uniq.append(d)
    if not uniq:
        raise RuntimeError("웹 검색 결과를 가져오지 못했습니다. 인터넷 연결을 확인하고 잠시 뒤 다시 시도해 주세요.")
    say(0.25, f"📰 검색 결과 {len(uniq)}건 읽음 — 제품 목록 추리는 중...")
    products = _discover(topic, uniq, chat_fn, n=max_products + 2)[:max_products]
    if not products:
        raise RuntimeError("검색 결과에서 구체적인 제품명을 찾지 못했습니다. 제품 분야를 더 구체적으로 적어 주세요.")
    say(0.35, "📦 제품 후보: " + ", ".join(p["name"] for p in products))
    for i, p in enumerate(products):
        say(0.35 + 0.5 * i / len(products), f"🧾 [{i + 1}/{len(products)}] {p['name']} 가격·특징 확인 중...")
        _enrich(p, topic, uniq, chat_fn)
        say(0.35 + 0.5 * (i + 0.6) / len(products), f"📷 [{i + 1}/{len(products)}] {p['name']} 사진 찾는 중...")
        try:
            _photo(p, topic, chat_fn)
        except Exception:
            pass
    products = [p for p in products if p["price"] or p["features"] or p.get("image")]   # 아무 정보도 못 얻은 제품은 제외
    if not products:
        raise RuntimeError("제품별 정보를 확인하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
    products.sort(key=lambda p: (not p.get("price"), not p.get("image")))                # 가격·사진 있는 제품을 앞으로
    sources, seenu = [], set()
    for p in products:
        for s in p["sources"]:
            if s["url"] not in seenu:
                seenu.add(s["url"])
                sources.append(s)
    say(1.0, "✅ 완료")
    ctx = "\n\n".join(f"{p['name']} | 가격: {p['price'] or '확인 안 됨'} | " + " / ".join(p["features"]) for p in products)
    return {"html": render(topic, products, sources, trend), "content": {"title": topic["category"], "products": products},
            "theme": {}, "topic": topic, "sources": sources, "removed": sum(1 for p in products if not p.get("price")), "context": ctx}
