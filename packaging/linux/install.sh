#!/usr/bin/env bash
# 로컬 AI 작업실 — 리눅스 서버 설치 스크립트 (Docker 불필요, 네이티브 Python venv + Ollama + systemd)
# 사용: sudo ./install.sh [옵션]
#   --prefix DIR         설치 위치 (기본 /opt/local-ai-workspace)
#   --port N             웹 포트 (기본 8501)
#   --model NAME|auto    언어 모델 (기본 auto: 메모리 32GB↑ gemma4:26b, 18GB↑ qwen3:14b, 그 외 qwen3:8b)
#   --password PW        접속 비밀번호 (서버를 여러 사람이 쓸 때 권장)
#   --open-firewall      ufw/firewalld 에 포트 개방
#   --with-imagegen      이미지 생성(ComfyUI) 설치  --gpu cuda|xpu|cpu (기본 cuda)
#   --with-hwp           구형 .hwp 읽기 도구(pyhwp, AGPL) 설치
#   --skip-ollama        Ollama 설치·모델 받기 생략 (이미 다른 서버의 Ollama 를 쓸 때: --ollama-url 지정)
#   --ollama-url URL     Ollama 주소 (기본 http://127.0.0.1:11434)
#   --offline-wheels DIR 인터넷 없는 서버: 미리 받아 둔 pip 휠 폴더 사용
set -euo pipefail

PREFIX=/opt/local-ai-workspace; PORT=8501; MODEL=auto; PASSWORD=""; OPEN_FW=0
WITH_IMG=0; GPU=cuda; WITH_HWP=0; SKIP_OLLAMA=0; OLLAMA_URL="http://127.0.0.1:11434"; WHEELS=""; MODEL_SET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --model) MODEL="$2"; [[ "$2" != auto ]] && MODEL_SET=1; shift 2;;
    --password) PASSWORD="$2"; shift 2;;
    --open-firewall) OPEN_FW=1; shift;;
    --with-imagegen) WITH_IMG=1; shift;;
    --gpu) GPU="$2"; shift 2;;
    --with-hwp) WITH_HWP=1; shift;;
    --skip-ollama) SKIP_OLLAMA=1; shift;;
    --ollama-url) OLLAMA_URL="$2"; shift 2;;
    --offline-wheels) WHEELS="$2"; shift 2;;
    -h|--help) sed -n '2,15p' "$0"; exit 0;;
    *) echo "알 수 없는 옵션: $1"; exit 1;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"     # 압축을 푼 패키지 최상위
SVC_USER=lai
log() { echo -e "\n\033[1;36m[$(date +%H:%M:%S)] $*\033[0m"; }
die() { echo -e "\033[1;31m오류: $*\033[0m" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "관리자 권한이 필요합니다: sudo ./install.sh"
[[ -f "$SRC/app/app.py" ]] || die "패키지 구조가 올바르지 않습니다 ($SRC/app/app.py 없음)"

# ---------------------------------------------------------------- 1. 시스템 패키지
log "1/8 시스템 패키지 확인 (Python 3.10~3.13, 한글 글꼴, curl)"
PKG=""
if command -v apt-get >/dev/null; then PKG=apt
elif command -v dnf >/dev/null; then PKG=dnf
elif command -v yum >/dev/null; then PKG=yum; fi
PY=""
for c in python3.12 python3.13 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)'; then PY=$(command -v "$c"); break; fi
done
case "$PKG" in
  apt)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y curl ca-certificates fonts-nanum fontconfig pciutils zstd
    if [[ -z "$PY" ]]; then apt-get install -y python3 python3-venv python3-pip; PY=$(command -v python3); fi
    PYV=$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    apt-get install -y "python${PYV}-venv" 2>/dev/null || apt-get install -y python3-venv || true
    ;;
  dnf|yum)
    $PKG install -y curl ca-certificates fontconfig pciutils zstd || true
    $PKG install -y google-nanum-fonts-common naver-nanum-gothic-fonts 2>/dev/null || $PKG install -y google-noto-sans-cjk-ttc-fonts 2>/dev/null || true
    if [[ -z "$PY" ]]; then $PKG install -y python3.12 python3.12-pip 2>/dev/null || $PKG install -y python3 python3-pip; fi
    for c in python3.12 python3.11 python3; do command -v "$c" >/dev/null && { PY=$(command -v "$c"); break; }; done
    ;;
  *) echo "패키지 관리자를 찾지 못했습니다. Python 3.10+ 와 한글 글꼴(나눔고딕)이 설치되어 있어야 합니다.";;
