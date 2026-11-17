"""로컬 AI 작업실 (Streamlit): 문서·보고서·슬라이드·웹페이지·다이어그램·이미지 생성."""
import os
import time

import psutil
import streamlit as st
import streamlit.components.v1 as components

import diagram_canvas as dc
import exporters
import llm_client
import map_reduce_summarizer as mrs
import rag_engine
import style_presets as sp
import template_injector as ti
import web_search
from md_parser import parse_slides

st.set_page_config(page_title="로컬 AI 작업실", page_icon="✳️", layout="wide", initial_sidebar_state="expanded")
fragment = getattr(st, "fragment", None)

SS = st.session_state
SS.setdefault("results", {})
SS.setdefault("sources", {})

# 서버 모드 접속 비밀번호 (환경변수 LAI_PASSWORD 가 설정된 경우에만, 설치 프로그램이 서비스에 설정)
_PW = os.environ.get("LAI_PASSWORD", "")
if _PW and not SS.get("_authed"):
    import hmac
    st.markdown("## ✳ 로컬 AI 작업실")
    _pw_in = st.text_input("접속 비밀번호", type="password", key="_pw_in")
    if _pw_in:
        if hmac.compare_digest(_pw_in.encode("utf-8"), _PW.encode("utf-8")):
            SS["_authed"] = True
            st.rerun()
        else:
            time.sleep(1.5)                                   # 무차별 대입 지연
            st.error("비밀번호가 맞지 않습니다.")
    st.stop()

# ------------------------------------------------------------------ 공통 도우미
def qwen(messages, options=None):
    return llm_client.chat(messages, options)


def build_context(query: str, label: str):
    """사이드바 토글에 따라 RAG + 웹 검색 컨텍스트 생성. (context, used_sources_flag)"""
    parts, web_used = [], False
    use_rag, use_web = SS.get("use_rag", False), SS.get("use_web", False)
    if use_web:
        with st.status("🌐 실시간 웹 검색 중...", expanded=False) as stt:
            res = web_search.search(query, "news" if SS.get("web_mode", "").startswith("최신") else "both",
                                    SS.get("web_n", 3))
            stt.update(label=f"🔍 실시간 웹 검색 출처 확인 — 키워드: {res['keywords']} · 엔진: {res['engine']} · {len(res['results'])}건",
                       state="complete", expanded=True)
            if res["results"]:
                for r in res["results"]:
                    st.markdown(f"- [{r['title']}]({r['url']}) — {r['source']}")
            else:
                st.warning("웹 검색 결과가 없습니다. " + res.get("error", ""))
            if res["context"]:
                parts.append("### 웹 검색 결과\n" + res["context"])
                web_used = True
    if use_rag:
        r = rag_engine.search(query, k=4, max_chars=2500 if use_web else 3500)
        if r:
            with st.expander("📚 참고한 내부 문서 조각", expanded=False):
                for s, t in r:
                    st.caption(f"[내부문서: {s}]")
                    st.text(t[:300] + ("…" if len(t) > 300 else ""))
            parts.append("### 내부 문서 발췌\n" + rag_engine.format_context(r))
        else:
            st.info("지식보관함에 관련 문서가 없습니다.")
    return "\n\n".join(parts)


def generate(instruction: str, query: str, extra_text: str = "", label="gen", preset_override=None) -> str:
    preset = preset_override or SS.get("preset", sp.DEFAULT_PRESET)
    ctx = build_context(query, label)
    sysmsg = sp.get_system_prompt(preset, with_sources=bool(ctx))
    user = instruction
    if extra_text:
        user += "\n\n### 대상 텍스트\n" + extra_text
    if ctx:
        user += "\n\n" + ctx
    ph = st.empty()
    out = llm_client.chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": user}],
                          sp.get_options(preset), stream_callback=lambda t: ph.markdown(t + " ▌"))
    ph.empty()
    out = exporters.strip_non_korean_cjk(out)
    return out if "서술형" in preset else exporters.to_gaejosik(out)


def tpl_path(kind):
    name = SS.get("sel_hwpx") if kind == "hwpx" else SS.get("sel_pptx_tab")
    if name and not name.startswith("("):
        p = os.path.join(ti.HWPX_DIR if kind == "hwpx" else ti.PPTX_DIR, name)
        return p if os.path.exists(p) else None
    return None


def make_file(fmt: str, text: str, images=None):
    if fmt == "hwpx":
        p = tpl_path("hwpx")
        return ti.inject_hwpx(p, text, images=images) if p else exporters.to_hwpx(text, images=images)
    return exporters.export(fmt, text, images=images)


def show_doc(md: str, images=None):
    """마크다운 미리보기. ![캡션](img:키) 줄은 실제 그림으로 표시."""
    import re as _re
    buf = []
    for line in md.split("\n"):
        m = _re.match(r"^!\[([^\]]*)\]\(img:([^)]+)\)\s*$", line.strip())
        if m and images and m.group(2) in images:
            if buf:
                st.markdown("\n".join(buf))
                buf = []
            st.image(images[m.group(2)], caption=m.group(1))
        else:
            buf.append(line)
    if buf:
        st.markdown("\n".join(buf))


def remember(kind, title, text=None, files=None, meta=None, key=None):
    """결과물을 작업 보관함에 자동 저장 (같은 결과는 한 번만). 실패해도 화면 작업은 계속."""
    import hashlib
    import history
    if key:
        sig = kind + ":" + hashlib.sha1(key.encode("utf-8")).hexdigest()
    else:
        h = hashlib.sha1((text or "").encode("utf-8"))
        for n in sorted(files or {}):
            h.update(n.encode("utf-8"))
            h.update(files[n])
        sig = kind + ":" + h.hexdigest()
    saved = SS.setdefault("_saved", {})
    if sig in saved:
        return saved[sig]
    try:
        saved[sig] = history.save(kind, title, text, files, meta, dedupe_key=key)
    except Exception as e:
        saved[sig] = None
        st.toast(f"작업 보관함 저장 실패: {e}")
    return saved[sig]


def show_numcheck(text: str, source: str, key: str):
    """결과물 속 숫자가 원문에 있는지 즉시 대조해 보여 줌 (AI 호출 없음)."""
    import fact_check
    if not (text and source and source.strip()):
        return
    res = fact_check.check(text, source)
    if not res["total"]:
        return
    label = fact_check.summary(res)
    if not res["missing"]:
        st.caption("✅ " + label)
        return
    with st.expander("🔎 " + label):
        st.caption("원문에서 같은 숫자를 찾지 못한 항목입니다. 합계·단위 환산이거나 AI가 잘못 쓴 값일 수 있으니 확인하세요.")
        for m_ in res["missing"][:40]:
            st.markdown(f"- **{m_['num']}** — {m_['line']}")


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_file(fmt, text, tpl, img_keys, _images):
    return make_file(fmt, text, _images)


