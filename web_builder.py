"""웹페이지 제작 엔진.
1) 사실 자료 수집(위키백과·웹) → 2) Qwen 이 자료 안의 사실만으로 내용(JSON) 작성 + 근거 문장 검증
3) Qwen 이 디자인 테마(색·글꼴·배경 스타일)만 선택 → 4) 검증된 고품질 레이아웃으로 HTML 렌더링"""
import datetime
import html
import json
import random
import re

CONTENT_SYS = """당신은 웹 콘텐츠 에디터이다. 사용자 요청에 맞는 웹페이지 내용을 JSON 으로 작성한다.
[절대 규칙]
- [자료]에 있는 사실만 사용한다. 자료에 없는 인물·연도·수치·고유명사·사건은 절대 만들지 않는다. 확인 안 되는 항목은 아예 빼라.
- 모든 item 에는 근거(evidence)를 넣는다: [자료]에서 그대로 복사한 원문 구절(10~40자, 자료의 언어 그대로).
- 한국어로 작성. 영어 자료의 고유명사는 한국어 자료에 나온 표기를 우선 사용.
- 사용자 요청의 구성 요소마다 섹션을 하나씩 만든다(예: 세계관 / 시리즈별 전개 / 등장인물).
- 섹션 layout: 개념·배경 설명=prose, 작품·연도 순서=timeline, 인물·항목 나열=cards, 핵심 수치=facts.
- items 는 섹션당 최대 6개, body 는 90자 이내. prose 섹션은 intro 에 2~3문장, items 는 핵심 키워드 3~5개.
- timeline 의 tag 는 연도, cards 의 subtitle 은 역할/배우 등 보조 정보(자료에 있을 때만).
출력 형식(JSON 객체만):
{"title":"페이지 제목","tagline":"한 줄 소개","subtitle":"보조 설명 1문장",
 "sections":[{"nav":"메뉴명(2~5자)","heading":"섹션 제목","layout":"prose|timeline|cards|facts","intro":"섹션 소개",
   "items":[{"title":"","subtitle":"","tag":"","body":"","evidence":"자료 원문 구절"}]}]}"""

THEME_SYS = """당신은 웹 디자이너이다. 주제의 시각적 아이덴티티에 맞는 디자인 테마를 JSON 으로 고른다.
- 색은 #RRGGBB. bg/bg2 는 배경(어두운 테마 권장), surface 는 카드 배경, accent/accent2 는 강조색.
- heading_font 는 다음 중 하나: "Cinzel","Playfair Display","Cormorant Garamond","Orbitron","Bebas Neue","Black Han Sans","Noto Serif KR","Gowun Batang","Do Hyeon","IBM Plex Sans KR"
- body_font 는 다음 중 하나: "Noto Sans KR","IBM Plex Sans KR","Gothic A1","Noto Serif KR","Gowun Batang"
- hero 는 다음 중 하나: "dunes"(사막·모래), "stars"(우주·밤하늘), "grid"(기술·미래), "waves"(바다·물), "mist"(판타지·신비), "minimal"
- mood 는 분위기를 나타내는 한국어 단어 3개.
- 먼저 symbol 에 주제를 대표하는 장소·사물·색을 적고, 그에 맞춰 고를 것. 예시:
  사막 행성 SF(예: 듄) → {"symbol":"사막, 모래 언덕, 스파이스","bg":"#120D08","bg2":"#1E150D","surface":"#2A1D12","text":"#F3E9DA","muted":"#BFA98C","accent":"#D9822B","accent2":"#F2C46D","heading_font":"Cinzel","body_font":"Noto Sans KR","hero":"dunes"}
  우주 SF(예: 스타워즈) → {"symbol":"우주, 별, 광선검","bg":"#05070F","accent":"#3FA9F5","accent2":"#FFE81F","heading_font":"Orbitron","hero":"stars"}
  마법 판타지(예: 해리 포터) → {"symbol":"성, 마법, 촛불","bg":"#140B0B","accent":"#9E2A2B","accent2":"#E0B04F","heading_font":"Cormorant Garamond","hero":"mist"}
  바다(예: 모아나) → hero "waves", 청록 계열 / 기술·AI → hero "grid", 시안 계열 / 한국 전통 → "Gowun Batang", 먹·단청 계열
출력: {"symbol":"","bg":"","bg2":"","surface":"","text":"","muted":"","accent":"","accent2":"","heading_font":"","body_font":"","hero":"","mood":["","",""]}"""

FONTS = {"Cinzel": "Cinzel:wght@500;700", "Playfair Display": "Playfair+Display:wght@600;800",
         "Cormorant Garamond": "Cormorant+Garamond:wght@500;700", "Orbitron": "Orbitron:wght@500;800",
         "Bebas Neue": "Bebas+Neue", "Black Han Sans": "Black+Han+Sans", "Noto Serif KR": "Noto+Serif+KR:wght@400;700;900",
         "Gowun Batang": "Gowun+Batang:wght@400;700", "Do Hyeon": "Do+Hyeon", "IBM Plex Sans KR": "IBM+Plex+Sans+KR:wght@400;600",
         "Noto Sans KR": "Noto+Sans+KR:wght@400;500;700", "Gothic A1": "Gothic+A1:wght@400;600"}
