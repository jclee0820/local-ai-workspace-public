"""로컬 아이콘 라이브러리 (Lucide · Tabler · Phosphor · Bootstrap Icons · Heroicons, 모두 MIT/ISC).
- find(keyword): 영문 키워드로 아이콘 찾기 (정확 일치 → 단어 일치 → 동의어 → 부분 일치)
- svg(name, color): 색을 입힌 SVG 문자열 (웹페이지 인라인용)
- png(name, color, size): 색을 입힌 투명 PNG 경로 (PPTX·DOCX·PDF·HWPX 용, 캐시)"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "icons", "sets")
CACHE = os.path.join(HERE, "icons", "_cache")
INDEX = os.path.join(HERE, "icons", "index.json")
SETS = {"lucide": "Lucide (선형, 기본)", "tabler": "Tabler (선형·채움)", "phosphor": "Phosphor (6가지 굵기)",
        "bootstrap-icons": "Bootstrap Icons", "heroicons": "Heroicons"}
DEFAULT_SET = "lucide"
# 세트별로 우선 쓸 하위 스타일 (선형 위주: 디자인 시스템의 '단색 선형 아이콘' 규칙)
PREFERRED_STYLE = {"tabler": "outline", "phosphor": "regular", "heroicons": "24/outline"}

SYN = {  # 자주 쓰는 개념 → 아이콘 이름 후보 (Lucide 기준, 다른 세트도 비슷한 이름)
    "vehicle": ["car", "car-front"], "autonomous": ["bot", "car-front"], "road": ["route", "milestone", "signpost"],
    "traffic": ["traffic-cone", "siren"], "signal": ["radio-tower", "signal", "antenna"], "v2x": ["radio-tower", "wifi"],
    "communication": ["radio-tower", "message-square", "wifi"], "network": ["network", "share-2"],
    "data": ["database", "chart-bar"], "analysis": ["chart-line", "chart-bar", "search"], "statistics": ["chart-bar"],
    "money": ["banknote", "coins", "wallet"], "budget": ["wallet", "banknote"], "cost": ["coins"],
    "safety": ["shield-check", "shield"], "security": ["lock", "shield"], "risk": ["triangle-alert", "alert-triangle"],
    "warning": ["triangle-alert", "alert-triangle"], "policy": ["landmark", "scale"], "law": ["scale", "gavel"],
    "government": ["landmark"], "standard": ["badge-check", "file-check"], "certification": ["badge-check", "award"],
    "document": ["file-text", "file"], "report": ["file-text", "clipboard-list"], "plan": ["calendar", "list-checks"],
    "schedule": ["calendar", "clock"], "time": ["clock", "timer"], "goal": ["target", "flag"], "strategy": ["target", "compass"],
    "people": ["users", "user"], "person": ["user"], "team": ["users"], "organization": ["building-2", "building"],
    "city": ["building-2", "map"], "map": ["map", "map-pin"], "location": ["map-pin"], "gps": ["satellite", "locate"],
    "sensor": ["scan", "radar", "eye"], "camera": ["camera", "cctv"], "ai": ["brain", "cpu", "sparkles"],
    "computer": ["cpu", "monitor", "server"], "cloud": ["cloud"], "server": ["server"], "energy": ["zap", "battery"],
    "electric": ["zap", "plug"], "environment": ["leaf", "tree-pine"], "growth": ["trending-up"], "decline": ["trending-down"],
    "idea": ["lightbulb"], "check": ["circle-check", "check"], "process": ["workflow", "git-branch"], "cooperation": ["handshake"],
    "education": ["graduation-cap", "book-open"], "research": ["microscope", "flask-conical"], "test": ["flask-conical", "clipboard-check"],
    "infrastructure": ["construction", "building"], "maintenance": ["wrench", "settings"], "settings": ["settings"],
    "global": ["globe"], "international": ["globe"], "korea": ["flag"], "question": ["circle-help"], "success": ["trophy", "award"],
}
KO = {  # 한국어 단어 → 영문 개념 (LLM이 아이콘 키워드를 주지 않았을 때 본문에서 추정)
    "자율주행": "autonomous", "차량": "vehicle", "자동차": "car", "도로": "road", "교통": "traffic", "신호": "signal",
    "통신": "communication", "네트워크": "network", "데이터": "data", "분석": "analysis", "통계": "statistics",
    "예산": "budget", "비용": "cost", "투자": "money", "재원": "money", "안전": "safety", "보안": "security",
    "위험": "risk", "사고": "warning", "정책": "policy", "법": "law", "제도": "law", "규제": "law", "정부": "government",
    "표준": "standard", "인증": "certification", "문서": "document", "보고": "report", "계획": "plan", "일정": "schedule",
    "기간": "time", "목표": "goal", "전략": "strategy", "비전": "goal", "국민": "people", "인력": "team", "조직": "organization",
    "기관": "organization", "도시": "city", "지도": "map", "위치": "location", "측위": "gps", "센서": "sensor",
    "카메라": "camera", "인공지능": "ai", "AI": "ai", "플랫폼": "computer", "시스템": "computer", "클라우드": "cloud",
    "서버": "server", "에너지": "energy", "전기": "electric", "환경": "environment", "탄소": "environment",
    "성장": "growth", "증가": "growth", "감소": "decline", "개선": "idea", "혁신": "idea", "추진": "process",
    "절차": "process", "협력": "cooperation", "협업": "cooperation", "교육": "education", "연구": "research",
    "실증": "test", "시험": "test", "인프라": "infrastructure", "구축": "infrastructure", "유지": "maintenance",
    "관리": "settings", "운영": "settings", "글로벌": "global", "국제": "international", "해외": "global",
    "과제": "question", "문제": "question", "성과": "success", "효과": "success", "현황": "statistics", "배경": "document",
    "고속도로": "road", "교차로": "traffic", "도심": "city", "전국": "map", "확대": "growth", "연계": "network",
    "확산": "growth", "보행자": "person", "운전자": "person", "사용자": "people", "시민": "people", "서비스": "settings",
    "정보": "data", "수집": "data", "제공": "communication", "개발": "research", "기술": "computer", "검증": "check",
    "평가": "check", "요구사항": "list", "법령": "law", "가이드": "document", "로드맵": "route", "결론": "check",
    "시사점": "idea", "제언": "idea", "방향": "strategy", "단계": "process", "사업": "plan", "산업": "growth",
    "시장": "growth", "수익": "money", "주차": "car", "물류": "truck", "철도": "train", "항공": "plane", "버스": "bus",
}
GENERIC = {"단계", "방향", "사업", "관리", "운영", "서비스", "정보", "기술", "시스템", "플랫폼", "추진", "구축", "확대",
           "개선", "제공", "문제", "과제", "현황", "계획"}       # 너무 일반적인 말은 뒤로
KO["요구사항"] = "requirement"
SYN.update({"requirement": ["list-checks", "clipboard-list"], "truck": ["truck"], "train": ["train-front", "train"], "plane": ["plane"],
            "bus": ["bus"], "route": ["route"]})
_IDX = None


def build_index():
    """아이콘 파일 목록 → {set: {name: relpath}} (선호 스타일 우선)."""
    idx = {}
    for s in SETS:
        base = os.path.join(ROOT, s)
        if not os.path.isdir(base):
            continue
        names = {}
        pref = PREFERRED_STYLE.get(s, "")
        for dp, _, files in os.walk(base):
            rel_dir = os.path.relpath(dp, base).replace("\\", "/")
            for f in files:
                if not f.endswith(".svg"):
                    continue
                name = re.sub(r"-(bold|duotone|fill|light|thin)$", "", f[:-4]) if s == "phosphor" else f[:-4]
                rel = (rel_dir + "/" + f) if rel_dir != "." else f
                is_pref = (not pref) or rel_dir == pref
                if name not in names or (is_pref and not names[name][1]):
                    names[name] = (rel, is_pref)
        idx[s] = {k: v[0] for k, v in names.items()}
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(idx, f)
    return idx


def index():
    global _IDX
    if _IDX is None:
        if os.path.exists(INDEX):
            with open(INDEX, encoding="utf-8") as f:
                _IDX = json.load(f)
        else:
            _IDX = build_index()
    return _IDX


def available() -> bool:
    return os.path.isdir(ROOT) and bool(index())


def find(keyword: str, icon_set: str = DEFAULT_SET):
    """영문 키워드(또는 아이콘 이름) → 아이콘 이름. 없으면 None."""
    if not keyword:
        return None
    names = index().get(icon_set) or index().get(DEFAULT_SET, {})
    k = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    if k in names:
        return k
    words = [w for w in k.split("-") if w]
    for w in words:                                   # 동의어 사전
        for cand in SYN.get(w, []):
            if cand in names:
                return cand
    for w in words:                                   # 단어 단독 이름
        if w in names:
            return w
    for w in sorted(words, key=len, reverse=True):    # 부분 일치 (짧은 이름 우선)
        hits = sorted((n for n in names if w in n.split("-")), key=len)
        if hits:
            return hits[0]
    return None


def candidates(text: str, icon_set: str = DEFAULT_SET, hint: str = ""):
    """어울리는 아이콘 이름 후보들(우선순위 순): 영문 키워드 → 본문 속 한국어 개념(앞쪽 등장 순) → 영문 단어."""
    out = []

    def add(n):
        if n and n not in out:
            out.append(n)
    if hint:
        add(find(hint, icon_set))
    t = text or ""
    hits = sorted((ko in GENERIC, t.find(ko), -len(ko), en) for ko, en in KO.items() if ko in t)
    for _, _, _, en in hits:
        add(find(en, icon_set))
        for cand in SYN.get(en, []):
            if cand in index().get(icon_set, {}):
                add(cand)
    names = index().get(icon_set, {})
    for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", t):   # 영문 단어는 동의어/정확한 이름일 때만
        w = w.lower()
        if w in SYN or w in names:
            add(find(w, icon_set))
    return out


def guess(text: str, icon_set: str = DEFAULT_SET, hint: str = "", avoid=()):
    """가장 어울리는 아이콘 1개 (avoid 에 있는 것은 피함). 없으면 None."""
    c = candidates(text, icon_set, hint)
    for n in c:
        if n not in avoid:
            return n
    return c[0] if c else None


SETTINGS = os.path.join(HERE, "icons", "settings.json")


def doc_icons_enabled() -> bool:
    """문서(HWPX·DOCX·PDF) 소제목 아이콘 사용 여부 (사이드바에서 켜고 끔, 기본 켬)."""
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return bool(json.load(f).get("doc_icons", True))
    except Exception:
        return True


def set_doc_icons(on: bool):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump({"doc_icons": bool(on)}, f)


def heading_icon(text: str, color: str = "#1F3864", used=None, size: int = 128):
    """문서 소제목용 아이콘 PNG 경로. 꺼져 있거나 못 찾으면 None. used 리스트로 같은 문서 안 중복 회피."""
    if not (doc_icons_enabled() and available()):
        return None
    name = guess(text, avoid=used or ())
    if not name:
        return None
    if used is not None:
        used.append(name)
    return png(name, color, size=size)


def inline_icons(html: str, icon_set: str = DEFAULT_SET) -> str:
    """HTML 속 <i data-icon="키워드" class="..."></i> 를 실제 SVG(현재 글자색)로 교체. 못 찾으면 원 모양 점."""
    def rep(m):
        attrs = m.group(1)
        kw = re.search(r'data-icon="([^"]+)"', attrs).group(1)
        cls = re.search(r'class="([^"]*)"', attrs)
        name = find(kw, icon_set) or "circle"
        s = svg(name, "currentColor", icon_set, size=24)
        s = re.sub(r'\swidth="[^"]*"|\sheight="[^"]*"', "", s, count=2)
        style = '' if cls and re.search(r"\b(w|h|size)-", cls.group(1)) else ' style="width:1.25em;height:1.25em"'
        return s.replace("<svg", f'<svg{(" class=" + chr(34) + cls.group(1) + chr(34)) if cls else ""}{style} '
                                  f'aria-hidden="true" data-icon-name="{name}"', 1)
    return re.sub(r'<i\s+([^>]*data-icon="[^"]+"[^>]*)>\s*</i>', rep, html or "")


def search(query: str, icon_set: str = DEFAULT_SET, limit: int = 40):
    names = index().get(icon_set, {})
    q = query.lower().strip()
    return sorted((n for n in names if q in n), key=lambda n: (not n.startswith(q), len(n)))[:limit]


def svg(name: str, color: str = "currentColor", icon_set: str = DEFAULT_SET, size: int = 24, stroke: float = None) -> str:
    """색을 입힌 SVG 문자열 (주석·class 제거)."""
    rel = (index().get(icon_set) or {}).get(name)
    if not rel:
        return ""
    t = open(os.path.join(ROOT, icon_set, rel), encoding="utf-8").read()
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r'\sclass="[^"]*"', "", t)
    t = t.replace("currentColor", color)
    if 'fill="' not in t.split(">", 1)[0] and "stroke=" not in t:      # 채움형 아이콘(색 지정 없음)
        t = t.replace("<svg", f'<svg fill="{color}"', 1)
    t = re.sub(r'\swidth="[^"]*"', f' width="{size}"', t, count=1)
    t = re.sub(r'\sheight="[^"]*"', f' height="{size}"', t, count=1)
    if stroke is not None:
        t = re.sub(r'stroke-width="[^"]*"', f'stroke-width="{stroke}"', t)
    return t.strip()


def png(name: str, color: str = "#000000", icon_set: str = DEFAULT_SET, size: int = 256) -> str:
    """투명 PNG 경로 (캐시). 문서·슬라이드용."""
    if not name:
        return None
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f"{icon_set}__{name}__{color.lstrip('#')}__{size}.png")
    if os.path.exists(out):
        return out
    s = svg(name, color, icon_set, size=24)
    if not s:
        return None
    import fitz
    doc = fitz.open(stream=s.encode("utf-8"), filetype="svg")
    pg = doc[0]
    z = size / max(pg.rect.width, pg.rect.height)
    pg.get_pixmap(matrix=fitz.Matrix(z, z), alpha=True).save(out)
    return out


if __name__ == "__main__":
    idx = build_index()
    print({k: len(v) for k, v in idx.items()})
    for kw in ("car", "vehicle", "radio-tower", "safety", "budget", "ai", "road", "standard"):
        print(kw, "->", find(kw), find(kw, "tabler"), find(kw, "phosphor"))
    print(png("car", "#1272C9"), png("shield-check", "#005878", "tabler"))
