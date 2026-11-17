"""수치 검증: AI가 쓴 요약·보고서 속 숫자가 원문에 실제로 있는지 대조 (AI 호출 없이 즉시).
'없는 숫자'는 틀렸다는 뜻이 아니라 원문에서 같은 표기를 찾지 못했다는 뜻 — 합계·단위 환산일 수 있어 사람이 확인."""
import re

UNIT = (r"(?:%|％|퍼센트|억\s?원|만\s?원|천\s?원|조\s?원|백만\s?원|억|조|만|원|달러|명|건|개소|개월|개|대|곳|회|배|"
        r"km|㎞|cm|mm|m|㎡|㎢|GHz|MHz|kHz|Hz|Mbps|Gbps|ms|초|분|시간|일|주|월|년|차|호|종|단계|세|위|점|톤|kg|GB|MB|TB)")
NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?" + UNIT + r")?(?![\d])")


def _clean_line(l: str) -> str:
    l = re.sub(r"\[\d{1,2}[^\]]{0,12}\]", " ", l)                     # 인용 번호 [1], [2·p.3]
    l = re.sub(r"^\s*(#+\s*)?(\d+(\.\d+)*[.)]|\(\d+\)|[①-⑳])\s+", " ", l)   # 목차·항목 번호
    l = re.sub(r"^\s*#+\s*\d+(\.\d+)*\s", " ", l)
    return l


def _src_norm(source: str) -> str:
    s = re.sub(r"(?<=\d),(?=\d{3})", "", source)
    return re.sub(r"\s+", "", s)


def check(output: str, source: str, limit: int = 300) -> dict:
    """반환: {'total','ok','missing':[{'num','line'}]} (같은 숫자는 한 번만 셈)"""
    src = _src_norm(source)                                           # 띄어쓰기 제거판: '100 ms', 줄바꿈으로 갈린 숫자 대응
    src_sp = re.sub(r"(?<=\d),(?=\d{3})", "", source)                 # 띄어쓰기 유지판: 'X7 358H' 가 '7358'로 붙어 못 찾는 것 방지
    seen, missing, ok = set(), [], 0
    for raw in output.split("\n"):
        if re.match(r"^\s*\|?[\s:|-]+\|?\s*$", raw):                  # 표 구분선
            continue
        line = _clean_line(raw)
        for m in NUM.finditer(line):
            whole, frac, unit = m.group(1), m.group(2) or "", (m.group(3) or "").strip()
            digits = whole.replace(",", "") + frac
            if not unit and not frac and len(digits) < 2:              # 단위 없는 한 자리 수는 순번일 때가 많아 제외
                continue
            key = digits + "|" + unit
            if key in seen:
                continue
            seen.add(key)
            if len(seen) > limit:
                break
            pat = r"(?<![\d.])" + re.escape(digits) + r"(?!\d|\.\d)"
            if re.search(pat, src) or re.search(pat, src_sp):
                ok += 1
            else:
                missing.append({"num": m.group(0).strip(), "line": re.sub(r"\s+", " ", raw).strip(" |")[:120]})
    return {"total": ok + len(missing), "ok": ok, "missing": missing}


def summary(res: dict) -> str:
    if not res["total"]:
        return "수치 검증: 결과물에 확인할 수치가 없습니다."
    if not res["missing"]:
        return f"수치 검증: 수치 {res['total']}개 모두 원문에서 확인됨"
    return f"수치 검증: 수치 {res['total']}개 중 {res['ok']}개 원문 확인, {len(res['missing'])}개는 원문에서 못 찾음"
