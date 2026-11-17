#!/usr/bin/env bash
# ComfyUI 설치 (리눅스). 사용: bash setup_comfyui.sh --python /usr/bin/python3.12 --gpu cuda|xpu|cpu
# cuda = NVIDIA (PyPI 기본 리눅스 PyTorch 휠), xpu = Intel Arc (PyTorch XPU 휠), cpu = GPU 없음 (매우 느림)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=python3; GPU=cuda; TAG=v0.45.0
while [[ $# -gt 0 ]]; do
  case "$1" in --python) PY="$2"; shift 2;; --gpu) GPU="$2"; shift 2;; --tag) TAG="$2"; shift 2;; *) shift;; esac
done
DST="$ROOT/ComfyUI"
if [[ ! -f "$DST/main.py" ]]; then
  echo "[1/4] ComfyUI $TAG 다운로드"
  TMP="$(mktemp -d)"
  curl -L --fail -s -o "$TMP/comfy.tar.gz" "https://github.com/Comfy-Org/ComfyUI/archive/refs/tags/$TAG.tar.gz"
  tar -xzf "$TMP/comfy.tar.gz" -C "$TMP"
  mv "$TMP"/ComfyUI-* "$DST"
  rm -rf "$TMP"
fi
echo "[2/4] 가상환경 생성"
[[ -x "$DST/.venv/bin/python" ]] || "$PY" -m venv "$DST/.venv"
VPY="$DST/.venv/bin/python"
"$VPY" -m pip install --disable-pip-version-check --upgrade pip >/dev/null
echo "[3/4] PyTorch 설치 (GPU=$GPU)"
case "$GPU" in
  xpu) "$VPY" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/xpu;;
  cpu) "$VPY" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu;;
  *)   "$VPY" -m pip install torch torchvision torchaudio;;
esac
echo "[4/4] ComfyUI 의존성 설치"
"$VPY" -m pip install -r "$DST/requirements.txt"
"$VPY" - <<'EOF'
import torch
cuda = torch.cuda.is_available()
xpu = hasattr(torch, "xpu") and torch.xpu.is_available()
name = torch.cuda.get_device_name(0) if cuda else (torch.xpu.get_device_name(0) if xpu else "CPU")
print("torch", torch.__version__, "| GPU:", name)
EOF
