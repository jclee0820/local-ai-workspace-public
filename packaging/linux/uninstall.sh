#!/usr/bin/env bash
# 로컬 AI 작업실 제거. 기본은 프로그램만 지우고 사용자 데이터(작업 보관함·지식보관함)는 남김.
#   --remove-data   데이터까지 모두 삭제     --remove-ollama   Ollama 와 받은 모델도 삭제
set -euo pipefail
PREFIX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RM_DATA=0; RM_OLLAMA=0
for a in "$@"; do case "$a" in --remove-data) RM_DATA=1;; --remove-ollama) RM_OLLAMA=1;; esac; done
[[ $EUID -eq 0 ]] || { echo "sudo 로 실행하세요."; exit 1; }
[[ -f "$PREFIX/app/app.py" ]] || { echo "설치 폴더가 아닌 곳에서 실행되었습니다: $PREFIX"; exit 1; }
systemctl disable --now local-ai-workspace 2>/dev/null || true
rm -f /etc/systemd/system/local-ai-workspace.service
rm -f /etc/systemd/system/ollama.service.d/local-ai.conf
systemctl daemon-reload
if [[ $RM_DATA -eq 1 ]]; then
  rm -rf "$PREFIX"; rm -f /etc/local-ai-workspace.env
  userdel lai 2>/dev/null || true
  echo "프로그램과 데이터를 모두 삭제했습니다."
else
  BK="$PREFIX-data-$(date +%Y%m%d%H%M)"
  mkdir -p "$BK"
  for d in outputs chroma_db templates model.json; do
    if [[ -e "$PREFIX/app/$d" ]]; then mv "$PREFIX/app/$d" "$BK/"; fi
  done
  rm -rf "$PREFIX"
  echo "프로그램을 삭제했습니다. 사용자 데이터는 $BK 에 남겨 두었습니다."
fi
if [[ $RM_OLLAMA -eq 1 ]]; then
  systemctl disable --now ollama 2>/dev/null || true
  rm -f /etc/systemd/system/ollama.service "$(command -v ollama)" ; rm -rf /usr/share/ollama /usr/lib/ollama /usr/local/lib/ollama
  userdel ollama 2>/dev/null || true; systemctl daemon-reload
  echo "Ollama 와 모델을 삭제했습니다."
fi
