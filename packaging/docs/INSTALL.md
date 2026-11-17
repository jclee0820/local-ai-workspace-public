# 로컬 AI 작업실 — 서버 설치 안내 (v{VERSION})

외부 클라우드 없이 서버 한 대에서 동작하는 생성형 AI 업무 도구입니다. Docker·WSL 없이 **네이티브 Python 가상환경 + Ollama** 로 설치되며,
설치 후에는 직원들이 브라우저로 `http://서버주소:8501` 에 접속해 사용합니다.

## 1. 서버 요구 사항

| 항목 | 최소 | 권장 |
|---|---|---|
| CPU | x86-64 4코어 | 8코어 이상 |
| 메모리 | 16GB (qwen3:8b) | 32GB 이상 (gemma4:26b) |
| GPU | 없어도 동작(느림) | NVIDIA 16GB↑ 또는 Intel Arc |
| 디스크 | 30GB | 80GB (이미지 생성 포함 시 +25GB) |
| OS | Ubuntu 22.04/24.04, Rocky·RHEL 9 / Windows Server 2019·2022·2025 | |
| Python | 3.10 ~ 3.13 (Windows 는 없으면 3.12 자동 설치) | **3.12** (라이브러리 버전 검증 기준. 3.10·3.11·3.13 은 미검증 — Ubuntu 22.04 는 python3.12 를 먼저 설치 권장) |
| 인터넷 | 설치할 때만 필요 (모델·라이브러리 다운로드) | |

- 언어 모델은 `auto` 로 두면 메모리에 맞춰 고릅니다: 32GB↑ `gemma4:26b`, 18GB↑ `qwen3:14b`, 그 외 `qwen3:8b`.
- 동시에 여러 명이 쓰면 요청이 차례로 처리됩니다(모델 1개를 GPU에 올려 공유). 10명 이하 부서 단위에 맞습니다.

## 2. 리눅스 서버

```bash
tar -xzf LocalAIWorkspace-{VERSION}-linux.tar.gz
cd LocalAIWorkspace-{VERSION}-linux
sudo ./linux/install.sh --password '접속비밀번호' --open-firewall
```

설치가 끝나면 화면에 접속 주소가 나옵니다. 주요 옵션:

| 옵션 | 설명 |
|---|---|
| `--prefix /opt/local-ai-workspace` | 설치 위치 |
| `--port 8501` | 웹 포트 |
| `--model auto` | `gemma4:26b`, `qwen3:14b` 등 직접 지정 가능 |
| `--with-imagegen --gpu cuda\|xpu\|cpu` | 이미지 생성(ComfyUI, FLUX.2 Klein·Z-Image-Turbo) 설치 |
| `--with-hwp` | 구형 `.hwp` 읽기(pyhwp, **AGPL-3.0**) — 없으면 HWPX/PDF 로 올리도록 안내 |
| `--skip-ollama --ollama-url http://gpu-server:11434` | 다른 서버의 Ollama 사용 |
| `--offline-wheels DIR` | 인터넷 없는 서버 (아래 7절) |

관리 명령:
```bash
systemctl status local-ai-workspace      # 상태
journalctl -u local-ai-workspace -f      # 로그
sudo systemctl restart local-ai-workspace
sudo /opt/local-ai-workspace/uninstall.sh            # 제거 (데이터는 보존)
```
- 설정 파일: `/etc/local-ai-workspace.env` (`LAI_PASSWORD`, `OLLAMA_URL`). 고친 뒤 `systemctl restart local-ai-workspace`.
- 서비스는 전용 계정 `lai` 로 실행되고, Ollama 는 `127.0.0.1` 에서만 열립니다(외부 직접 접근 차단).
- Intel 내장 GPU만 있는 서버는 Ollama 에 `OLLAMA_VULKAN=1`, `OLLAMA_IGPU_ENABLE=1` 을 자동으로 넣습니다.

## 3. Windows Server

관리자 PowerShell 에서:
```powershell
Expand-Archive LocalAIWorkspace-{VERSION}-windows-server.zip C:\Setup
cd C:\Setup\LocalAIWorkspace-{VERSION}-windows-server
powershell -ExecutionPolicy Bypass -File .\windows-server\install.ps1 -Password "접속비밀번호" -OpenFirewall
```

| 옵션 | 설명 |
|---|---|
| `-InstallDir C:\LocalAIWorkspace` | 설치 위치 |
| `-Port 8501`, `-Model auto` | 리눅스와 같음 |
| `-WithImageGen -Gpu cuda\|xpu\|cpu` | 이미지 생성 설치 (NVIDIA 는 PyTorch `cu128` 판 사용 — 서버 드라이버가 CUDA 12.8 이상인지 확인) |
| `-SkipOllama -OllamaUrl ...` | 다른 Ollama 사용 |
| `-NoService` | 자동 시작 등록 없이 설치만 (시험용) |

