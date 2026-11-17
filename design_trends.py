"""웹페이지 디자인 트렌드 프리셋 13종 (Figma 웹 디자인 트렌드 분류 기준).
트렌드를 고르면 색·글꼴·카드 모양·효과(CSS)가 그 스타일로 바뀐다. 제품 가이드(product_builder)와 정보·소개 페이지(web_builder) 공용.
- P: 제품 가이드용 색 변수, W: 정보·소개 페이지용 테마(색·글꼴·배경 효과), CSS: 두 페이지 공통 추가 스타일."""

FONTS = {"Orbitron": "Orbitron:wght@500;800", "Black Han Sans": "Black+Han+Sans", "Do Hyeon": "Do+Hyeon",
         "Gowun Batang": "Gowun+Batang:wght@400;700", "Playfair Display": "Playfair+Display:wght@600;800",
         "Noto Serif KR": "Noto+Serif+KR:wght@400;700;900", "Bebas Neue": "Bebas+Neue", "IBM Plex Sans KR": "IBM+Plex+Sans+KR:wght@400;600"}

HEAD = "h1,h2,h3,.price,.stats strong,.top b,.brand,.tl-tag,.fact strong"   # 제목류(트렌드 글꼴 적용 대상)
CARD = ".pc,.card,.tl-card,.fact,.keys li"
HERO_IN = ".hero .in,.hero-inner{position:relative;z-index:2}.hero{position:relative;overflow:hidden}"


def _p(ink, mu, line, bg, card, ac, ac2, h1, h2, topbg="rgba(255,255,255,.86)", thbg="#F8FAFC", li="#334155", kind="#EFF6FF"):
    return {"ink": ink, "mu": mu, "line": line, "bg": bg, "card": card, "ac": ac, "ac2": ac2, "hero1": h1, "hero2": h2,
            "topbg": topbg, "thbg": thbg, "li": li, "kindbg": kind}


def _w(bg, bg2, sf, tx, mu, ac, ac2, hf, bf="Noto Sans KR", hero="minimal"):
    return {"bg": bg, "bg2": bg2, "surface": sf, "text": tx, "muted": mu, "accent": ac, "accent2": ac2,
            "heading_font": hf, "body_font": bf, "hero": hero, "mood": []}


DARK_P = dict(topbg="rgba(10,14,26,.82)", thbg="rgba(255,255,255,.05)", li="#B7C0D8", kind="rgba(255,255,255,.08)")

