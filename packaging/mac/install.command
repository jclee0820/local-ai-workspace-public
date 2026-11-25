#!/bin/bash
# 로컬 AI 작업실 — 맥북 설치 (이 파일을 더블클릭하면 터미널 창에서 자동으로 진행됩니다)
# 관리자 권한(암호)이 필요 없고, 모두 홈 폴더 안(~/LocalAIWorkspace)에 설치됩니다.
# 하는 일: ① Python(uv) ② 라이브러리 ③ Ollama ④ 언어 모델(메모리에 맞춰 자동) ⑤ 임베딩 모델·한글 글꼴 ⑥ 실행 아이콘
# 실패해도 이 파일을 다시 더블클릭하면 이어서 진행합니다.
set -uo pipefail
cd "$(dirname "$0")" || exit 1
SRC="$(pwd)"
DEST="$HOME/LocalAIWorkspace"
mkdir -p "$DEST"
exec > >(tee -a "$DEST/install.log") 2>&1

c() { printf '\033[1;36m%s\033[0m\n' "$*"; }
info() { echo "      $*"; }
pause_exit() { echo; read -r -p "Enter 키를 누르면 창이 닫힙니다 " _ </dev/tty || true; exit "${1:-1}"; }
fail() {
  printf '\n\033[1;31m설치를 마치지 못했습니다: %s\033[0m\n' "$1"
  echo "인터넷 연결을 확인한 뒤, 이 '설치' 파일을 다시 더블클릭하면 이어서 진행합니다."
  echo "기록 파일: $DEST/install.log"
  pause_exit 1
}
ollama_alive() { curl -fs --max-time 3 http://127.0.0.1:11434 >/dev/null 2>&1; }

echo "=============================================================="
echo "  로컬 AI 작업실 설치 (인터넷 필요 · 수십 분 걸릴 수 있습니다)"
echo "  언어 모델을 받는 동안 이 창을 닫지 마세요."
echo "=============================================================="

[[ "$(uname -s)" == "Darwin" ]] || fail "맥(macOS) 전용 설치 파일입니다."
[[ -f "$SRC/app/app.py" ]] || fail "압축을 푼 폴더가 올바르지 않습니다 (app 폴더 없음). 압축을 먼저 풀고 폴더 안에서 실행해 주세요."
if [[ "$(uname -m)" != "arm64" ]]; then
  fail "Apple 실리콘(M1·M2·M3·M4…) 맥만 지원합니다. 인텔 맥은 필요한 라이브러리(PyTorch)가 더 이상 제공되지 않아 설치할 수 없습니다."
fi

MEM=$(( $(sysctl -n hw.memsize) / 1073741824 ))
if (( MEM >= 30 )); then MODEL=gemma4:26b; NEED=20
elif (( MEM >= 18 )); then MODEL=qwen3:14b; NEED=12
else MODEL=qwen3:8b; NEED=8; fi
if [[ -f "$DEST/app/model.json" ]]; then            # 다시 설치할 때는 쓰던 모델 유지
  OLD=$(sed -n 's/.*"model"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$DEST/app/model.json" | head -n1)
  [[ -n "$OLD" ]] && MODEL="$OLD"
fi
FREE=$(( $(df -k "$HOME" | awk 'NR==2 {print $4}') / 1048576 ))
info "이 맥 메모리 ${MEM}GB → 언어 모델 $MODEL · 남은 디스크 ${FREE}GB"

# ---------------------------------------------------------------- 1. 프로그램 파일
c "[1/6] 프로그램 파일 복사 ($DEST)"
# 사용자 데이터(보관함·지식보관함·설정)는 업데이트 때 덮어쓰지 않음
mkdir -p "$DEST/app"
rsync -a --exclude 'outputs/' --exclude 'chroma_db/' --exclude 'model.json' --exclude 'icons/settings.json' "$SRC/app/" "$DEST/app/" || fail "파일 복사 실패"
mkdir -p "$DEST/app/outputs" "$DEST/hf" "$DEST/mac" "$DEST/docs"
cp -f "$SRC/mac/"*.sh "$DEST/mac/" && chmod +x "$DEST/mac/"*.sh
cp -f "$SRC/requirements-mac.txt" "$SRC/TORCH_VERSION" "$SRC/VERSION" "$DEST/" 2>/dev/null
cp -f "$SRC/docs/"* "$DEST/docs/" 2>/dev/null

# ---------------------------------------------------------------- 2. Python
c "[2/6] Python 3.12 준비 (uv 사용 · 관리자 암호 불필요)"
export UV_UNMANAGED_INSTALL="$DEST/uv"
UV="$DEST/uv/uv"
if [[ ! -x "$UV" ]]; then
  curl -fsSL https://astral.sh/uv/install.sh | sh || fail "Python 관리 도구(uv)를 받지 못했습니다."
fi
[[ -x "$UV" ]] || fail "uv 설치 위치를 찾지 못했습니다."
export UV_PYTHON_INSTALL_DIR="$DEST/python"
if [[ ! -x "$DEST/venv/bin/python" ]]; then
  "$UV" venv --python 3.12 "$DEST/venv" || fail "Python 3.12 를 준비하지 못했습니다."
fi
VPY="$DEST/venv/bin/python"
info "$("$VPY" -V)"

# ---------------------------------------------------------------- 3. 라이브러리
c "[3/6] 라이브러리 설치 (수 분 소요)"
TV="$(cat "$SRC/TORCH_VERSION" 2>/dev/null | tr -d '[:space:]')"
"$UV" pip install --python "$VPY" "torch${TV:+==$TV}" || "$UV" pip install --python "$VPY" torch || fail "PyTorch 설치 실패"
if ! "$UV" pip install --python "$VPY" -r "$SRC/requirements-mac.txt"; then
  info "고정 버전으로 한 번에 설치하지 못해, 하나씩 설치합니다(시간이 더 걸립니다)…"
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    "$UV" pip install --python "$VPY" "$line" -q 2>/dev/null || "$UV" pip install --python "$VPY" "${line%%==*}" -q 2>/dev/null || info "건너뜀: $line"
  done < "$SRC/requirements-mac.txt"
fi
"$VPY" -c "import streamlit, chromadb, pymupdf; print('      프로그램 구성 요소 정상')" || fail "라이브러리를 불러오지 못했습니다."

# ---------------------------------------------------------------- 4. Ollama
c "[4/6] Ollama(언어 모델 실행기) 확인"
OLLAMA=""
for p in "/Applications/Ollama.app/Contents/Resources/ollama" "$HOME/Applications/Ollama.app/Contents/Resources/ollama" \
         "$DEST/Ollama.app/Contents/Resources/ollama" "$(command -v ollama || true)"; do
  [[ -n "$p" && -x "$p" ]] && { OLLAMA="$p"; break; }
done
if [[ -z "$OLLAMA" ]]; then
  info "Ollama 공식 배포 파일을 받는 중 (약 230MB)…"
  TMPZ="$(mktemp -d)/Ollama-darwin.zip"
  curl -fL --progress-bar -o "$TMPZ" https://ollama.com/download/Ollama-darwin.zip || fail "Ollama 를 받지 못했습니다."
  rm -rf "$DEST/Ollama.app"
  ditto -x -k "$TMPZ" "$DEST" || fail "Ollama 압축을 풀지 못했습니다."
  rm -f "$TMPZ"
  OLLAMA="$DEST/Ollama.app/Contents/Resources/ollama"
  [[ -x "$OLLAMA" ]] || fail "Ollama 실행 파일을 찾지 못했습니다."
else info "이미 설치되어 있습니다: $OLLAMA"; fi
echo "$OLLAMA" > "$DEST/ollama_path"
if ! ollama_alive; then
  info "Ollama 시작 중…"
  OLLAMA_KEEP_ALIVE=10m nohup "$OLLAMA" serve >"$DEST/ollama.log" 2>&1 &
  for _ in $(seq 1 40); do ollama_alive && break; sleep 1; done
  ollama_alive || fail "Ollama 가 시작되지 않았습니다 ($DEST/ollama.log 확인)."
fi

# ---------------------------------------------------------------- 5. 언어 모델
c "[5/6] 언어 모델 $MODEL 받기 (수 GB — 인터넷 속도에 따라 수십 분)"
MODEL_BASE="${MODEL%%:*}"
if "$OLLAMA" list 2>/dev/null | grep -q "^$MODEL"; then info "이미 받아 두었습니다."
else
  (( FREE >= NEED )) || fail "디스크 공간이 부족합니다 (필요 약 ${NEED}GB, 남은 ${FREE}GB)."
  ok=0
  for t in 1 2 3; do
    if "$OLLAMA" pull "$MODEL"; then ok=1; break; fi     # 끊겨도 받은 만큼 이어 받음
    info "다시 시도합니다 ($t/3)…"; sleep 5
  done
  (( ok == 1 )) || fail "언어 모델 $MODEL 을 받지 못했습니다."
fi
printf '{"model": "%s"}' "$MODEL" > "$DEST/app/model.json"

# ---------------------------------------------------------------- 6. 임베딩 · 글꼴 · 아이콘
c "[6/6] 문서 검색용 모델·한글 글꼴 받기, 실행 아이콘 만들기"
HF_HOME="$DEST/hf" "$VPY" -c "from sentence_transformers import SentenceTransformer as S; S('paraphrase-multilingual-MiniLM-L12-v2', device='cpu'); print('      임베딩 모델 준비 완료')" \
  || info "임베딩 모델을 지금 받지 못했습니다. 처음 지식보관함을 쓸 때 자동으로 다시 받습니다."
FD="$DEST/app/assets/fonts"; mkdir -p "$FD"                # PDF 저장용 한글 글꼴(나눔고딕, SIL OFL)
G="https://github.com/google/fonts/raw/main/ofl/nanumgothic"
[[ -s "$FD/NanumGothic.ttf" ]] || curl -fsSL -o "$FD/NanumGothic.ttf" "$G/NanumGothic-Regular.ttf" || info "글꼴을 받지 못했습니다(PDF 저장 시 필요)."
[[ -s "$FD/NanumGothicBold.ttf" ]] || curl -fsSL -o "$FD/NanumGothicBold.ttf" "$G/NanumGothic-Bold.ttf" || true

make_app() {   # make_app "이름" "실행할 스크립트"  → 홈/Applications 와 바탕화면에 .app 생성
  local name="$1" script="$2" dir="$HOME/Applications/$1.app"
  rm -rf "$dir"; mkdir -p "$dir/Contents/MacOS"
  printf '#!/bin/bash\nexec "%s"\n' "$script" > "$dir/Contents/MacOS/run"; chmod +x "$dir/Contents/MacOS/run"
  cat > "$dir/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>$name</string><key>CFBundleDisplayName</key><string>$name</string>
<key>CFBundleIdentifier</key><string>local.ai.workspace.$(echo "$script" | md5 | cut -c1-8)</string>
<key>CFBundleExecutable</key><string>run</string><key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
</dict></plist>
PL
  rm -rf "$HOME/Desktop/$name.app"; cp -R "$dir" "$HOME/Desktop/$name.app" 2>/dev/null || true
}
mkdir -p "$HOME/Applications"
make_app "로컬 AI 작업실" "$DEST/mac/start.sh"
make_app "로컬 AI 작업실 끄기" "$DEST/mac/stop.sh"
touch "$DEST/install_ok"

printf '\n\033[1;32m설치가 끝났습니다!\033[0m 바탕화면의 \033[1m로컬 AI 작업실\033[0m 아이콘을 더블클릭하면 브라우저에서 열립니다.\n'
echo "(처음 한 번 '확인되지 않은 개발자' 경고가 뜨면: 아이콘을 우클릭 → 열기 → 열기)"
sleep 2
open "$HOME/Desktop/로컬 AI 작업실.app" 2>/dev/null || true
pause_exit 0
