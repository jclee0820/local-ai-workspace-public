"""AI 비서: 사용자 문장 → 실행할 작업 목록 (규칙 기반이라 즉시·예측 가능, 여러 작업 한 번에 가능)."""
import re

RULES = [  # (작업, 패턴)
    ("compare", r"신\s*구\s*대조|대조표|비교|달라진|바뀐\s*(점|내용|부분|곳)|변경\s*(사항|내용|점)|차이"),
    ("mindmap", r"마인드\s*맵|mind\s*map|생각\s*지도"),
    ("gantt", r"간트|gantt|WBS|wbs|공정표|일정표\s*(를|로|만들|작성)|추진\s*일정.*(정리|만들|뽑)"),
    ("slides", r"슬라이드|발표\s*자료|발표자료|PPT|ppt|파워포인트|프레젠테이션|발표문"),
    ("report", r"보고서|기안문?|공문|품의|검토\s*의견서|초안\s*(을|으로)?\s*(써|작성)"),
    ("web", r"웹\s*페이지|홈\s*페이지|랜딩\s*페이지|html"),
    ("image", r"(그림|이미지|포스터|일러스트|삽화|로고|사진)\s*(을|를|으로|로)?\s*(하나\s*)?(그려|만들어|생성)|그려\s*(줘|주세요|봐)"),
    ("summary", r"요약|핵심만|간추려|줄여\s*(줘|서)|정리해\s*(줘|주세요)"),
]
LABEL = {"mindmap": "마인드맵", "gantt": "WBS·간트 차트", "slides": "발표 슬라이드", "report": "보고서 초안", "web": "웹페이지",
         "image": "이미지", "summary": "문서 요약", "answer": "답변", "compare": "문서 비교(신구대조표)"}


def route(msg: str, has_docs: bool, n_docs: int = 0):
    """[(작업, 인자)] — 문장에 나온 순서대로. 아무 것도 없으면 답변."""
    found = []
    for act, pat in RULES:
        m = re.search(pat, msg)
        if m:
            found.append((m.start(), act))
    acts = [a for _, a in sorted(found)]
    if "compare" in acts:                                  # 문서가 두 개 이상 첨부됐을 때만 대조표 (아니면 일반 질문)
        if n_docs >= 2 and not ({"slides", "report", "mindmap", "gantt"} & set(acts)):
            acts = ["compare"]
        else:
            acts.remove("compare")
    if "report" in acts or "slides" in acts:              # '요약해서 보고서로' → 보고서만
        acts = [a for a in acts if a != "summary"]
    if "web" in acts and "slides" in acts and not re.search(r"웹\s*페이지", msg):
        acts.remove("web")
    if "mindmap" in acts:                                  # 마인드맵은 항상 먼저 (뒤의 발표자료·웹페이지가 그 마인드맵을 씀)
        drop = {"mindmap", "summary", "image"}             # '마인드맵 그려줘'는 그림 생성이 아님
        if not re.search(r"보고서\s*(도|를|로)?\s*(써|작성|만들)", msg):   # '보고서를 마인드맵으로'는 보고서 작성이 아님
            drop.add("report")
        acts = ["mindmap"] + [a for a in acts if a not in drop]
    if "summary" in acts and not has_docs and len(msg) < 200:   # 요약할 대상이 없으면 그냥 답변
        acts.remove("summary")
    if "gantt" in acts and not has_docs:
        acts = [a for a in acts if a != "gantt"] + ["need_doc_gantt"]
    out = []
    for a in acts or ["answer"]:
        args = {}
        if a == "slides":
            args["theme"] = "blue" if re.search(r"블루|blue", msg, re.I) else "modern"
            m = re.search(r"(\d{1,2})\s*(장|페이지|슬라이드)", msg)
            args["n"] = max(3, min(int(m.group(1)), 15)) if m else 6
        if a == "gantt":
            args["unit"] = "week" if re.search(r"주\s*단위|주간", msg) else ("month" if re.search(r"월\s*단위", msg) else "auto")
        out.append((a, args))
    return out
