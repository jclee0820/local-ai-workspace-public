#!/bin/bash
# 로컬 AI 작업실 실행 (바탕화면 아이콘 → 이 파일). 켜져 있으면 브라우저만 열고, 아니면 Ollama·작업실을 띄운 뒤 연다.
DEST="$(cd "$(dirname "$0")/.." && pwd)"
URL="http://localhost:8501"
say() { osascript -e "display dialog \"$1\" with title \"로컬 AI 작업실\" buttons {\"확인\"} default button 1" >/dev/null 2>&1; }
up() { curl -fs --max-time 2 "$1" >/dev/null 2>&1; }

if up "$URL/_stcore/health"; then open "$URL"; exit 0; fi
[[ -f "$DEST/install_ok" ]] || { say "설치가 아직 끝나지 않았습니다. 설치 폴더의 '설치' 파일을 다시 더블클릭해 주세요."; exit 1; }

if ! up http://127.0.0.1:11434; then
  OLLAMA="$(cat "$DEST/ollama_path" 2>/dev/null)"
  [[ -x "$OLLAMA" ]] || OLLAMA="$(command -v ollama)"
  [[ -x "$OLLAMA" ]] || { say "Ollama 를 찾지 못했습니다. 설치 파일을 다시 실행해 주세요."; exit 1; }
  OLLAMA_KEEP_ALIVE=10m nohup "$OLLAMA" serve >"$DEST/ollama.log" 2>&1 &
  for _ in $(seq 1 40); do up http://127.0.0.1:11434 && break; sleep 1; done
fi

cd "$DEST/app" || exit 1
export HF_HOME="$DEST/hf" PYTHONIOENCODING=utf-8
nohup "$DEST/venv/bin/python" -m streamlit run app.py --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false --server.maxUploadSize 500 >"$DEST/workspace.log" 2>&1 &
for _ in $(seq 1 120); do
  if up "$URL/_stcore/health"; then open "$URL"; exit 0; fi
  sleep 1
done
say "작업실이 2분 안에 열리지 않았습니다. 기록 파일: $DEST/workspace.log"
exit 1
