"""마크다운(개조식 포함) → 블록 리스트, 슬라이드 구조 파서. 모든 익스포터가 공유."""
import json
import re

SYMS = {"□": "box", "ㅇ": "circle", "○": "circle", "◦": "circle", "-": "dash", "•": "dash", "·": "dash",
        "※": "note"}
SYM_CHAR = {"box": "□", "circle": "ㅇ", "dash": "-", "note": "※"}
SYM_LEVEL = {"box": 0, "circle": 1, "dash": 2, "note": 2}


_GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "theta": "θ", "lambda": "λ",
          "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "omega": "ω", "chi": "χ",
          "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω", "Phi": "Φ", "Theta": "Θ", "Gamma": "Γ", "Lambda": "Λ"}
_OPS = {"times": "×", "cdot": "·", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠",
        "approx": "≈", "pm": "±", "infty": "∞", "sum": "Σ", "prod": "Π", "int": "∫", "partial": "∂",
        "rightarrow": "→", "to": "→", "leftarrow": "←", "Rightarrow": "⇒", "sim": "~", "propto": "∝",
        "circ": "°", "degree": "°", "ldots": "…", "cdots": "…", "quad": " ", "qquad": "  ", ",": " ", ";": " "}
_SUP = str.maketrans("0123456789+-n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ")
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def latex_to_text(s: str) -> str:
    """LaTeX 수식 → 읽을 수 있는 유니코드 문자열 (₩Delta, $$ 같은 깨짐 방지)."""
    s = re.sub(r"\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}", r"\1", s)
    for _ in range(3):
        s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)
        s = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", s)
    s = re.sub(r"\\(left|right|big|Big|bigg)\b", "", s)
    s = re.sub(r"\\([A-Za-z]+) ?", lambda m: _GREEK.get(m.group(1), _OPS.get(m.group(1), m.group(1)))
               + (" " if m.group(1) in _OPS and m.group(1) not in ("sum", "prod", "int", "partial") else ""), s)
    s = re.sub(r"\\([,;!])", " ", s)
    s = re.sub(r"\^\{([0-9+\-n]+)\}", lambda m: m.group(1).translate(_SUP), s)
    s = re.sub(r"\^([0-9n])", lambda m: m.group(1).translate(_SUP), s)
    s = re.sub(r"_\{([0-9]+)\}", lambda m: m.group(1).translate(_SUB), s)
    s = re.sub(r"_([0-9])", lambda m: m.group(1).translate(_SUB), s)
    s = re.sub(r"\^\{([^{}]*)\}", r"^(\1)", s)
    s = re.sub(r"_\{([^{}]*)\}", r"_\1", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s{2,}", " ", s).strip()


def fix_math_chars(s: str) -> str:
    """𝜹 𝟗 𝒐 같은 '수학용 영숫자 기호'(대부분 글꼴에 없음)를 일반 문자로 바꿈. 한글 자모(ㅇ 등)는 건드리지 않음."""
    import unicodedata
    return "".join(unicodedata.normalize("NFKC", c) if 0x1D400 <= ord(c) <= 0x1D7FF or c in "ℎᶲ" else c
                   for c in s)


def clean_inline(s: str) -> str:
    s = fix_math_chars(s)
    s = re.sub(r"\$\$(.+?)\$\$", lambda m: latex_to_text(m.group(1)), s)
    s = re.sub(r"\$([^$\n]+?)\$", lambda m: latex_to_text(m.group(1)), s)
    s = re.sub(r"\\\((.+?)\\\)", lambda m: latex_to_text(m.group(1)), s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", s)
    s = s.replace("\\", "/")      # 남은 역슬래시는 맑은 고딕에서 ₩로 보이므로 치환
    return s.strip()


def _is_sep(line: str) -> bool:
    return bool(re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", line))


def split_row(line: str):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [clean_inline(c) for c in line.split("|")]


def parse_blocks(md: str):
    """반환: ('h', level, text) | ('sym', kind, text) | ('p', text) | ('table', rows) | ('img', key, caption)"""
    blocks = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            i += 1
            continue
        if re.match(r"^([-*_])\1{2,}$", s.replace(" ", "")):      # 구분선(---) 은 출력하지 않음
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(img:([^)]+)\)$", s)          # 그림: ![캡션](img:키)
        if m:
            blocks.append(("img", m.group(2), clean_inline(m.group(1))))
            i += 1
            continue
        if s.startswith("$$") or s.startswith("\\["):                # 수식 블록 → 한 줄 텍스트
            opener = "$$" if s.startswith("$$") else "\\["
            closer = "$$" if opener == "$$" else "\\]"
            rest = s[len(opener):].rstrip()
            i += 1
            if rest.strip() and rest.endswith(closer):
                body = rest[: -len(closer)]
            else:
                body = rest
                while i < len(lines):
                    t = lines[i].strip()
                    i += 1
                    if t.endswith(closer):
                        body += " " + t[: -len(closer)]
                        break
                    body += " " + t
            if body.strip():
                blocks.append(("p", latex_to_text(body)))
            continue
        if s.startswith("|") and s.count("|") >= 2:
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not _is_sep(lines[i]):
                    rows.append(split_row(lines[i]))
                i += 1
            if rows:
                n = max(len(r) for r in rows)
                rows = [r + [""] * (n - len(r)) for r in rows]
                blocks.append(("table", rows))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            blocks.append(("h", len(m.group(1)), clean_inline(m.group(2))))
            i += 1
            continue
        first = s[0]
        indent = len(line) - len(line.lstrip())
        if first in ("□", "ㅇ", "○", "◦", "※"):
            blocks.append(("sym", SYMS[first], clean_inline(s[1:])))
        elif first in ("-", "•", "·", "*") and len(s) > 1 and s[1] == " ":
            blocks.append(("sym", "dash", clean_inline(s[2:])))
        elif re.match(r"^\d+[.)]\s", s):
            blocks.append(("p", clean_inline(s)))
        else:
            blocks.append(("p", clean_inline(s)))
        i += 1
    return blocks


# ---------------------------------------------------------------- 슬라이드
def _extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    cand = m.group(1) if m else None
    if not cand:
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b > a:
            cand = text[a:b + 1]
    if not cand:
        a = text.find("{")
        if a == -1:
            return None
        cand = text[a:]
    try:
        return json.loads(cand)
    except Exception:
        return _repair_json(text[text.find("{"):] if text.find("{") != -1 else cand)


def _close_brackets(s: str):
    """문자열 밖의 열린 괄호를 순서대로 닫아 준다. 문자열이 열린 채 끝나면 None."""
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            esc = (ch == "\\" and not esc)
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return None if in_str else s + "".join(reversed(stack))


def _repair_json(s: str):
    """응답이 중간에 잘린 JSON 복구: 뒤에서부터 완결된 '}' 또는 ']' 위치로 자르고 열린 괄호를 닫아 본다(최대 60회)."""
    s = re.sub(r"\s*```\s*$", "", s.strip())
    cuts = [i for i, ch in enumerate(s) if ch in "}]"][::-1][:60]
    for i in cuts:
        fixed = _close_brackets(re.sub(r",\s*$", "", s[:i + 1]))
        if fixed is None:
            continue
        try:
            d = json.loads(fixed)
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    return None


def _norm_bullet(b):
    if isinstance(b, dict):
        lvl = int(b.get("level", 0))
        return (max(0, min(lvl, 2)), clean_inline(str(b.get("text", ""))))
    s = str(b)
    st = s.strip()
    if not st:
        return None
    ind = len(s) - len(s.lstrip())
    if st[0] in SYMS and (st[0] != "-" or True):
        kind = SYMS[st[0]]
        return (SYM_LEVEL[kind], clean_inline(st[1:]))
    return (min(ind // 2, 2), clean_inline(st))


def parse_slides(text: str):
    """JSON 또는 마크다운 → {'title','subtitle','slides':[{'title','bullets':[(lvl,txt)],'table','notes'}]}"""
    data = _extract_json(text)
    if data and isinstance(data, dict):
        slides = []
        for s in data.get("slides", []):
            bl = [x for x in (_norm_bullet(b) for b in s.get("bullets", [])) if x]
            tbl = s.get("table")
            if isinstance(tbl, list) and tbl:
                tbl = [[clean_inline(str(c)) for c in r] for r in tbl if isinstance(r, list)]
            else:
                tbl = None
            slides.append({"title": clean_inline(str(s.get("title", ""))), "bullets": bl,
                           "table": tbl, "notes": str(s.get("notes", "") or ""),
                           "keypoint": clean_inline(str(s.get("keypoint", "") or "")),
                           "icon": str(s.get("icon", "") or "").strip(),
                           "source": clean_inline(str(s.get("source", "") or ""))})
        return {"title": clean_inline(str(data.get("title", ""))),
                "subtitle": clean_inline(str(data.get("subtitle", ""))), "slides": slides}
    # 마크다운 폴백
    title, subtitle, slides, cur = "", "", [], None
    for b in parse_blocks(text):
        if b[0] == "h" and b[1] == 1 and not title:
            title = b[2]
        elif b[0] == "h":
            cur = {"title": b[2], "bullets": [], "table": None, "notes": ""}
            slides.append(cur)
        elif cur is not None:
            if b[0] == "sym":
                cur["bullets"].append((SYM_LEVEL[b[1]], b[2]))
            elif b[0] == "p":
                cur["bullets"].append((0, b[1]))
            elif b[0] == "table" and cur["table"] is None:
                cur["table"] = b[1]
    return {"title": title or (slides[0]["title"] if slides else ""), "subtitle": subtitle, "slides": slides}
