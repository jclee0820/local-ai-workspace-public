"""FP8 가중치(weight_dtype=fp8_e4m3fn) 적용 시 콜드/웜 시간·메모리 비교."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_backend as cb

orig = cb.load_workflow


def fp8_workflow(model):
    wf = orig(model)
    for n in wf.values():
        if n["class_type"] == "UNETLoader":
            n["inputs"]["weight_dtype"] = "fp8_e4m3fn"
    return wf


cb.load_workflow = fp8_workflow
cb.unload_llm()
cb.start_comfy()
p = "A cozy bookstore interior at golden hour, wooden shelves, warm light, cinematic, highly detailed"
res = []
for model in ("flux2-klein-4b", "z-image-turbo"):
    cb.free_comfy_memory()
    for i, seed in enumerate((11, 22, 33)):
        r = cb.generate(p, "", 1024, 1024, 0, seed, model, unload_llm_first=False, extra_meta={"weight_dtype": "fp8_e4m3fn"})
        res.append({"model": model, "run": "cold" if i == 0 else f"warm{i}", "sec": r["elapsed_sec"],
                    "comfy_gb": r["peak_comfy_process_gb"], "sys_gb": r["peak_system_ram_used_gb"],
                    "gpu_gb": r["peak_gpu_shared_gb"], "image": r["image"]})
        print(json.dumps(res[-1], ensure_ascii=False), flush=True)
cb.free_comfy_memory()
json.dump(res, open(os.path.join(cb.OUT_ROOT, "benchmark_fp8.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