def download_row(text: str, key: str, order=("md", "pdf", "docx", "hwpx"), stem="결과물", images=None):
    mime = {"md": "text/markdown", "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "hwpx": "application/octet-stream"}
    cols = st.columns(len(order))
    for c, fmt in zip(cols, order):
        try:
            data = _cached_file(fmt, text, tpl_path("hwpx"), tuple(sorted(images or {})), images)
            c.download_button(f"⬇ {fmt.upper()} 다운로드", data, f"{stem}.{fmt}", mime[fmt], key=f"{key}_{fmt}",
                              width="stretch")
        except Exception as e:
            c.error(f"{fmt.upper()} 변환 오류: {e}")


# ------------------------------------------------------------------ 디자인 (따뜻한 미니멀 스타일)
st.markdown("""
<style>
/* 본문 폭을 읽기 좋은 너비로 */
.block-container {max-width: 940px; padding-top: 2.6rem; padding-bottom: 4rem;}
/* 페이지 머리말 */
.pg-head h1 {font-family: 'Noto Serif KR', serif; font-weight: 600; font-size: 2.1rem; letter-spacing: -0.01em; margin: 0 0 .35rem 0;}
.pg-head p {opacity: .62; font-size: .98rem; margin: 0 0 1.6rem 0;}
.pg-mark {color: var(--primary-color, #C96442); margin-right: .45rem;}
/* 사이드바 브랜드 */
.brand {font-family: 'Noto Serif KR', serif; font-weight: 600; font-size: 1.22rem; padding: .2rem 0 .9rem .2rem;}
.brand span {color: #C96442; margin-right: .35rem;}
.side-label {font-size: .74rem; letter-spacing: .06em; opacity: .55; margin: 1.1rem 0 .3rem .25rem; text-transform: uppercase;}
/* 사이드바 메뉴: 라디오 원을 숨기고 목록형으로 */
section[data-testid="stSidebar"] div[role="radiogroup"] {gap: 2px;}
section[data-testid="stSidebar"] div[role="radiogroup"] label[data-testid="stRadioOption"] {
  display: flex; padding: .48rem .7rem; border-radius: .6rem; width: 100%; margin: 0; cursor: pointer; transition: background .15s;}
section[data-testid="stSidebar"] div[role="radiogroup"] label[data-testid="stRadioOption"] > div > div:first-child {display: none;}
section[data-testid="stSidebar"] div[role="radiogroup"] label[data-testid="stRadioOption"]:hover {background: rgba(127,112,90,.12);}
section[data-testid="stSidebar"] div[role="radiogroup"] label[data-selected="true"] {background: rgba(201,100,66,.16);}
section[data-testid="stSidebar"] div[role="radiogroup"] label[data-selected="true"] p {font-weight: 600;}
section[data-testid="stSidebar"] div[role="radiogroup"] p {font-size: .93rem;}
/* 버튼·입력 부드럽게 */
.stButton > button, .stDownloadButton > button {font-weight: 500;}
div[data-testid="stExpander"] details {border-radius: .75rem;}
/* 상태 카드 */
.status-chip {display:inline-block; font-size:.8rem; padding:.18rem .6rem; border-radius:999px; background: rgba(127,112,90,.12); margin:.1rem 0 .5rem 0;}
.status-chip.ok {background: rgba(76,140,90,.16);} .status-chip.warn {background: rgba(214,140,40,.18);} .status-chip.err {background: rgba(200,60,60,.16);}
/* 사이드바 상태 영역을 작게 */
section[data-testid="stSidebar"] [data-testid="stMetricValue"] {font-size: 1.3rem;}
section[data-testid="stSidebar"] [data-testid="stMetricLabel"] p {font-size: .78rem; opacity: .7;}
section[data-testid="stSidebar"] .stButton > button {font-size: .82rem; padding: .3rem .4rem;}
/* 본문 소제목(####)도 세리프 */
.block-container h4 {font-family: 'Noto Serif KR', serif; font-weight: 600;}
/* 이미지 갤러리 */
.gal-cap {font-size:.78rem; opacity:.6; margin-top:-.4rem;}
</style>""", unsafe_allow_html=True)


def page_header(title, desc, icon="✳"):
    st.markdown(f'<div class="pg-head"><h1><span class="pg-mark">{icon}</span>{title}</h1><p>{desc}</p></div>',
                unsafe_allow_html=True)


PAGES = {"chat": ":material/forum: AI 비서", "doc": ":material/description: 문서 요약·추출",
         "compare": ":material/difference: 문서 비교", "report": ":material/edit_note: 보고서·기안문",
         "slides": ":material/slideshow: 발표 슬라이드", "web": ":material/web: 웹페이지",
         "diagram": ":material/account_tree: 다이어그램", "mindmap": ":material/hub: 마인드맵", "gantt": ":material/view_timeline: WBS·간트 차트",
         "image": ":material/image: 이미지 생성", "history": ":material/inventory_2: 작업 보관함"}

# ------------------------------------------------------------------ 사이드바
with st.sidebar:
    st.markdown('<div class="brand"><span>✳</span>로컬 AI 작업실</div>', unsafe_allow_html=True)
    if not llm_client.is_alive():
        st.error("Ollama 서버가 꺼져 있습니다. 바탕화면 '로컬AI_작업실_실행.bat'로 다시 실행하세요.")
    PAGE = st.radio("메뉴", list(PAGES), format_func=lambda k: PAGES[k], key="page", label_visibility="collapsed")

    st.markdown('<div class="side-label">설정</div>', unsafe_allow_html=True)
    MODEL_LABELS = {"gemma4:26b": "Gemma 4 26B · 고성능 (약 20GB)",
                    "qwen3:14b": "Qwen3 14B · 가벼움 (약 10GB)",
                    "qwen2.5:14b": "Qwen2.5 14B · 가벼움 (약 10GB)"}
    with st.expander(":material/neurology: AI 모델", expanded=False):
        installed = [m for m in llm_client.list_models() if not m.startswith("all-minilm")] or [llm_client.MODEL]
        if llm_client.MODEL not in installed:
            installed.insert(0, llm_client.MODEL)
        chosen = st.selectbox("사용할 AI 모델", installed, index=installed.index(llm_client.MODEL),
                              format_func=lambda m: MODEL_LABELS.get(m, m), key="model_sel")
        if chosen != llm_client.MODEL:
            llm_client.set_model(chosen)
            st.toast(f"모델을 {chosen}(으)로 바꿨습니다. 이전 모델은 메모리에서 내렸습니다.")
        st.caption("메모리가 부족하면 '가벼움' 모델을 고르세요.")

    with st.expander(":material/format_quote: 문체 · 작성 규칙"):
        st.selectbox("문서 문체 프리셋", list(sp.PRESETS.keys()), key="preset")
        rules = st.text_area("기관 고유 용어·추가 지시사항", sp.load_custom_rules(), height=110, key="rules_box")
        if st.button("규칙 저장", key="save_rules"):
            sp.save_custom_rules(rules)
            st.success("저장됨")
        import icon_library
        ion = st.toggle("문서 소제목에 아이콘 넣기 (HWPX·DOCX·PDF)", value=icon_library.doc_icons_enabled(),
                        key="doc_icons", help="내용에 맞는 선형 아이콘을 소제목(##) 앞에 넣습니다. 공문 등 아이콘이 어울리지 않으면 끄세요.")
        if ion != icon_library.doc_icons_enabled():
            icon_library.set_doc_icons(ion)

    with st.expander(":material/library_books: 참고 자료 (지식보관함 · 웹)"):
        st.toggle("지식보관함 참고", key="use_rag")
        st.toggle("실시간 웹 검색 참고", key="use_web")
        if SS.get("use_web"):
            st.radio("검색 모드", ["일반 웹 + 뉴스 통합", "최신 뉴스 전용"], key="web_mode")
            st.slider("검색 결과 개수", 1, 5, 3, key="web_n")
        files = st.file_uploader("지식보관함에 문서 추가", type=["pdf", "hwp", "hwpx", "docx", "txt", "md"],
                                 accept_multiple_files=True, key="rag_up")
        if st.button("학습시키기", width="stretch", key="rag_learn") and files:
            bar = st.progress(0.0)
            for i, f in enumerate(files):
                try:
                    n = rag_engine.add_document(f.name, f.getvalue())
                    st.success(f"{f.name}: {n}개 조각")
                except Exception as e:
                    st.error(f"{f.name}: {e}")
                bar.progress((i + 1) / len(files))
        # ---- 폴더 연결: 내 문서·공유 폴더·구글 드라이브 동기화 폴더를 통째로 색인 (바뀐 파일만 다시 읽음)
        import kb_sync
        st.markdown("**폴더 연결**")
        kst = kb_sync.load_state()
        kb_sync.auto_sync()
        for fi, fpath in enumerate(kst["folders"]):
            fc1, fc2 = st.columns([5, 1])
            nfile = sum(1 for v in kst["files"].values() if v.get("folder") == fpath and v.get("chunks"))
            fc1.caption(f"📁 {fpath} · 문서 {nfile}개")
            if fc2.button("✕", key=f"kb_rm_{fi}", help="연결 끊기 (원본 파일은 그대로, 지식보관함에서만 빠짐)"):
                kb_sync.remove_folder(fpath)
                st.rerun()
        sug = [("직접 입력", "")] + [(f"{lab} — {pth}", pth) for lab, pth in kb_sync.suggest_folders() if pth not in kst["folders"]]
        pick = st.selectbox("추가할 폴더", sug, format_func=lambda x: x[0], key="kb_pick")
        typed = st.text_input("폴더 경로", key="kb_path", placeholder=r"예) D:\업무자료  (탐색기 주소창에서 복사)",
                              label_visibility="collapsed") if not pick[1] else ""
        kc1, kc2 = st.columns(2)
        if kc1.button("폴더 연결", key="kb_add", width="stretch") and (pick[1] or typed.strip()):
            err = kb_sync.add_folder(pick[1] or typed)
            if err:
                st.warning(err)
            else:
                kb_sync.start_background()
                st.rerun()
        if kc2.button("지금 동기화", key="kb_sync_now", width="stretch", disabled=not kst["folders"]):
            kb_sync.start_background()
            st.rerun()
        hwp_on = st.toggle("구형 .hwp 도 읽기 (한컴오피스 필요, 파일당 10초 이상)", value=kst.get("hwp", False), key="kb_hwp")
        if hwp_on != kst.get("hwp", False):
            kst["hwp"] = hwp_on
            kb_sync.save_state(kst)
        if kb_sync.STATUS["running"]:
            stt_ = kb_sync.STATUS
            st.info(f"동기화 중 {stt_['done']}/{stt_['total']} · {stt_['msg'][-40:]}")
            st.button("진행 상황 새로 고침", key="kb_refresh")
        elif kst.get("last"):
            rp = kst.get("report", {})
            msg_ = f"마지막 동기화 {time.strftime('%m-%d %H:%M', time.localtime(kst['last']))} · 추가·갱신 {rp.get('added', 0)} · 제거 {rp.get('removed', 0)}"
            if rp.get("skipped"):
                msg_ += " · 건너뜀: " + ", ".join(f"{k} {v}" for k, v in rp["skipped"].items())
            st.caption(msg_)
            if rp.get("failed"):
                with st.popover(f"읽지 못한 파일 {len(rp['failed'])}개"):
                    for nm, why in rp["failed"]:
                        st.caption(f"{nm} — {why}")
        st.toggle("AI 비서가 지식보관함을 자동으로 참고", value=True, key="kb_auto",
                  help="문서를 첨부하지 않고 질문하면 지식보관함에서 관련 내용을 찾아 출처와 함께 답합니다.")
        docs = rag_engine.list_documents()
        st.caption((f"저장된 문서 {len(docs)}개 · 조각 {sum(docs.values()):,}개"
                    + (" — " + " · ".join(list(docs)[:6]) + (" …" if len(docs) > 6 else ""))) if docs else "저장된 문서 없음")
        if docs and st.button("지식보관함 비우기", key="rag_reset"):
            rag_engine.reset_db()
            st.rerun()

    with st.expander(":material/folder_open: 업무 양식 (HWPX)"):
        up = st.file_uploader(".hwpx 양식 업로드", type=["hwpx"], accept_multiple_files=True, key="tpl_up_hwpx")
        for f in up or []:
            if not os.path.exists(os.path.join(ti.HWPX_DIR, f.name)):
                ti.save_template("hwpx", f.name, f.getvalue())
        st.selectbox("사용할 HWPX 양식", ["(기본 익스포터 사용)"] + ti.list_templates("hwpx"), key="sel_hwpx")
        p = tpl_path("hwpx")
        if p:
            st.caption(ti.hwpx_status(p))
        st.caption("양식 안에 {{제목}} {{일자}} {{본문}} 을 적어두면 해당 위치에 채워집니다. "
                   "슬라이드 템플릿은 '발표 슬라이드' 메뉴에서 올립니다.")

    monitor_box = st.container()

# 이미지 생성 페이지를 떠나면 ComfyUI 가 들고 있는 이미지 모델을 내려 LLM 메모리를 확보
if PAGE != "image" and SS.get("comfy_loaded"):
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "imagegen"))
        import comfy_backend as _icb
        _icb.free_comfy_memory()
    except Exception:
        pass
    SS["comfy_loaded"] = False

# ---- 탭 1
if PAGE == "doc":
    import figure_table_extractor as fx
    import re as _re
    page_header("문서 요약·추출", "문서를 올리고 원하는 작업을 적으세요. 요약, 요청 처리, 그림·표 추출을 알아서 판단합니다.")
    ups = st.file_uploader("대상 문서 (여러 개 가능)", type=["pdf", "hwp", "hwpx", "docx", "txt", "md"],
                           accept_multiple_files=True, key="sum_up")
    txt = st.text_area("요청사항 (문서를 올렸다면 원하는 작업을 적으세요) 또는 요약할 텍스트", height=130, key="sum_txt",
                       placeholder="예) 첨부 문서의 그림과 표를 추출해서 각각 설명을 정리해 HWPX로 만들어줘\n예) 성능 요구사항 위주로 요약해줘")
    TASKS = ["자동 판단", "요약 · 요청 처리", "그림·표 추출 정리"]
    c1, c2 = st.columns([2, 3])
    task_sel = c1.selectbox("작업 종류", TASKS, key="sum_task")
    desc_mode = c2.radio("그림·표 설명 수준", ["상세 설명(느림)", "국문 제목만(빠름)", "AI 없이 추출만"],
                         horizontal=True, key="fx_mode")

    def detect_task(instr: str) -> str:
        s = instr.lower()
        if _re.search(r"(그림|표|도표|도면|figure|table|fig\.)", s) and _re.search(r"(추출|뽑|정리|목록|모아|설명)", s):
            return TASKS[2]
        return TASKS[1]

    if st.button("실행", type="primary", key="sum_btn", icon=":material/play_arrow:"):
        texts, pdfs = [], []
        for f in ups or []:
            try:
                texts.append((f.name, rag_engine.extract_text(f.name, f.getvalue())))
                if f.name.lower().endswith(".pdf"):
                    pdfs.append((f.name, f.getvalue()))
            except Exception as e:
                st.error(f"{f.name} 읽기 실패: {e}")
        instr = txt.strip() if ups else ""            # 문서가 있으면 입력칸은 '요청사항'
        source = "\n\n".join(f"===== {n} =====\n{t}" for n, t in texts) if texts else txt
        task = detect_task(txt.strip()) if task_sel == TASKS[0] else task_sel
        SS.results["sum_images"] = None
        SS.results["sum_src"] = source if texts else ""
        SS.results["sum_order"] = ("hwpx", "docx", "pdf", "md") if "hwpx" in instr.lower() or "한글" in instr else ("md", "pdf", "docx", "hwpx")
        st.caption(f"🧭 판단된 작업: **{task}**" + (f" · 요청: {instr[:80]}" if instr else ""))
        if task == TASKS[2]:
            if not pdfs:
                st.warning("그림·표 추출은 PDF 문서에서만 지원됩니다. PDF를 올려 주세요.")
            else:
                all_items, names = [], []
                bar = st.progress(0.0)
                with st.status("🔍 그림·표 추출 중", expanded=True) as stt:
                    def prog(f, m):
                        bar.progress(min(f, 1.0))
                        stt.update(label=m)
                    for name, data in pdfs:
                        res = fx.extract(data, prog)
                        for it in res["items"]:
                            if len(pdfs) > 1:
                                it["id"] = f"{len(names)}_{it['id']}"
                        all_items += res["items"]
                        names.append(name.rsplit(".", 1)[0])
                    st.write(f"그림 {sum(i['kind'] == 'figure' for i in all_items)}개, "
                             f"표 {sum(i['kind'] == 'table' for i in all_items)}개를 찾았습니다.")
                    mode = {"상세 설명(느림)": "detail", "국문 제목만(빠름)": "title", "AI 없이 추출만": "none"}[desc_mode]
                    use_vision = llm_client.supports_vision() and mode == "detail"
                    if use_vision:
                        st.write("🖼️ 현재 모델이 그림을 직접 볼 수 있어, 그림 이미지를 함께 보고 설명합니다.")
                    fx.describe(all_items, llm_client.chat, ", ".join(names), mode, prog, vision=use_vision)
                    stt.update(label=f"✅ 완료: 그림·표 {len(all_items)}개", state="complete")
                md, images = fx.to_markdown(all_items, ", ".join(names), vision=use_vision)
                SS.results["sum"] = exporters.to_gaejosik(md)
                SS.results["sum_images"] = images
        elif not source.strip() and not (SS.get("use_rag") or SS.get("use_web")):
            st.warning("문서/텍스트를 입력하거나 RAG·웹 검색을 켜 주세요.")
        else:
            doc_name = ", ".join(n for n, _ in texts)
            if len(source) > mrs.CHUNK_LIMIT:
                st.info(f"문서가 {len(source):,}자로 길어 Map-Reduce 분할 처리를 사용합니다.")
                bar = st.progress(0.0)
                with st.status("🔄 [Map-Reduce 진행 중]", expanded=True) as stt:
                    def prog(f, m):
                        bar.progress(min(f, 1.0))
                        stt.update(label=m)
                    res = mrs.summarize(source, SS.get("preset", sp.DEFAULT_PRESET), progress=prog,
                                        extra_instruction=instr, doc_name=doc_name)
                    stt.update(label=f"✅ Map-Reduce 완료 ({res['chunks']}개 조각, {res['method']})", state="complete")
                SS.results["sum"] = res["result"]
            else:
                ask = (f"[사용자 요청] {instr}\n위 요청을 수행하라." if instr else
                       "다음 내용을 개조식과 비교 표 중심으로 요약하라.")
                if doc_name:
                    ask += f"\n[원문 문서명] {doc_name} — 문서 번호·표준명은 원문 표기 그대로, 추측 금지."
                SS.results["sum"] = generate(ask, instr or source[:300] or "요약", source, "sum")
    if SS.results.get("sum"):
        _imgs = SS.results.get("sum_images") or {}
        remember("doc", (SS.get("sum_txt") or "").strip()[:60] or ", ".join(f.name for f in (ups or [])) or "문서 요약",
                 SS.results["sum"], {f"img_{k}.png": v for k, v in _imgs.items()}, {"images": list(_imgs)})
        show_doc(SS.results["sum"], SS.results.get("sum_images"))
        show_numcheck(SS.results["sum"], SS.results.get("sum_src", ""), "sum")
        download_row(SS.results["sum"], "sum", order=SS.results.get("sum_order", ("md", "pdf", "docx", "hwpx")),
                     stem="결과물", images=SS.results.get("sum_images"))
    st.divider()
    st.markdown("#### 문서에 질문하기")
    q = st.text_input("질문", key="qa_q")
    if st.button("질문하기", key="qa_btn", icon=":material/chat:") and q:
        SS.results["qa"] = generate("다음 질문에 답하라: " + q, q, "", "qa")
    if SS.results.get("qa"):
        st.markdown(SS.results["qa"])

