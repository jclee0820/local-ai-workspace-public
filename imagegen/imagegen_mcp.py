"""imagegen-mcp: 로컬 이미지 생성 MCP 서버 (stdio).
도구: generate_image(prompt_en, negative, width, height, steps, seed, model)
→ ComfyUI /prompt API 호출 → ./outputs/YYYYMMDD/ 에 PNG + 메타데이터 JSON 저장.
실행: python imagegen_mcp.py   (MCP 클라이언트가 stdio 로 연결)"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_backend as cb  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

server = MCPServer(name="imagegen-mcp", version="1.0.0",
                   instructions="Local text-to-image generation (ComfyUI on Intel Arc). Prompts must be in English.")


@server.tool(description="Generate one image locally from an English prompt. Returns saved PNG path and metadata. "
                         "model: 'z-image-turbo' (default, better text rendering) or 'flux2-klein-4b' (faster). "
                         "width/height are rounded to multiples of 16 (0 = keep the first reference's aspect ratio). "
                         "steps=0 uses the model default. seed=-1 is random. refs: up to 3 local reference image paths "
                         "(person, object, style); when given, FLUX.2 Klein is used and the prompt should refer to them "
                         "as 'image 1', 'image 2', ...")
async def generate_image(prompt_en: str, negative: str = "", width: int = 1024, height: int = 1024,
                         steps: int = 0, seed: int = -1, model: str = cb.DEFAULT_MODEL, refs: list[str] = None) -> str:
    res = await asyncio.to_thread(cb.generate, prompt_en, negative, width, height, steps, seed, model, True, None, refs)
    return json.dumps(res, ensure_ascii=False)


@server.tool(description="List available local image models with default steps and license.")
async def list_image_models() -> str:
    return json.dumps({k: {"default_steps": v["steps"], "license": v["license"], "files": v["files"]}
                       for k, v in cb.MODELS.items()}, ensure_ascii=False)


if __name__ == "__main__":
    server.run("stdio")
