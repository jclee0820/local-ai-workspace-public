"""로컬 문서 RAG: 파서(PDF/DOCX/TXT/MD/HWPX) + ChromaDB(CPU 임베딩)."""
import hashlib
import io
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.environ.get("LAI_DB_DIR") or os.path.join(BASE, "chroma_db")
CACHE_DIR = os.environ.get("LAI_CACHE_DIR") or os.path.join(BASE, "outputs", ".cache")


def _disk_cache(kind: str, data: bytes, fn, keep: int = 400):
    """같은 파일을 다시 읽을 때 변환 결과를 재사용 (PDF 표 인식·한컴 변환은 수 초~수십 초 걸림).
    열쇠는 파일 내용 해시라서 이름이 바뀌어도 맞고, 내용이 바뀌면 새로 읽음."""
    d = os.path.join(CACHE_DIR, "parse")
    p = os.path.join(d, f"{hashlib.sha1(data).hexdigest()}.{kind}.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            v = json.load(f)
        os.utime(p, None)
        return v
    except Exception:
        pass
    v = fn()
    try:
        os.makedirs(d, exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(v, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
        names = os.listdir(d)
        if len(names) > keep:                                   # 오래 안 쓴 것부터 정리
            full = sorted((os.path.join(d, n) for n in names), key=os.path.getmtime)
            for old in full[: len(names) - keep]:
                os.remove(old)
    except Exception:
        pass
    return v
COLLECTION = "knowledge"
EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


# ---------------------------------------------------------------- 파서
def _local(tag: str) -> str:
    return tag.split("}")[-1]


def parse_hwpx(data: bytes) -> str:
    """HWPX(ZIP) → Contents/section*.xml 에서 <hp:t> 텍스트와 표를 순서대로 추출."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted((n for n in z.namelist()
                        if re.match(r"Contents/section\d+\.xml$", n)),
                       key=lambda s: int(re.findall(r"\d+", s)[-1]))
        for n in names:
            root = ET.fromstring(z.read(n))
            _walk_hwpx(root, out)
    return "\n".join(l for l in out if l.strip())


def _para_text(p) -> str:
    parts = []
    for el in p.iter():
        if _local(el.tag) == "t" and el.text:
            parts.append(el.text)
        elif _local(el.tag) == "t":
            parts.append("".join(el.itertext()))
    return "".join(parts)


def _walk_hwpx(node, out):
    for child in node:
        ln = _local(child.tag)
        if ln == "tbl":
            rows = []
            for tr in child:
                if _local(tr.tag) != "tr":
                    continue
                cells = []
                for tc in tr:
                    if _local(tc.tag) != "tc":
                        continue
                    cells.append(" ".join(_para_text(p) for p in tc.iter() if _local(p.tag) == "p").strip())
                rows.append("| " + " | ".join(cells) + " |")
            out.extend(rows)
        elif ln == "p":
            # 문단 안의 표를 먼저 처리하고 일반 텍스트는 표 바깥 run 만 취합
            has_tbl = any(_local(e.tag) == "tbl" for e in child.iter())
            if has_tbl:
                for run in child:
                    _walk_hwpx(run, out)
            else:
                out.append(_para_text(child))
        else:
            _walk_hwpx(child, out)


def pdf_pages(data: bytes):
    """PDF → [(쪽 번호, 텍스트)] (변환 결과는 디스크에 보관해 재사용)."""
    return [(int(n), t) for n, t in _disk_cache("pdf2", data, lambda: _pdf_pages_raw(data))]


def _pdf_pages_raw(data: bytes):
    """표는 '| a | b |' 행으로 따로 뽑아 칸 정렬을 지킴
    (그냥 글자만 뽑으면 일정표의 ● 가 몇 월 칸인지 알 수 없게 섞임)."""
    import pymupdf as fitz
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
    doc = fitz.open(stream=data, filetype="pdf")
    wm = re.compile(r"Downloaded from .{0,60} by |This document is licensed", re.I)   # 다운로드 워터마크 제거
    out = []
    for i, page in enumerate(doc):
        tables, boxes = [], []
        try:
            for t in page.find_tables().tables:
                rows = t.extract()
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    boxes.append(fitz.Rect(t.bbox))
                    tables.append((t.bbox[1], "\n".join(
                        "| " + " | ".join(re.sub(r"\s+", " ", c or "").strip() for c in r) + " |" for r in rows)))
        except Exception:
            tables, boxes = [], []
        parts = []
        for b in page.get_text("blocks"):
            r = fitz.Rect(b[:4])
            if b[6] != 0 or any(r.intersects(bx) and (r & bx).get_area() > 0.5 * r.get_area() for bx in boxes):
                continue
            txt = "\n".join(l for l in b[4].splitlines() if not wm.search(l))
            if txt.strip():
                parts.append((b[1], txt))
        parts += tables
        out.append((i + 1, "\n".join(t for _, t in sorted(parts, key=lambda x: x[0]))))
    return out


def parse_pdf(data: bytes) -> str:
    return "\n".join(t for _, t in pdf_pages(data))


def parse_docx(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    out = []
    body = d.element.body
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for el in body.iterchildren():
        if el.tag.endswith("}p"):
            out.append(Paragraph(el, d).text)
        elif el.tag.endswith("}tbl"):
            t = Table(el, d)
            for row in t.rows:
                out.append("| " + " | ".join(c.text.strip() for c in row.cells) + " |")
    return "\n".join(out)


def parse_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def parse_hwp(data: bytes) -> str:
    """구형 .hwp → 설치된 한컴오피스로 HWPX 로 바꿔 읽음 (한컴오피스가 없으면 안내 오류)."""
    import shutil
    import tempfile
    if os.name != "nt":                                  # 리눅스: 한컴오피스가 없으므로 pyhwp(hwp5txt, 선택 설치) 사용
        exe = shutil.which("hwp5txt") or os.path.join(os.path.dirname(os.sys.executable), "hwp5txt")
        if not os.path.exists(exe):
            raise ValueError(".hwp 를 읽으려면 서버에 HWP 변환 도구(설치 옵션 --with-hwp)가 필요합니다. "
                             "한글에서 HWPX 또는 PDF로 저장해 올려주세요.")
        import subprocess
        tmp = tempfile.mkdtemp(prefix="lai_hwp_")
        try:
            src = os.path.join(tmp, "in.hwp")
            with open(src, "wb") as f:
                f.write(data)
            r = subprocess.run([exe, src], capture_output=True, timeout=120)
            if r.returncode != 0 or not r.stdout.strip():
                raise ValueError(".hwp 변환 실패. 한글에서 HWPX 또는 PDF로 저장해 올려주세요.")
            return r.stdout.decode("utf-8", "ignore")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    import hwp_convert
    tmp = tempfile.mkdtemp(prefix="lai_hwp_")       # 시스템 TEMP: 한컴 보안 확인창 없이 열리는 위치
    src, dst = os.path.join(tmp, "in.hwp"), os.path.join(tmp, "out.hwpx")
    try:
        with open(src, "wb") as f:
            f.write(data)
        if not hwp_convert.convert_safe(src, dst):
            raise ValueError(".hwp 를 읽지 못했습니다(한컴오피스 필요). 한글에서 HWPX 또는 PDF로 저장해 올려주세요.")
        with open(dst, "rb") as f:
            return parse_hwpx(f.read())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


DOC_TYPES = ["pdf", "hwp", "hwpx", "docx", "pptx", "xlsx", "xlsm", "csv", "tsv", "html", "htm", "rtf", "txt", "md"]


def _md_table(rows, limit=200):
    rows = [[re.sub(r"\s+", " ", str(c if c is not None else "")).strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)][:limit]
    if not rows:
        return ""
    w = max(len(r) for r in rows)
    rows = [r + [""] * (w - len(r)) for r in rows]
    return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + "---|" * w] + ["| " + " | ".join(r) + " |" for r in rows[1:]])


def parse_pptx(data: bytes) -> str:
    """슬라이드마다 제목·본문·표·발표자 노트를 '[슬라이드 N]' 단위로."""
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    out = []
    for i, s in enumerate(prs.slides, 1):
        parts = []
        for sh in s.shapes:
            if getattr(sh, "has_table", False) and sh.has_table:
                parts.append(_md_table([[c.text for c in r.cells] for r in sh.table.rows]))
            elif getattr(sh, "has_text_frame", False) and sh.has_text_frame and sh.text_frame.text.strip():
                parts.append(sh.text_frame.text.strip())
        if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
            parts.append("(노트) " + s.notes_slide.notes_text_frame.text.strip())
        if parts:
            out.append(f"[슬라이드 {i}]\n" + "\n".join(parts))
    return "\n\n".join(out)


def parse_xlsx(data: bytes) -> str:
    """시트마다 값(수식은 계산된 값)을 마크다운 표로. 시트당 최대 200행."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        t = _md_table(list(ws.iter_rows(values_only=True)))
        if t:
            out.append(f"## 시트: {ws.title}\n{t}")
    return "\n\n".join(out)


def parse_csv(data: bytes, sep=None) -> str:
    import csv
    text = parse_text(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",\t;|") if sep is None else None
        rows = list(csv.reader(io.StringIO(text), dialect) if dialect else csv.reader(io.StringIO(text), delimiter=sep))
    except Exception:
        rows = list(csv.reader(io.StringIO(text), delimiter=sep or ","))
    return _md_table(rows, limit=500)


def parse_html(data: bytes) -> str:
    raw = parse_text(data)
    try:
        import trafilatura
        t = trafilatura.extract(raw, include_tables=True, output_format="markdown") or ""
        if len(t) > 200:
            return t
    except Exception:
        pass
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "lxml")
    for x in soup(["script", "style", "nav", "footer"]):
        x.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()


def parse_rtf(data: bytes) -> str:
    """간단한 RTF 글자 추출(서식 명령 제거, \\'xx 코드페이지 글자와 \\uN 유니코드 처리)."""
    s = data.decode("latin-1")
    s = re.sub(r"\{\\(?:fonttbl|colortbl|stylesheet|info|\*)(?:[^{}]|\{[^{}]*\})*\}", "", s)   # 글꼴·색·스타일 표 등 본문 아닌 묶음 제거
    s = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), s)
    s = re.sub(r"(?:\\'([0-9a-fA-F]{2}))+",
               lambda m: bytes.fromhex(m.group(0).replace("\\'", "")).decode("cp949", "ignore"), s)
    s = re.sub(r"\\par[d]?\b", "\n", s)
    s = re.sub(r"\{\\\*[^{}]*\}|\\[a-zA-Z]+-?\d* ?|[{}]", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")


def extract_text(filename: str, data: bytes) -> str:
    """모든 형식 공통: 제어문자(글꼴 정보가 깨진 PDF 표지 등)를 지운 글을 돌려준다 — 워드·엑셀·한글 저장 오류 방지."""
    return _CTRL.sub("", _extract_text(filename, data))


def _extract_text(filename: str, data: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".hwp":
        return _disk_cache("hwp", data, lambda: parse_hwp(data))
    if ext == ".pdf":
        return parse_pdf(data)
    if ext == ".docx":
        return _disk_cache("docx", data, lambda: parse_docx(data))
    if ext == ".hwpx":
        return _disk_cache("hwpx", data, lambda: parse_hwpx(data))
    if ext == ".pptx":
        return _disk_cache("pptx", data, lambda: parse_pptx(data))
    if ext in (".xlsx", ".xlsm"):
        return _disk_cache("xlsx", data, lambda: parse_xlsx(data))
    if ext in (".csv", ".tsv"):
        return parse_csv(data, "\t" if ext == ".tsv" else None)
    if ext in (".html", ".htm"):
        return parse_html(data)
    if ext == ".rtf":
        return parse_rtf(data)
    if ext in (".txt", ".md"):
        return parse_text(data)
    if ext in (".doc", ".ppt", ".xls"):
        raise ValueError(f"예전 형식({ext})은 읽을 수 없습니다. 해당 프로그램에서 {ext}x 로 다시 저장해 올려주세요.")
    raise ValueError(f"지원하지 않는 형식: {ext}")


# ---------------------------------------------------------------- 청킹
def chunk_text(text: str, size: int = 800, overlap: int = 100):
    paras = [p for p in re.split(r"\n+", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 1 <= size:
            cur += p + "\n"
        else:
            if cur:
                chunks.append(cur.strip())
            while len(p) > size:
                chunks.append(p[:size])
                p = p[size - overlap:]
            cur = p + "\n"
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


# ---------------------------------------------------------------- 임베딩(CPU 전용)
class _HashEmbedding:
    """모델 다운로드 실패 시 쓰는 오프라인 대체 임베딩(문자 n-gram 해시)."""
    DIM = 384

    def __init__(self):
        pass

    def name(self):
        return "hash-ngram"

    def __call__(self, input):
        res = []
        for t in input:
            v = [0.0] * self.DIM
            t = re.sub(r"\s+", "", t)
            for n in (2, 3):
                for i in range(len(t) - n + 1):
                    h = int(hashlib.md5(t[i:i + n].encode("utf-8")).hexdigest(), 16)
                    v[h % self.DIM] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            res.append([x / norm for x in v])
        return res

    def embed_query(self, input):
        return self.__call__(input)


_client = None
_embedder_name = None


_EMB = None


def _get_embedder():
    """임베딩 모델은 한 번만 로드해 재사용 (화면 갱신마다 재로딩하면 느리고 메모리 누수)."""
    global _EMB
    if _EMB is None:
        _EMB = _load_embedder()
    return _EMB


def _load_embedder():
    global _embedder_name
    try:
        from chromadb.utils import embedding_functions
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL, device="cpu")
        _embedder_name = EMBED_MODEL
        return ef
    except Exception:
        _embedder_name = "hash-ngram(대체)"
        return _HashEmbedding()


def _col():
    global _client
    import chromadb
    if _client is None:
        os.makedirs(DB_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(path=DB_DIR)
    name = COLLECTION
    # 임베더가 바뀌면 컬렉션 충돌 방지를 위해 이름에 구분자 부여
    ef = _get_embedder()
    suffix = "" if _embedder_name == EMBED_MODEL else "_h"
    return _client.get_or_create_collection(name + suffix, embedding_function=ef,
                                            metadata={"hnsw:space": "cosine"})


def embedder_name():
    return _embedder_name


def load_pages(filename: str, data: bytes):
    """파일 → [(쪽 표시, 텍스트)]. PDF 는 실제 쪽 번호('p.3'), 그 밖의 형식은 쪽 개념이 없어 빈 문자열."""
    if filename.lower().endswith(".pdf"):
        return [(f"p.{n}", t) for n, t in pdf_pages(data) if t.strip()]
    return [("", extract_text(filename, data))]


def page_chunks(pages, size: int = 800):
    """줄 단위로 묶어 조각을 만듦. 표가 조각 경계에서 잘리면 다음 조각 맨 앞에 표 머리글 행을 다시 붙여
    '이 숫자가 어느 칸 값인지'가 조각마다 남게 함. 반환: [(쪽 표시, 텍스트)]"""
    out = []
    for pg, t in pages:
        lines = [re.sub(r"[ \t]+", " ", l).strip() for l in t.split("\n")]
        buf, n, head, prev_tbl = [], 0, None, False
        for l in (x for x in lines if x):
            while len(l) > size:                                # 줄바꿈 없는 긴 문단
                if buf:
                    out.append((pg, "\n".join(buf)))
                    buf, n = [], 0
                out.append((pg, l[:size]))
                l = l[size - 100:]
            is_tbl = l.startswith("|")
            if is_tbl and not prev_tbl:
                head = l
            prev_tbl = is_tbl
            if n + len(l) > size and buf:
                out.append((pg, "\n".join(buf)))
                tail = buf[-1:] if not is_tbl else []           # 문맥 잇기용 겹침
                buf = ([head] if is_tbl and head and l != head else []) + tail
                n = sum(len(x) for x in buf)
            buf.append(l)
            n += len(l)
        if buf:
            out.append((pg, "\n".join(buf)))
    return out


_STAMP = 0          # 지식보관함이 바뀔 때마다 증가 → 글자 검색 색인을 다시 맞춤
_LEX = {}
import threading as _threading
_LEX_LOCK = _threading.Lock()


def _touch():
    global _STAMP
    _STAMP += 1


def add_document(filename: str, data: bytes, source: str = None) -> int:
    """source: 지식보관함에 표시할 이름(폴더 연결 시 '폴더/하위/파일'). 같은 이름은 새 내용으로 교체."""
    source = source or filename
    chunks = page_chunks(load_pages(filename, data))
    delete_document(source)
    if not chunks:
        return 0
    col = _col()
    for a in range(0, len(chunks), 400):                         # 한 번에 너무 많이 넣으면 Chroma 한도 초과
        part = chunks[a:a + 400]
        col.add(ids=[hashlib.md5(f"{source}-{a + i}".encode()).hexdigest() for i in range(len(part))],
                documents=[t for _, t in part],
                metadatas=[{"source": source, "idx": a + i, "page": pg, "h": hashlib.md5(t.encode("utf-8")).hexdigest()[:10]}
                           for i, (pg, t) in enumerate(part)])
    _touch()
    return len(chunks)


def delete_document(filename: str):
    try:
        _col().delete(where={"source": filename})
        _touch()
    except Exception:
        pass


def list_documents():
    try:
        got = _col().get(include=["metadatas"])
        counts = {}
        for m in got["metadatas"]:
            counts[m["source"]] = counts.get(m["source"], 0) + 1
        return counts
    except Exception:
        return {}


def count() -> int:
    try:
        return _col().count()
    except Exception:
        return 0


def reset_db():
    global _client
    import chromadb
    c = _client or chromadb.PersistentClient(path=DB_DIR)
    for col in c.list_collections():
        name = col if isinstance(col, str) else col.name
        c.delete_collection(name)
    _touch()


# ---------------------------------------------------------------- 검색 (의미 + 글자 결합)
LEX_LIMIT = 80000      # 이보다 조각이 많으면 글자 색인을 만들지 않고 의미 검색만 사용 (메모리 보호)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def _lex_file():
    return os.path.join(DB_DIR, "lex_index.joblib")


def _lex_load():
    try:
        import joblib
        d = joblib.load(_lex_file())
        return d if isinstance(d, dict) and d.get("vec") is not None and d.get("mat") is not None else None
    except Exception:
        return None


def _lex_save(d):
    """색인을 디스크에 저장(앱을 다시 켜도 처음부터 다시 계산하지 않게). 검색을 막지 않도록 별도 스레드에서."""
    import threading

    def run(snap):
        try:
            import joblib
            tmp = _lex_file() + ".tmp"
            joblib.dump(snap, tmp)
            os.replace(tmp, _lex_file())
        except Exception:
            pass
    snap = {k: d[k] for k in ("keys", "ids", "docs", "metas", "vec", "mat", "fit_n", "drift")}
    threading.Thread(target=run, args=(snap,), daemon=True).start()


def _fit(docs):
    from sklearn.feature_extraction.text import TfidfVectorizer
    import warnings
    vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 3), sublinear_tf=True, preprocessor=_norm,
                          max_features=400000, dtype="float32")
    with warnings.catch_warnings():                                # float32 사용 경고(메모리 절약을 위해 일부러 씀) 숨김
        warnings.simplefilter("ignore", UserWarning)
        mat = vec.fit_transform(docs)
    return vec, mat


def _lex(col):
    """글자 n-그램 TF-IDF 색인. 임베딩이 놓치는 고유명사·문서번호·수치(예: J3295, 5.9GHz, 제12조)를 정확히 잡음.
    - 바뀐 조각만 반영: 조각마다 (id, 내용 해시)를 비교해 추가·삭제분만 행렬에 더하고 뺀다(전체 재계산은 변경이 30%를 넘을 때만).
    - 디스크 저장: 앱을 다시 켜도 저장된 색인을 불러와 바뀐 부분만 반영한다.
      (조각 1만 개 기준 전체 재계산 약 25초 → 증분·불러오기는 수 초 이내)"""
    with _LEX_LOCK:
        n = col.count()
        if _LEX.get("stamp") == _STAMP and _LEX.get("n") == n and (_LEX.get("mat") is not None or not 0 < n <= LEX_LIMIT):
            return _LEX
        if not 0 < n <= LEX_LIMIT:
            _LEX.clear()
            _LEX.update(stamp=_STAMP, n=n, mat=None)
            return _LEX
        meta = col.get(include=["metadatas"])
        cur_keys = [f"{i}:{(m or {}).get('h', '')}" for i, m in zip(meta["ids"], meta["metadatas"])]
        base = _LEX if _LEX.get("mat") is not None and _LEX.get("keys") else _lex_load()
        changed = True
        if base:
            pos = {k: r for r, k in enumerate(base["keys"])}
            cur_set = set(cur_keys)
            keep = [r for r, k in enumerate(base["keys"]) if k in cur_set]
            add_ix = [j for j, k in enumerate(cur_keys) if k not in pos]
            diff = (len(base["keys"]) - len(keep)) + len(add_ix)
            if diff == 0:
                d, changed = dict(base), base is not _LEX and False
            elif diff <= max(200, 0.3 * base.get("fit_n", len(base["keys"]))) and base.get("drift", 0) + diff <= 0.5 * base.get("fit_n", 1):
                from scipy.sparse import vstack
                d = {"vec": base["vec"], "fit_n": base.get("fit_n", len(base["keys"])), "drift": base.get("drift", 0) + diff,
                     "keys": [base["keys"][r] for r in keep], "ids": [base["ids"][r] for r in keep],
                     "docs": [base["docs"][r] for r in keep], "metas": [base["metas"][r] for r in keep], "mat": base["mat"][keep]}
                if add_ix:
                    add_ids = [meta["ids"][j] for j in add_ix]
                    got = {"ids": [], "documents": [], "metadatas": []}
                    for a in range(0, len(add_ids), 5000):
                        g = col.get(ids=add_ids[a:a + 5000], include=["documents", "metadatas"])
                        for kk in got:
                            got[kk] += g[kk]
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        d["mat"] = vstack([d["mat"], d["vec"].transform(got["documents"])]).tocsr()
                    d["keys"] += [f"{i}:{(m or {}).get('h', '')}" for i, m in zip(got["ids"], got["metadatas"])]
                    d["ids"] += got["ids"]
                    d["docs"] += got["documents"]
                    d["metas"] += got["metadatas"]
            else:
                base = None
        if not base:
            got = col.get(include=["documents", "metadatas"])
            vec, mat = _fit(got["documents"])
            d = {"vec": vec, "mat": mat, "fit_n": len(got["ids"]), "drift": 0, "ids": got["ids"], "docs": got["documents"],
                 "metas": got["metadatas"], "keys": [f"{i}:{(m or {}).get('h', '')}" for i, m in zip(got["ids"], got["metadatas"])]}
        if changed or not os.path.exists(_lex_file()):
            _lex_save(d)
        _LEX.clear()
        _LEX.update(d, stamp=_STAMP, n=n)
        return _LEX


def search_hits(query: str, k: int = 6, max_chars: int = 3500, pool: int = 30):
    """의미 검색(임베딩) 순위와 글자 검색 순위를 RRF 로 합침.
    반환: [{'source','page','text','dense'(코사인 유사도),'lex'(글자 유사도),'score'}] 점수 높은 순."""
    col = _col()
    n = col.count()
    if n == 0 or not query.strip():
        return []
    cand = {}
    res = col.query(query_texts=[query], n_results=min(pool, n))
    for r, (i, doc, meta, dist) in enumerate(zip(res["ids"][0], res["documents"][0], res["metadatas"][0],
                                                  res["distances"][0])):
        cand[i] = {"source": meta["source"], "page": meta.get("page", ""), "text": doc, "dense": 1 - dist, "lex": 0.0,
                   "score": 1 / (60 + r)}
    lx = _lex(col)
    if lx.get("mat") is not None:
        import numpy as np
        sims = (lx["mat"] @ lx["vec"].transform([query]).T).toarray().ravel()
        toks = re.findall(r"[A-Za-z]*\d[\w.\-]*|[A-Z]{2,}", query)      # 수치·영문 약어가 그대로 있으면 가산
        if toks:
            order = np.argsort(-sims)[: pool * 4]
            for j in order:
                sims[j] += 0.15 * sum(t in lx["docs"][j] for t in toks)
        for r, j in enumerate(np.argsort(-sims)[:pool]):
            if sims[j] <= 0.02:
                break
            i = lx["ids"][j]
            c = cand.setdefault(i, {"source": lx["metas"][j]["source"], "page": lx["metas"][j].get("page", ""),
                                    "text": lx["docs"][j], "dense": 0.0, "lex": 0.0, "score": 0.0})
            c["lex"] = float(sims[j])
            c["score"] += 1 / (60 + r)
    out, total = [], 0
    for c in sorted(cand.values(), key=lambda x: -x["score"]):
        if len(out) >= k:
            break
        if total + len(c["text"]) > max_chars:
            continue
        out.append(c)
        total += len(c["text"])
    return out


def coverage(query: str, text: str) -> float:
    """질문의 낱말 속 두 글자 묶음 가운데 조각에 실제로 나오는 비율 (0~1)."""
    t = _norm(text)
    grams = {w[i:i + 2] for w in re.findall(r"[가-힣a-z0-9]+", query.lower()) for i in range(len(w) - 1)}
    return sum(g in t for g in grams) / len(grams) if grams else 0.0


def is_relevant(query: str, hits) -> bool:
    """질문과 맞닿았을 가능성이 있는 조각이 있는지 보는 느슨한 1차 거름망 (전혀 무관하면 자료를 아예 안 붙여 속도 확보).
    최종 판단은 답변 단계에서 모델이 함: 관련 없으면 자료를 무시하고 번호를 달지 않도록 지시."""
    return any(coverage(query, h["text"]) >= 0.34 or h["dense"] >= 0.45 for h in hits[:3])


def _label(h) -> str:
    return h["source"] + (f" {h['page']}" if h.get("page") else "")


def search(query: str, k: int = 4, max_chars: int = 3500):
    """관련 조각 검색 → [(출처 표시, 텍스트)]"""
    return [(_label(h), h["text"]) for h in search_hits(query, k, max_chars)]


def format_context(results) -> str:
    return "\n\n".join(f"[내부문서: {s}]\n{t}" for s, t in results)
