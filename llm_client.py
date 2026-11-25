"""Ollama 호출 래퍼: 모든 탭 공통. 속도(tok/s)·TTFT 메타데이터를 수집한다."""
import json
import os
import time

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

_BASE = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(_BASE, "model.json")


def _load_model() -> str:
    """사용 모델명은 model.json 한 곳에서만 관리 (없으면 기본값)."""
    try:
        with open(MODEL_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("model", "qwen2.5:14b")
    except Exception:
        return "qwen2.5:14b"


MODEL = _load_model()
METRICS_FILE = os.path.join(_BASE, "last_metrics.json")

DEFAULT_OPTIONS = {"temperature": 0.2, "top_p": 0.85, "repeat_penalty": 1.1, "num_ctx": 8192}

LAST_METRICS = {}


def compute_metrics(meta: dict) -> dict:
    """Ollama 응답 메타데이터에서 tok/s, TTFT(초) 계산. 0으로 나누기 방지."""
    eval_count = meta.get("eval_count") or 0
    eval_dur = meta.get("eval_duration") or 0          # ns
    prompt_dur = meta.get("prompt_eval_duration") or 0  # ns
    load_dur = meta.get("load_duration") or 0           # ns
    tps = (eval_count / (eval_dur / 1e9)) if eval_dur > 0 else 0.0
    ttft = (prompt_dur + load_dur) / 1e9
    return {"tps": round(tps, 2), "ttft": round(ttft, 2), "tokens": eval_count, "ts": time.time()}


def _save(m: dict):
    LAST_METRICS.clear()
    LAST_METRICS.update(m)
    try:
        with open(METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(m, f)
    except Exception:
        pass


def load_last_metrics() -> dict:
    try:
        with open(METRICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(LAST_METRICS)


def list_models():
    try:
        return sorted(m["name"] for m in requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).json().get("models", []))
    except Exception:
        return [MODEL]


def set_model(name: str):
    """사용 모델 변경 + model.json 저장. 이전 모델은 메모리에서 내려 두 모델이 동시에 올라가지 않게 함."""
    global MODEL
    if name == MODEL:
        return
    unload_model()
    MODEL = name
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        json.dump({"model": name}, f)


_CAPS = {}


def _caps(model: str = None):
    """Ollama 가 알려 주는 모델 기능 목록(vision·thinking·tools 등). 모델별로 한 번만 물어봄."""
    m = model or MODEL
    if m not in _CAPS:
        try:
            _CAPS[m] = requests.post(f"{OLLAMA_URL}/api/show", json={"model": m}, timeout=5).json().get("capabilities", [])
        except Exception:
            return []
    return _CAPS[m]


def supports_vision(model: str = None) -> bool:
    return "vision" in _caps(model)


def supports_thinking(model: str = None) -> bool:
    m = model or MODEL
    return "thinking" in _caps(m) or any(k in m for k in ("qwen3", "gpt-oss", "gemma4", "deepseek-r1", "inkling"))


def runner_memory_gb() -> float:
    """모델 실행 프로세스(llama-server / ollama runner)가 실제로 차지한 메모리(GB).
    Arc 내장 GPU는 시스템 RAM을 공유하므로 /api/ps 의 size 보다 이 값이 정확함."""
    try:
        import psutil
        tot = 0
        for p in psutil.process_iter(["name"]):
            n = (p.info["name"] or "").lower()
            if n.startswith("llama-server") or "runner" in n:
                tot += p.memory_info().private if hasattr(p.memory_info(), "private") else p.memory_info().rss
        return round(tot / 2**30, 1)
    except Exception:
        return 0.0


CACHE_DIR = os.path.join(os.environ.get("LAI_CACHE_DIR") or os.path.join(_BASE, "outputs", ".cache"), "llm")
CACHE_KEEP, CACHE_DAYS = 3000, 30
CACHE_STATS = {"hit": 0, "miss": 0}


def _cache_path(model, messages, opts, fmt):
    import hashlib
    raw = json.dumps([model, messages, opts, fmt], ensure_ascii=False, sort_keys=True)
    return os.path.join(CACHE_DIR, hashlib.sha256(raw.encode("utf-8")).hexdigest() + ".txt")


def _cache_put(path, text):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(path + ".tmp", path)
        names = os.listdir(CACHE_DIR)
        if len(names) > CACHE_KEEP + 200:                      # 가끔 한 번에 정리
            full = sorted((os.path.join(CACHE_DIR, n) for n in names), key=os.path.getmtime)
            for old in full[: len(names) - CACHE_KEEP]:
                os.remove(old)
    except Exception:
        pass


def cached(fn=None):
    """chat 과 같은 함수이되 결과를 재사용하는 판. 문서 조각 요약·일정 추출처럼 '같은 입력이면 같은 답이어야 하는' 작업에만 씀."""
    import functools
    return functools.partial(fn or chat, cache=True)


def chat(messages, options=None, stream_callback=None, keep_alive="10m", fmt=None, cache=False) -> str:
    """현재 모델 호출. stream_callback(누적텍스트)을 주면 스트리밍.
    cache=True: 모델·입력·옵션이 모두 같은 호출의 결과를 디스크에서 다시 꺼냄 (긴 문서 재요약 시 조각 요약을 건너뜀)."""
    opts = dict(DEFAULT_OPTIONS)
    if options:
        opts.update(options)
    opts["num_ctx"] = 8192           # 호출마다 num_ctx 가 다르면 모델이 매번 다시 적재되므로 고정
    cpath = _cache_path(MODEL, messages, opts, fmt) if cache else None
    if cpath:
        try:
            if time.time() - os.path.getmtime(cpath) < CACHE_DAYS * 86400:
                with open(cpath, "r", encoding="utf-8") as f:
                    hit = f.read()
                if hit.strip():
                    CACHE_STATS["hit"] += 1
                    if stream_callback:
                        stream_callback(hit)
                    return hit
        except OSError:
            pass
        CACHE_STATS["miss"] += 1
    payload = {"model": MODEL, "messages": messages, "stream": True,
               "options": opts, "keep_alive": keep_alive}
    if fmt:
        payload["format"] = fmt      # "json" → JSON 형식 강제
    if supports_thinking(MODEL):
        payload["think"] = False   # 추론(thinking) 출력 끄기: 속도·문체 안정 (Ollama 가 'thinking' 기능이 있다고 알려 주는 모델 모두)
    text = ""
    meta = {}
    with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=(10, 900)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            d = json.loads(line)
            if "error" in d:
                raise RuntimeError(d["error"])
            text += d.get("message", {}).get("content", "")
            if stream_callback:
                stream_callback(text)
            if d.get("done"):
                meta = d
    _save(compute_metrics(meta))
    if cpath and text.strip():
        _cache_put(cpath, text)
    return text


def get_ps() -> dict:
    """/api/ps 파싱 → {state, size, size_vram}"""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/ps", timeout=3)
        models = r.json().get("models", [])
        for m in models:
            if MODEL in (m.get("name"), m.get("model")) or m.get("name", "").startswith(MODEL):
                return {"state": "loaded", "size": m.get("size", 0), "size_vram": m.get("size_vram", 0)}
        return {"state": "idle"}
    except Exception as e:
        return {"state": "offline", "error": str(e)}


def unload_model() -> bool:
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate",
                          json={"model": MODEL, "keep_alive": 0}, timeout=30)
        return r.status_code == 200
    except Exception:
        return False


def is_alive() -> bool:
    try:
        return requests.get(OLLAMA_URL, timeout=2).status_code == 200
    except Exception:
        return False