esac
[[ -n "$PY" ]] || die "Python 3.10~3.13 을 찾지 못했습니다."
"$PY" -c 'import sys; exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)' || die "Python 버전이 맞지 않습니다: $("$PY" -V)"
log "Python: $("$PY" -V)"

# ---------------------------------------------------------------- 2. 파일 복사 · 사용자
log "2/8 $PREFIX 에 프로그램 복사"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$PREFIX/home" --shell /usr/sbin/nologin "$SVC_USER"
mkdir -p "$PREFIX"
# 사용자 데이터(보관함·지식보관함·양식·설정)는 업데이트 때 덮어쓰지 않음
if command -v rsync >/dev/null; then
  rsync -a --exclude 'outputs/' --exclude 'chroma_db/' --exclude 'model.json' --exclude 'icons/settings.json' "$SRC/app/" "$PREFIX/app/"
else
  mkdir -p "$PREFIX/app"; cp -a "$SRC/app/." "$PREFIX/app/"
fi
cp -a "$SRC/docs" "$PREFIX/" 2>/dev/null || true
cp -a "$SRC/linux/uninstall.sh" "$PREFIX/" && chmod +x "$PREFIX/uninstall.sh"
mkdir -p "$PREFIX/app/outputs" "$PREFIX/hf"

# ---------------------------------------------------------------- 3. Python 가상환경
log "3/8 Python 가상환경과 라이브러리 설치 (수 분 소요)"
[[ -x "$PREFIX/venv/bin/python" ]] || "$PY" -m venv "$PREFIX/venv"
VPY="$PREFIX/venv/bin/python"
PIPX=(-m pip install --disable-pip-version-check)
if [[ -n "$WHEELS" ]]; then PIPX+=(--no-index --find-links "$WHEELS"); fi
"$VPY" "${PIPX[@]}" --upgrade pip wheel
# 임베딩은 CPU 전용 → PyTorch CPU 판 (CUDA 판 수 GB 다운로드 방지)
TV="$(cat "$SRC/TORCH_VERSION" 2>/dev/null || true)"
TSPEC="torch${TV:+==$TV}"
if [[ -n "$WHEELS" ]]; then "$VPY" "${PIPX[@]}" "$TSPEC"
else "$VPY" "${PIPX[@]}" "$TSPEC" --index-url https://download.pytorch.org/whl/cpu \
     || "$VPY" "${PIPX[@]}" torch --index-url https://download.pytorch.org/whl/cpu; fi
"$VPY" "${PIPX[@]}" -r "$SRC/requirements-linux.txt"
if [[ $WITH_HWP -eq 1 ]]; then
  log ".hwp 읽기 도구(pyhwp) 설치 — AGPL-3.0 라이선스"
  "$VPY" "${PIPX[@]}" pyhwp || echo "pyhwp 설치 실패: .hwp 는 HWPX/PDF 로 변환해 올리도록 안내됩니다."
fi

# ---------------------------------------------------------------- 4. Ollama
GPU_ENV=""
GPUS="$(lspci 2>/dev/null | grep -iE 'VGA|3D|Display' || true)"
if [[ -n "$GPUS" ]] && ! grep -qi nvidia <<<"$GPUS" && grep -qi intel <<<"$GPUS"; then
  GPU_ENV=$'Environment="OLLAMA_VULKAN=1"\nEnvironment="OLLAMA_IGPU_ENABLE=1"'   # Intel Arc 내장 GPU 가속 (Windows 에서 검증된 설정)
fi
if [[ $SKIP_OLLAMA -eq 0 ]]; then
  log "4/8 Ollama 설치 (공식 설치 스크립트) · 127.0.0.1 에서만 열림"
  if ! command -v ollama >/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  mkdir -p /etc/systemd/system/ollama.service.d
  {
    echo "[Service]"
    echo 'Environment="OLLAMA_HOST=127.0.0.1:11434"'
    echo 'Environment="OLLAMA_KEEP_ALIVE=10m"'
    if [[ -n "$GPU_ENV" ]]; then echo "$GPU_ENV"; fi
  } > /etc/systemd/system/ollama.service.d/local-ai.conf
  systemctl daemon-reload; systemctl enable --now ollama; systemctl restart ollama
  for i in $(seq 1 30); do curl -fs http://127.0.0.1:11434 >/dev/null && break; sleep 1; done
  if [[ "$MODEL" == auto ]]; then
    MEM=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
    if (( MEM >= 30 )); then MODEL=gemma4:26b; elif (( MEM >= 18 )); then MODEL=qwen3:14b; else MODEL=qwen3:8b; fi
    log "메모리 ${MEM}GB → 언어 모델 $MODEL"
  fi
  log "언어 모델 $MODEL 받는 중 (수 GB, 수십 분 걸릴 수 있음)"
  ollama pull "$MODEL"