- Python 3.12 가 없으면 python.org 공식 설치 파일로 자동 설치합니다.
- Ollama 는 서비스용 단독 실행판(`ollama-windows-amd64.zip`)을 설치 폴더 안에 두고, 모델도 `설치폴더\ollama\models` 에 받습니다.
- 부팅하면 작업 스케줄러의 `LocalAI-Ollama`, `LocalAI-Workspace` 가 SYSTEM 계정으로 자동 실행됩니다(로그인 불필요, 실패 시 1분 뒤 재시작).
- 로그: `설치폴더\workspace.log`, `설치폴더\ollama\server.log`. 제거: `설치폴더\uninstall.ps1` (데이터 보존, `-RemoveData` 로 전부 삭제).
- **`.hwp` 변환**: 한컴오피스가 설치된 서버에서도 SYSTEM 계정(비대화형)으로는 한글 자동화가 막힐 수 있습니다. 이 경우 2분 안에 스스로 포기하고
  "HWPX 또는 PDF로 저장해 올려주세요"라고 안내합니다. HWPX·PDF·DOCX 는 한컴오피스 없이 읽습니다.

## 4. 처음 접속한 뒤

1. 비밀번호를 넣고 들어가면 **AI 비서** 화면이 열립니다. 📎로 문서를 첨부하고 말로 요청하면 됩니다.
2. 결과물은 모두 **작업 보관함**에 자동 저장됩니다(서버의 모든 사용자가 함께 봅니다 — 부서 공용 보관함).
3. 자세한 사용법은 `docs/사용_가이드.md` 를 보세요.

## 5. 보안 참고

- 접속 비밀번호는 한 개(공용)입니다. 사용자별 계정·권한이 필요하면 사내 SSO 를 앞단 프록시(nginx 등)로 붙이는 것을 권장합니다.
- 문서·질문은 서버 밖으로 나가지 않습니다. 단, **웹페이지 만들기(위키백과 조사)**, **실시간 웹 검색** 기능을 켜면 그 검색어는 인터넷으로 나갑니다.
- HTTPS 가 필요하면 nginx/IIS 역방향 프록시에서 인증서를 붙이세요(Streamlit 은 WebSocket 을 쓰므로 프록시에 WebSocket 전달 설정 필요).

## 6. 업데이트

새 패키지를 풀고 같은 설치 명령을 다시 실행하면 됩니다. 작업 보관함(`outputs`), 지식보관함(`chroma_db`), 선택한 모델(`model.json`),
업로드한 양식(`templates`), 접속 비밀번호는 그대로 유지됩니다.

## 7. 인터넷이 없는 서버 (폐쇄망)

인터넷이 되는 같은 OS·같은 Python 버전 PC 에서:
```bash
python3.12 -m pip download -d wheels -r requirements-linux.txt
python3.12 -m pip download -d wheels torch==$(cat TORCH_VERSION) --index-url https://download.pytorch.org/whl/cpu
```
`wheels` 폴더와 함께 Ollama(리눅스: 공식 tgz, Windows: `ollama-windows-amd64.zip`), 모델 폴더(`ollama pull` 후 `~/.ollama/models` 또는
`OLLAMA_MODELS` 폴더), 임베딩 모델(`HF_HOME` 폴더)을 옮긴 뒤 `--offline-wheels wheels --skip-ollama` 로 설치하고 Ollama 는 수동 배치합니다.

## 8. 구성 요소 라이선스

| 구성 | 라이선스 |
|---|---|
| Ollama | MIT |
| Gemma 4 | Apache-2.0 (`ollama show` 라이선스 필드로 확인, 2026-11-11) |
| Qwen3 | Apache-2.0 (미확인 — 설치 후 `ollama show qwen3:14b --license` 로 확인) |
| 임베딩 paraphrase-multilingual-MiniLM-L12-v2 | Apache-2.0 |
| FLUX.2 Klein 4B / Z-Image-Turbo (선택) | Apache-2.0 |
| ComfyUI (선택) | GPL-3.0 (별도 프로그램으로 실행) |
| 아이콘 Lucide·Tabler·Phosphor·Bootstrap·Heroicons | ISC/MIT (`app/icons/LICENSES.md`) |
| pyhwp (선택) | AGPL-3.0 |
| 슬라이드 테마의 로고·배경 그림 | 포함하지 않음 (원하면 `slide_themes/` 에 직접 추가) |
