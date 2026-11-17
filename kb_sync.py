"""지식보관함 폴더 연결: 지정한 폴더(내 문서, 공유 폴더, 구글 드라이브·원드라이브 동기화 폴더)를 훑어
새로 생기거나 바뀐 문서만 색인하고, 지워진 문서는 지식보관함에서도 뺀다.
- 파일을 복사하지 않고 그 자리에서 읽기만 함 (원본은 건드리지 않음)
- 구글 문서·시트(.gdoc 등)는 내용이 PC에 없는 바로가기라서 읽을 수 없음 → 건수만 알려줌"""
import json
import os
import threading
import time

import rag_engine

STATE_FILE = os.path.join(rag_engine.DB_DIR, "folders.json")
EXTS = {".pdf", ".hwpx", ".docx", ".txt", ".md"}
CLOUD_ONLY = {".gdoc", ".gsheet", ".gslides", ".gform", ".gdraw"}
MAX_BYTES = 80 * 2**20
AUTO_EVERY = 30 * 60          # 화면을 열었을 때 마지막 동기화가 이보다 오래됐으면 자동으로 다시 훑음

_LOCK = threading.Lock()
STATUS = {"running": False, "msg": "", "done": 0, "total": 0}


def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("folders", [])
    s.setdefault("files", {})
    s.setdefault("hwp", False)
    s.setdefault("last", 0)
    s.setdefault("report", {})
    return s


def save_state(s: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(STATE_FILE + ".tmp", STATE_FILE)


def suggest_folders():
    """자주 쓰는 위치 중 실제로 있는 폴더 [(표시 이름, 경로)]. 구글 드라이브는 '데스크톱용 Drive'가 만든 드라이브 문자를 찾음."""
    home = os.path.expanduser("~")
    out = []
    if os.name == "nt":
        import string
        for d in string.ascii_uppercase[3:]:                   # D: 이후
            for sub in ("내 드라이브", "My Drive", "공유 드라이브", "Shared drives"):
                p = f"{d}:\\{sub}"
                if os.path.isdir(p):
                    out.append((f"구글 드라이브 · {sub}", p))
    for label, p in (("구글 드라이브", os.path.join(home, "Google Drive")),
                     ("구글 드라이브", os.path.join(home, "내 드라이브")),
                     ("원드라이브", os.environ.get("OneDrive", "")),
                     ("문서", os.path.join(home, "Documents")),
                     ("바탕 화면", os.path.join(home, "Desktop")),
                     ("다운로드", os.path.join(home, "Downloads"))):
        if p and os.path.isdir(p) and all(p != q for _, q in out):
            out.append((label, p))
    return out


def add_folder(path: str) -> str:
    """오류 문구를 돌려줌 (성공이면 빈 문자열)."""
    path = os.path.normpath(os.path.expanduser(path.strip().strip('"')))
    if not os.path.isdir(path):
        return "폴더를 찾을 수 없습니다. 탐색기 주소창의 경로를 그대로 붙여 넣어 주세요."
    s = load_state()
    if any(os.path.normcase(path) == os.path.normcase(f) for f in s["folders"]):
        return "이미 연결된 폴더입니다."
    s["folders"].append(path)
    save_state(s)
    return ""


def remove_folder(path: str):
    """연결을 끊고 그 폴더에서 온 문서를 지식보관함에서 뺌 (원본 파일은 그대로)."""
    with _LOCK:
        s = load_state()
        s["folders"] = [f for f in s["folders"] if f != path]
        for src, info in list(s["files"].items()):
            if info.get("folder") == path:
                rag_engine.delete_document(src)
                del s["files"][src]
        save_state(s)


def _prefix(folder: str, folders) -> str:
    base = os.path.basename(folder.rstrip("\\/")) or folder.replace(":", "").strip("\\/")
    same = [f for f in folders if (os.path.basename(f.rstrip("\\/")) or f) == base]
    return base if len(same) <= 1 else f"{base}({folders.index(folder) + 1})"


def scan(s: dict):
    """반환: (색인할 것 [(경로, 표시이름, 폴더, mtime, size)], 사라진 표시이름들, 건너뛴 사유별 건수)"""
    exts = EXTS | ({".hwp"} if s.get("hwp") else set())
    todo, seen, skipped = [], set(), {}

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1

    for folder in s["folders"]:
        if not os.path.isdir(folder):
            skip("폴더에 접근할 수 없음")
            seen |= {src for src, i in s["files"].items() if i.get("folder") == folder}   # 잠시 끊긴 드라이브: 지우지 않음
            continue
        pre = _prefix(folder, s["folders"])
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith((".", "$", "~"))]
            for name in names:
                ext = os.path.splitext(name)[1].lower()
                if name.startswith(("~$", ".")):
                    continue
                if ext in CLOUD_ONLY:
                    skip("구글 문서 형식(PC에 내용 없음)")
                    continue
                if ext == ".hwp" and ext not in exts:
                    skip("구형 .hwp (옵션 꺼짐)")
                    continue
                if ext not in exts:
                    continue
                path = os.path.join(root, name)
                try:
                    stt = os.stat(path)
                except OSError:
                    skip("읽을 수 없음")
                    continue
                if stt.st_size > MAX_BYTES:
                    skip("80MB 초과")
                    continue
                if stt.st_size == 0:
                    continue
                src = pre + "/" + os.path.relpath(path, folder).replace("\\", "/")
                seen.add(src)
                old = s["files"].get(src)
                if old and old.get("mtime") == int(stt.st_mtime) and old.get("size") == stt.st_size:
                    continue
                todo.append((path, src, folder, int(stt.st_mtime), stt.st_size))
    gone = [src for src in s["files"] if src not in seen]
    return todo, gone, skipped