TRENDS = {
    "auto": {"name": "자동 (주제에 맞춤)", "desc": "주제에 어울리는 디자인을 AI가 고릅니다."},
    "3d": {
        "name": "3D·몰입형", "desc": "입체 그림자와 떠 있는 구체, 마우스를 올리면 카드가 기울어집니다.",
        "font": "Orbitron",
        "P": _p("#EAF0FF", "#9AA7C7", "#263055", "#0B1020", "#151C33", "#7C5CFF", "#22D3EE", "#070B18", "#1B1446", **DARK_P),
        "W": _w("#0B1020", "#121933", "#19213F", "#EAF0FF", "#9AA7C7", "#7C5CFF", "#22D3EE", "Orbitron", hero="grid"),
        "CSS": HERO_IN + CARD + """{transform-style:preserve-3d;box-shadow:0 1px 0 rgba(255,255,255,.07) inset,0 30px 50px -22px rgba(0,0,0,.75),0 0 0 1px rgba(124,92,255,.25);transition:transform .35s,box-shadow .35s}
.pc:hover,.card:hover,.tl-card:hover{transform:perspective(900px) rotateX(5deg) rotateY(-6deg) translateY(-10px) scale(1.02)}
.hero h1{text-shadow:0 1px 0 #6d4cff,0 2px 0 #5b3df0,0 3px 0 #4a2fd0,0 4px 0 #3a22a8,0 18px 30px rgba(0,0,0,.55)}
.hero::before{content:"";position:absolute;width:min(420px,60vw);aspect-ratio:1;border-radius:50%;right:6%;top:10%;background:radial-gradient(circle at 30% 30%,#b3a8ff,#5b3df0 55%,#1b1446);box-shadow:0 40px 80px rgba(91,61,240,.5);animation:fl3 7s ease-in-out infinite alternate;opacity:.5}
@keyframes fl3{to{transform:translateY(-28px) scale(1.06)}}"""},
    "experimental": {
        "name": "실험적 탐색", "desc": "격자를 일부러 어긋나게 배치한 비대칭 레이아웃, 큰 글자와 화살표.",
        "font": "Playfair Display",
        "P": _p("#141414", "#6B6558", "#D9D0BD", "#F2EDE0", "#FBF8F0", "#FF4D2E", "#1F3BFF", "#141414", "#2B2B2B", thbg="#EFE8D6", li="#3A362D", kind="#FFE3DC"),
        "W": _w("#F2EDE0", "#E8E1CE", "#FBF8F0", "#141414", "#6B6558", "#FF4D2E", "#1F3BFF", "Playfair Display", hero="minimal"),
        "CSS": """.grid>.pc:nth-child(3n+2),.cards>.card:nth-child(3n+2){transform:translateY(54px)}
.grid>.pc:nth-child(3n),.cards>.card:nth-child(3n){transform:translateY(-16px) rotate(1.4deg)}
.grid{padding-bottom:60px}.hero{text-align:left}.hero .in,.hero-inner{max-width:1100px;margin:0 auto}
.hero h1{letter-spacing:-.05em;font-size:clamp(3rem,10vw,8rem);font-style:italic}
.sec h2,.sec-head h2{letter-spacing:-.03em}.sec h2::before{content:"↘ ";color:var(--ac)}
.pc,.card{border-radius:6px}.price{font-style:italic}"""},
    "vivid": {
        "name": "생생한 색채", "desc": "채도 높은 핑크·보라·노랑 그라데이션으로 활기찬 분위기.",
        "font": "Do Hyeon",
        "P": _p("#1B1033", "#6B5B8C", "#F0D9F5", "#FFF7F0", "#FFFFFF", "#FF3D81", "#FFB800", "#FF3D81", "#6D28D9", kind="#FFE0EC"),
        "W": _w("#FFF7F0", "#FFEAD9", "#FFFFFF", "#1B1033", "#6B5B8C", "#FF3D81", "#7C3AED", "Do Hyeon", hero="mist"),
        "CSS": """.sec h2,.sec-head h2{background:linear-gradient(90deg,#FF3D81,#7C3AED,#06B6D4);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero{background:linear-gradient(120deg,#FF3D81,#FF8A00,#7C3AED)!important;color:#fff}.hero p,.hero .tagline{color:#fff!important}
.pc,.card,.tl-card{border:2px solid transparent;background:linear-gradient(#fff,#fff) padding-box,linear-gradient(135deg,#FF3D81,#FFB800,#7C3AED) border-box}
.price{color:#FF3D81}.stats strong{color:#FFE066}"""},
    "bold": {
        "name": "대담한 타이포그래피", "desc": "거대한 제목 글자와 흑백 대비로 글자가 곧 디자인입니다.",
        "font": "Black Han Sans",
        "P": _p("#000000", "#555555", "#000000", "#FFFFFF", "#FFFFFF", "#E11D48", "#000000", "#000000", "#111111", thbg="#F2F2F2", li="#222", kind="#000"),
        "W": _w("#FFFFFF", "#F2F2F2", "#F7F7F7", "#000000", "#555555", "#E11D48", "#000000", "Black Han Sans", hero="minimal"),
        "CSS": """.hero h1{font-size:clamp(3.6rem,14vw,11rem);line-height:.92;letter-spacing:-.03em;text-transform:uppercase}
.sec h2,.sec-head h2{font-size:clamp(2.6rem,7vw,5.2rem);line-height:1;letter-spacing:-.03em}
.hero{text-align:left}.hero .in,.hero-inner{max-width:1100px;margin:0 auto}.kind{color:#fff!important}
.pc,.card,.tl-card,.keys li,.fact{border:2px solid #000;border-radius:0;box-shadow:none}.price{font-size:2rem;color:#E11D48}
.top,.nav{border-bottom:3px solid #000;background:#fff}.hero .tag,.eyebrow{border-color:#fff;color:#fff}"""},
    "dark": {
        "name": "다크 모드", "desc": "어두운 배경에 네온 포인트 컬러, 눈이 편한 야간용 디자인.",
        "font": "IBM Plex Sans KR",
        "P": _p("#E6EDF3", "#8B98A9", "#232B38", "#0A0C10", "#141922", "#00F2FF", "#7C4DFF", "#05070B", "#0F1A2B", **DARK_P),
        "W": _w("#0A0C10", "#10141B", "#171C26", "#E6EDF3", "#8B98A9", "#00F2FF", "#7C4DFF", "IBM Plex Sans KR", hero="grid"),
        "CSS": CARD + """{box-shadow:0 0 0 1px rgba(0,242,255,.12),0 10px 30px rgba(0,0,0,.5)}
.pc:hover,.card:hover{box-shadow:0 0 0 1px rgba(0,242,255,.5),0 0 32px rgba(0,242,255,.18)}
.price{color:#00F2FF;text-shadow:0 0 18px rgba(0,242,255,.35)}.ph{background:#fff}"""},
    "motion": {
        "name": "모션·애니메이션", "desc": "움직이는 그라데이션, 순서대로 나타나는 카드, 부드러운 호버 반응.",
        "font": "IBM Plex Sans KR",
        "P": _p("#0F172A", "#64748B", "#E2E8F0", "#F5F7FA", "#FFFFFF", "#2563EB", "#06B6D4", "#0B1220", "#16213E"),
        "W": _w("#0B1220", "#121B30", "#18233D", "#EAF0FF", "#9AA7C7", "#38BDF8", "#A78BFA", "IBM Plex Sans KR", hero="mist"),
        "CSS": """.hero{background-size:260% 260%!important;animation:mgrad 12s ease infinite}
@keyframes mgrad{0%{background-position:0 50%}50%{background-position:100% 50%}100%{background-position:0 50%}}
.hero h1{animation:mup 1s cubic-bezier(.2,.7,.2,1) both}.hero p,.hero .tagline{animation:mup 1s .25s cubic-bezier(.2,.7,.2,1) both}
@keyframes mup{from{opacity:0;transform:translateY(34px)}to{opacity:1;transform:none}}
.grid>*:nth-child(2),.cards>*:nth-child(2){transition-delay:.12s}.grid>*:nth-child(3),.cards>*:nth-child(3){transition-delay:.24s}
.grid>*:nth-child(4),.cards>*:nth-child(4){transition-delay:.36s}.grid>*:nth-child(5),.cards>*:nth-child(5){transition-delay:.48s}
.pc img{transition:transform .7s cubic-bezier(.2,.7,.2,1)}.pc:hover img{transform:scale(1.09) rotate(-1.5deg)}
.price{transition:letter-spacing .3s}.pc:hover .price{letter-spacing:.02em;color:var(--ac)}"""},
    "game": {
        "name": "게임화된 디자인", "desc": "두꺼운 테두리·버튼 같은 그림자·배지로 게임 UI 느낌.",
        "font": "Do Hyeon",
        "P": _p("#1E1B4B", "#5B5886", "#1E1B4B", "#EEF2FF", "#FFFFFF", "#FF9F1C", "#2EC4B6", "#6C5CE7", "#00B4D8", thbg="#FFD166", li="#2B2766", kind="#FFD166"),
        "W": _w("#EEF2FF", "#E0E7FF", "#FFFFFF", "#1E1B4B", "#5B5886", "#FF9F1C", "#2EC4B6", "Do Hyeon", hero="mist"),
        "CSS": CARD + """{border:3px solid #1E1B4B!important;box-shadow:0 6px 0 #1E1B4B;border-radius:22px!important}
.pc:hover,.card:hover{transform:translateY(-5px);box-shadow:0 11px 0 #1E1B4B}
.stats strong{background:#FFD166;color:#1E1B4B;border:3px solid #1E1B4B;border-radius:14px;padding:2px 18px;box-shadow:0 4px 0 #1E1B4B}
.kind,.chip,.tag{font-weight:800;border:2px solid #1E1B4B;color:#1E1B4B!important;background:#FFD166!important}
.price::before{content:"🪙 ";font-size:.8em}.mk::before{content:"★ "}th{color:#1E1B4B!important}
.tw{border:3px solid #1E1B4B;box-shadow:0 6px 0 #1E1B4B}"""},
    "neumorphism": {
        "name": "뉴모피즘", "desc": "배경에서 부드럽게 솟아오른 듯한 입체 카드, 은은한 단색 톤.",
        "font": "IBM Plex Sans KR",
        "P": _p("#3D4468", "#6B7599", "#D1D9E6", "#E0E5EC", "#E0E5EC", "#5B6CFF", "#8B9BFF", "#E0E5EC", "#E0E5EC", topbg="rgba(224,229,236,.9)", thbg="#E0E5EC", li="#4B5378", kind="#E0E5EC"),
        "W": _w("#E0E5EC", "#D8DEE8", "#E0E5EC", "#3D4468", "#6B7599", "#5B6CFF", "#8B9BFF", "IBM Plex Sans KR", hero="minimal"),
        "CSS": CARD + """{border:none!important;background:#E0E5EC!important;box-shadow:9px 9px 18px #A3B1C6,-9px -9px 18px #fff;border-radius:26px}
.pc:hover,.card:hover{transform:none;box-shadow:inset 6px 6px 12px #A3B1C6,inset -6px -6px 12px #fff}
.hero{color:#3D4468!important}.hero p,.hero .tagline,.subtitle{color:#6B7599!important}.hero h1{color:#3D4468;text-shadow:2px 2px 4px #fff,-1px -1px 3px #A3B1C6}
.stats strong{color:#3D4468}.stats span{color:#6B7599}.tag,.eyebrow{color:#5B6CFF!important;border-color:#5B6CFF66!important}
.ph{background:#E0E5EC;box-shadow:inset 4px 4px 9px #A3B1C6,inset -4px -4px 9px #fff;border:none;margin:16px 16px 0;border-radius:20px}
.tw{background:#E0E5EC;border:none;box-shadow:9px 9px 18px #A3B1C6,-9px -9px 18px #fff}.top,.nav{background:#E0E5EC;border:none;box-shadow:0 4px 10px #A3B1C6}
footer{background:#D1D9E6;color:#4B5378}footer h4{color:#3D4468}"""},
    "retro": {
        "name": "레트로퓨처리즘", "desc": "80년대 네온 핑크·시안, 석양과 격자 바닥의 복고풍 미래.",
        "font": "Orbitron",
        "P": _p("#F3E8FF", "#B9A6DD", "#3A2A66", "#120B2E", "#1D1245", "#FF2E97", "#00E5FF", "#1A0B3D", "#3B0F6B", **DARK_P),
        "W": _w("#120B2E", "#1A1040", "#241556", "#F3E8FF", "#B9A6DD", "#FF2E97", "#00E5FF", "Orbitron", hero="grid"),
        "CSS": HERO_IN + """.hero::after{content:"";position:absolute;left:50%;bottom:-300px;width:min(520px,80vw);aspect-ratio:1;transform:translateX(-50%);border-radius:50%;background:linear-gradient(#FFE14D,#FF2E97);-webkit-mask-image:repeating-linear-gradient(#000 0 15px,transparent 15px 22px);mask-image:repeating-linear-gradient(#000 0 15px,transparent 15px 22px);opacity:.8;z-index:1}
.hero h1{text-shadow:3px 3px 0 #FF2E97,-3px -3px 0 #00E5FF}
""" + CARD + """{border:1px solid #FF2E97;box-shadow:0 0 18px rgba(255,46,151,.3),inset 0 0 18px rgba(0,229,255,.08)}
.price{color:#00E5FF;text-shadow:0 0 12px #00E5FF}.ph{background:#fff}"""},
    "maximal": {
        "name": "맥시멀리즘", "desc": "무늬 배경, 여러 색의 두꺼운 테두리, 화려하게 겹친 장식.",
        "font": "Playfair Display",
        "P": _p("#2B1B00", "#7A5A2A", "#FFB703", "#FFF1D6", "#FFFFFF", "#E63946", "#2A9D8F", "#E63946", "#6A00F4", thbg="#FFE3A3", li="#4A3412", kind="#FFD6A5"),
        "W": _w("#FFF1D6", "#FFE3A3", "#FFFFFF", "#2B1B00", "#7A5A2A", "#E63946", "#2A9D8F", "Playfair Display", hero="mist"),
        "CSS": """body{background-image:radial-gradient(#ff7a0030 2px,transparent 2.5px),radial-gradient(#2a9d8f30 2px,transparent 2.5px);background-size:26px 26px;background-position:0 0,13px 13px}
.hero{background:conic-gradient(from 200deg at 70% 40%,#E63946,#FFB703,#2A9D8F,#6A00F4,#E63946)!important;color:#fff}.hero p,.hero .tagline{color:#fff!important}
.pc,.card,.tl-card,.fact,.keys li{border:4px solid #2B1B00!important;border-radius:28px!important;box-shadow:8px 8px 0 #FFB703,16px 16px 0 #2A9D8F}
.grid>.pc:nth-child(even),.cards>.card:nth-child(even){box-shadow:8px 8px 0 #E63946,16px 16px 0 #6A00F4}
.sec h2,.sec-head h2{text-decoration:underline wavy #E63946;text-underline-offset:10px}.price{color:#E63946}"""},
    "collage": {
        "name": "콜라주", "desc": "종이 질감 위에 테이프로 붙인 폴라로이드 사진 느낌.",
        "font": "Gowun Batang",
        "P": _p("#2E2418", "#7A6A55", "#D8CBB4", "#EAE0CF", "#FBF7EE", "#B5532F", "#2F6F6B", "#3B2F20", "#6B4F2E", thbg="#E3D6BE", li="#4A3C2A", kind="#F1DEC0"),
        "W": _w("#EAE0CF", "#E0D3BB", "#FBF7EE", "#2E2418", "#7A6A55", "#B5532F", "#2F6F6B", "Gowun Batang", "Gowun Batang", hero="minimal"),
        "CSS": """body{background-image:repeating-linear-gradient(45deg,rgba(0,0,0,.015) 0 2px,transparent 2px 6px)}
.grid>.pc:nth-child(odd){transform:rotate(-1.6deg)}.grid>.pc:nth-child(even){transform:rotate(1.3deg) translateY(10px)}
.pc,.card,.tl-card{position:relative;overflow:visible;border-radius:3px;border:none;box-shadow:0 10px 22px rgba(60,40,10,.25)}
.pc::before,.card::before{content:"";position:absolute;top:-12px;left:50%;width:96px;height:26px;transform:translateX(-50%) rotate(-3deg);background:rgba(255,214,102,.75);box-shadow:0 1px 3px rgba(0,0,0,.2);z-index:3}
.ph{margin:18px 18px 0;border:10px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.2);border-radius:0}.pb{padding-top:16px}
.pc:hover{transform:rotate(0) scale(1.03);z-index:5}.hero h1{font-style:italic}.hero{background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.05) 0 10px,transparent 10px 20px)!important}"""},
    "brutal": {
        "name": "네오 브루탈리즘", "desc": "굵은 검정 테두리, 어긋난 그림자, 원색 — 일부러 거칠게(안티 디자인).",
        "font": "Do Hyeon",
        "P": _p("#000000", "#333333", "#000000", "#FFFDF5", "#FFFFFF", "#FFDE00", "#FF6B9D", "#FFDE00", "#FFDE00", topbg="#FFFDF5", thbg="#FF6B9D", li="#111", kind="#9BF6FF"),
        "W": _w("#FFFDF5", "#FFF3B0", "#FFFFFF", "#000000", "#333333", "#FFDE00", "#FF6B9D", "Do Hyeon", hero="minimal"),
        "CSS": """*{border-radius:0!important}.hero{background:#FFDE00!important;color:#000;border-bottom:4px solid #000}
.hero p,.hero .tagline,.subtitle{color:#000!important}.hero h1{color:#000;text-shadow:5px 5px 0 #FF6B9D;letter-spacing:-.02em}
.tag,.eyebrow{border:3px solid #000!important;color:#000!important;background:#fff}.stats strong{color:#000;background:#fff;border:3px solid #000;padding:0 14px;box-shadow:4px 4px 0 #000}.stats span{color:#000}
""" + CARD + """{border:3px solid #000!important;box-shadow:7px 7px 0 #000;background:#fff}
.pc:hover,.card:hover{transform:translate(-3px,-3px);box-shadow:11px 11px 0 #000}
.price{background:#FFDE00;display:inline-block;padding:2px 10px;border:3px solid #000;box-shadow:3px 3px 0 #000;align-self:flex-start}.price.na{background:#eee}
.top,.nav{border-bottom:4px solid #000;background:#fff}.tw{border:3px solid #000;box-shadow:7px 7px 0 #000}th{color:#000!important;border-bottom:3px solid #000}
.kind,.chip{border:2px solid #000;color:#000!important}footer{background:#000}"""},
    "sustainable": {
        "name": "지속 가능한 웹 디자인", "desc": "애니메이션·무거운 효과 없이 가볍고 차분한 흙·초록 톤(저전력).",
        "font": "Noto Serif KR",
        "P": _p("#23301F", "#667260", "#D9DECF", "#F4F1EA", "#FFFFFF", "#3F6B4F", "#B08968", "#2F4A38", "#3F6B4F", thbg="#EEF0E6", li="#3C4A38", kind="#E6EFDF"),
        "W": _w("#F4F1EA", "#E9E6DB", "#FFFFFF", "#23301F", "#667260", "#3F6B4F", "#B08968", "Noto Serif KR", "Noto Serif KR", hero="minimal"),
        "CSS": """*{animation:none!important;transition:none!important}.rv,.reveal{opacity:1!important;transform:none!important}
.hero{background:var(--hero1,#2F4A38)!important;min-height:0;padding-top:72px;padding-bottom:64px}.hero::before,.hero::after,.hero-art{display:none!important}
.pc,.card,.tl-card{box-shadow:none;border:1px solid #D9DECF}.pc:hover,.card:hover{transform:none;box-shadow:none}
.top,.nav{backdrop-filter:none}"""},
}

ORDER = list(TRENDS)


def label(tid):
    t = TRENDS.get(tid) or TRENDS["auto"]
    return t["name"]


def _root(vars_):
    return ":root{" + ";".join(f"--{k}:{v}" for k, v in vars_.items()) + "}"


def font_param(tid):
    f = (TRENDS.get(tid) or {}).get("font")
    return (f, FONTS[f]) if f in FONTS else (None, None)


def product_css(tid):
    """제품 가이드 페이지에 덧붙일 CSS (없으면 빈 문자열)."""
    t = TRENDS.get(tid)
    if not t or "P" not in t:
        return ""
    f = t.get("font")
    fam = (f"{HEAD}{{font-family:'{f}','Noto Sans KR',sans-serif!important}}" if f else "")
    return _root(t["P"]) + fam + t["CSS"]


def web_theme(theme, tid):
    """정보·소개 페이지: 트렌드 테마가 AI 가 고른 테마를 덮어쓴다."""
    t = TRENDS.get(tid)
    return {**(theme or {}), **t["W"]} if t and "W" in t else theme


def web_css(tid):
    t = TRENDS.get(tid)
    return t["CSS"] if t and "CSS" in t else ""
