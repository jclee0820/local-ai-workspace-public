"""ComfyUI 백엔드: API 포맷 워크플로 생성 → /prompt 제출 → 완료 대기 → PNG + 메타데이터 JSON 저장.
메모리 예산상 LLM(Gemma 4 26B, 약 21GB)과 이미지 모델을 동시에 올릴 수 없으므로 생성 전에 Ollama 모델을 내린다."""
import copy
import datetime
import io
import json
import os
import random
import subprocess
import sys
import threading
import time
import uuid

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
COMFY_DIR = os.path.join(HERE, "ComfyUI")
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OUT_ROOT = os.path.join(HERE, "outputs")
WF_DIR = os.path.join(HERE, "workflows")

MODELS = {
    "flux2-klein-4b": {"workflow": "flux2_klein_4b_api.json", "steps": 4, "license": "Apache-2.0",
                       "files": ["flux-2-klein-4b.safetensors", "qwen_3_4b.safetensors", "flux2-vae.safetensors"],
                       "negative_supported": False},
    "z-image-turbo": {"workflow": "z_image_turbo_api.json", "steps": 8, "license": "Apache-2.0",
                      "files": ["z_image_turbo_bf16.safetensors", "qwen_3_4b.safetensors", "ae.safetensors"],
                      "negative_supported": False},
}
DEFAULT_MODEL = os.environ.get("IMAGEGEN_MODEL", "z-image-turbo")
# FP8 적재 시 Z-Image 웜 생성 85초 → 31초 (bf16 은 인코더와 함께 GPU 메모리에 들어가지 않아 매번 재적재). "default" 로 bf16 사용
WEIGHT_DTYPE = os.environ.get("IMAGEGEN_WEIGHT_DTYPE", "fp8_e4m3fn")


# ------------------------------------------------------------------ ComfyUI 서버 관리
def comfy_alive() -> bool:
    try:
        return requests.get(f"{COMFY_URL}/system_stats", timeout=2).status_code == 200
    except Exception:
        return False


def start_comfy(wait=180) -> bool:
    """ComfyUI 가 꺼져 있으면 백그라운드로 실행하고 준비될 때까지 대기."""
    if comfy_alive():
        return True
    py = (os.path.join(COMFY_DIR, ".venv", "Scripts", "python.exe") if os.name == "nt"
          else os.path.join(COMFY_DIR, ".venv", "bin", "python"))
    log = open(os.path.join(HERE, "comfyui.log"), "a", encoding="utf-8")
    flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
    subprocess.Popen([py, "main.py", "--listen", "127.0.0.1", "--port", COMFY_URL.rsplit(":", 1)[-1],
                      "--disable-auto-launch"], cwd=COMFY_DIR, stdout=log, stderr=log, creationflags=flags)
    t = time.time()
    while time.time() - t < wait:
        if comfy_alive():
            return True
        time.sleep(2)
    return False


LOG_PATH = os.path.join(HERE, "comfyui.log")
GPU_FATAL = ("DEVICE_LOST", "OUT_OF_DEVICE_MEMORY")


def _log_size() -> int:
    try:
        return os.path.getsize(LOG_PATH)
    except OSError:
        return 0


def _gpu_fault_since(offset: int) -> bool:
    """offset 이후 ComfyUI 로그에 Intel GPU 치명 오류(장치 손실·메모리 부족)가 찍혔는지."""
    try:
        with open(LOG_PATH, "rb") as f:
            f.seek(offset)
            tail = f.read().decode("utf-8", "ignore")
        return any(k in tail for k in GPU_FATAL)
    except OSError:
        return False


_LOG_AT_IMPORT = _log_size()


def restart_comfy() -> bool:
    """GPU 장치 손실 등으로 ComfyUI 가 망가졌을 때 프로세스를 내리고 새로 띄움."""
    import psutil
    for q in psutil.process_iter(["name", "cmdline"]):
        try:
            if "main.py" in " ".join(q.info["cmdline"] or []) and os.path.normcase(q.cwd()) == os.path.normcase(COMFY_DIR):
                q.kill()
        except Exception:
            continue
    _PROC["p"] = None
    _save_state({})
    time.sleep(3)
    return start_comfy()