def sync(progress=None) -> dict:
    """바뀐 것만 색인. 반환: {'added','removed','failed':[(이름, 사유)],'skipped':{...},'chunks','secs'}"""
    say = progress or (lambda done, total, msg: None)
    with _LOCK:
        t0 = time.time()
        s = load_state()
        todo, gone, skipped = scan(s)
        rep = {"added": 0, "removed": 0, "failed": [], "skipped": skipped, "chunks": 0}
        for src in gone:
            rag_engine.delete_document(src)
            s["files"].pop(src, None)
            rep["removed"] += 1
        for i, (path, src, folder, mtime, size) in enumerate(todo):
            say(i, len(todo), src)
            try:
                with open(path, "rb") as f:
                    data = f.read()
                n = rag_engine.add_document(os.path.basename(path), data, source=src)
                rep["added"] += 1
                rep["chunks"] += n
            except Exception as e:
                n = 0
                rep["failed"].append((src, str(e)[:120]))
            s["files"][src] = {"folder": folder, "mtime": mtime, "size": size, "chunks": n}   # 실패도 기록: 매번 다시 시도하지 않음
            if i % 20 == 19:
                save_state(s)
        rep["secs"] = round(time.time() - t0, 1)
        s["last"] = time.time()
        s["report"] = {**rep, "failed": rep["failed"][:30]}
        save_state(s)
        say(len(todo), len(todo), "완료")
        return rep


def start_background() -> bool:
    """화면을 막지 않고 뒤에서 동기화. 이미 도는 중이면 False."""
    if STATUS["running"]:
        return False
    STATUS.update(running=True, msg="폴더를 훑는 중…", done=0, total=0)

    def run():
        try:
            sync(lambda d, t, m: STATUS.update(done=d, total=t, msg=m))
        except Exception as e:
            STATUS["msg"] = f"오류: {e}"
        finally:
            STATUS["running"] = False

    threading.Thread(target=run, daemon=True, name="kb-sync").start()
    return True


def auto_sync():
    """연결된 폴더가 있고 마지막 동기화가 오래됐으면 뒤에서 한 번 훑음."""
    s = load_state()
    if s["folders"] and time.time() - s.get("last", 0) > AUTO_EVERY:
        start_background()