DEFAULT_THEME = {"bg": "#0F1115", "bg2": "#1B1F27", "surface": "#1F242E", "text": "#F2EEE6", "muted": "#A9A39A",
                 "accent": "#D9822B", "accent2": "#F2C46D", "heading_font": "Noto Serif KR", "body_font": "Noto Sans KR",
                 "hero": "minimal", "mood": []}


# ------------------------------------------------------------------ 검증
def _norm(s):
    return re.sub(r"[\s\"'“”‘’«»「」『』()\[\],.·:;!?-]", "", (s or "").lower())


def verify(content, raw_sources):
    """근거 구절이 실제 자료에 있는 항목만 남긴다. 반환: (content, 제거된 항목 수)"""
    src = _norm(raw_sources)
    removed = 0
    for sec in content.get("sections", []):
        kept = []
        for it in sec.get("items", []) or []:
            ev = _norm(it.get("evidence", ""))
            ok = False
            if len(ev) >= 6:
                if ev in src:
                    ok = True
                else:                             # 거의 그대로 복사한 경우만 인정: 6자 조각 85% 이상 일치
                    pieces = [ev[i:i + 6] for i in range(0, max(len(ev) - 5, 1), 3)]
                    ok = sum(p in src for p in pieces) / max(len(pieces), 1) >= 0.85
            title_core = _norm(re.split(r"[(/]", it.get("title", ""))[0])
            sub_core = _norm(re.split(r"[(/,]", it.get("subtitle", "") or "")[0])
            if ok and title_core and len(title_core) >= 2 and sec.get("layout") in ("cards", "prose"):
                pos = src.find(ev[:12]) if len(ev) >= 12 else -1
                if pos >= 0:                      # 근거 구절 주변(±250자)에 항목 이름(또는 배우명)이 있어야 함
                    win = src[max(0, pos - 250): pos + len(ev) + 250]
                    ok = title_core in win or (len(sub_core) >= 2 and sub_core in win)
                else:
                    ok = title_core in src
            if ok:
                kept.append(it)
            else:
                removed += 1
        sec["items"] = kept
    content["sections"] = [s for s in content.get("sections", []) if s.get("items") or s.get("intro")]
    return content, removed


