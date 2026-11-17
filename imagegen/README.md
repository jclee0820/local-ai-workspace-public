# 로컬 이미지 생성 환경 (Gemma 4 + ComfyUI)

한국어 요청 → **Gemma 4 26B(Ollama)**가 영문 프롬프트로 확장하고 `generate_image` 도구 호출
→ **imagegen-mcp**(MCP 서버) → **ComfyUI(PyTorch XPU, Intel Arc B390)** → `outputs/YYYYMMDD/`에 PNG + 메타데이터 JSON

## 사용법
```
cd <설치 폴더>\imagegen
..\.venv\Scripts\python.exe gen.py "벚꽃이 핀 경복궁 야경을 수채화 느낌으로, 가로로 긴 그림"
..\.venv\Scripts\python.exe gen.py "카페 간판 사진" --model flux2-klein-4b --seed 7
```
- `--model z-image-turbo`(기본) | `flux2-klein-4b`, `--seed N`, `--llm gemma4:26b`, `--direct`(MCP 생략)
- **참조 이미지**: `--ref 사진1.png --ref 사진2.png` (최대 3장, 순서대로 image 1·2·3).
  FLUX.2 Klein 4B로 자동 전환되고(Z-Image는 참조 미지원), Gemma 4가 참조 이미지를 직접 보고 "image 1의 인물 유지, …" 형태의 지시문을 씁니다.
  출력 크기는 기본으로 첫 참조 이미지 비율(약 1MP)을 따릅니다. 워크플로: `workflows/flux2_klein_4b_edit_api.json`
- Intel GPU 장치 손실(`DEVICE_LOST`)이 로그에 찍히면 ComfyUI를 자동으로 다시 띄우고 한 번 재시도합니다.
- ComfyUI가 꺼져 있으면 자동으로 띄웁니다(로그: `comfyui.log`).

## 구성 파일
| 파일 | 역할 |
|---|---|
| `gen.py` | CLI. Gemma 4 프롬프트 확장 → MCP 도구 호출 → 결과 경로 출력 |
| `imagegen_mcp.py` | MCP 서버(stdio). 도구 `generate_image`, `list_image_models` |
| `comfy_backend.py` | ComfyUI `/prompt` 호출, 메모리 관리(LLM↔이미지 모델 교대), 측정, 저장 |
| `workflows/*.json` | ComfyUI **API 포맷** 워크플로 (공식 템플릿 값 기준) |
| `benchmark.py` | 테스트 5종 + 콜드/웜 벤치마크 |
| `setup_comfyui.ps1`, `download_models.ps1` | 재설치용 스크립트 |

## 메모리 정책 (32GB 공유 메모리)
Gemma 4 26B(약 21GB)와 이미지 모델(약 15~24GB)은 **동시에 올릴 수 없습니다.**
- 이미지 생성 직전: Ollama 모델을 `keep_alive: 0`으로 즉시 내림
- LLM 호출 직전(`gen.py`): ComfyUI `/free`로 이미지 모델을 내림
- 그래서 `gen.py`로 한 장씩 만들면 매번 **콜드 스타트**입니다(약 50~90초). 같은 모델로 여러 장을 연속 생성할 때만 웜 상태가 유지됩니다.
- 확산 모델은 기본으로 **FP8로 적재**합니다(Z-Image 웜 생성 85초 → 31초). bf16을 쓰려면 `set IMAGEGEN_WEIGHT_DTYPE=default`.

## 다른 MCP 클라이언트에 등록 (예: Claude Desktop 등)
```json
{"mcpServers": {"imagegen": {"command": "<설치 폴더>\\.venv\\Scripts\\python.exe",
  "args": ["<설치 폴더>\\imagegen\\imagegen_mcp.py"]}}}
```

## (선택) Open WebUI 연동 절차
출처: Open WebUI 공식 문서(ComfyUI 페이지), GitHub README.
1. 설치(Python 3.12, 별도 가상환경 권장): `pip install open-webui` → 실행 `open-webui serve` → http://localhost:8080
2. ComfyUI 실행: `ComfyUI\.venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188`
3. Open WebUI: **Settings > Admin > Images** → **Image Generation** 켜기 → **Image Generation Engine** = `ComfyUI`
4. **Base URL** = `http://127.0.0.1:8188/` (새로고침 아이콘으로 연결 확인)
5. **ComfyUI Workflow** → Upload → `workflows/z_image_turbo_api.json` (또는 `flux2_klein_4b_api.json`)
6. **ComfyUI Workflow Nodes** 매핑

| 항목 | Z-Image-Turbo (key / node id) | FLUX.2 Klein 4B (key / node id) |
|---|---|---|
| Prompt | `text` / `27` | `text` / `74` |
| Model | `unet_name` / `28` | `unet_name` / `70` |
| Width | `width` / `13` | `width` / `66,62` |
| Height | `height` / `13` | `height` / `66,62` |
| Steps | `steps` / `3` | `steps` / `62` |
| Seed | `seed` / `3` | `noise_seed` / `73` |

7. 채팅 입력창 **+ > Image** 켜고 요청
- 주의: Open WebUI 경로는 위 메모리 정책(LLM 언로드)을 거치지 않습니다. 채팅 모델이 올라간 채로 이미지를 만들면 메모리가 부족할 수 있으니,
  Open WebUI에서는 가벼운 채팅 모델(예: `gemma4:e4b`, 약 6.6GB)을 쓰거나 Ollama `keep_alive`를 짧게 설정하세요.