def unload_llm():
    """Ollama 에 올라간 모든 모델을 즉시 내림 (keep_alive=0)."""
    try:
        for m in requests.get(f"{OLLAMA_URL}/api/ps", timeout=3).json().get("models", []):
            requests.post(f"{OLLAMA_URL}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=30)
        return True
    except Exception:
        return False


def free_comfy_memory():
    """ComfyUI 가 들고 있는 모델 메모리를 비움 (다음 LLM 호출을 위해)."""
    try:
        mark = _log_size()
        requests.post(f"{COMFY_URL}/free", json={"unload_models": True, "free_memory": True}, timeout=120)
        time.sleep(3)                                     # 실제 해제가 끝날 때까지 잠시 대기
        _save_state({})                                   # 다음 생성은 콜드 스타트
        if _gpu_fault_since(mark):                        # 모델을 내리다 GPU 가 고장 나면 ComfyUI 를 내려 메모리 회수
            restart_comfy()
    except Exception:
        pass


_PROC = {"p": None}


def comfy_process():
    """ComfyUI 서버 프로세스 (venv 런처가 기본 python 을 띄우므로 작업 폴더+main.py 로 식별)."""
    import psutil
    p = _PROC["p"]
    if p is not None and p.is_running():
        return p
    found = []
    for q in psutil.process_iter(["name", "cmdline"]):
        try:
            if (q.info["name"] or "").lower().startswith("python") and "main.py" in " ".join(q.info["cmdline"] or []) \
                    and os.path.normcase(q.cwd()) == os.path.normcase(COMFY_DIR):
                found.append(q)
        except Exception:
            continue
    if not found:
        return None
    # venv 런처(python.exe)와 실제 서버 프로세스가 함께 잡히므로 메모리가 가장 큰 쪽이 실제 서버
    _PROC["p"] = max(found, key=lambda q: q.memory_info().rss)
    return _PROC["p"]


STATE = os.path.join(HERE, "outputs", ".loaded_state.json")


def _save_state(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(d, f)


def _is_warm(model) -> bool:
    """같은 ComfyUI 프로세스가 이 모델을 직전에 올려 둔 상태(메모리 비움 없이)이면 웜."""
    try:
        with open(STATE, encoding="utf-8") as f:
            s = json.load(f)
        p = comfy_process()
        return bool(p) and s.get("model") == model and abs(s.get("comfy_started", 0) - p.create_time()) < 1
    except Exception:
        return False


# ------------------------------------------------------------------ 메모리 측정 (Arc 내장 GPU = 시스템 RAM 공유)
class MemSampler(threading.Thread):
    """생성 중 0.5초마다 ComfyUI 프로세스 메모리와 시스템 사용량, GPU 공유 메모리 사용량 최댓값을 기록."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = False
        self.peak_proc = self.peak_sys = self.peak_gpu = 0.0

    def _gpu_shared_gb(self):
        if os.name != "nt":                          # 리눅스: Windows 성능 카운터가 없으므로 측정 생략
            return 0.0
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "((Get-Counter '\\GPU Adapter Memory(*)\\Shared Usage').CounterSamples | "
                                  "Measure-Object -Property CookedValue -Sum).Sum"],
                                 capture_output=True, text=True, timeout=8, creationflags=0x08000000).stdout
            return float(out.strip() or 0) / 2**30
        except Exception:
            return 0.0

    def run(self):
        import psutil
        n = 0
        while not self.stop_flag:
            try:
                vm = psutil.virtual_memory()
                self.peak_sys = max(self.peak_sys, (vm.total - vm.available) / 2**30)
                p = comfy_process()
                if p:
                    mi = p.memory_info()
                    self.peak_proc = max(self.peak_proc, getattr(mi, "private", mi.rss) / 2**30)
                if n % 4 == 0:
                    self.peak_gpu = max(self.peak_gpu, self._gpu_shared_gb())
            except Exception:
                pass
            n += 1
            time.sleep(0.5)


# ------------------------------------------------------------------ 워크플로
def load_workflow(model: str) -> dict:
    with open(os.path.join(WF_DIR, MODELS[model]["workflow"]), encoding="utf-8") as f:
        return json.load(f)


def fill_workflow(wf: dict, prompt_en, negative, width, height, steps, seed) -> dict:
    """워크플로의 _meta.title 표식으로 입력 노드를 찾아 값을 채움."""
    wf = copy.deepcopy(wf)
    for node in wf.values():
        t = node.get("_meta", {}).get("title", "")
        ins = node["inputs"]
        if node.get("class_type") == "UNETLoader":      # 메모리 절약: 확산 모델 가중치를 FP8 로 적재 (기본값)
            ins["weight_dtype"] = WEIGHT_DTYPE
        if t == "POSITIVE":
            ins["text"] = prompt_en
        elif t == "NEGATIVE" and "text" in ins:
            ins["text"] = negative or ""
        elif t in ("LATENT", "SCHEDULER"):
            ins["width"], ins["height"] = width, height
            if "steps" in ins:
                ins["steps"] = steps
        elif t == "SAMPLER":
            if "seed" in ins:
                ins["seed"] = seed
            if "steps" in ins:
                ins["steps"] = steps
        elif t == "NOISE":
            ins["noise_seed"] = seed
    return wf


MAX_REFS = 3


def upload_image(path: str) -> str:
    """참조 이미지를 ComfyUI input 폴더로 업로드하고 LoadImage 에 쓸 파일명을 반환."""
    with open(path, "rb") as f:
        r = requests.post(f"{COMFY_URL}/upload/image", files={"image": (os.path.basename(path), f, "image/png")},
                          data={"overwrite": "true", "subfolder": "imagegen_refs"}, timeout=60)
    r.raise_for_status()
    d = r.json()
    return f"{d['subfolder']}/{d['name']}" if d.get("subfolder") else d["name"]


def build_edit_workflow(prompt_en: str, ref_names: list, width: int, height: int, steps: int, seed: int) -> dict:
    """FLUX.2 Klein 4B 참조 이미지 워크플로 (공식 템플릿 image_flux2_klein_image_edit_4b_distilled 구조).
    참조 이미지마다 VAEEncode → ReferenceLatent 를 긍정/부정 조건에 이어 붙임. width/height=0 이면 첫 참조 이미지 비율(약 1MP)."""
    wf = copy.deepcopy(load_workflow("flux2-klein-4b"))
    for k in ("66", "62"):                                 # 크기는 아래에서 다시 연결
        wf[k]["inputs"].pop("width", None)
        wf[k]["inputs"].pop("height", None)
    wf["70"]["inputs"]["weight_dtype"] = WEIGHT_DTYPE
    wf["74"]["inputs"]["text"] = prompt_en
    wf["73"]["inputs"]["noise_seed"] = seed
    wf["62"]["inputs"]["steps"] = steps
    pos, neg = ["74", 0], ["76", 0]
    for i, name in enumerate(ref_names):
        li, sc, en, rp, rn = (f"r{i}_load", f"r{i}_scale", f"r{i}_enc", f"r{i}_pos", f"r{i}_neg")
        wf[li] = {"class_type": "LoadImage", "inputs": {"image": name}, "_meta": {"title": f"REF{i + 1}"}}
        wf[sc] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [li, 0], "upscale_method": "nearest-exact",
                                                                       "megapixels": 1.0, "resolution_steps": 16}}
        wf[en] = {"class_type": "VAEEncode", "inputs": {"pixels": [sc, 0], "vae": ["72", 0]}}
        wf[rp] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [en, 0]}}
        wf[rn] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg, "latent": [en, 0]}}
        pos, neg = [rp, 0], [rn, 0]
    wf["63"]["inputs"]["positive"], wf["63"]["inputs"]["negative"] = pos, neg
    if width and height:
        for k in ("66", "62"):
            wf[k]["inputs"]["width"], wf[k]["inputs"]["height"] = width, height
    else:                                                  # 출력 크기 = 첫 참조 이미지(1MP 로 맞춘) 크기
        wf["size"] = {"class_type": "GetImageSize", "inputs": {"image": ["r0_scale", 0]}}
        for k in ("66", "62"):
            wf[k]["inputs"]["width"], wf[k]["inputs"]["height"] = ["size", 0], ["size", 1]
    return wf


def generate(prompt_en: str, negative: str = "", width: int = 1024, height: int = 1024, steps: int = 0,
             seed: int = -1, model: str = DEFAULT_MODEL, unload_llm_first: bool = True, extra_meta: dict = None,
             refs: list = None) -> dict:
    """이미지 1장 생성. refs: 참조 이미지 경로 목록(최대 3장, FLUX.2 Klein 으로 자동 전환). 반환: {'image','metadata', ...}"""
    refs = [r for r in (refs or []) if r][:MAX_REFS]
    if refs:
        model = "flux2-klein-4b"                           # Z-Image-Turbo 는 참조 이미지 입력을 지원하지 않음
    if model not in MODELS:
        raise ValueError(f"지원 모델: {list(MODELS)}")
    width, height = int(width or 0) // 16 * 16, int(height or 0) // 16 * 16
    steps = int(steps) or MODELS[model]["steps"]
    seed = int(seed) if seed is not None and int(seed) >= 0 else random.randint(0, 2**31 - 1)
    if unload_llm_first:
        unload_llm()
    if not start_comfy():
        raise RuntimeError("ComfyUI 서버를 시작하지 못했습니다. imagegen/comfyui.log 를 확인하세요.")
    if _gpu_fault_since(getattr(generate, "_log_mark", _LOG_AT_IMPORT)):  # 직전 작업에서 GPU 가 고장 났으면 재시작
        restart_comfy()
    sampler = MemSampler()
    sampler.start()
    hist, t0 = None, time.time()
    for attempt in range(2):                                     # GPU 장치 손실 시 ComfyUI 재시작 후 1회 재시도
        if refs:
            wf = build_edit_workflow(prompt_en, [upload_image(r) for r in refs], width, height, steps, seed)
        else:
            width, height = width or 1024, height or 1024
            wf = fill_workflow(load_workflow(model), prompt_en, negative, width, height, steps, seed)
        cold = not _is_warm(model)
        mark = _log_size()
        t0 = time.time()
        r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": wf, "client_id": str(uuid.uuid4())}, timeout=30)
        if r.status_code != 200:
            sampler.stop_flag = True
            raise RuntimeError(f"ComfyUI 워크플로 오류: {r.text[:800]}")
        pid = r.json()["prompt_id"]
        hist, fault = None, False
        while time.time() - t0 < 900:                            # 한 장당 최대 15분
            h = requests.get(f"{COMFY_URL}/history/{pid}", timeout=10).json()
            if pid in h and h[pid].get("status", {}).get("completed") is not None:
                hist = h[pid]
                if hist["status"].get("status_str") == "error" or hist.get("outputs"):
                    break
            if _gpu_fault_since(mark) or not comfy_alive():
                fault = True
                break
            time.sleep(1)
        if hist and hist.get("outputs"):
            break
        msgs = json.dumps((hist or {}).get("status", {}).get("messages", []), ensure_ascii=False)
        if attempt == 0 and (fault or any(k in msgs for k in GPU_FATAL) or hist is None):
            restart_comfy()                                      # GPU 오류·무응답 → 재시작 후 재시도
            continue
        break
    elapsed = time.time() - t0
    sampler.stop_flag = True
    sampler.join(timeout=10)
    generate._log_mark = _log_size()
    if not hist or not hist.get("outputs"):
        msgs = (hist or {}).get("status", {}).get("messages", [])
        raise RuntimeError(f"생성 실패: {json.dumps(msgs, ensure_ascii=False)[:1200]}")
    img_info = next(o["images"][0] for o in hist["outputs"].values() if o.get("images"))
    png = requests.get(f"{COMFY_URL}/view", params={"filename": img_info["filename"], "subfolder": img_info.get("subfolder", ""),
                                                    "type": img_info.get("type", "output")}, timeout=60).content
    p = comfy_process()
    _save_state({"model": model, "comfy_started": p.create_time() if p else 0})
    day = datetime.datetime.now().strftime("%Y%m%d")
    stamp = datetime.datetime.now().strftime("%H%M%S")
    out_dir = os.path.join(OUT_ROOT, day)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"{stamp}_{model}_{seed}")
    with open(base + ".png", "wb") as f:
        f.write(png)
    if not (width and height):
        from PIL import Image
        width, height = Image.open(io.BytesIO(png)).size
    meta = {"prompt_en": prompt_en, "negative": negative, "references": [os.path.basename(r) for r in refs],
            "negative_applied": MODELS[model]["negative_supported"], "model": model,
            "model_files": MODELS[model]["files"], "license": MODELS[model]["license"], "weight_dtype": WEIGHT_DTYPE,
            "width": width, "height": height, "steps": steps, "seed": seed,
            "elapsed_sec": round(elapsed, 2), "cold_start": cold,
            "peak_comfy_process_gb": round(sampler.peak_proc, 2), "peak_system_ram_used_gb": round(sampler.peak_sys, 2),
            "peak_gpu_shared_gb": round(sampler.peak_gpu, 2), "backend": "ComfyUI (PyTorch XPU)",
            "created": datetime.datetime.now().isoformat(timespec="seconds")}
    if extra_meta:
        meta.update(extra_meta)
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return {"image": base + ".png", "metadata": base + ".json", **meta}


if __name__ == "__main__":
    print(json.dumps(generate(" ".join(sys.argv[1:]) or "a red apple on a wooden table, studio light"), ensure_ascii=False, indent=2))
