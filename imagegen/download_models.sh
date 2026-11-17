#!/usr/bin/env bash
# 이미지 모델 다운로드 (Hugging Face Comfy-Org 저장소). 이어받기 지원.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
M="$ROOT/ComfyUI/models"
FILES=(
  "Comfy-Org/Flux-2-Klein-4B|split_files/diffusion_models/flux-2-klein-4b.safetensors|diffusion_models"
  "Comfy-Org/Flux-2-Klein-4B|split_files/vae/flux2-vae.safetensors|vae"
  "Comfy-Org/Flux-2-Klein-4B|split_files/text_encoders/qwen_3_4b.safetensors|text_encoders"
  "Comfy-Org/z_image_turbo|split_files/diffusion_models/z_image_turbo_bf16.safetensors|diffusion_models"
  "Comfy-Org/z_image_turbo|split_files/vae/ae.safetensors|vae"
)
fail=0
for f in "${FILES[@]}"; do
  IFS='|' read -r repo path sub <<<"$f"
  mkdir -p "$M/$sub"
  out="$M/$sub/$(basename "$path")"
  if [[ -f "$out" ]]; then echo "있음: $out"; continue; fi
  echo "다운로드: $path"
  if curl -L --fail --retry 5 -C - -o "$out.part" "https://huggingface.co/$repo/resolve/main/$path"; then
    mv "$out.part" "$out"
  else
    echo "실패: $path"; fail=1
  fi
done
du -h "$M"/*/*.safetensors 2>/dev/null || true
exit $fail