else
  log "4/8 Ollama 설치 생략 ($OLLAMA_URL 사용)"
  if [[ "$MODEL" == auto ]]; then MODEL=gemma4:26b; fi
fi
if [[ $MODEL_SET -eq 1 || ! -f "$PREFIX/app/model.json" ]]; then echo "{\"model\": \"$MODEL\"}" > "$PREFIX/app/model.json"; fi

# ---------------------------------------------------------------- 5. 임베딩 모델 미리 받기
log "5/8 문서 검색용 임베딩 모델 미리 받기 (CPU)"
chown -R "$SVC_USER:$SVC_USER" "$PREFIX"
runuser -u "$SVC_USER" -- env HF_HOME="$PREFIX/hf" "$VPY" -c \
  "from sentence_transformers import SentenceTransformer as S; S('paraphrase-multilingual-MiniLM-L12-v2', device='cpu'); print('ok')" \
  || echo "임베딩 모델을 지금 받지 못했습니다. 처음 지식보관함을 쓸 때 다시 받습니다."

# ---------------------------------------------------------------- 6. 이미지 생성 (선택)
if [[ $WITH_IMG -eq 1 ]]; then
  log "6/8 이미지 생성(ComfyUI, GPU=$GPU) 설치 — 모델 포함 약 20GB"
  runuser -u "$SVC_USER" -- env HF_HOME="$PREFIX/hf" bash "$PREFIX/app/imagegen/setup_comfyui.sh" --python "$PY" --gpu "$GPU"
  runuser -u "$SVC_USER" -- bash "$PREFIX/app/imagegen/download_models.sh"
else
  log "6/8 이미지 생성 설치 생략 (나중에: sudo $0 --with-imagegen)"
fi

# ---------------------------------------------------------------- 7. 서비스 등록
log "7/8 systemd 서비스 등록 (local-ai-workspace)"
ENVF=/etc/local-ai-workspace.env
OLD_PW=""
if [[ -f "$ENVF" ]]; then OLD_PW="$(grep '^LAI_PASSWORD=' "$ENVF" | head -n1 | cut -d= -f2- || true)"; fi
if [[ -z "$PASSWORD" ]]; then PASSWORD="$OLD_PW"; fi        # 재설치 때 기존 비밀번호 유지
umask 077
{
  echo "OLLAMA_URL=$OLLAMA_URL"
  echo "HF_HOME=$PREFIX/hf"
  if [[ -n "$PASSWORD" ]]; then echo "LAI_PASSWORD=$PASSWORD"; fi
} > "$ENVF"
umask 022
cat > /etc/systemd/system/local-ai-workspace.service <<EOF
[Unit]
Description=Local AI Workspace (Streamlit)
After=network-online.target ollama.service
Wants=network-online.target

[Service]
User=$SVC_USER
WorkingDirectory=$PREFIX/app
EnvironmentFile=$ENVF
ExecStart=$PREFIX/venv/bin/python -m streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true --browser.gatherUsageStats false --server.maxUploadSize 500
Restart=on-failure
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now local-ai-workspace
systemctl restart local-ai-workspace

if [[ $OPEN_FW -eq 1 ]]; then
  if command -v ufw >/dev/null; then ufw allow "$PORT/tcp" || true
  elif command -v firewall-cmd >/dev/null; then firewall-cmd --permanent --add-port="$PORT/tcp" && firewall-cmd --reload || true; fi
fi

# ---------------------------------------------------------------- 8. 확인
log "8/8 동작 확인"
ok=0
for i in $(seq 1 40); do
  if [[ "$(curl -fs "http://127.0.0.1:$PORT/_stcore/health" || true)" == *ok* ]]; then ok=1; break; fi; sleep 2
done
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [[ $ok -eq 1 ]]; then
  echo -e "\n\033[1;32m설치 완료!\033[0m  브라우저에서  http://${IP:-서버주소}:$PORT  로 접속하세요."
  [[ -n "$PASSWORD" ]] || echo "※ 접속 비밀번호가 없습니다. 여러 사람이 접근하는 서버라면 --password 로 다시 설치하거나 $ENVF 에 LAI_PASSWORD=... 를 넣고 'systemctl restart local-ai-workspace'."
else
  echo "웹 화면이 아직 응답하지 않습니다. 확인: journalctl -u local-ai-workspace -n 50"
fi
echo "관리: systemctl status|restart local-ai-workspace · 로그: journalctl -u local-ai-workspace -f · 제거: sudo $PREFIX/uninstall.sh"
