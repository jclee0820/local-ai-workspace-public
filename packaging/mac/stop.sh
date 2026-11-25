#!/bin/bash
# 로컬 AI 작업실 끄기: 작업실(8501)과 이 설치가 띄운 Ollama 를 종료
DEST="$(cd "$(dirname "$0")/.." && pwd)"
pkill -f "$DEST/venv/bin/python -m streamlit" 2>/dev/null
OLLAMA="$(cat "$DEST/ollama_path" 2>/dev/null)"
[[ -n "$OLLAMA" ]] && pkill -f "$OLLAMA serve" 2>/dev/null
osascript -e 'display notification "작업실을 껐습니다." with title "로컬 AI 작업실"' >/dev/null 2>&1
exit 0