# ---- 탭 2
if PAGE == "report":
    page_header("보고서·기안문", "주제나 목차를 적으면 선택한 문체로 보고서 초안을 작성합니다.")
    topic = st.text_area("주제 또는 목차", height=140, key="rep_topic",
                         placeholder="예: 최근 자율주행 표준화 동향과 관련 법규 개정안 조사 보고서")
    if st.button("보고서 작성", type="primary", key="rep_btn", icon=":material/edit:") and topic.strip():
        SS.results["rep"] = generate("다음 주제로 체계적인 보고서를 작성하라 (제목, 추진 배경, 현황, 비교 표, 시사점, 향후 계획 포함):\n" + topic,
                                     topic, "", "rep")
    if SS.results.get("rep"):
        remember("report", (SS.get("rep_topic") or "보고서").strip()[:60], SS.results["rep"])
        st.markdown(SS.results["rep"])
        download_row(SS.results["rep"], "rep", order=("hwpx", "docx", "pdf", "md"), stem="보고서")

# ---- 탭 3
SLIDE_SCHEMA = """JSON만 출력하라(코드펜스 가능, 설명 금지). 형식:
{"title":"발표 제목","subtitle":"부제","slides":[{"title":"슬라이드 제목","icon":"영문 아이콘 키워드 1개","keypoint":"이 슬라이드의 핵심 한 문장","bullets":["대항목","  하위 항목","    세부 항목"],"table":[["구분","A","B"],["항목","값","값"]] 또는 null,"source":"출처(기관, 문서명) 또는 빈 문자열","notes":"발표자 노트"}]}
- 슬라이드당 bullets 3~6개, 표가 있는 슬라이드는 bullets 2~3개. 표가 필요 없으면 table은 null.
- bullets 는 들여쓰기 공백(0/2/4칸)으로 위계를 나타내고, 앞에 □ ㅇ - 같은 기호를 붙이지 말 것.
- keypoint 는 45자 이내 한 문장. source 는 확인된 출처만, 모르면 빈 문자열(지어내지 말 것).
- icon 은 슬라이드 내용을 나타내는 영어 단어 1개(예: car, shield-check, chart-bar, users, wallet, target, radio-tower)."""
import slide_themes as sthemes
SLIDE_THEMES = {**{k: v["label"] for k, v in sthemes.THEMES.items()},
                "custom": "내 템플릿 (PPTX·PDF 업로드)", "basic": "기본 비즈니스 테마"}
