"""첨부 문서 질의응답 (쪽 번호 인용). 임베딩 모델 없이 글자 n-그램 TF-IDF로 빠르게 검색 → LLM이 근거 번호를 달아 답함.
- PDF는 실제 쪽 번호, HWP·HWPX·DOCX·TXT는 '구간' 번호(약 1,500자 단위)
- 답변의 [n] 표시를 (파일, 쪽) 출처로 바꿔 보여주고, 근거 없는 답은 '찾을 수 없음'으로 유도"""
import re

import rag_engine


def load(name: str, data: bytes):
    """파일 → [(쪽 표시, 텍스트)]"""
    if name.lower().endswith(".pdf"):
        return [(f"p.{n}", t) for n, t in rag_engine.pdf_pages(data) if t.strip()]
    text = rag_engine.extract_text(name, data)
    out, buf, n = [], [], 0
    for line in text.split("\n"):
        buf.append(line)
        if sum(len(x) for x in buf) >= 1500:
            n += 1
            out.append((f"구간 {n}", "\n".join(buf)))
            buf = []
    if buf:
        out.append((f"구간 {n + 1}", "\n".join(buf)))
    return out


class Index:
    def __init__(self):
        self.chunks = []          # (파일, 쪽, 텍스트)
        self.vec = self.mat = None

    def add(self, name, pages, size=800):
        """줄 단위로 묶어 조각을 만듦. 표가 조각 경계에서 잘리면 다음 조각 맨 앞에 표 머리글 행을 다시 붙임."""
        for pg, t in pages:
            lines = [re.sub(r"[ \t]+", " ", l).strip() for l in t.split("\n")]
            lines = [l for l in lines if l]
            buf, n, head, prev_tbl = [], 0, None, False
            for l in lines:
                is_tbl = l.startswith("|")
                if is_tbl and not prev_tbl:
                    head = l                                  # 표의 첫 행 = 머리글
                prev_tbl = is_tbl
                if n + len(l) > size and buf:
                    self.chunks.append((name, pg, "\n".join(buf)))
                    tail = buf[-2:] if not is_tbl else []     # 문맥 잇기용 겹침
                    buf = ([head] if is_tbl and head and l != head else []) + tail
                    n = sum(len(x) for x in buf)
                buf.append(l)
                n += len(l)
            if buf:
                self.chunks.append((name, pg, "\n".join(buf)))
        self._fit()

    def _fit(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        if not self.chunks:
            return
        # 띄어쓰기·줄바꿈을 지우고 글자 n-그램으로 색인 (PDF 칸 줄바꿈 '미래모빌 리티' 도 '미래모빌리티'로 찾힘)
        self.vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), sublinear_tf=True, min_df=1,
                                   preprocessor=lambda s: re.sub(r"\s+", "", s.lower()))
        self.mat = self.vec.fit_transform([c[2] for c in self.chunks])

    def search(self, q, k=6, max_chars=4800):
        if self.mat is None:
            return []
        import numpy as np
        sims = (self.mat @ self.vec.transform([q]).T).toarray().ravel()
        # 숫자·영문 약어(예: J3295, 5.9GHz)가 그대로 들어 있으면 가산
        for tok in re.findall(r"[A-Za-z]*\d[\w.\-]*|[A-Z]{2,}", q):
            for i, c in enumerate(self.chunks):
                if tok in c[2]:
                    sims[i] += 0.15
        out, n = [], 0
        for i in np.argsort(-sims)[: k * 2]:
            if sims[i] <= 0.02 or len(out) >= k:
                break
            c = self.chunks[i]
            if n + len(c[2]) > max_chars:
                continue
            out.append(c)
            n += len(c[2])
        return out

    def names(self):
        return sorted({c[0] for c in self.chunks})


SYS = """너는 업무 문서를 읽고 답하는 비서다. 반드시 [자료]에 있는 내용만으로 한국어로 답한다.
- 문장이나 항목 끝에 근거가 된 자료 번호를 [1], [2]처럼 단다. 여러 개면 [1][3].
- 자료에 답이 없으면 지어내지 말고 "첨부 문서에서 해당 내용을 찾지 못했습니다."라고 말한 뒤, 관련해 찾은 내용만 짧게 알려준다.
- 수치·고유명사·문서 번호는 자료 표기 그대로 옮긴다. 핵심을 먼저, 필요하면 개조식(- )으로 정리한다."""


def answer(question, index: Index, chat_fn, history=None, stream_callback=None):
    """반환: (답변 텍스트, 사용된 출처 [(번호, 파일, 쪽, 발췌)])"""
    hits = index.search(question)
    ctx = "\n\n".join(f"[{i}] ({c[0]} {c[1]})\n{c[2]}" for i, c in enumerate(hits, 1))
    msgs = [{"role": "system", "content": SYS}]
    for h in (history or [])[-4:]:
        msgs.append({"role": h["role"], "content": h["content"][:600]})
    msgs.append({"role": "user", "content": f"[자료]\n{ctx or '(관련 자료 없음)'}\n\n[질문] {question}"})
    out = chat_fn(msgs, {"temperature": 0.2}, stream_callback=stream_callback)
    used = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", out) if 0 < int(n) <= len(hits)})
    return out, [(n, hits[n - 1][0], hits[n - 1][1], hits[n - 1][2]) for n in used]


SYS_KB = """너는 공공기관 실무자를 돕는 정확한 한국어 업무 비서다. [자료]는 기관 지식보관함에서 찾은 문서 조각이다.
- [자료]가 질문과 관련 있으면 그 내용을 근거로 답하고, 문장이나 항목 끝에 근거 번호를 [1], [2]처럼 단다. 수치·고유명사는 자료 표기 그대로.
- [자료]가 질문과 관련 없으면 자료가 없는 것처럼 행동한다: 자료나 지식보관함을 언급하지 말고, 거절하지도 말고, 평소의 친절한 비서로서 네가 아는 범위에서 바로 답한다(일상 질문·일반 상식·글쓰기 도움 포함). 이때 번호는 달지 않는다.
- 자료에도 없고 확실히 알지도 못하는 사실은 지어내지 말고 모른다고 말한다."""


def answer_kb(question, hits, chat_fn, history=None, stream_callback=None):
    """지식보관함 조각으로 답변. hits: [(파일, 쪽, 텍스트)]. 반환: (답변, 인용된 출처 [(번호, 파일, 쪽, 발췌)])"""
    ctx = "\n\n".join(f"[{i}] ({c[0]} {c[1]})\n{c[2]}" for i, c in enumerate(hits, 1))
    msgs = [{"role": "system", "content": SYS_KB}]
    for h in (history or [])[-4:]:
        msgs.append({"role": h["role"], "content": h["content"][:600]})
    msgs.append({"role": "user", "content": f"[자료]\n{ctx}\n\n[질문] {question}"})
    out = chat_fn(msgs, {"temperature": 0.3}, stream_callback=stream_callback)
    used = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", out) if 0 < int(n) <= len(hits)})
    return out, [(n, hits[n - 1][0], hits[n - 1][1], hits[n - 1][2]) for n in used]
