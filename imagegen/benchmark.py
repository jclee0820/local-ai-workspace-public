"""벤치마크: 테스트 프롬프트 5종(한글 포스터 포함) + 모델별 콜드/웜 시간 + 메모리 최댓값 + LLM 프롬프트 확장 시간.
결과: outputs/benchmark_YYYYMMDD_HHMM.json 및 표(Markdown)."""
import datetime
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import comfy_backend as cb  # noqa: E402
import gen  # noqa: E402

TESTS = [
    ("poster_ko", "'봄꽃 축제 2027'이라는 큰 한글 제목과 '4월 5일 여의도'라는 부제가 들어간 축제 포스터를 만들어줘. 벚꽃과 파스텔 톤"),
    ("photo", "비 오는 서울 골목에서 투명 우산을 든 노인을 찍은 흑백 다큐멘터리 사진"),
    ("product", "미니멀한 흰 배경 위에 놓인 무선 이어폰 제품 사진, 부드러운 그림자, 광고용"),
    ("concept", "자율주행차와 도로변 기지국(RSU)이 신호를 주고받는 개념 일러스트, 아이소메트릭 스타일"),
    ("sign_en", "'OPEN' 이라고 적힌 네온사인이 걸린 한밤의 작은 카페 외관 사진"),
]
LLM = os.environ.get("IMAGEGEN_LLM", "gemma4:26b")


class LLMMem(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop = False
        self.peak = 0.0

    def run(self):
        import psutil
        while not self.stop:
            tot = 0
            for p in psutil.process_iter(["name"]):
                if (p.info["name"] or "").lower().startswith(("llama-server", "ollama")):
                    try:
                        mi = p.memory_info()
                        tot += getattr(mi, "private", mi.rss)
                    except Exception:
                        pass
            self.peak = max(self.peak, tot / 2**30)
            time.sleep(0.5)


def main():
    tools = gen.mcp_tools_for_ollama()
    rows, timing = [], []
    # A) 요청 5종: LLM 확장 → (LLM 언로드) → 1024x1024 생성. 한글 포스터는 두 모델 모두.
    for key, req in TESTS:
        cb.start_comfy()
        cb.free_comfy_memory()
        m = LLMMem()
        m.start()
        args, secs, called = gen.expand(req, LLM, tools)
        m.stop = True
        m.join()
        models = ["z-image-turbo", "flux2-klein-4b"] if key == "poster_ko" else ["z-image-turbo"]
        for mi, model in enumerate(models):
            if mi > 0:
                cb.free_comfy_memory()
            r = cb.generate(args.get("prompt_en", req), args.get("negative", ""), 1024, 1024, 0, 1234, model,
                            extra_meta={"request_ko": req, "llm": LLM, "llm_expand_sec": round(secs, 2),
                                        "tool_called_by_llm": called})
            rows.append({"test": key, "request": req, "model": model, "llm_expand_sec": round(secs, 1),
                         "llm_peak_mem_gb": round(m.peak, 1), "tool_called": called,
                         "gen_sec_cold": r["elapsed_sec"], "peak_comfy_gb": r["peak_comfy_process_gb"],
                         "peak_sys_ram_gb": r["peak_system_ram_used_gb"], "peak_gpu_shared_gb": r["peak_gpu_shared_gb"],
                         "image": r["image"], "prompt_en": r["prompt_en"]})
            print("A", json.dumps(rows[-1], ensure_ascii=False), flush=True)
    # B) 모델별 콜드 1회 + 웜 2회 (같은 프롬프트, 다른 시드), LLM 없이
    p = "A cozy bookstore interior at golden hour, wooden shelves, warm light, cinematic, highly detailed"
    cb.unload_llm()
    for model in ("flux2-klein-4b", "z-image-turbo"):
        cb.free_comfy_memory()
        for i, seed in enumerate((11, 22, 33)):
            r = cb.generate(p, "", 1024, 1024, 0, seed, model, unload_llm_first=False)
            timing.append({"model": model, "run": "cold" if i == 0 else f"warm{i}", "cold_flag": r["cold_start"],
                           "sec": r["elapsed_sec"], "peak_comfy_gb": r["peak_comfy_process_gb"],
                           "peak_sys_ram_gb": r["peak_system_ram_used_gb"], "peak_gpu_shared_gb": r["peak_gpu_shared_gb"],
                           "image": r["image"]})
            print("B", json.dumps(timing[-1], ensure_ascii=False), flush=True)
    cb.free_comfy_memory()
    out = os.path.join(cb.OUT_ROOT, f"benchmark_{datetime.datetime.now():%Y%m%d_%H%M}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"requests": rows, "cold_warm": timing}, f, ensure_ascii=False, indent=2)
    print("saved", out)


if __name__ == "__main__":
    main()