if PAGE == "slides":
    page_header("발표 슬라이드", "주제와 장수를 정하면 구성안을 만들고, 선택한 디자인 테마로 편집 가능한 PPTX를 만듭니다.")
    theme = st.selectbox("디자인 테마", list(SLIDE_THEMES), format_func=SLIDE_THEMES.get, key="slide_theme",
                         index=list(SLIDE_THEMES).index(sthemes.DEFAULT_THEME))
    if theme in sthemes.THEMES:
        st.caption(f"{sthemes.THEMES[theme]['desc']} · 디자인 시스템의 색·서체·레이아웃을 그대로 적용합니다.")
    if theme == "custom":
      with st.expander("🎨 내 슬라이드 템플릿 선택 / 업로드 (PPTX 또는 PDF)", expanded=True):
          tup = st.file_uploader("원하는 디자인의 템플릿을 올리세요 (.pptx 또는 .pdf)", type=["pptx", "pdf"],
                                 accept_multiple_files=True, key="tpl_up_slide")
          for f in tup or []:
              if not os.path.exists(os.path.join(ti.PPTX_DIR, f.name)):
                  ti.save_template("pptx", f.name, f.getvalue())
          st.selectbox("사용할 슬라이드 템플릿", ["(기본 비즈니스 테마)"] + ti.list_templates("pptx"), key="sel_pptx_tab")
          tp = tpl_path("pptx")
          if tp:
              st.caption(ti.pptx_status(tp))
              if tp.lower().endswith(".pdf"):
                  import pdf_template as pt
                  try:
                      import fitz
                      n_pages = pt.page_count(tp)
                      ac, ab, ae = pt.auto_pages(fitz.open(tp))
                      thumbs = pt.page_thumbnails(tp, 12)
                      cols = st.columns(4)
                      for i, img in enumerate(thumbs):
                          cols[i % 4].image(img, caption=f"{i + 1}쪽", width="stretch")
                      pc = st.columns(3)
                      nums = list(range(1, n_pages + 1))
                      cov = pc[0].selectbox("표지로 쓸 쪽", nums, index=ac, key=f"pdf_cover_{tp}")
                      con = pc[1].selectbox("본문으로 쓸 쪽", nums, index=ab, key=f"pdf_content_{tp}")
                      end_opts = ["없음"] + nums
                      endv = pc[2].selectbox("마무리(감사) 쪽", end_opts, index=0 if ae is None else ae + 1,
                                             key=f"pdf_end_{tp}")
                      clean = st.checkbox("본문 영역의 샘플 박스·카드 지우기 (권장 — 머리말/꼬리말·로고는 유지)", value=True,
                                          key=f"pdf_clean_{tp}")
                      SS["pdf_pages"] = {"cover": cov - 1, "content": con - 1, "clean_body": clean,
                                         "end": None if endv == "없음" else endv - 1}
                  except Exception as e:
                      st.warning(f"PDF 미리보기 실패: {e}")
                  st.caption("원본 글자는 지우고 배경·로고·도형·색상·제목 위치만 활용합니다. "
                             "본문 쪽은 글자를 넣을 공간이 넓은 페이지를 고르세요.")
              else:
                  st.caption("PPTX는 슬라이드 마스터·레이아웃·폰트 테마를 그대로 상속합니다.")
    c1, c2 = st.columns([3, 1])
    ptopic = c1.text_area("발표 주제", height=100, key="ppt_topic")
    n = c2.number_input("슬라이드 장수(표지 제외)", 3, 15, 6, key="ppt_n")
    if st.button("구성안 만들기", type="primary", key="ppt_btn", icon=":material/slideshow:") and ptopic.strip():
        style_rule = sthemes.THEMES.get(theme, {}).get("style", "")
        narrative = theme == "blue"                # 블루 테마는 존댓말 평서체 → 개조식 자동 교정 끔
        raw = generate(f"'{ptopic}' 주제로 본문 슬라이드 {int(n)}장 구성안을 작성하라.\n"
                       + (f"[문체] {style_rule}\n" if style_rule else "") + SLIDE_SCHEMA, ptopic, "", "ppt",
                       preset_override="④ 일반 비즈니스 서술형 (~입니다 체)" if narrative else None)
        SS.results["ppt_raw"] = raw
        SS.results["ppt"] = parse_slides(raw)
    d = SS.results.get("ppt")
    if d:
        if not d["slides"]:
            st.error("슬라이드 구조를 해석하지 못했습니다. 다시 생성해 주세요.")
            st.code(SS.results.get("ppt_raw", ""))
        else:
            st.markdown(f"### {d['title']}  \n{d['subtitle']}")
            for i, s in enumerate(d["slides"], 1):
                with st.expander(f"슬라이드 {i}. {s['title']}", expanded=i <= 2):
                    if s.get("keypoint"):
                        st.markdown(f"**KEY POINT** · {s['keypoint']}")
                    for lvl, t in s["bullets"]:
                        st.markdown("&nbsp;" * (lvl * 6) + ["□ ", "ㅇ ", "- "][lvl] + t)
                    if s["table"]:
                        hdr = "| " + " | ".join(s["table"][0]) + " |\n|" + "---|" * len(s["table"][0]) + "\n"
                        st.markdown(hdr + "\n".join("| " + " | ".join(r) + " |" for r in s["table"][1:]))
                    if s.get("source"):
                        st.caption("자료: " + s["source"])
                    if s["notes"]:
                        st.caption("🗒️ 발표자 노트: " + s["notes"])
            try:
                p = tpl_path("pptx") if theme == "custom" else None
                if theme in sthemes.THEMES:
                    data, label = sthemes.render(theme, d), f"{SLIDE_THEMES[theme].split(' (')[0]} 테마 PPTX 다운로드"
                elif p:
                    data, label = ti.build_slides(p, d, SS.get("pdf_pages")), "내 템플릿 적용 PPTX 다운로드"
                else:
                    data, label = exporters.to_pptx(d), "기본 비즈니스 테마 PPTX 다운로드"
                import json as _json
                remember("slides", d.get("title") or "발표 슬라이드", SS.results.get("ppt_raw"),
                         {"발표자료.pptx": data}, {"theme": theme},
                         key=theme + _json.dumps(d, ensure_ascii=False, sort_keys=True, default=str))
                st.download_button(label, data, "발표자료.pptx",
                                   "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                   key="ppt_dl", icon=":material/download:")
            except Exception as e:
                st.error(f"PPTX 변환 오류: {e}")

# ---- 탭 4
if PAGE == "web":
    import web_builder
    page_header("웹페이지", "위키백과 자료로 사실을 확인한 뒤, 주제에 어울리는 디자인으로 한 페이지를 만듭니다.")
    wdesc = st.text_area("만들고 싶은 웹페이지 설명", height=110, key="web_desc",
                         placeholder="예) 듄(영화) 시리즈의 세계관, 시리즈별 전개, 주요 등장인물을 보여주는 웹페이지를 듄의 분위기에 맞게 만들어줘")
    wmode = st.radio("제작 방식", ["📚 정보·소개 페이지 (위키백과 자료 조사 + 사실 검증, 권장)",
                                 "🎨 자유 디자인 (대시보드·랜딩 화면 등 — 사실 확인 없음)"], key="web_mode_sel")
    import design_trends as dt
    import product_builder
    tsel = st.selectbox("디자인 트렌드", dt.ORDER, format_func=dt.label, key="web_trend",
                        help="만든 뒤에 바꿔도 자료를 다시 조사하지 않고 디자인만 즉시 바뀝니다.")
    st.caption(f"🎨 {dt.TRENDS[tsel]['desc']}")
    st.caption("제품 종류·가격·사진을 묻는 요청은 자동으로 웹 검색 방식으로 바뀌어 제품별 가격·특징·사진을 찾아 정리합니다(5~10분). "
               "그 외 정보·소개 페이지: 위키백과(한국어·영어)에서 자료를 모으고, 자료에 근거가 있는 내용만 남깁니다. "
               "지식보관함(RAG) 토글이 켜져 있으면 내부 문서도 함께 씁니다. 3~5분 정도 걸립니다.")
    web_clicked = st.button("웹페이지 만들기", type="primary", key="web_btn", icon=":material/web:") and wdesc.strip()
    if web_clicked and wmode.startswith("📚"):
        bar = st.progress(0.0)
        with st.status("📚 자료 조사 중...", expanded=True) as stt:
            def wprog(f, m):
                bar.progress(min(f, 1.0))
                stt.update(label=m)
            extra = ""
            if SS.get("use_rag"):
                extra = rag_engine.format_context(rag_engine.search(wdesc, k=4, max_chars=2500))
            try:
                res = web_builder.build(wdesc, llm_client.chat, wprog, extra_context=extra, trend=tsel)
                res["trend"] = tsel
                SS.results["html"] = res["html"]
                SS.results["web_meta"] = res
                if isinstance(res["content"].get("products"), list):
                    stt.update(label=f"✅ 완료 — 제품 {len(res['content']['products'])}종 (가격 미확인 {res['removed']}종)", state="complete")
                else:
                    stt.update(label=f"✅ 완료 — 근거 없는 항목 {res['removed']}개 제외", state="complete")
            except Exception as e:
                stt.update(label=f"⚠️ 실패: {e}", state="error")
    _m = SS.results.get("web_meta")
    if _m and wmode.startswith("📚") and not web_clicked and _m.get("trend") != tsel:      # 디자인 트렌드만 바꾼 경우: 재조사 없이 다시 그리기
        try:
            if _m.get("topic"):
                SS.results["html"] = product_builder.render(_m["topic"], _m["content"]["products"], _m["sources"], tsel)
            else:
                SS.results["html"] = web_builder.render(_m["content"], _m["theme"], _m["sources"], tsel)
            _m["trend"] = tsel
        except Exception as e:
            st.warning(f"디자인 변경 실패: {e}")
    if SS.results.get("web_meta") and wmode.startswith("📚"):
        meta = SS.results["web_meta"]
        with st.expander(f"🔍 사용한 자료 출처 {len(meta['sources'])}건 · 근거 부족으로 제외된 항목 {meta['removed']}개"):
            for s in meta["sources"]:
                st.markdown(f"- [{s['title']}]({s['url']})")
            st.text_area("모델에 제공된 자료 원문", meta["context"], height=200, key="web_ctx_view")
    if web_clicked and wmode.startswith("🎨"):
        import re
        SS.results["web_meta"] = None
        ph = st.empty()
        _hint = "" if tsel == "auto" else f" 디자인은 '{dt.TRENDS[tsel]['name']}' 트렌드({dt.TRENDS[tsel]['desc']})를 충실히 따른다."
        out = llm_client.chat([
            {"role": "system", "content": _hint + "당신은 프론트엔드 개발자이다. Tailwind CSS CDN(<script src=\"https://cdn.tailwindcss.com\"></script>)을 사용한 "
             "단일 HTML 파일 하나만 ```html 코드블록으로 출력한다. 한국어 UI, 반응형, 외부 이미지 없이. 중국어 한자 금지. "
             "아이콘이 필요하면 SVG를 직접 그리지 말고 <i data-icon=\"영문키워드\" class=\"w-6 h-6\"></i> 형태로 쓴다 "
             "(예: car, users, chart-bar, shield-check, map-pin, calendar, wallet, target, settings, bell, search). "
             "로컬 아이콘 라이브러리가 실제 아이콘으로 바꿔 넣는다. 이모지는 쓰지 않는다."},
            {"role": "user", "content": wdesc}], {"temperature": 0.4, "num_ctx": 8192},
            stream_callback=lambda t: ph.code(t[-1500:], language="html"))
        ph.empty()
        m = re.search(r"```html\s*(.*?)```", out, re.S) or re.search(r"(<!DOCTYPE.*</html>)", out, re.S | re.I)
        import icon_library
        SS.results["html"] = icon_library.inline_icons(m.group(1).strip() if m else out)
    if SS.results.get("html"):
        import re as _re2
        _t = _re2.search(r"<title>(.*?)</title>", SS.results["html"], _re2.S)
        remember("web", (_t.group(1).strip() if _t else "") or (SS.get("web_desc") or "웹페이지")[:60],
                 None, {"page.html": SS.results["html"].encode("utf-8")})
        components.html(SS.results["html"], height=650, scrolling=True)
        st.download_button("⬇ HTML 파일 다운로드", SS.results["html"].encode("utf-8"), "page.html", "text/html", key="html_dl")
        with st.expander("HTML 코드 보기"):
            st.code(SS.results["html"], language="html")

# ---- 탭 5
if PAGE == "diagram":
    page_header("다이어그램", "설명을 적으면 도형으로 그려 주고, 마우스로 직접 옮기고 고칠 수 있습니다.")
    ddesc = st.text_area("시스템 구성도·순서도·시퀀스를 한국어로 설명하세요", height=110, key="dia_desc",
                         placeholder="예: 사용자가 웹에서 로그인하면 인증 서버가 확인하고, 성공 시 대시보드, 실패 시 오류 화면으로 이동")
    if st.button("다이어그램 그리기", type="primary", key="dia_btn", icon=":material/account_tree:") and ddesc.strip():
        with st.spinner("Qwen이 Draw.io 도형 구조를 생성 중..."):
            xml, msg = dc.generate_drawio(ddesc, qwen)
            SS.results["drawio"] = xml
            SS.results["drawio_msg"] = msg
            SS.results["mermaid"] = dc.generate_mermaid(ddesc, qwen)
    t1, t2 = st.tabs(["✏️ Draw.io 편집기 (마우스 편집)", "⚡ Mermaid 빠른 확인"])
    with t1:
        if SS.results.get("drawio"):
            ok, msg, nv, ne = dc.validate_mxgraph(SS.results["drawio"])
            st.caption(f"노드 {nv}개 / 연결선 {ne}개 · 박스 드래그=이동, 더블클릭=글자 수정 · 인터넷 연결 필요(embed.diagrams.net)")
            components.html(dc.drawio_embed_html(SS.results["drawio"], 750), height=770)
            st.download_button("⬇ .drawio 원본 저장(초안)", SS.results["drawio"].encode("utf-8"), "diagram.drawio",
                               "application/xml", key="dio_dl")
        elif SS.results.get("drawio_msg"):
            st.error("다이어그램 XML 생성 실패: " + SS.results["drawio_msg"])
        else:
            st.info("설명을 입력하고 '다이어그램 그리기'를 누르면 빈 캔버스 대신 자동 생성된 도형이 로드됩니다.")
            components.html(dc.drawio_embed_html('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>', 750), height=770)
    with t2:
        if SS.results.get("mermaid"):
            components.html(dc.mermaid_html(SS.results["mermaid"], 560), height=580, scrolling=True)
            with st.expander("Mermaid 코드"):
                st.code(SS.results["mermaid"])
        else:
            st.info("다이어그램을 생성하면 여기에 미리보기가 표시됩니다.")


# ---- WBS · 간트 차트
if PAGE == "gantt":
    import datetime as _dt
    import gantt_builder as gb
    page_header("WBS · 간트 차트", "연구개발계획서·제안서·과업지시서를 올리면 작업분류체계(WBS)와 일정을 뽑아 "
                "엑셀 간트 차트로 만듭니다. 화면에서 고친 뒤 내려받을 수 있습니다.")
    gups = st.file_uploader("계획서·제안서 (PDF, HWP, HWPX, DOCX, TXT · 여러 개 가능)",
                            type=["pdf", "hwp", "hwpx", "docx", "txt", "md"], accept_multiple_files=True, key="gantt_up")
    greq = st.text_area("추가 요청 (선택)", height=70, key="gantt_req",
                        placeholder="예) 2차년도 과업까지 3수준으로 나눠줘 / 보고·검수 일정을 마일스톤으로 넣어줘")
    g1, g2, g3 = st.columns(3)
    auto_start = g1.toggle("사업 시작일은 문서에서 찾기", value=True, key="gantt_auto_start")
    ustart = None if auto_start else g1.date_input("사업 시작일", _dt.date.today().replace(day=1), key="gantt_start")
    depth = g2.selectbox("분석 깊이", [1, 2, 3], index=1, key="gantt_depth",
                         format_func=lambda n: {1: "빠름 (1회, 약 2분)", 2: "표준 (2회, 약 4분)", 3: "정밀 (3회, 약 6분)"}[n])
    unit = g3.selectbox("간트 칸 단위", ["auto", "month", "week"], key="gantt_unit",
                        format_func=lambda u: {"auto": "자동 (6개월 이하는 주 단위)", "month": "월 단위", "week": "주 단위"}[u])
    if st.button("WBS·일정 추출", type="primary", key="gantt_btn", icon=":material/view_timeline:") and gups:
        texts = []
        for f in gups:
            try:
                with st.spinner(f"{f.name} 읽는 중…"):
                    texts.append(rag_engine.extract_text(f.name, f.getvalue()))
            except Exception as e:
                st.error(f"{f.name} 읽기 실패: {e}")
        if texts:
            doc = "\n\n".join(texts)
            bar = st.progress(0.0)
            with st.status("📅 문서에서 일정·과업을 찾는 중…", expanded=False) as stt:
                def gprog(fr, msg):
                    bar.progress(min(fr, 1.0))
                    stt.update(label=msg)
                try:
                    raw = gb.extract(doc, llm_client.cached(), depth=depth, request=greq.strip(), progress=gprog)
                    plan = gb.build(raw, doc, ustart)
                    SS.results["gantt"] = plan
                    SS.results["gantt_src"] = ", ".join(f.name for f in gups)
                    SS.results["gantt_ver"] = SS.results.get("gantt_ver", 0) + 1
                    import json as _json
                    _pj = _json.dumps(plan, ensure_ascii=False, default=str)
                    remember("gantt", plan["project"]["name"], None,
                             {"간트차트.xlsx": gb.to_excel(plan, unit, SS.results["gantt_src"]),
                              "plan.json": _pj.encode("utf-8")}, {"source": SS.results["gantt_src"]}, key=_pj)
                    n_tbl = len(raw.get("schedule") or [])
                    stt.update(label=f"✅ 작업 {len(plan['tasks'])}개 추출"
                                     + (f" · 일정표 {n_tbl}행에서 기간 직접 계산" if n_tbl else ""), state="complete")
                except Exception as e:
                    stt.update(label=f"⚠️ 실패: {e}", state="error")
    elif not gups:
        st.caption("문서를 올리고 [WBS·일정 추출]을 누르세요. 표에 ●·■ 로 표시된 추진일정표가 있으면 그 기간을 그대로 씁니다.")
    plan = SS.results.get("gantt")
    if plan:
        tasks = plan["tasks"]
        if not tasks:
            st.warning("문서에서 과업을 찾지 못했습니다. '추진 일정', '세부 추진내용' 같은 부분이 들어 있는지 확인하세요.")
        else:
            pj = plan["project"]
            chk = sum(1 for t in tasks if not t["verified"])
            est = sum(1 for t in tasks if t["basis"].startswith(("추정", "기간 없음")))
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("작업 수", len(tasks))
            m2.metric("사업 기간", f"{pj['start']:%Y.%m} ~ {pj['end']:%Y.%m}")
            m3.metric("기간 추정·없음", est)
            m4.metric("근거 확인 필요", chk)
            pname = st.text_input("사업(과제)명", pj["name"], key=f"gantt_name_{SS.results['gantt_ver']}")
            st.markdown("**WBS 표** — 칸을 눌러 바로 고칠 수 있습니다. 맨 아래 빈 줄에 작업을 추가하거나, 행을 골라 지울 수 있습니다.")
            edited = st.data_editor(
                gb.to_rows(plan), num_rows="dynamic", width="stretch", hide_index=True,
                key=f"gantt_ed_{SS.results['gantt_ver']}",
                column_config={
                    "WBS": st.column_config.TextColumn(width="small", help="1 / 1.1 / 1.1.1 형식 (점 개수 = 수준)"),
                    "작업명": st.column_config.TextColumn(width="large"),
                    "시작일": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "종료일": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "마일스톤": st.column_config.CheckboxColumn(width="small"),
                    "일정 근거": st.column_config.TextColumn(disabled=True),
                    "원문 확인": st.column_config.TextColumn(disabled=True),
                    "근거 구절": st.column_config.TextColumn(disabled=True)})
            rows = edited.to_dict("records") if hasattr(edited, "to_dict") else edited
            plan2 = gb.from_rows(rows, pname, pj)
            # 미리보기 간트
            import altair as alt
            import pandas as pd
            dated = [t for t in plan2["tasks"] if t["start"]]
            if dated:
                df = pd.DataFrame([{"작업": f"{t['wbs']}  {t['name']}", "시작": pd.Timestamp(t["start"]),
                                    "종료": pd.Timestamp(t["end"]) + pd.Timedelta(days=1), "수준": f"{min(t['level'], 3)}수준",
                                    "담당": t["owner"], "마일스톤": t["milestone"] or t["start"] == t["end"]} for t in dated])
                order = list(df["작업"])
                colors = alt.Scale(domain=["1수준", "2수준", "3수준"], range=["#1F3864", "#2E75B6", "#9DC3E6"])
                bars = alt.Chart(df[~df["마일스톤"]]).mark_bar(cornerRadius=3, height=14).encode(
                    x=alt.X("시작:T", title=None, axis=alt.Axis(format="%Y.%m", grid=True)), x2="종료:T",
                    y=alt.Y("작업:N", sort=order, title=None, axis=alt.Axis(labelLimit=320)),
                    color=alt.Color("수준:N", scale=colors, legend=alt.Legend(orient="top", title=None)),
                    tooltip=["작업", alt.Tooltip("시작:T", format="%Y-%m-%d"), alt.Tooltip("종료:T", format="%Y-%m-%d"), "담당"])
                ms = alt.Chart(df[df["마일스톤"]]).mark_point(shape="diamond", size=140, filled=True, color="#E46C0A").encode(
                    x="시작:T", y=alt.Y("작업:N", sort=order), tooltip=["작업", alt.Tooltip("시작:T", format="%Y-%m-%d")])
                today = alt.Chart(pd.DataFrame({"t": [pd.Timestamp(_dt.date.today())]})).mark_rule(
                    color="#C00000", strokeDash=[4, 3]).encode(x="t:T")
                st.altair_chart((bars + ms + today).properties(height=max(220, 24 * len(df))), width="stretch")
            undated = [t["name"] for t in plan2["tasks"] if not t["start"] and t["basis"] != "마일스톤 묶음"]
            if undated:
                st.caption("기간이 없어 차트에 안 나오는 작업: " + ", ".join(undated[:10]) + (" 외" if len(undated) > 10 else ""))
            xl = gb.to_excel(plan2, unit, SS.results.get("gantt_src", ""))
            import json as _json
            _pj = _json.dumps(plan2, ensure_ascii=False, default=str)
            st.download_button("엑셀 간트 차트 다운로드 (.xlsx)", xl, f"{pname[:40] or 'WBS'}_간트차트.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               type="primary", key="gantt_dl", icon=":material/download:",
                               on_click=remember, args=("gantt", pname, None,
                                                        {f"{pname[:40] or 'WBS'}_간트차트.xlsx": xl,
                                                         "plan.json": _pj.encode("utf-8")},
                                                        {"source": SS.results.get("gantt_src", "")}, "dl" + _pj))
            st.caption("엑셀에서 시작일·종료일·진척률을 고치면 막대가 자동으로 바뀝니다. "
                       "AI가 뽑은 초안이므로 '원문 근거' 시트와 빨간 글씨(추정) 항목은 원문과 대조하세요.")


# ---- AI 비서 (대화형 첫 화면)
def mm_context(query):
    """사이드바 '참고 자료' 토글(지식보관함·웹 검색)이 켜져 있으면 관련 자료를 모아 마인드맵 AI에 넘김.
    찾은 자료는 SS['mm_ref']에 쌓아 두고(근거 표시·자료 보기용) 문자열로 돌려줌."""
    if not (SS.get("use_rag") or SS.get("use_web")):
        return ""
    ctx = build_context(query[:300], "mm")
    if ctx:
        old = SS.get("mm_ref", "")
        if ctx not in old:
            SS["mm_ref"] = (old + "\n\n" + ctx).strip()[-12000:]
    return ctx


def _open_mindmap(text, doc="", src="", ref=""):
    """다른 화면(AI 비서·작업 보관함)에서 마인드맵 편집기로 넘기기 (단추 콜백)."""
    SS["page"] = "mindmap"
    SS["_mm_new_text"] = text
    SS["mm_doc"], SS["mm_src"], SS["mm_ref"] = doc, src, ref


def _goto_image(prompt):
    SS["page"] = "image"
    SS["img_req"] = prompt


def _render_artifacts(arts, mi):
    for j, a in enumerate(arts or []):
        k = f"c{mi}_{j}"
        if a["type"] == "doc":
            with st.container(border=True):
                with st.container(height=300):
                    show_doc(a["text"])
                show_numcheck(a["text"], a.get("src", ""), k)
                download_row(a["text"], k, order=("hwpx", "docx", "pdf", "md"), stem=a.get("stem", "결과물"))
        elif a["type"] == "file":
            st.download_button(a["label"], a["data"], a["name"], a["mime"], key=k, type="primary",
                               icon=":material/download:")
        elif a["type"] == "image":
            st.image(a["data"], width="stretch")
        elif a["type"] == "goto_mm":
            st.button("마인드맵 편집기에서 열기", key=k, icon=":material/hub:", on_click=_open_mindmap,
                      args=(a["text"], a.get("doc", ""), a.get("src", ""), a.get("ref", "")))
        elif a["type"] == "goto_image":
            st.button("이미지 생성 메뉴에서 그리기", key=k, icon=":material/brush:", on_click=_goto_image,
                      args=(a["prompt"],))
        elif a["type"] == "sources":
            with st.expander(f"근거 {len(a['items'])}건 보기"):
                for n, f, pg, snip in a["items"]:
                    st.markdown(f"**[{n}] {f} · {pg}**")
                    st.caption(snip[:400] + ("…" if len(snip) > 400 else ""))
        elif a["type"] == "save_answer":
            if st.button("📌 이 답변을 보관함에 저장", key=k):
                remember("answer", a["title"], a["text"])
                st.toast("작업 보관함에 저장했습니다.")


if PAGE == "chat":
    import assistant
    import doc_qa
    import gantt_builder as gb
    SS.setdefault("chat_msgs", [])
    SS.setdefault("chat_docs", {})          # 파일명 → 전체 텍스트
    page_header("AI 비서", "하고 싶은 일을 말로 적으세요. 문서를 첨부하면 쪽 번호를 달아 답하고, "
                "요약·보고서·발표자료·간트 차트도 대화 안에서 바로 만들어 드립니다.")
    if SS["chat_docs"] or SS["chat_msgs"]:
        b1, b2 = st.columns([4, 1])
        if SS["chat_docs"]:
            b1.markdown(" ".join(f'<span class="status-chip">📎 {n}</span>' for n in SS["chat_docs"]),
                        unsafe_allow_html=True)
        if b2.button("새 대화", icon=":material/add_comment:", key="chat_new", width="stretch"):
            for k in ("chat_msgs", "chat_docs", "chat_index"):
                SS.pop(k, None)
            st.rerun()
    if not SS["chat_msgs"]:
        st.markdown("""
<div style="opacity:.75;line-height:1.9">
이렇게 말해 보세요 (📎 단추로 문서 첨부)<br>
· <b>이 계획서로 간트 차트 만들고 발표자료도 8장으로 만들어줘</b><br>
· <b>첨부한 규격에서 통신 지연 요구사항이 뭐야?</b> — 쪽 번호와 함께 답합니다<br>
· <b>첨부 문서 핵심만 요약해줘</b> / <b>자율주행 표준화 동향 보고서 초안 써줘</b><br>
· <b>블루 테마로 발표 슬라이드 만들어줘</b> / <b>벚꽃 핀 경복궁 그림 그려줘</b><br>
· 문서 두 개를 첨부하고 <b>달라진 점 비교해줘</b> — 신구대조표를 만듭니다<br>
· 지식보관함에 폴더를 연결해 두면, 첨부 없이 물어도 <b>기관 문서에서 찾아 출처와 함께</b> 답합니다
</div>""", unsafe_allow_html=True)
    for mi, m in enumerate(SS["chat_msgs"]):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            _render_artifacts(m.get("arts"), mi)

    ci = st.chat_input("무엇을 도와드릴까요? (문서는 📎로 첨부)", accept_file="multiple",
                       file_type=["pdf", "hwp", "hwpx", "docx", "txt", "md"], key="chat_in")
    if ci:
        msg = (ci.text or "").strip() if hasattr(ci, "text") else str(ci)
        files = list(getattr(ci, "files", []) or [])
        new_names = []
        if files:
            idx = SS.get("chat_index") or doc_qa.Index()
            with st.spinner("첨부 문서를 읽는 중…"):
                for f in files:
                    if f.name in SS["chat_docs"]:
                        continue
                    try:
                        data = f.getvalue()
                        pages = doc_qa.load(f.name, data)
                        idx.add(f.name, pages)
                        SS["chat_docs"][f.name] = "\n".join(t for _, t in pages)
                        new_names.append(f.name)
                    except Exception as e:
                        st.error(f"{f.name} 읽기 실패: {e}")
            SS["chat_index"] = idx
        user_txt = msg + (("\n\n📎 " + ", ".join(new_names)) if new_names else "")
        if not msg and new_names:
            user_txt = "📎 " + ", ".join(new_names)
        SS["chat_msgs"].append({"role": "user", "content": user_txt})
        with st.chat_message("user"):
            st.markdown(user_txt)
        has_docs = bool(SS["chat_docs"])
        doc_all = "\n\n".join(f"===== {n} =====\n{t}" for n, t in SS["chat_docs"].items())
        doc_names = ", ".join(SS["chat_docs"])
        hist = [{"role": x["role"], "content": x["content"]} for x in SS["chat_msgs"][:-1] if x["role"] in ("user", "assistant")]
        steps = assistant.route(msg, has_docs, len(SS["chat_docs"])) if msg else []
        with st.chat_message("assistant"):
            parts, arts = [], []
            if not msg:
                parts.append(f"문서 {len(new_names)}개를 읽었습니다 ({sum(len(SS['chat_docs'][n]) for n in new_names):,}자). "
                             "궁금한 점을 물어보시거나 '요약해줘', '간트 차트 만들어줘', '발표자료 만들어줘'라고 말씀해 주세요.")
            if len(steps) > 1:
                st.caption("🧭 할 일: " + " → ".join(assistant.LABEL.get(a, a) for a, _ in steps))

            def doc_context(q, chars=5000):
                hits = SS["chat_index"].search(q, k=10, max_chars=chars) if has_docs else []
                return "\n\n".join(f"({f} {pg})\n{t}" for f, pg, t in hits)

            mm_tree = None
            for act, args in steps:
                try:
                    if act == "mindmap":
                        import mindmap as mm
                        import re as _re3
                        mm_ctx = build_context(msg, "chat_mm") if (SS.get("use_rag") or SS.get("use_web")) else ""
                        with st.status("🧠 마인드맵 만드는 중…") as stt:
                            if has_docs:
                                mm_tree = mm.from_document(doc_all, llm_client.chat, msg, doc_names, mm_ctx)
                            else:
                                topic = _re3.sub(r"마인드\s*맵|생각\s*지도|(으)?로|만들어\s*(줘|주세요)|그려\s*(줘|주세요)|"
                                                 r"정리해\s*(줘|주세요)|발표\s*자료도?|슬라이드도?|웹\s*페이지도?|PPT도?|와|과|하고",
                                                 " ", msg)
                                mm_tree = mm.brainstorm(_re3.sub(r"\s+", " ", topic).strip() or msg, llm_client.chat, mm_ctx)
                            stt.update(label=f"✅ 마인드맵 완료 (노드 {mm.count(mm_tree)}개)", state="complete")
                        outline = mm.to_outline(mm_tree)
                        png = mm.to_png(mm_tree)
                        remember("mindmap", mm_tree["t"], outline, {"마인드맵.png": png, "마인드맵.mm": mm.to_freemind(mm_tree)},
                                 {"source": doc_names})
                        gnd = mm.grounded(mm_tree, mm_ctx + "\n" + (doc_all if has_docs else "")) if (mm_ctx or has_docs) else set()
                        basis = (f" ({doc_names} 기준" + (", 지식보관함·웹 자료 함께 참고" if mm_ctx else "") + ")." if has_docs else
                                 (" (지식보관함·웹 자료를 참고한 초안입니다)." if mm_ctx else
                                  " (주제만으로 잡은 아이디어 초안입니다. 사실은 확인해 주세요)."))
                        parts.append(f"**{mm_tree['t']}** 마인드맵을 만들었습니다" + basis
                                     + (f" 노드 {mm.count(mm_tree) - 1}개 중 {len(gnd)}개가 자료에서 확인됩니다." if gnd else "")
                                     + " 편집기에서 가지를 고치거나 AI로 펼칠 수 있습니다.")
                        if mm_ctx and not has_docs and not gnd:
                            parts[-1] += " ⚠️ 참고 자료에서 이 주제와 맞는 내용을 찾지 못해 사실상 AI 아이디어 초안입니다."
                        arts += [{"type": "image", "data": png},
                                 {"type": "file", "label": "XMind·FreeMind 파일", "data": mm.to_freemind(mm_tree),
                                  "name": f"{mm_tree['t'][:30]}.mm", "mime": "application/x-freemind"},
                                 {"type": "goto_mm", "text": outline, "doc": doc_all if has_docs else "", "src": doc_names,
                                  "ref": mm_ctx}]
                    elif act in ("slides", "web") and mm_tree is not None:       # 방금 만든 마인드맵으로 발표자료·웹페이지
                        import mindmap as mm
                        with st.status("✍️ 마인드맵으로 " + ("발표자료" if act == "slides" else "웹페이지") + " 만드는 중…") as stt:
                            theme = args.get("theme", "modern")
                            try:
                                info = mm.enrich(mm_tree, llm_client.chat, doc_all if has_docs else "",
                                                 sthemes.THEMES[theme].get("style", "") if act == "slides" else "", mm_ctx)
                            except Exception:
                                info = None
                            if act == "slides":
                                data = sthemes.render(theme, mm.to_slides_data(mm_tree, info, True, doc_names))
                                fname = f"{mm_tree['t'][:40]}.pptx"
                                remember("slides", mm_tree["t"], None, {fname: data}, {"theme": theme, "from": "mindmap"})
                                arts.append({"type": "file", "label": "PPTX 다운로드", "data": data, "name": fname,
                                             "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation"})
                            else:
                                page = mm.to_web(mm_tree, info, doc_names)
                                fname = f"{mm_tree['t'][:40]}.html"
                                remember("web", mm_tree["t"], None, {"page.html": page.encode("utf-8")}, {"from": "mindmap"})
                                arts.append({"type": "file", "label": "웹페이지(HTML) 다운로드", "data": page.encode("utf-8"),
                                             "name": fname, "mime": "text/html"})
                            stt.update(label="✅ 완료", state="complete")
                        parts.append(("발표자료" if act == "slides" else "웹페이지") + "를 마인드맵 구조대로 만들었습니다"
                                     + (" (첫 장에 전체 마인드맵, 가지마다 한 장)." if act == "slides" else "."))
                    elif act == "answer":
                        ph = st.empty()
                        if has_docs:
                            out, used = doc_qa.answer(msg, SS["chat_index"], llm_client.chat, hist,
                                                      stream_callback=lambda t: ph.markdown(t + " ▌"))
                            ph.empty()
                            if used:
                                for n, f, pg, _ in used:
                                    out = out.replace(f"[{n}]", f"[{n}·{pg}]")
                                arts.append({"type": "sources", "items": used})
                            parts.append(out)
                        elif (SS.get("kb_auto", True) and not SS.get("use_web") and rag_engine.count()
                              and rag_engine.is_relevant(msg, _kb := rag_engine.search_hits(msg, k=6, max_chars=4200))):
                            out, used = doc_qa.answer_kb(msg, [(h["source"], h["page"] or "본문", h["text"]) for h in _kb],
                                                         llm_client.chat, hist, stream_callback=lambda t: ph.markdown(t + " ▌"))
                            ph.empty()
                            out = exporters.strip_non_korean_cjk(out)
                            if used:
                                for n, f, pg, _ in used:
                                    out = out.replace(f"[{n}]", f"[{n}·{os.path.basename(f)[:24]}{'' if pg == '본문' else ' ' + pg}]")
                                arts.append({"type": "sources", "items": used})
                            parts.append(out)
                        else:
                            ctx = build_context(msg, "chat")
                            sysm = ("너는 공공기관 실무자를 돕는 친절하고 정확한 한국어 업무 비서다. 모르는 사실은 지어내지 말고 "
                                    "모른다고 말한다. 이 작업실에서 할 수 있는 일(문서 요약, 보고서, 발표 슬라이드, 웹페이지, "
                                    "다이어그램, WBS·간트 차트, 이미지 생성)을 필요하면 안내한다.")
                            msgs = [{"role": "system", "content": sysm}] + [
                                {"role": h["role"], "content": h["content"][:800]} for h in hist[-6:]]
                            msgs.append({"role": "user", "content": msg + (("\n\n[참고 자료]\n" + ctx) if ctx else "")})
                            out = llm_client.chat(msgs, {"temperature": 0.4},
                                                  stream_callback=lambda t: ph.markdown(t + " ▌"))
                            ph.empty()
                            parts.append(exporters.strip_non_korean_cjk(out))
                        arts.append({"type": "save_answer", "title": msg[:60], "text": parts[-1]})
                    elif act == "compare":
                        import doc_compare as dcmp
                        (n_old, t_old), (n_new, t_new) = list(SS["chat_docs"].items())[-2:]
                        with st.status("🔍 두 문서를 대조하는 중…") as stt:
                            cres = dcmp.compare(t_old, t_new)
                            cst = cres["stats"]
                            stt.update(label="✍️ 주요 변경 사항 정리 중…")
                            csum = dcmp.summarize(cres, llm_client.chat, n_old, n_new) if cres["rows"] else ""
                            stt.update(label=f"✅ 대조 완료 (수정 {cst['수정']} · 신설 {cst['신설']} · 삭제 {cst['삭제']})", state="complete")
                        if not cres["rows"]:
                            parts.append(f"**{n_old}** 와 **{n_new}** 의 내용이 같습니다 (띄어쓰기 차이만 무시).")
                        else:
                            cdocx, cxlsx = dcmp.to_docx(cres, n_old, n_new, csum), dcmp.to_xlsx(cres, n_old, n_new)
                            remember("compare", f"{n_old} → {n_new}"[:60], csum + "\n\n" + dcmp.to_markdown(cres, n_old, n_new),
                                     {"신구대조표.docx": cdocx, "신구대조표.xlsx": cxlsx})
                            parts.append(f"먼저 첨부한 **{n_old}** 을(를) 현행, 나중에 첨부한 **{n_new}** 을(를) 개정안으로 보고 대조했습니다 "
                                         f"({cres['mode']} 단위). 수정 {cst['수정']}건, 신설 {cst['신설']}건, 삭제 {cst['삭제']}건입니다.\n\n" + csum)
                            arts += [{"type": "file", "label": "신구대조표 (워드)", "data": cdocx, "name": "신구대조표.docx",
                                      "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
                                     {"type": "file", "label": "신구대조표 (엑셀)", "data": cxlsx, "name": "신구대조표.xlsx",
                                      "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}]
                    elif act == "summary":
                        with st.status("📄 문서 요약 중…") as stt:
                            if len(doc_all) > mrs.CHUNK_LIMIT:
                                res = mrs.summarize(doc_all, SS.get("preset", sp.DEFAULT_PRESET),
                                                    progress=lambda f, m_: stt.update(label=m_),
                                                    extra_instruction=msg, doc_name=doc_names)
                                text = res["result"]
                            else:
                                text = generate(f"[사용자 요청] {msg}\n위 요청대로 문서를 요약하라. 원문 표기 그대로, 추측 금지.",
                                                msg, doc_all, "chat_sum")
                            stt.update(label="✅ 요약 완료", state="complete")
                        remember("doc", f"요약 · {doc_names}"[:60], text)
                        parts.append("문서를 요약했습니다.")
                        arts.append({"type": "doc", "text": text, "stem": "요약", "src": doc_all})
                    elif act == "report":
                        with st.status("📝 보고서 초안 작성 중…") as stt:
                            ctx = doc_context(msg)
                            text = generate("다음 요청에 맞춰 체계적인 보고서를 작성하라 (제목, 추진 배경, 현황, 비교 표, 시사점, "
                                            "향후 계획 포함). 첨부 문서 발췌가 있으면 그 내용을 근거로 쓰고 없는 사실은 만들지 말 것.\n"
                                            f"[요청] {msg}", msg, ctx, "chat_rep")
                            stt.update(label="✅ 보고서 초안 완료", state="complete")
                        remember("report", msg[:60], text)
                        parts.append("보고서 초안을 작성했습니다. 아래에서 형식을 골라 내려받으세요.")
                        arts.append({"type": "doc", "text": text, "stem": "보고서", "src": doc_all if has_docs else ""})
                    elif act == "slides":
                        theme = args["theme"]
                        with st.status(f"📊 발표 슬라이드 구성 중 ({sthemes.THEMES[theme]['label']})…") as stt:
                            style_rule = sthemes.THEMES[theme].get("style", "")
                            raw = generate(f"'{msg}' 요청에 맞는 본문 슬라이드 {args['n']}장 구성안을 작성하라. "
                                           "첨부 문서 발췌가 있으면 그 내용을 근거로 하라.\n"
                                           + (f"[문체] {style_rule}\n" if style_rule else "") + SLIDE_SCHEMA,
                                           msg, doc_context(msg, 4500), "chat_ppt",
                                           preset_override="④ 일반 비즈니스 서술형 (~입니다 체)" if theme == "blue" else None)
                            d = parse_slides(raw)
                            if not d["slides"]:
                                raise ValueError("슬라이드 구조를 해석하지 못했습니다. 다시 요청해 주세요.")
                            data = sthemes.render(theme, d)
                            stt.update(label=f"✅ 슬라이드 {len(d['slides'])}장 완료", state="complete")
                        fname = f"{(d.get('title') or '발표자료')[:40]}.pptx"
                        remember("slides", d.get("title") or msg[:60], raw, {fname: data}, {"theme": theme})
                        outline = "\n".join(f"{i}. {s['title']}" for i, s in enumerate(d["slides"], 1))
                        parts.append(f"**{d.get('title', '')}** 발표자료를 만들었습니다 "
                                     f"({sthemes.THEMES[theme]['label']}, 표지·마무리 포함).\n\n{outline}")
                        arts.append({"type": "file", "label": "PPTX 다운로드", "data": data, "name": fname,
                                     "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation"})
                    elif act == "gantt":
                        bar = st.progress(0.0)
                        with st.status("📅 WBS·일정 추출 중…") as stt:
                            raw = gb.extract(doc_all, llm_client.cached(), depth=2, request=msg,
                                             progress=lambda f, m_: (bar.progress(min(f, 1.0)), stt.update(label=m_)))
                            plan = gb.build(raw, doc_all)
                            xl = gb.to_excel(plan, args["unit"], doc_names)
                            stt.update(label=f"✅ 작업 {len(plan['tasks'])}개", state="complete")
                        bar.empty()
                        import json as _json
                        fname = f"{plan['project']['name'][:40]}_간트차트.xlsx"
                        remember("gantt", plan["project"]["name"], None,
                                 {fname: xl, "plan.json": _json.dumps(plan, ensure_ascii=False, default=str).encode("utf-8")},
                                 {"source": doc_names})
                        pj = plan["project"]
                        est = sum(1 for t in plan["tasks"] if t["basis"].startswith(("추정", "기간 없음")))
                        top = "\n".join(f"- {t['wbs']} {t['name']} ({t['start']:%Y.%m}~{t['end']:%Y.%m})"
                                        for t in plan["tasks"] if t["level"] == 1 and t["start"])
                        parts.append(f"**{pj['name']}** WBS·간트 차트를 만들었습니다. 작업 {len(plan['tasks'])}개, "
                                     f"기간 {pj['start']:%Y.%m}~{pj['end']:%Y.%m}"
                                     + (f", 기간 추정 {est}개(엑셀에 빨간 글씨)" if est else "") + ".\n\n" + top
                                     + "\n\n세부 수정은 'WBS·간트 차트' 메뉴나 엑셀에서 하실 수 있습니다.")
                        arts.append({"type": "file", "label": "엑셀 간트 차트 다운로드", "data": xl, "name": fname,
                                     "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
                    elif act == "need_doc_gantt":
                        parts.append("간트 차트를 만들려면 연구개발계획서·제안서 같은 문서가 필요합니다. "
                                     "📎 단추로 문서를 첨부하고 다시 말씀해 주세요.")
                    elif act == "image":
                        parts.append("이미지는 그리는 동안 언어 모델을 잠시 내려야 해서 '이미지 생성' 메뉴에서 그립니다. "
                                     "아래 단추를 누르면 요청 내용을 그대로 옮겨 드립니다.")
                        arts.append({"type": "goto_image", "prompt": msg})
                    elif act == "web":
                        parts.append("웹페이지는 자료 조사와 사실 확인을 거쳐 3~5분 걸려 '웹페이지' 메뉴에서 만듭니다. "
                                     "왼쪽 메뉴의 '웹페이지'에 같은 요청을 적어 주세요.")
                except Exception as e:
                    parts.append(f"⚠️ {assistant.LABEL.get(act, act)} 중 오류: {e}")
            reply = "\n\n".join(parts)
            st.markdown(reply)
            n_msg = len(SS["chat_msgs"])
            _render_artifacts(arts, n_msg)
        SS["chat_msgs"].append({"role": "assistant", "content": reply, "arts": arts})


# ---- 문서 비교 (신구대조표)
if PAGE == "compare":
    import doc_compare as dcmp
    page_header("문서 비교", "개정 전·후 문서를 올리면 바뀐 곳을 찾아 신구대조표를 만들고, 주요 변경 사항을 정리합니다.")
    cc1, cc2 = st.columns(2)
    TYPES = ["pdf", "hwp", "hwpx", "docx", "txt", "md"]
    f_old = cc1.file_uploader("현행 (이전 문서)", type=TYPES, key="cmp_old")
    f_new = cc2.file_uploader("개정안 (새 문서)", type=TYPES, key="cmp_new")
    with st.expander("파일 없이 글을 붙여 넣어 비교"):
        pc1, pc2 = st.columns(2)
        p_old = pc1.text_area("현행", height=160, key="cmp_told")
        p_new = pc2.text_area("개정안", height=160, key="cmp_tnew")
    want_sum = st.toggle("AI로 주요 변경 사항 요약", value=True, key="cmp_sum")
    if st.button("비교하기", type="primary", key="cmp_btn", icon=":material/difference:"):
        try:
            with st.spinner("문서를 읽는 중…"):
                t_old = rag_engine.extract_text(f_old.name, f_old.getvalue()) if f_old else p_old
                t_new = rag_engine.extract_text(f_new.name, f_new.getvalue()) if f_new else p_new
            if not t_old.strip() or not t_new.strip():
                st.warning("현행과 개정안을 모두 넣어 주세요.")
            else:
                n_old = f_old.name if f_old else "현행"
                n_new = f_new.name if f_new else "개정안"
                cres = dcmp.compare(t_old, t_new)
                csum = ""
                if want_sum and cres["rows"]:
                    ph = st.empty()
                    csum = dcmp.summarize(cres, llm_client.chat, n_old, n_new, stream_callback=lambda t: ph.markdown(t + " ▌"))
                    ph.empty()
                SS.results["cmp"] = {"res": cres, "sum": exporters.strip_non_korean_cjk(csum), "old": n_old, "new": n_new}
        except Exception as e:
            st.error(f"비교하지 못했습니다: {e}")
    C = SS.results.get("cmp")
    if C:
        cres, cst = C["res"], C["res"]["stats"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("수정", f"{cst['수정']}건")
        m2.metric("신설", f"{cst['신설']}건")
        m3.metric("삭제", f"{cst['삭제']}건")
        m4.metric("글자 유사도", f"{cres['similarity']}%")
        st.caption(f"{cres['mode']} 단위로 맞췄습니다. 바뀌지 않은 {cst['동일']}곳은 표에서 뺐습니다."
                   + (" 조 번호가 통째로 밀린 개정은 조문마다 '수정'으로 나올 수 있습니다." if cres["mode"] == "조문" else ""))
        if not cres["rows"]:
            st.success("두 문서의 내용이 같습니다 (띄어쓰기 차이는 무시).")
        else:
            if C["sum"]:
                st.markdown(C["sum"])
            cdocx = dcmp.to_docx(cres, C["old"], C["new"], C["sum"])
            cxlsx = dcmp.to_xlsx(cres, C["old"], C["new"])
            cmd = dcmp.to_markdown(cres, C["old"], C["new"])
            remember("compare", f"{C['old']} → {C['new']}"[:60], (C["sum"] + "\n\n" + cmd).strip(),
                     {"신구대조표.docx": cdocx, "신구대조표.xlsx": cxlsx})
            d1, d2, d3 = st.columns(3)
            d1.download_button("⬇ 워드 (바뀐 글자 표시)", cdocx, "신구대조표.docx", key="cmp_dl_docx", width="stretch", type="primary",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            d2.download_button("⬇ 엑셀 (바뀐 글자 표시)", cxlsx, "신구대조표.xlsx", key="cmp_dl_xlsx", width="stretch",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            try:
                d3.download_button("⬇ 한글 HWPX (표만)", exporters.to_hwpx(cmd, title="신구대조표"), "신구대조표.hwpx",
                                   key="cmp_dl_hwpx", width="stretch", mime="application/octet-stream")
            except Exception as e:
                d3.caption(f"HWPX 변환 오류: {e}")
            st.html(dcmp.to_html(cres, C["old"], C["new"]))


# ---- 마인드맵
MM_SAMPLE = """스마트 교차로 사업
- 추진 배경
  - 교차로 사고 증가
  - 자율주행 대응
- 추진 내용
  - 신호 연동 시스템
  - 보행자 감지 센서
- 추진 일정
  - 1단계 설계
  - 2단계 구축
- 기대 효과
  - 지체 시간 감소
  - 사고 예방"""


if PAGE == "mindmap":
    import mindmap as mm
    page_header("마인드맵", "직접 만들거나 문서를 올려 구조를 뽑고, 그 마인드맵으로 발표자료나 웹페이지를 만듭니다.")
    if "_mm_new_text" in SS:                                # 편집기 내용 교체는 위젯을 그리기 전에
        SS["mm_text"] = SS.pop("_mm_new_text")
    SS.setdefault("mm_text", MM_SAMPLE)
    SS.setdefault("mm_doc", "")
    SS.setdefault("mm_src", "")
    SS.setdefault("mm_ref", "")
    _on = lambda k: "**켜짐**" if SS.get(k) else "꺼짐"
    st.caption(f"AI가 참고할 자료 — 지식보관함 {_on('use_rag')} · 실시간 웹 검색 {_on('use_web')} "
               "(왼쪽 '참고 자료'에서 바꿀 수 있습니다. 켜 두면 AI 초안·가지 펼치기·문장 보강 때 관련 자료를 찾아 근거로 씁니다)")
    how = st.radio("시작 방법", ["✍️ 직접 만들기", "📄 문서로 만들기"], horizontal=True, key="mm_how",
                   label_visibility="collapsed")
    if how.startswith("📄"):
        mups = st.file_uploader("보고서·계획서·문서 (PDF, HWP, HWPX, DOCX, TXT · 여러 개 가능)",
                                type=["pdf", "hwp", "hwpx", "docx", "txt", "md"], accept_multiple_files=True, key="mm_up")
        mfocus = st.text_input("정리 방향 (선택)", key="mm_focus", placeholder="예) 추진 전략 중심으로 / 기술 요소만 3단계까지")
        if st.button("마인드맵으로 구조화", type="primary", key="mm_doc_btn", icon=":material/account_tree:") and mups:
            texts = []
            for f in mups:
                try:
                    with st.spinner(f"{f.name} 읽는 중…"):
                        texts.append(rag_engine.extract_text(f.name, f.getvalue()))
                except Exception as e:
                    st.error(f"{f.name} 읽기 실패: {e}")
            if texts:
                doc = "\n\n".join(texts)
                names = ", ".join(f.name for f in mups)
                SS["mm_ref"] = ""
                ctx = mm_context((mfocus.strip() + " " + mm.skeleton(doc, 300)).strip())
                with st.spinner("AI가 문서 구조를 마인드맵으로 정리하는 중… (1~2분)"):
                    try:
                        tree = mm.from_document(doc, llm_client.chat, mfocus.strip(), names, ctx)
                        outline = mm.to_outline(tree)
                        SS["mm_doc"], SS["mm_src"] = doc, names
                        remember("mindmap", tree["t"], outline, {"마인드맵.png": mm.to_png(tree), "마인드맵.mm": mm.to_freemind(tree)},
                                 {"source": names})
                        SS["_mm_new_text"] = outline
                        st.rerun()
                    except Exception as e:
                        st.error(f"구조화 실패: {e}")
        if SS["mm_src"]:
            st.caption(f"📎 원문: {SS['mm_src']} — 발표자료·웹페이지를 만들 때 이 문서를 근거로 문장을 보강합니다.")
    else:
        st.caption("첫 줄은 가운데 주제, 그 아래는 '- '와 들여쓰기(2칸)로 가지를 적습니다. 아래 미리보기가 바로 바뀝니다.")
        i1, i2 = st.columns([4, 1])
        itopic = i1.text_input("주제만 적으면 AI가 초안을 잡아 드립니다 (선택)", key="mm_topic",
                               placeholder="예) 2027년 C-ITS 대국민 홍보 방안")
        i2.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if i2.button("AI 초안", key="mm_idea", width="stretch", icon=":material/auto_awesome:") and itopic.strip():
            SS["mm_ref"] = ""
            ctx = mm_context(itopic.strip())
            with st.spinner("AI가 마인드맵 초안을 잡는 중…"):
                try:
                    SS["_mm_new_text"] = mm.to_outline(mm.brainstorm(itopic.strip(), llm_client.chat, ctx))
                    SS["mm_doc"] = SS["mm_src"] = ""
                    st.rerun()
                except Exception as e:
                    st.error(f"실패: {e}")
        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("예시 불러오기", key="mm_sample"):
            SS["_mm_new_text"] = MM_SAMPLE
            SS["mm_doc"] = SS["mm_src"] = SS["mm_ref"] = ""
            st.rerun()
        if b2.button("비우기", key="mm_clear"):
            SS["_mm_new_text"] = "새 주제\n- 가지 1\n- 가지 2"
            SS["mm_doc"] = SS["mm_src"] = SS["mm_ref"] = ""
            st.rerun()

    mtext = st.text_area("마인드맵 내용 (들여쓰기 목록)", height=300, key="mm_text")
    tree = mm.parse_outline(mtext)
    marks = mm.grounded(tree, SS["mm_ref"] + "\n" + SS["mm_doc"]) if (SS["mm_ref"] or SS["mm_doc"]) else set()
    st.caption(f"노드 {mm.count(tree)}개 · {mm.depth(tree)}단계 · 1단계 가지 {len(tree['c'])}개"
               + (f" · ✓ 자료에서 확인된 항목 {len(marks)}개 (초록 표시, 나머지는 AI 정리·아이디어)" if marks else ""))
    L = mm.layout(tree)
    components.html(mm.to_html(tree, height=min(max(380, int(L['h'] * 0.75)), 640), marks=marks),
                    height=min(max(380, int(L['h'] * 0.75)), 640) + 8)
    if SS["mm_ref"]:
        with st.expander("🔍 AI가 참고한 지식보관함·웹 자료 보기"):
            st.text(SS["mm_ref"][:6000])

    # AI 가지 펼치기
    with st.expander("✨ AI로 가지 펼치기 — 고른 가지에 붙일 하위 항목을 제안합니다", expanded=False):
        opts = mm.paths(tree)
        e1, e2 = st.columns([2, 3])
        pick = e1.selectbox("펼칠 가지", range(len(opts)), format_func=lambda i: opts[i][1], key="mm_pick")
        ehint = e2.text_input("요청 (선택)", key="mm_ehint", placeholder="예) 위험 요인 위주로 / 예산 관점")
        if st.button("하위 항목 제안받기", key="mm_expand", icon=":material/auto_awesome:"):
            _n = mm.node_at(tree, opts[pick][0])
            ctx = mm_context(f"{tree['t']} {_n['t']} {ehint.strip()}")
            with st.spinner("AI가 하위 항목을 만드는 중…"):
                try:
                    new = mm.expand(tree, opts[pick][0], llm_client.chat, ehint.strip(), ctx)
                    if new:
                        SS["_mm_new_text"] = mm.to_outline(tree)
                        st.toast(f"{len(new)}개 항목을 추가했습니다: " + ", ".join(new))
                        st.rerun()
                    else:
                        st.info("새로 추가할 항목을 찾지 못했습니다.")
                except Exception as e:
                    st.error(f"실패: {e}")

    # 저장
    st.markdown("#### 저장")
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.download_button("PNG 그림", mm.to_png(tree), f"{tree['t'][:30]}.png", "image/png", key="mm_png", width="stretch")
    d2.download_button("HTML (확대·이동)", mm.to_html(tree).encode("utf-8"), f"{tree['t'][:30]}.html", "text/html",
                       key="mm_html", width="stretch")
    d3.download_button("XMind·FreeMind", mm.to_freemind(tree), f"{tree['t'][:30]}.mm", "application/x-freemind",
                       key="mm_mm", width="stretch", help="XMind, FreeMind, Freeplane 에서 열 수 있는 .mm 파일")
    d4.download_button("PPTX 한 장", mm.to_pptx(tree), f"{tree['t'][:30]}_마인드맵.pptx",
                       "application/vnd.openxmlformats-officedocument.presentationml.presentation", key="mm_pptx1",
                       width="stretch", help="PowerPoint 도형으로 그려져 직접 고칠 수 있습니다")
    if d5.button("📌 보관함에 저장", key="mm_save", width="stretch"):
        remember("mindmap", tree["t"], mtext, {"마인드맵.png": mm.to_png(tree), "마인드맵.mm": mm.to_freemind(tree)},
                 {"source": SS["mm_src"]})
        st.toast("작업 보관함에 저장했습니다.")

    # 마인드맵 → 발표자료 / 웹페이지
    st.markdown("#### 이 마인드맵으로 만들기")
    o1, o2 = st.columns([1, 2])
    kind = o1.radio("만들 것", ["발표자료 (PPTX)", "웹페이지 (HTML)"], key="mm_kind")
    with o2:
        if kind.startswith("발표"):
            mtheme = st.selectbox("디자인 테마", list(sthemes.THEMES), format_func=lambda k: sthemes.THEMES[k]["label"],
                                  key="mm_theme")
            overview = st.checkbox("'전체 구조' 장에 마인드맵 넣기", value=True, key="mm_over")
        enrich_on = st.checkbox("AI로 설명 문장 보강 (1~2분 더 걸림)", value=bool(SS["mm_doc"]), key="mm_enrich",
                                help="가지마다 핵심 메시지와 항목 설명을 씁니다. 문서로 만든 마인드맵이면 그 문서를 근거로 씁니다. "
                                     "끄면 마인드맵 글자만 그대로 씁니다(가지별 작은 마인드맵 장).")
    if st.button("만들기", type="primary", key="mm_make", icon=":material/rocket_launch:"):
        info = None
        if enrich_on:
            ctx = mm_context(tree["t"] + " " + " ".join(b["t"] for b in tree["c"]))
            with st.spinner("AI가 가지별 설명을 쓰는 중…"):
                try:
                    info = mm.enrich(tree, llm_client.chat, SS["mm_doc"],
                                     sthemes.THEMES.get(SS.get("mm_theme", ""), {}).get("style", "") if kind.startswith("발표") else "",
                                     ctx)
                except Exception as e:
                    st.warning(f"문장 보강에 실패해 마인드맵 글자만으로 만듭니다: {e}")
        try:
            if kind.startswith("발표"):
                data = sthemes.render(mtheme, mm.to_slides_data(tree, info, overview, SS["mm_src"]))
                fname = f"{tree['t'][:40]}.pptx"
                remember("slides", tree["t"], mtext, {fname: data}, {"theme": mtheme, "from": "mindmap"})
                SS.results["mm_out"] = ("pptx", data, fname)
            else:
                page = mm.to_web(tree, info, SS["mm_src"])
                remember("web", tree["t"], None, {"page.html": page.encode("utf-8")}, {"from": "mindmap"})
                SS.results["mm_out"] = ("html", page, f"{tree['t'][:40]}.html")
        except Exception as e:
            st.error(f"만들기 실패: {e}")
    out = SS.results.get("mm_out")
    if out:
        if out[0] == "pptx":
            st.download_button(f"⬇ {out[2]}", out[1], out[2],
                               "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                               key="mm_out_dl", type="primary")
        else:
            st.download_button(f"⬇ {out[2]}", out[1].encode("utf-8"), out[2], "text/html", key="mm_out_dl", type="primary")
            components.html(out[1], height=600, scrolling=True)


# ---- 작업 보관함
if PAGE == "history":
    import history
    page_header("작업 보관함", "만든 결과물이 모두 자동으로 저장됩니다. 언제든 다시 열어 보고 원하는 형식으로 내려받으세요.")
    KICON = {"doc": "📄", "report": "📝", "slides": "📊", "web": "🌐", "gantt": "📅", "image": "🖼️", "answer": "💬",
             "diagram": "🔀", "mindmap": "🧠", "compare": "🔍"}
    h1, h2 = st.columns([3, 2])
    hq = h1.text_input("검색 (제목·본문)", key="hist_q", placeholder="예) 자율주행, 간트, 보고서")
    hk = h2.selectbox("종류", ["(전체)"] + list(history.KINDS), format_func=lambda k: history.KINDS.get(k, "전체"),
                      key="hist_kind")
    its = history.items(None if hk == "(전체)" else hk, hq)
    n_all, size = history.stats()
    st.caption(f"전체 {n_all}건 · {size / 1024 ** 2:.1f} MB 사용 · 저장 위치: outputs\\history")
    if not its:
        st.info("아직 저장된 결과물이 없습니다. 다른 메뉴에서 결과를 만들면 여기에 자동으로 쌓입니다."
                if not hq else "검색 결과가 없습니다.")
    lim = SS.get("hist_lim", 20)
    for m in its[:lim]:
        when = m["created"].replace("T", " ")[:16]
        with st.expander(f"{KICON.get(m['kind'], '•')} {m['title']}  ·  {history.KINDS.get(m['kind'], m['kind'])}  ·  {when}"):
            iid = m["id"]
            text = history.load_text(iid) if m.get("has_text") else ""
            imgs = {f[4:-4]: history.read_file(iid, f) for f in m["files"] if f.startswith("img_") and f.endswith(".png")}
            if m["kind"] in ("doc", "report", "answer") and text:
                with st.container(height=320):
                    show_doc(text, imgs or None)
                download_row(text, f"h_{iid}", order=("hwpx", "docx", "pdf", "md"), stem=m["title"][:40] or "결과물",
                             images=imgs or None)
            else:
                if m["kind"] == "mindmap" and text:
                    st.button("마인드맵 편집기에서 열기", key=f"hmm_{iid}", icon=":material/hub:", on_click=_open_mindmap,
                              args=(text, "", m["meta"].get("source", "")))
                for f in m["files"]:
                    if f.lower().endswith(".png") and m["kind"] in ("image", "mindmap"):
                        st.image(history.file_path(iid, f), width="stretch")
                        if m["meta"].get("prompt_en"):
                            st.caption(m["meta"]["prompt_en"][:300])
                mime = {".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        ".html": "text/html", ".png": "image/png", ".json": "application/json",
                        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
                shown = [f for f in m["files"] if not f.endswith(".json") and not f.startswith("img_")]
                cols = st.columns(max(len(shown), 1) + 1)
                for c, f in zip(cols, shown):
                    c.download_button(f"⬇ {f}", history.read_file(iid, f), f, mime.get(os.path.splitext(f)[1], None),
                                      key=f"hdl_{iid}_{f}", width="stretch")
                if m["kind"] == "web" and "page.html" in m["files"] and st.toggle("미리보기", key=f"hprev_{iid}"):
                    components.html(history.read_file(iid, "page.html").decode("utf-8", "ignore"), height=520, scrolling=True)
            with st.popover("삭제", icon=":material/delete:"):
                st.write("이 결과물을 보관함에서 지울까요? 되돌릴 수 없습니다.")
                if st.button("지우기", key=f"hdel_{iid}", type="primary"):
                    history.delete(iid)
                    st.rerun()
    if len(its) > lim and st.button(f"더 보기 ({len(its) - lim}건 남음)", key="hist_more"):
        SS["hist_lim"] = lim + 20
        st.rerun()


# ---- 이미지 생성
if PAGE == "image":
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "imagegen"))
    import comfy_backend as icb
    import gen as igen
    page_header("이미지 생성", "한국어로 설명하면 AI가 영문 프롬프트로 다듬은 뒤, 이 PC의 GPU로 직접 그립니다.")
    ireq = st.text_area("어떤 이미지를 만들까요?", height=110, key="img_req",
                        placeholder="예) 벚꽃이 핀 경복궁 야경을 수채화 느낌으로, 가로로 긴 그림\n"
                                    "예) (참조 사진을 올린 뒤) 이 사람이 눈 내리는 한옥 마당에 서 있는 모습으로")
    # ---- 참조 이미지 (인물·사물·스타일, 최대 3장)
    SS.setdefault("img_extra_refs", [])
    ref_dir = os.path.join(icb.HERE, "refs", time.strftime("%Y%m%d"))
    with st.expander(":material/add_photo_alternate: 참조 이미지 (인물·사물·스타일, 최대 3장)",
                     expanded=bool(SS["img_extra_refs"])):
        ups = st.file_uploader("참조할 이미지를 올리세요", type=["png", "jpg", "jpeg", "webp"],
                               accept_multiple_files=True, key="img_refs_up")
        st.caption("올린 순서대로 image 1, image 2, image 3 으로 쓰입니다. "
                   "예) '1번 사진의 사람에게 2번 사진의 옷을 입혀줘', '이 제품을 대리석 탁자 위에 놓인 광고 사진으로'")
        st.caption("⚠️ 인물 사진은 본인이거나 동의를 받은 사람의 사진만 쓰세요. 실존 인물을 사칭하거나 비방하는 이미지는 만들지 마세요.")
    ref_paths = []
    for f in (ups or []):
        os.makedirs(ref_dir, exist_ok=True)
        pth = os.path.join(ref_dir, f.name)
        with open(pth, "wb") as fh:
            fh.write(f.getvalue())
        ref_paths.append(pth)
    ref_paths = (SS["img_extra_refs"] + ref_paths)[:3]
    if ref_paths:
        rc = st.columns(len(ref_paths) + 1)
        for i, pth in enumerate(ref_paths):
            rc[i].image(pth, caption=f"image {i + 1}", width="stretch")
        if SS["img_extra_refs"] and rc[-1].button("이어서 고치기 해제", key="img_ref_clear", icon=":material/close:"):
            SS["img_extra_refs"] = []
            st.rerun()
    IMG_MODELS = {"z-image-turbo": "Z-Image-Turbo · 글자 표현이 나음", "flux2-klein-4b": "FLUX.2 Klein 4B · 더 빠름"}
    SIZES = {"auto": "AI가 판단" if not ref_paths else "참조 이미지 비율 유지",
             "1024x1024": "정사각 1024×1024", "1344x768": "가로 1344×768", "832x1216": "세로 832×1216"}
    c1, c2, c3 = st.columns([2.2, 2, 1.2])
    if ref_paths:
        c1.selectbox("이미지 모델", ["flux2-klein-4b"], format_func=lambda m: "FLUX.2 Klein 4B · 참조 이미지 지원",
                     key="img_model_ref", disabled=True)
        imodel = "flux2-klein-4b"
    else:
        imodel = c1.selectbox("이미지 모델", list(IMG_MODELS), format_func=IMG_MODELS.get, key="img_model")
    isize = c2.selectbox("크기", list(SIZES), format_func=SIZES.get, key="img_size")
    iseed = c3.number_input("시드 (-1=무작위)", value=-1, step=1, key="img_seed")
    with st.expander("고급: 영문 프롬프트 직접 입력"):
        direct = st.toggle("AI 확장 없이 아래 영문 프롬프트를 그대로 사용", key="img_direct")
        dprompt = st.text_area("영문 프롬프트", height=90, key="img_prompt_en")
    st.caption("이미지를 그리는 동안에는 메모리 확보를 위해 AI 언어 모델을 잠시 내립니다. 첫 장은 1~2분, 같은 설정으로 이어서 그리면 더 빠릅니다.")
    if st.button("이미지 만들기", type="primary", key="img_go", icon=":material/brush:") and (ireq.strip() or dprompt.strip()):
        with st.status("준비 중...", expanded=True) as stt:
            try:
                if direct and dprompt.strip():
                    args, secs, called = {"prompt_en": dprompt.strip()}, 0.0, False
                else:
                    if icb.comfy_alive():
                        icb.free_comfy_memory()
                    stt.update(label=f"✍️ {llm_client.MODEL}가 요청을 영문 프롬프트로 다듬는 중...")
                    props = {"prompt_en": {"type": "string", "description": "Detailed English image prompt"},
                             "negative": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"},
                             "steps": {"type": "integer"}, "seed": {"type": "integer"}}
                    tools = [{"type": "function", "function": {"name": "generate_image", "description": "Generate an image",
                              "parameters": {"type": "object", "properties": props, "required": ["prompt_en"]}}}]
                    use_vision = bool(ref_paths) and llm_client.supports_vision()
                    if ref_paths and not use_vision:
                        st.write("현재 언어 모델은 그림을 볼 수 없어, 참조 이미지는 이미지 모델에만 전달됩니다.")
                    args, secs, called = igen.expand(ireq, llm_client.MODEL, tools,
                                                     images=ref_paths if use_vision else None)
                    st.write(f"프롬프트 확장 {secs:.0f}초")
                    st.code(args.get("prompt_en", ""), language=None, wrap_lines=True)
                if ref_paths:                              # 참조 이미지: 비율 유지가 기본
                    w, h = (args.get("width") or 0, args.get("height") or 0)
                else:
                    w, h = (args.get("width") or 1024, args.get("height") or 1024)
                if isize != "auto":
                    w, h = map(int, isize.split("x"))
                stt.update(label="🎨 언어 모델을 내리고 이미지를 그리는 중... (처음엔 1~2분)")
                res = icb.generate(args.get("prompt_en", ireq), args.get("negative", ""), w, h, 0,
                                   int(iseed), imodel, extra_meta={"request_ko": ireq, "llm": llm_client.MODEL,
                                                                   "llm_expand_sec": round(secs, 2), "tool_called_by_llm": called},
                                   refs=ref_paths or None)
                SS["comfy_loaded"] = True
                SS.results["img"] = res
                with open(res["image"], "rb") as _f:
                    remember("image", ireq.strip()[:60] or args.get("prompt_en", "")[:60], None,
                             {os.path.basename(res["image"]): _f.read()},
                             {"prompt_en": args.get("prompt_en", ""), "model": imodel, "seed": res.get("seed")})
                stt.update(label=f"✅ 완료 — {res['elapsed_sec']:.0f}초", state="complete", expanded=False)
            except Exception as e:
                stt.update(label=f"⚠️ 실패: {e}", state="error")
    res = SS.results.get("img")
    if res and os.path.exists(res["image"]):
        st.image(res["image"], width="stretch")
        m1, m2 = st.columns([3, 1])
        m1.caption(f"{IMG_MODELS.get(res['model'], res['model'])} · {res['width']}×{res['height']} · seed {res['seed']} · "
                   f"{res['elapsed_sec']:.0f}초{' (콜드 스타트)' if res.get('cold_start') else ''}")
        with open(res["image"], "rb") as f:
            m2.download_button("PNG 저장", f.read(), os.path.basename(res["image"]), "image/png",
                               key="img_dl", icon=":material/download:", width="stretch")
        if res.get("references"):
            st.caption("참조 이미지: " + ", ".join(res["references"]))
        if st.button("이 결과를 참조로 이어서 고치기", key="img_continue", icon=":material/edit:"):
            SS["img_extra_refs"] = [res["image"]]
            st.rerun()
        with st.expander("사용한 영문 프롬프트"):
            st.write(res["prompt_en"])
    # 최근 갤러리
    import glob as _glob
    recent = sorted(_glob.glob(os.path.join(icb.OUT_ROOT, "*", "*.png")), key=os.path.getmtime, reverse=True)[:9]
    if recent:
        st.markdown("#### 최근에 만든 이미지")
        cols = st.columns(3)
        for i, pth in enumerate(recent):
            with cols[i % 3]:
                st.image(pth, width="stretch")
                st.markdown(f'<div class="gal-cap">{os.path.basename(os.path.dirname(pth))} · '
                            f'{os.path.basename(pth).split("_")[1] if "_" in os.path.basename(pth) else ""}</div>',
                            unsafe_allow_html=True)


# ------------------------------------------------------------------ 하드웨어 모니터 (사이드바 맨 아래)
def monitor():
    st.markdown('<div class="side-label">상태</div>', unsafe_allow_html=True)
    m = llm_client.load_last_metrics()
    c1, c2 = st.columns(2)
    c1.metric("생성 속도", f"{m['tps']:.1f} tok/s" if m.get("tps") else "–")
    c2.metric("첫 반응", f"{m['ttft']:.1f}초" if m.get("ts") else "–")
    ps = llm_client.get_ps()
    if ps["state"] == "loaded":
        size, vram = ps.get("size", 0), ps.get("size_vram", 0)
        gb = max(vram / 1024 ** 3, llm_client.runner_memory_gb())   # Ollama 보고값이 부정확한 모델이 있어 실제 사용량 병기
        if size > 0 and vram >= size * 0.99:
            chip = f'<span class="status-chip ok">● {llm_client.MODEL} · GPU 가속 · {gb:.1f} GB</span>'
        else:
            pct = (vram / size * 100) if size else 0
            chip = f'<span class="status-chip warn">● 일부 CPU 처리 (GPU {pct:.0f}%) · {gb:.1f} GB</span>'
    elif ps["state"] == "idle":
        chip = '<span class="status-chip">○ 언어 모델 대기 중</span>'
    else:
        chip = '<span class="status-chip err">● Ollama 연결 안 됨</span>'
    st.markdown(chip, unsafe_allow_html=True)
    vm = psutil.virtual_memory()
    used, total = (vm.total - vm.available) / 1024 ** 3, vm.total / 1024 ** 3
    st.progress(min(vm.percent / 100, 1.0), text=f"메모리 {used:.1f} / {total:.0f} GB")
    if vm.percent >= 85:
        st.caption("⚠️ 메모리가 부족합니다. 프로그램을 닫거나 가벼운 모델로 바꾸세요.")
    b1, b2 = st.columns(2)
    if b1.button("새로고침", key="mon_refresh", width="stretch", icon=":material/refresh:"):
        pass  # 클릭 자체가 fragment 재실행을 유발
    if b2.button("비우기", key="mon_unload", width="stretch", icon=":material/memory:"):
        ok = llm_client.unload_model()
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "imagegen"))
            import comfy_backend as _icb
            if _icb.comfy_alive():
                _icb.free_comfy_memory()
        except Exception:
            pass
        st.toast("언어 모델과 이미지 모델을 메모리에서 내렸습니다." if ok else "메모리 비우기 실패")


with monitor_box:
    (fragment(monitor) if fragment else monitor)()
