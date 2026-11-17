"""gen.py "한국어 요청"
Gemma 4(Ollama)가 요청을 해석해 영문 이미지 프롬프트로 확장 → imagegen-mcp 의 generate_image 도구 호출 → 결과 경로 출력.
옵션: --model z-image-turbo|flux2-klein-4b  --llm gemma4:26b  --seed N  --direct(MCP 를 거치지 않고 직접 호출)"""
import argparse
import asyncio
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

SYSTEM = """You are an image-prompt engineer. Interpret the user's Korean request and call the generate_image tool exactly once.
Rules for prompt_en (English, 60-120 words):
- Describe subject, style/medium, composition & camera angle, lighting, color palette, mood, level of detail.
- If the user wants text in the image (signs, posters, titles), put the EXACT text in double quotes, keep the original
  language and script (e.g. Korean Hangul stays as Hangul: "봄 축제"), and say where and in what typography it appears.
- Do not add text the user did not ask for.
Size: square → 1024x1024; landscape/가로 → 1344x768; portrait/세로/poster/포스터 → 832x1216 (unless the user gives a size).
Keep steps=0 and seed=-1 unless the user specifies them. negative: short list of things to avoid (may be empty)."""


async def mcp_session_call(args: dict, tools_out: list):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(HERE, "imagegen_mcp.py")])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if args is None:                       # 도구 목록만 조회
                tl = await s.list_tools()
                tools_out.extend(tl.tools)
                return None
            res = await s.call_tool("generate_image", args)
            texts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
            if getattr(res, "isError", False) or getattr(res, "is_error", False):
                raise RuntimeError("MCP 도구 오류: " + " ".join(texts))
            return json.loads(texts[0])


def mcp_tools_for_ollama():
    """MCP 서버의 도구 스키마를 그대로 Ollama tools 형식으로 변환 (도구 정의를 한 곳에서만 관리)."""
    tools = []
    asyncio.run(mcp_session_call(None, tools))
    out = []
    for t in tools:
        if t.name != "generate_image":
            continue
        schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)
        out.append({"type": "function", "function": {"name": t.name, "description": t.description,
                                                     "parameters": schema}})
    return out


REF_SYSTEM = """You are an image-prompt engineer for FLUX.2 Klein, which takes reference images.
The user attached {n} reference image(s); they are "image 1"{more} in the order given. Look at them carefully.
Call the generate_image tool exactly once. prompt_en must be an English instruction (40-100 words) that:
- Refers to the references explicitly as "image 1", "image 2" ... and states what to KEEP from each
  (e.g. the person's face, hairstyle and identity from image 1; the outfit from image 2; the style/colors of image 3).
- Describes what to CHANGE or CREATE: scene, pose, clothing, style, lighting, composition, camera angle.
- If the user only gives a scene, keep the subject of image 1 unchanged and place it in that scene.
- Keep any text the user wants in the image in double quotes in its original language.
Leave width/height at 0 to keep the reference's aspect ratio unless the user asks for a shape
(square 1024x1024, landscape 1344x768, portrait 832x1216). Keep steps=0 and seed=-1."""


def _b64(path, max_side=896):
    """Gemma 비전 입력용 축소 이미지."""
    import base64
    import io as _io
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = _io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def expand(request: str, llm: str, tools: list, images: list = None):
    """images: 참조 이미지 경로 목록. 있으면 LLM(비전)이 직접 보고 참조형 지시문을 작성."""
    t = time.time()
    user = {"role": "user", "content": request}
    system = SYSTEM
    if images:
        n = len(images)
        system = REF_SYSTEM.format(n=n, more="".join(f', "image {i}"' for i in range(2, n + 1)))
        user["images"] = [_b64(p) for p in images]
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": llm, "stream": False, "think": False, "tools": tools,
        "options": {"num_ctx": 8192, "temperature": 0.4},
        "messages": [{"role": "system", "content": system}, user]}, timeout=900).json()
    secs = time.time() - t
    if "error" in r:
        raise RuntimeError(r["error"])
    calls = r.get("message", {}).get("tool_calls") or []
    for c in calls:
        if c["function"]["name"] == "generate_image":
            a = c["function"]["arguments"]
            return (json.loads(a) if isinstance(a, str) else a), secs, True
    # 모델이 도구를 부르지 않고 글로 답한 경우: 그 글을 프롬프트로 사용
    return {"prompt_en": r.get("message", {}).get("content", request).strip()}, secs, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--model", default=None, help="z-image-turbo | flux2-klein-4b")
    ap.add_argument("--llm", default=os.environ.get("IMAGEGEN_LLM", "gemma4:26b"))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--direct", action="store_true", help="MCP 서버를 거치지 않고 백엔드를 직접 호출")
    ap.add_argument("--ref", action="append", default=[], help="참조 이미지 경로 (최대 3번 반복 가능)")
    a = ap.parse_args()

    if a.direct:
        sys.path.insert(0, HERE)
        import comfy_backend as cb
        props = {"prompt_en": {"type": "string"}, "negative": {"type": "string"}, "width": {"type": "integer"},
                 "height": {"type": "integer"}, "steps": {"type": "integer"}, "seed": {"type": "integer"}}
        tools = [{"type": "function", "function": {"name": "generate_image", "description": "Generate an image",
                                                   "parameters": {"type": "object", "properties": props,
                                                                  "required": ["prompt_en"]}}}]
    else:
        tools = mcp_tools_for_ollama()
    sys.path.insert(0, HERE)
    import comfy_backend as cbm
    if cbm.comfy_alive():                     # 메모리 예산: 이미지 모델을 내린 뒤 LLM 을 올림
        cbm.free_comfy_memory()
    print(f"[1/2] {a.llm} 가 요청을 해석·확장 중...", flush=True)
    refs = [os.path.abspath(p) for p in a.ref][:3]
    args, llm_secs, called = expand(a.request, a.llm, tools, images=refs or None)
    if refs:
        args["refs"] = refs
        if not args.get("width") or not args.get("height"):
            args["width"], args["height"] = 0, 0
    if a.model:
        args["model"] = a.model
    if a.seed is not None:
        args["seed"] = a.seed
    args.pop("model", None) if args.get("model") not in (None, "z-image-turbo", "flux2-klein-4b") else None
    print(f"      프롬프트 확장 {llm_secs:.1f}초 · tool call={'예' if called else '아니오(본문 사용)'}")
    print("      prompt_en:", args.get("prompt_en", "")[:300])
    print("[2/2] 이미지 생성 중 (LLM 언로드 → ComfyUI)...", flush=True)
    if a.direct:
        res = cb.generate(**{k: v for k, v in args.items() if k in ("prompt_en", "negative", "width", "height",
                                                                    "steps", "seed", "model", "refs")},
                          extra_meta={"request_ko": a.request, "llm": a.llm, "llm_expand_sec": round(llm_secs, 2)})
    else:
        res = asyncio.run(mcp_session_call(args, []))
        meta_path = res["metadata"]                # 요청·LLM 정보를 메타데이터에 덧붙임
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta.update({"request_ko": a.request, "llm": a.llm, "llm_expand_sec": round(llm_secs, 2),
                     "tool_called_by_llm": called})
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"완료: {res['image']}")
    print(f"      생성 {res['elapsed_sec']}초 (콜드 스타트: {res['cold_start']}) · {res['model']} · seed {res['seed']}")
    print(f"      메타데이터: {res['metadata']}")


if __name__ == "__main__":
    main()