def _hex(c, default):
    return c if isinstance(c, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", c) else default


def _lum(c):
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def fix_theme(t):
    t = {k: (_hex(t.get(k), v) if k not in ("heading_font", "body_font", "hero", "mood") else t.get(k, v))
         for k, v in DEFAULT_THEME.items()} if isinstance(t, dict) else dict(DEFAULT_THEME)
    if t["heading_font"] not in FONTS:
        t["heading_font"] = DEFAULT_THEME["heading_font"]
    if t["body_font"] not in FONTS:
        t["body_font"] = DEFAULT_THEME["body_font"]
    if t["hero"] not in ("dunes", "stars", "grid", "waves", "mist", "minimal"):
        t["hero"] = "minimal"
    if abs(_lum(t["text"]) - _lum(t["bg"])) < 0.45:           # 글자/배경 대비 보장
        t["text"] = "#F4F1EA" if _lum(t["bg"]) < 0.5 else "#14161A"
        t["muted"] = "#A8A39B" if _lum(t["bg"]) < 0.5 else "#5A5650"
    if abs(_lum(t["surface"]) - _lum(t["bg"])) < 0.02:
        t["surface"] = t["bg2"]
    return t


# ------------------------------------------------------------------ 렌더링
def _e(s):
    return html.escape(str(s or ""))


def _hero_bg(t):
    a, a2, bg = t["accent"], t["accent2"], t["bg"]
    if t["hero"] == "dunes":
        return f"""<svg class="hero-art" viewBox="0 0 1440 600" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{bg}"/><stop offset="1" stop-color="{a}" stop-opacity=".55"/></linearGradient>
<linearGradient id="d1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{a2}"/><stop offset="1" stop-color="{a}"/></linearGradient></defs>
<rect width="1440" height="600" fill="url(#sky)"/><circle cx="1080" cy="210" r="110" fill="{a2}" opacity=".85"/>
<path d="M0 420 C240 330 420 360 640 410 S1080 330 1440 380 V600 H0Z" fill="url(#d1)" opacity=".55"/>
<path d="M0 480 C300 420 520 470 760 500 S1180 430 1440 470 V600 H0Z" fill="{a}" opacity=".75"/>
<path d="M0 540 C320 500 640 560 900 545 S1260 510 1440 530 V600 H0Z" fill="{bg}" opacity=".9"/></svg>"""
    if t["hero"] == "stars":
        rnd = random.Random(7)
        dots = ",".join(f"{rnd.randint(0, 1600)}px {rnd.randint(0, 900)}px {a2 if i % 9 == 0 else '#ffffff'}" for i in range(160))
        return f'<div class="hero-art stars" style="box-shadow:{dots}"></div><div class="hero-art glow"></div>'
    if t["hero"] == "grid":
        return '<div class="hero-art grid"></div><div class="hero-art glow"></div>'
    if t["hero"] == "waves":
        return f"""<svg class="hero-art" viewBox="0 0 1440 600" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
<rect width="1440" height="600" fill="{bg}"/><path d="M0 430 Q180 380 360 430 T720 430 T1080 430 T1440 430 V600 H0Z" fill="{a}" opacity=".35"/>
<path d="M0 480 Q180 440 360 480 T720 480 T1080 480 T1440 480 V600 H0Z" fill="{a2}" opacity=".35"/>
<path d="M0 530 Q180 500 360 530 T720 530 T1080 530 T1440 530 V600 H0Z" fill="{a}" opacity=".6"/></svg>"""
    if t["hero"] == "mist":
        return '<div class="hero-art mist m1"></div><div class="hero-art mist m2"></div><div class="hero-art glow"></div>'
    return '<div class="hero-art glow"></div>'


def _initials(name):
    n = re.sub(r"\(.*?\)", "", name).strip()
    parts = n.split()
    if re.match(r"[가-힣]", n):
        return n[:1]                              # 한글 이름은 첫 글자 하나 (예: 폴, 챠, 가)
    return "".join(p[0] for p in parts[:2]).upper() or "•"


def _ic(text, cls="ic", size=24, avoid=None):
    """본문 내용에 맞는 로컬 선형 아이콘(Lucide, ISC)을 인라인 SVG로. 못 찾으면 빈 문자열."""
    try:
        import icon_library as il
        name = il.guess(text, avoid=avoid or ())
        if not name:
            return ""
        if avoid is not None:
            avoid.append(name)
        return f'<span class="{cls}" aria-hidden="true">{il.svg(name, "currentColor", size=size, stroke=1.75)}</span>'
    except Exception:
        return ""


def _section(i, s):
    lay = s.get("layout", "prose")
    sid = f"s{i}"
    used = []
    head = (f'<header class="sec-head reveal"><span class="sec-no">'
            f'{_ic((s.get("heading") or "") + " " + (s.get("intro") or ""), "ic sec-ic", 22, used)}{i:02d}</span>'
            f'<h2>{_e(s.get("heading") or s.get("nav"))}</h2>'
            + (f'<p class="sec-intro">{_e(s.get("intro"))}</p>' if s.get("intro") and lay != "prose" else "") + "</header>")
    items = s.get("items", [])
    if lay == "timeline":
        body = '<ol class="timeline">' + "".join(
            f'<li class="tl-item reveal"><div class="tl-dot"></div><div class="tl-card">'
            f'<span class="tl-tag">{_e(it.get("tag"))}</span><h3>{_e(it.get("title"))}</h3>'
            + (f'<p class="sub">{_e(it.get("subtitle"))}</p>' if it.get("subtitle") else "")
            + f'<p>{_e(it.get("body"))}</p></div></li>' for it in items) + "</ol>"
    elif lay == "cards":
        body = '<div class="cards">' + "".join(
            f'<article class="card reveal"><div class="avatar">'
            f'{_ic(it.get("title", "") + " " + (it.get("subtitle") or ""), "ic", 28, used) or _e(_initials(it.get("title", "")))}</div>'
            f'<h3>{_e(it.get("title"))}</h3>'
            + (f'<p class="sub">{_e(it.get("subtitle"))}</p>' if it.get("subtitle") else "")
            + f'<p>{_e(it.get("body"))}</p>'
            + (f'<span class="chip">{_e(it.get("tag"))}</span>' if it.get("tag") else "") + "</article>" for it in items) + "</div>"
    elif lay == "facts":
        body = '<div class="facts">' + "".join(
            f'<div class="fact reveal">{_ic((it.get("title") or "") + " " + (it.get("body") or ""), "ic fact-ic", 26, used)}'
            f'<strong>{_e(it.get("tag") or it.get("title"))}</strong>'
            f'<span>{_e(it.get("title") if it.get("tag") else it.get("body"))}</span>'
            + (f'<p>{_e(it.get("body"))}</p>' if it.get("tag") else "") + "</div>" for it in items) + "</div>"
    else:
        body = (f'<div class="prose reveal"><p class="lead">{_e(s.get("intro"))}</p>'
                + ('<ul class="keys">' + "".join(
                    f'<li><b>{_ic((it.get("title") or "") + " " + (it.get("body") or ""), "ic", 18, used)}'
                    f'{_e(it.get("title"))}</b><span>{_e(it.get("body"))}</span></li>' for it in items) + "</ul>"
                   if items else "") + "</div>")
    return f'<section id="{sid}" class="sec sec-{lay}">{head}{body}</section>'


def render(content, theme, sources, trend=None):
    import design_trends as dt
    t = fix_theme(dt.web_theme(theme, trend))
    fams = "&".join(f"family={FONTS[f]}" for f in {t["heading_font"], t["body_font"], "Noto Serif KR", "Noto Sans KR"})
    secs = content.get("sections", [])
    nav = "".join(f'<a href="#s{i}">{_e(s.get("nav") or s.get("heading"))}</a>' for i, s in enumerate(secs, 1))
    src = "".join(f'<li><a href="{_e(s["url"])}" target="_blank" rel="noopener">{_e(s["title"])}</a></li>' for s in sources)
    today = datetime.date.today().isoformat()
    css = f"""
:root{{--bg:{t['bg']};--bg2:{t['bg2']};--sf:{t['surface']};--tx:{t['text']};--mu:{t['muted']};--ac:{t['accent']};--ac2:{t['accent2']};
--hf:'{t['heading_font']}','Noto Serif KR',serif;--bf:'{t['body_font']}','Noto Sans KR',sans-serif}}
*{{box-sizing:border-box;margin:0;padding:0}} html{{scroll-behavior:smooth}}
body{{background:var(--bg);color:var(--tx);font-family:var(--bf);line-height:1.75;font-size:17px;-webkit-font-smoothing:antialiased}}
a{{color:var(--ac2)}}
.nav{{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:14px clamp(16px,5vw,64px);
background:color-mix(in srgb,var(--bg) 72%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid color-mix(in srgb,var(--tx) 10%,transparent)}}
.brand{{font-family:var(--hf);letter-spacing:.12em;font-weight:700;text-transform:uppercase}}
.nav nav{{display:flex;gap:clamp(10px,2.5vw,28px);flex-wrap:wrap}} .nav nav a{{color:var(--mu);text-decoration:none;font-size:.95rem;transition:color .2s}}
.nav nav a:hover{{color:var(--ac2)}}
.hero{{position:relative;min-height:88vh;display:grid;place-items:center;text-align:center;overflow:hidden;padding:120px 20px 160px}}
.hero-art{{position:absolute;inset:0;width:100%;height:100%;z-index:0}}
.stars{{width:2px;height:2px;border-radius:50%;inset:auto;top:0;left:0;opacity:.8;animation:tw 6s ease-in-out infinite alternate}}
@keyframes tw{{from{{opacity:.45}}to{{opacity:.95}}}}
.glow{{background:radial-gradient(60% 50% at 70% 30%,color-mix(in srgb,var(--ac) 45%,transparent),transparent 70%),
radial-gradient(50% 40% at 20% 80%,color-mix(in srgb,var(--ac2) 25%,transparent),transparent 70%)}}
.grid{{background-image:linear-gradient(color-mix(in srgb,var(--ac) 35%,transparent) 1px,transparent 1px),linear-gradient(90deg,color-mix(in srgb,var(--ac) 35%,transparent) 1px,transparent 1px);
background-size:60px 60px;transform:perspective(600px) rotateX(60deg) translateY(30%);transform-origin:bottom;mask-image:linear-gradient(transparent,#000 60%)}}
.mist{{filter:blur(60px);opacity:.5}} .m1{{background:radial-gradient(40% 30% at 30% 40%,var(--ac),transparent)}} .m2{{background:radial-gradient(35% 30% at 75% 60%,var(--ac2),transparent);animation:drift 14s ease-in-out infinite alternate}}
@keyframes drift{{to{{transform:translate(-6%,4%)}}}}
.hero-inner{{position:relative;z-index:2;max-width:980px}}
.eyebrow{{display:inline-block;letter-spacing:.35em;text-transform:uppercase;font-size:.8rem;color:var(--ac2);margin-bottom:22px}}
.hero h1{{font-family:var(--hf);font-size:clamp(2.8rem,9vw,7rem);line-height:1.02;letter-spacing:.04em;text-shadow:0 8px 40px rgba(0,0,0,.45)}}
.tagline{{font-size:clamp(1.1rem,2.4vw,1.5rem);margin-top:22px;color:var(--tx);opacity:.92}}
.subtitle{{max-width:640px;margin:14px auto 0;color:var(--mu)}}
.cta{{display:flex;gap:12px;justify-content:center;margin-top:36px;flex-wrap:wrap}}
.cta a{{padding:12px 22px;border-radius:999px;text-decoration:none;font-weight:600;border:1px solid color-mix(in srgb,var(--ac2) 60%,transparent);color:var(--tx);transition:.25s}}
.cta a:first-child{{background:var(--ac);border-color:var(--ac);color:#111}} .cta a:hover{{transform:translateY(-2px);box-shadow:0 10px 30px color-mix(in srgb,var(--ac) 40%,transparent)}}
main{{max-width:1180px;margin:0 auto;padding:0 clamp(16px,5vw,48px)}}
.sec{{padding:clamp(70px,10vw,120px) 0;border-top:1px solid color-mix(in srgb,var(--tx) 8%,transparent)}}
.sec-head{{margin-bottom:44px;max-width:760px}} .sec-no{{font-family:var(--hf);color:var(--ac);font-size:.95rem;letter-spacing:.2em}}
.sec-head h2{{font-family:var(--hf);font-size:clamp(2rem,4.5vw,3.2rem);line-height:1.15;margin-top:8px}}
.sec-intro{{color:var(--mu);margin-top:14px;font-size:1.05rem}}
.prose{{display:grid;grid-template-columns:1.3fr 1fr;gap:48px;align-items:start}}
.lead{{font-size:clamp(1.15rem,2vw,1.4rem);line-height:1.8}} .lead::first-letter{{font-family:var(--hf);font-size:3.2em;float:left;line-height:.9;margin:6px 10px 0 0;color:var(--ac)}}
.keys{{list-style:none;display:grid;gap:14px}} .keys li{{background:var(--sf);border-left:3px solid var(--ac);padding:16px 18px;border-radius:12px}}
.keys b{{display:block;color:var(--ac2);margin-bottom:4px}} .keys span{{color:var(--mu);font-size:.97rem}}
.timeline{{list-style:none;position:relative;padding-left:34px}} .timeline::before{{content:"";position:absolute;left:9px;top:6px;bottom:6px;width:2px;background:linear-gradient(var(--ac),var(--ac2))}}
.tl-item{{position:relative;margin-bottom:26px}} .tl-dot{{position:absolute;left:-31px;top:22px;width:16px;height:16px;border-radius:50%;background:var(--ac);box-shadow:0 0 0 5px color-mix(in srgb,var(--ac) 25%,transparent)}}
.tl-card{{background:var(--sf);padding:22px 26px;border-radius:16px;border:1px solid color-mix(in srgb,var(--tx) 8%,transparent)}}
.tl-tag{{font-family:var(--hf);color:var(--ac2);font-size:1.4rem;font-weight:700}} .tl-card h3,.card h3{{font-size:1.2rem;margin:4px 0 6px}}
.sub{{color:var(--ac2);font-size:.92rem;margin-bottom:6px}} .tl-card p:not(.sub),.card p:not(.sub){{color:var(--mu);font-size:.97rem}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:22px}}
.card{{background:linear-gradient(160deg,var(--sf),var(--bg2));padding:26px;border-radius:18px;border:1px solid color-mix(in srgb,var(--tx) 8%,transparent);transition:transform .3s,box-shadow .3s}}
.card:hover{{transform:translateY(-6px);box-shadow:0 18px 40px rgba(0,0,0,.35)}}
.avatar{{width:62px;height:62px;border-radius:50%;display:grid;place-items:center;font-family:var(--hf);font-size:1.4rem;font-weight:700;color:#111;
background:linear-gradient(135deg,var(--ac2),var(--ac));margin-bottom:16px}}
.chip{{display:inline-block;margin-top:12px;font-size:.8rem;padding:4px 10px;border-radius:999px;background:color-mix(in srgb,var(--ac) 18%,transparent);color:var(--ac2)}}
.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px}} .fact{{background:var(--sf);border-radius:16px;padding:26px}}
.fact strong{{display:block;font-family:var(--hf);font-size:2.2rem;color:var(--ac2)}} .fact span{{font-weight:600}} .fact p{{color:var(--mu);font-size:.95rem;margin-top:6px}}
footer{{margin-top:40px;padding:48px clamp(16px,5vw,64px);background:var(--bg2);color:var(--mu);font-size:.9rem}}
footer h4{{color:var(--tx);margin-bottom:10px;font-family:var(--hf)}} footer ul{{list-style:none;display:grid;gap:6px;margin-bottom:16px}}
.reveal{{opacity:0;transform:translateY(24px);transition:opacity .8s ease,transform .8s ease}} .reveal.on{{opacity:1;transform:none}}
.ic{{display:inline-flex;vertical-align:-0.18em;line-height:0}} .ic svg{{display:block}}
.sec-ic{{color:var(--ac);margin-right:10px;vertical-align:-0.3em}} .keys b .ic{{margin-right:8px;color:var(--ac)}}
.avatar .ic{{color:#111}} .fact-ic{{color:var(--ac);margin-bottom:10px;display:flex}}
@media (max-width:820px){{.prose{{grid-template-columns:1fr}} .nav nav{{display:none}}}}
@media (prefers-reduced-motion:reduce){{.reveal{{opacity:1;transform:none;transition:none}} *{{animation:none!important}}}}
"""
    secs_html = "".join(_section(i, s) for i, s in enumerate(secs, 1))
    first = "#s1" if secs else "#"
    second = "#s2" if len(secs) > 1 else first
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(content.get('title'))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?{fams}&display=swap" rel="stylesheet"><style>{css}{dt.web_css(trend)}</style></head><body>
<div class="nav"><span class="brand">{_e(content.get('title'))}</span><nav>{nav}</nav></div>
<section class="hero">{_hero_bg(t)}<div class="hero-inner">
<span class="eyebrow">{_e(' · '.join(t.get('mood') or []) if t.get('mood') else '')}</span>
<h1>{_e(content.get('title'))}</h1><p class="tagline">{_e(content.get('tagline'))}</p><p class="subtitle">{_e(content.get('subtitle'))}</p>
<div class="cta"><a href="{first}">{_e(secs[0].get('nav') if secs else '시작')}</a>{f'<a href="{second}">{_e(secs[1].get("nav"))}</a>' if len(secs) > 1 else ''}</div>
</div></section>
<main>{secs_html}</main>
<footer><h4>자료 출처</h4><ul>{src}</ul><p>본문은 위 자료를 근거로 로컬 AI가 정리했습니다 (위키백과 본문: CC BY-SA 4.0). 생성일 {today}</p></footer>
<script>const io=new IntersectionObserver(es=>es.forEach(e=>{{if(e.isIntersecting){{e.target.classList.add('on');io.unobserve(e.target)}}}}),{{threshold:.12}});
document.querySelectorAll('.reveal').forEach(el=>io.observe(el));</script></body></html>"""


# ------------------------------------------------------------------ 전체 파이프라인
QUERY_SYS = """사용자의 웹페이지 제작 요청에서 '조사할 주제'만 뽑아 위키백과 검색어를 만든다.
'웹페이지, 디자인, 만들어줘, 보여주는, 아이덴티티' 같은 제작 지시 단어는 빼라.
출력 JSON: {"core":"주제 핵심어 1개(예: 듄)","ko":"한국어 검색어(2~4단어)","en":"English search query (2-4 words)"}"""


def _rule_core(request):
    m = re.match(r"\s*['\"“《『]?([0-9A-Za-z가-힣]+)", request)
    return m.group(1) if m else request[:6]


def make_queries(request, chat_fn):
    """검색어 생성. 모델이 희귀 글자(예: '듄'→'드류')를 바꿔 쓰는 경우가 있어 요청 원문과 대조해 보정."""
    core, ko, en = _rule_core(request), "", ""
    try:
        q = json.loads(chat_fn([{"role": "system", "content": QUERY_SYS}, {"role": "user", "content": request}],
                               {"temperature": 0.1, "num_ctx": 2048, "num_predict": 120}, fmt="json"))
        if q.get("core") and q["core"].strip() in request:
            core = q["core"].strip()
        ko, en = q.get("ko", ""), q.get("en", "")
    except Exception:
        pass
    qual = re.search(re.escape(core) + r"\s*\(([^)]{1,12})\)", request)          # 듄(영화) → '영화'
    qual = qual.group(1).strip() if qual else ""
    words = [w for w in re.split(r"\s+", ko) if w and w != core and w != qual and w in request]   # 요청에 실제로 있는 단어만
    ko = " ".join([core] + ([qual] if qual else []) + words[:1]) if (qual or words) else f"{core} 시리즈"
    return {"core": core, "ko": ko, "en": en or core, "qual": qual}


PH = "TERMX"   # 주제어 보호용 표식 (모델은 영문 식별자를 그대로 복사하는 데 강함)


def _protect(s, core):
    return s.replace(core, PH) if core and len(core) <= 6 else s


def _protect_list(items, core):
    return [{k: _protect(v, core) if isinstance(v, str) else v for k, v in it.items()} for it in items]


def _josa(text, core):
    """표식 복원 뒤 조사 교정: 받침 있는 주제어(듄) → 듄은/듄이/듄을/듄과/듄으로."""
    last = core[-1]
    if not ("가" <= last <= "힣"):
        return text
    jong = (ord(last) - 0xAC00) % 28
    pairs = [("는", "은"), ("가", "이"), ("를", "을"), ("와", "과"), ("라는", "이라는"), ("로", "으로")]
    for no_b, with_b in pairs:
        if jong:                                  # 받침 있음
            if no_b == "로" and jong == 8:        # ㄹ받침은 '로' 유지
                continue
            text = re.sub(re.escape(core) + no_b + r"(?=[\s,.)』》]|$)", core + with_b, text)
        else:
            text = re.sub(re.escape(core) + with_b + r"(?=[\s,.)』》]|$)", core + no_b, text)
    return text


def _restore(obj, core):
    if isinstance(obj, str):
        return _josa(obj.replace(PH, core), core)
    if isinstance(obj, list):
        return [_restore(x, core) for x in obj]
    if isinstance(obj, dict):
        return {k: _restore(v, core) for k, v in obj.items()}
    return obj


PLAN_SYS = """웹페이지 구성을 기획한다. 사용자 요청의 구성 요소마다 섹션을 1개씩 만든다(최대 5개, 요청에 없는 섹션 금지).
focus 는 다음 중 하나: 세계관, 전개, 인물, 줄거리, 역사, 특징, 평가
layout: 세계관·특징·평가·줄거리=prose, 전개·역사=timeline, 인물=cards
title 은 주제명(짧게). tagline 은 주제의 본질(배경·분위기·핵심 갈등)을 담은 15~30자 한 줄 소개로,
구체적 수치·연도 없이 쓴다. '웹페이지, 디자인, 아이덴티티, 디지털' 같은 제작 관련 단어는 금지.
출력 JSON: {"title":"","tagline":"","sections":[{"nav":"메뉴명(2~5자)","heading":"섹션 제목","focus":"","layout":""}]}"""

SECTION_SYS = """당신은 웹 콘텐츠 에디터이다. 웹페이지의 '한 섹션' 내용을 [자료]만 근거로 JSON 으로 작성한다.
[절대 규칙]
- [자료]에 있는 사실만 사용. 자료에 없는 인물·연도·수치·작품은 만들지 말고 빼라.
- 모든 item 에 evidence: [자료]에서 글자 그대로 복사한 구절(10~40자, 자료의 언어 그대로).
- 한국어로 작성하고, 인물·작품명은 한국어 자료 표기를 그대로 쓴다. title·subtitle·body 에 영어 단어를 섞지 말고
  한국어로 옮겨 쓴다(예: House Atreides→아트레이데스 가문, Fremen→프레멘). evidence 만 원문 언어 그대로.
- items 최대 6개, body 는 80자 이내, intro 는 1~2문장.
{layout_rule}
출력 JSON: {{"intro":"","items":[{{"title":"","subtitle":"","tag":"","body":"","evidence":""}}]}}"""

LAYOUT_RULE = {
    "timeline": "- [자료]의 [출처] 문서마다 다루는 작품(또는 사건)을 item 1개씩, 자료에 나온 작품은 빠짐없이 모두 넣는다(원작 소설 포함). "
                "공개/발생 순서대로. tag=연도(자료에 있는 것만), title=작품명, subtitle=감독·매체 등(자료에 있을 때), body=한 줄 요약.",
    "cards": "- 인물마다 item 1개. title=인물 이름, subtitle=배우 또는 역할(자료에 있을 때), body=인물 설명 한 줄.",
    "prose": "- intro 에 핵심 설명 2문장, items 는 핵심 개념 3~5개(title=개념명, body=설명).",
}


YEAR_RE = re.compile(r"(\d{4})년(?:\s*\d{1,2}월(?:\s*\d{1,2}일)?)?(?:부터|에)?\s*(?:미국에서\s*)?(개봉 예정|개봉|공개|방영|출판|출간|발매)")


def timeline_from_pages(pages, core):
    """작품 문서 첫 단락에서 공개 연도·감독을 직접 읽어 타임라인 항목 생성 (모델 누락 보완용)."""
    out = []
    for p in pages:
        if p.get("lang") != "ko" or not p.get("sections") or core not in p["title"] or "동음이의" in p["title"]:
            continue
        intro = p["sections"][0][1][:400]
        m = YEAR_RE.search(intro)
        if not m:
            m2 = re.search(r"(\d{4})년\s*(?:미국의\s*)?(?:SF|공상 과학|서사)?\s*영화", intro)
            if not m2:
                continue
            year, verb = m2.group(1), "개봉"
        else:
            year, verb = m.group(1), m.group(2)
        title = re.sub(r"\s*\(\d{4}년 영화\)|\s*\((소설|영화|드라마)\)", "", p["title"]).strip()
        kind = "소설" if verb in ("출판", "출간") else ("드라마" if verb == "방영" else "영화")
        if kind == "소설" and "소설" not in title:
            title += " (원작 소설)"
        d = re.search(r"([가-힣]{1,4}\s?[가-힣]{2,4})(?:가|이) (?:감독|공동각본)", intro)
        sub = f"{d.group(1)} 감독 {kind}" if d and kind == "영화" else kind
        first = re.split(r"(?<=[다음])\.\s", re.sub(r"\(영어:[^)]*\)", "", intro))[0].strip()
        out.append({"tag": year, "title": title, "subtitle": sub + (" (개봉 예정)" if verb == "개봉 예정" else ""),
                    "body": first[:90] + ("…" if len(first) > 90 else ""), "evidence": intro[:30]})
    return out


def _merge_timeline(items, auto):
    """중복 제거: 같은 연도이면서 제목이 한쪽에 포함되면 같은 작품(예: '듄' vs '듄 Part I')으로 본다."""
    def year(it):
        m = re.search(r"\d{4}", str(it.get("tag", "")))
        return m.group(0) if m else ""

    def core(it):
        return _norm(re.sub(r"\(.*?\)|part\s*[ivx0-9]+|파트\s*1", "", it.get("title", ""), flags=re.I))

    out = []
    for it in items + auto:
        it["tag"] = year(it) or it.get("tag", "")
        dup = any(year(o) == year(it) and (core(o) in core(it) or core(it) in core(o)) for o in out)
        if not dup:
            out.append(it)
    items[:] = out
    items.sort(key=lambda it: str(it.get("tag") or "9999"))
    return items


def _section_items(request, sec, ctx, chat_fn, core):
    rule = LAYOUT_RULE.get(sec.get("layout"), LAYOUT_RULE["prose"])
    out = chat_fn([{"role": "system", "content": SECTION_SYS.format(layout_rule=rule)},
                   {"role": "user", "content": f"[사용자 요청]\n{_protect(request, core)}\n\n[이번 섹션]\n{sec.get('heading')}"
                                               f" (초점: {sec.get('focus')})\n(표기 규칙: '{PH}' 는 주제명 표식이므로 그대로 쓸 것)"
                                               f"\n\n[자료]\n{_protect(ctx, core)}"}],
                  {"temperature": 0.15, "num_ctx": 8192, "num_predict": 1400}, fmt="json")
    d = json.loads(out)
    return d.get("intro", ""), d.get("items", []) or []


def build(request: str, chat_fn, progress=None, use_research=True, extra_context="", trend=None, core=None, allow_product=True):
    """반환: {'html','content','theme','sources','removed','context'}"""
    import fact_research
    import product_builder
    if use_research and allow_product and product_builder.is_product_request(request):
        return product_builder.build(request, chat_fn, progress, trend=trend)      # 현재 판매 제품·가격·사진 요청 → 웹 검색 기반 제품 가이드
    say = progress or (lambda f, m: None)
    q = {"core": _rule_core(request), "ko": _rule_core(request), "en": "", "qual": ""}
    pages = []
    if use_research:
        say(0.03, "🔑 검색어 추출 중...")
        q = make_queries(request, chat_fn)
        if core:                                                    # 틀에서 주제를 직접 입력한 경우: 추측하지 않고 그대로 씀
            qual = re.search(r"\(([^)]{1,12})\)", core)
            base = re.sub(r"\s*\([^)]*\)", "", core).strip()
            q.update(core=base, qual=qual.group(1) if qual else "", ko=f"{base} {qual.group(1)}" if qual else base)
        say(0.08, f"🔑 검색어: {q['ko']} / {q['en']}")
        pages = fact_research.collect(request, q["ko"], q["core"], q["en"], q.get("qual", ""),
                                      progress=lambda m: say(0.12, m))
    if extra_context:
        pages.append({"lang": "ko", "title": "내부 문서(RAG)", "url": "", "sections": [("개요", extra_context)]})
    if not pages:
        raise RuntimeError("근거 자료를 찾지 못했습니다. 주제어를 바꾸거나 지식보관함 문서를 추가해 주세요.")
    core = q["core"]
    say(0.2, "🗂️ 페이지 구성 기획 중...")
    try:
        plan = json.loads(chat_fn([{"role": "system", "content": PLAN_SYS},
                                   {"role": "user", "content": _protect(request, core) + f"\n(주제명 표식 '{PH}' 는 그대로 쓸 것)"}],
                                  {"temperature": 0.2, "num_ctx": 2048, "num_predict": 400}, fmt="json"))
    except Exception:
        plan = {}
    secs = [s for s in plan.get("sections", []) if isinstance(s, dict)][:5] or [
        {"nav": "개요", "heading": "개요", "focus": "세계관", "layout": "prose"}]
    if not re.search(r"수치|통계|숫자|기록|흥행|규모|매출", request):
        secs = [s for s in secs if s.get("layout") != "facts"]
    content = {"title": plan.get("title") or core, "tagline": plan.get("tagline", ""), "subtitle": "", "sections": []}
    removed, used_ctx = 0, []
    for i, sec in enumerate(secs):
        layout = sec.get("layout") if sec.get("layout") in ("prose", "timeline", "cards") else "prose"
        sec["layout"] = layout
        ctx = fact_research.select(pages, sec.get("focus", ""), layout)
        if not ctx:
            continue
        say(0.25 + 0.55 * i / len(secs), f"✍️ [{i + 1}/{len(secs)}] '{_restore(sec.get('heading', ''), core)}' 작성 중...")
        try:
            intro, items = _section_items(request, sec, ctx, chat_fn, core)
        except Exception:
            continue
        one = {"sections": [dict(sec, intro=intro, items=items)]}
        one, r = verify(one, _protect(ctx, core))
        removed += r
        if layout == "timeline":                       # 연도 tag 는 자료에 있어야 함 + 누락 작품 자동 보완
            auto = _protect_list(timeline_from_pages(pages, core), core) if sec.get("focus") in ("전개", "역사", "") else []
            for s in one["sections"]:
                s["items"] = [it for it in s["items"] if not it.get("tag") or str(it["tag"])[:4] in ctx]
                s["items"] = _merge_timeline(s["items"], auto)
            if not one["sections"] and auto:
                one["sections"] = [dict(sec, intro=intro, items=_merge_timeline([], auto))]
        content["sections"] += one["sections"]
        used_ctx.append(ctx)
    content = _restore(content, core)
    say(0.85, "🎨 디자인 테마 선택 중...")
    try:
        theme = json.loads(chat_fn([{"role": "system", "content": THEME_SYS},
                                    {"role": "user", "content": f"주제: {request}\n페이지 제목: {content.get('title', '')}"}],
                                   {"temperature": 0.4, "num_ctx": 4096, "num_predict": 300}, fmt="json"))
    except Exception:
        theme = {}
    sources = [{"title": f"{p['title']} - 위키백과({p['lang']})", "url": p["url"]} for p in pages if p.get("url")]
    say(1.0, "✅ 완료")
    return {"html": render(content, theme, sources, trend), "content": content, "theme": fix_theme(theme),
            "sources": sources, "removed": removed, "context": "\n\n".join(used_ctx)}
