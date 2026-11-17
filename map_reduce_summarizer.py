"""맵-리듀스 분할 요약 엔진: 대용량 문서를 8k 컨텍스트 한계 없이 요약."""
import re

import llm_client
import style_presets

CHUNK_LIMIT = 6000      # 이 글자 수를 넘으면 맵-리듀스 적용
MAP_CHUNK = 4500        # 조각당 목표 글자 수
REDUCE_BATCH = 9000     # 리듀스 입력 한도(초과 시 계층 병합)

MAP_INSTR = """아래는 대형 문서의 일부분({idx}/{total}번째 조각{title_part})이다. 이 조각의 핵심 팩트와 정량적 수치(숫자·날짜·법령명·표준명·제약사항)를
누락 없이 개조식으로 요약하라. 제목 줄 없이 `□`/`ㅇ`/`-` 기호 위계와 ~함/~음/~임 어미를 사용하고, 비교 가능한 항목은 마크다운 표로 정리하라.
원문에 없는 내용은 추가하지 말 것."""

REDUCE_INSTR = """아래는 하나의 대형 문서를 조각별로 요약한 결과이다. 이를 취합하여 중복을 제거하고 전체를 관통하는 종합 개조식 요약 보고서로 병합하라.
- 첫 줄은 `# 제목`. 대분류는 `## 1. 항목명` 목차 순서로 구성.
- 핵심 쟁점별 비교 표(마크다운)를 최소 1개 이상 포함.
- 수치·고유명사를 보존하고 ~함/~음/~임 어미와 □/ㅇ/-/※ 위계를 유지.{extra}"""


def split_by_toc(text: str):
    """목차/제목 구조(제1장, 1., Ⅰ., 숫자.숫자 등)가 충분하면 해당 경계로 분할."""
    pat = re.compile(r"^\s*(제\s*\d+\s*[장절편]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.\s]|\d{1,2}\.\s+\S|#{1,3}\s+\S)", re.M)
    idxs = [m.start() for m in pat.finditer(text)]
    if len(idxs) < 3:
        return None
    idxs = [0] + idxs if idxs[0] != 0 else idxs
    sections = [text[a:b] for a, b in zip(idxs, idxs[1:] + [len(text)])]
    return sections


def _pack(sections, limit):
    chunks, cur = [], ""
    for s in sections:
        while len(s) > limit:          # 너무 큰 섹션은 균등 분할
            chunks.extend(_even_split(s, limit))
            s = ""
        if cur and len(cur) + len(s) > limit:
            chunks.append(cur)
            cur = ""
        cur += s
    if cur.strip():
        chunks.append(cur)
    return chunks


def _even_split(text, limit):
    n = max(1, -(-len(text) // limit))
    size = -(-len(text) // n)
    out, i = [], 0
    while i < len(text):
        end = min(len(text), i + size)
        if end < len(text):             # 문장/줄 경계로 보정
            cut = max(text.rfind("\n", i, end), text.rfind(". ", i, end))
            if cut > i + size // 2:
                end = cut + 1
        out.append(text[i:end])
        i = end
    return out


def split_document(text: str, limit: int = MAP_CHUNK):
    """① 목차 구조 우선 → ② 균등 블록. 반환: (chunks, 방식)"""
    toc = split_by_toc(text)
    if toc:
        chunks = _pack(toc, limit)
        if len(chunks) >= 2:
            return chunks, "목차 구조"
    return _even_split(text, limit), "균등 분할"


def summarize(text: str, preset: str = style_presets.DEFAULT_PRESET, topic: str = "",
              progress=None, chat_fn=None, extra_instruction: str = "", doc_name: str = "") -> dict:
    """progress(frac, msg) 콜백. doc_name: 원문 파일명(문서번호 오기 방지). 반환: {'result','chunks','method','maps'}"""
    chat_fn = chat_fn or llm_client.chat
    # 조각 요약·중간 병합은 같은 입력이면 결과를 재사용 (같은 문서를 다른 요청으로 다시 요약할 때 대부분 건너뜀)
    step_fn = llm_client.cached(chat_fn) if chat_fn is llm_client.chat else chat_fn
    sysmsg = style_presets.get_system_prompt(style_presets.DEFAULT_PRESET)  # 개조식 강제
    if preset != style_presets.DEFAULT_PRESET:
        sysmsg = style_presets.get_system_prompt(preset)
    opts = style_presets.get_options(preset)
    say = progress or (lambda f, m: None)
    name_rule = (f"\n[원문 문서명] {doc_name} — 문서 번호·표준명은 원문 표기를 그대로 쓰고 추측하지 말 것." if doc_name else "")
    req = f"\n[사용자 요청] {extra_instruction} — 이 요청에 맞는 내용을 우선 정리할 것." if extra_instruction else ""
    finish = (lambda s: s) if "서술형" in preset else __import__("exporters").to_gaejosik

    if len(text) <= CHUNK_LIMIT:
        say(0.1, "🔄 [요약 진행 중] 문서가 짧아 단일 요약으로 처리...")
        r = chat_fn([{"role": "system", "content": sysmsg},
                     {"role": "user", "content": f"다음 문서를 요약하라.{name_rule}{req}\n\n{text}"}], opts)
        say(1.0, "✅ 요약 완료")
        return {"result": finish(r), "chunks": 1, "method": "단일", "maps": [r]}

    chunks, method = split_document(text)
    total = len(chunks)
    maps = []
    for i, ch in enumerate(chunks, 1):
        say((i - 1) / (total + 1), f"🔄 [Map-Reduce 진행 중] {i}/{total}번째 {'목차' if method == '목차 구조' else '구간'} 요약 중...")
        title_part = f", 주제: {topic}" if topic else ""
        r = step_fn([{"role": "system", "content": sysmsg},
                     {"role": "user", "content": MAP_INSTR.format(idx=i, total=total, title_part=title_part)
                      + name_rule + req + "\n\n" + ch}], opts)
        maps.append(r.strip())

    # Reduce (입력이 길면 계층적으로 먼저 병합)
    level = 0
    while sum(len(m) for m in maps) > REDUCE_BATCH and len(maps) > 1:
        level += 1
        groups, cur, grp = [], [], 0
        for m in maps:
            if grp + len(m) > REDUCE_BATCH // 2 and cur:
                groups.append(cur); cur, grp = [], 0
            cur.append(m); grp += len(m)
        if cur:
            groups.append(cur)
        new = []
        for gi, g in enumerate(groups, 1):
            say(0.85, f"🔄 [Map-Reduce 진행 중] 중간 병합 {level}단계 {gi}/{len(groups)}...")
            new.append(step_fn([{"role": "system", "content": sysmsg},
                                {"role": "user", "content": "다음 요약들을 수치 손실 없이 하나로 합쳐 개조식으로 압축하라.\n\n" + "\n\n".join(g)}], opts))
        if len(new) >= len(maps):
            break
        maps_reduced = new
        maps = maps_reduced
    say(0.92, "🔄 [Map-Reduce 진행 중] 종합 병합(Reduce) 중...")
    extra = f"\n- 사용자 추가 지시: {extra_instruction}" if extra_instruction else ""
    final = chat_fn([{"role": "system", "content": sysmsg},
                     {"role": "user", "content": REDUCE_INSTR.format(extra=extra) + name_rule + "\n\n" +
                      "\n\n".join(f"[조각 {i}]\n{m}" for i, m in enumerate(maps, 1))}], opts)
    say(1.0, f"✅ Map-Reduce 완료 ({total}개 조각 → 종합 보고서)")
    return {"result": finish(final), "chunks": total, "method": method, "maps": maps}
