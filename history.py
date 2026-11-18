"""작업 보관함: 만든 결과물(문서·보고서·슬라이드·웹페이지·간트·이미지·AI 비서 결과)을 자동 저장하고 다시 꺼내 씀.
저장 위치: outputs/history/<id>/ (meta.json + text.md + 첨부 파일)"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "history")
KINDS = {"doc": "문서 요약·추출", "report": "보고서·기안문", "slides": "발표 슬라이드", "web": "웹페이지",
         "gantt": "WBS·간트 차트", "image": "이미지", "answer": "AI 비서 답변", "diagram": "다이어그램", "mindmap": "마인드맵",
         "compare": "문서 비교"}


def _hash(text, files, meta_key):
    h = hashlib.sha1()
    if meta_key and meta_key.startswith("key:"):          # 내용 대신 지정한 키로 중복 판단 (매번 바이트가 달라지는 파일용)
        h.update(meta_key.encode("utf-8"))
        return h.hexdigest()[:12]
    h.update((text or "").encode("utf-8"))
    for n in sorted(files or {}):
        h.update(n.encode("utf-8"))
        h.update(hashlib.sha1(files[n]).digest())
    h.update((meta_key or "").encode("utf-8"))
    return h.hexdigest()[:12]


def _safe(name):
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip()[:80] or "file"


def save(kind: str, title: str, text: str = None, files: dict = None, meta: dict = None, dedupe_key: str = None):
    """결과물 저장. 같은 내용이 이미 있으면 새로 만들지 않고 기존 id 반환."""
    os.makedirs(ROOT, exist_ok=True)
    hid = _hash(text, files, ("key:" + dedupe_key) if dedupe_key else kind)
    for d in os.listdir(ROOT):
        if d.endswith("_" + hid):
            return d
    now = dt.datetime.now()
    item_id = f"{now:%Y%m%d-%H%M%S}_{hid}"
    p = os.path.join(ROOT, item_id)
    os.makedirs(p, exist_ok=True)
    names = []
    for n, data in (files or {}).items():
        n = _safe(n)
        with open(os.path.join(p, n), "wb") as f:
            f.write(data)
        names.append(n)
    if text is not None:
        with open(os.path.join(p, "text.md"), "w", encoding="utf-8") as f:
            f.write(text)
    title = re.sub(r"\s+", " ", title or KINDS.get(kind, kind)).strip()[:120]
    m = {"id": item_id, "kind": kind, "title": title, "created": now.isoformat(timespec="seconds"),
         "files": names, "has_text": text is not None, "meta": meta or {}}
    with open(os.path.join(p, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1, default=str)
    return item_id


def items(kind: str = None, query: str = "", limit: int = 200):
    if not os.path.isdir(ROOT):
        return []
    out = []
    q = (query or "").strip().lower()
    for d in sorted(os.listdir(ROOT), reverse=True):
        mp = os.path.join(ROOT, d, "meta.json")
        if not os.path.exists(mp):
            continue
        try:
            with open(mp, encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            continue
        if kind and m["kind"] != kind:
            continue
        if q:
            hay = m["title"].lower()
            if q not in hay and m.get("has_text"):
                hay += load_text(d)[:20000].lower()
            if q not in hay:
                continue
        out.append(m)
        if len(out) >= limit:
            break
    return out


def _inside(item_id: str, name: str = "") -> str:
    """보관함 폴더 밖('..' 등)을 가리키는 경로는 거부."""
    base = os.path.abspath(ROOT)
    p = os.path.abspath(os.path.join(base, os.path.basename(str(item_id)), os.path.basename(str(name)) if name else ""))
    if not (p == base or p.startswith(base + os.sep)):
        raise ValueError("허용되지 않는 보관함 경로입니다.")
    return p


def load_text(item_id: str) -> str:
    p = os.path.join(_inside(item_id), "text.md")
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8") as f:
        return f.read()


def file_path(item_id: str, name: str) -> str:
    return _inside(item_id, name)


def read_file(item_id: str, name: str) -> bytes:
    with open(file_path(item_id, name), "rb") as f:
        return f.read()


def delete(item_id: str):
    p = os.path.join(ROOT, item_id)
    if os.path.isdir(p) and os.path.dirname(os.path.abspath(p)) == os.path.abspath(ROOT):
        shutil.rmtree(p, ignore_errors=True)


def stats():
    its = items(limit=100000)
    size = 0
    for dp, _, fs in os.walk(ROOT):
        size += sum(os.path.getsize(os.path.join(dp, f)) for f in fs)
    return len(its), size
