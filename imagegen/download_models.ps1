# 이미지 모델 다운로드 (Hugging Face Comfy-Org 저장소, Apache-2.0)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$m = Join-Path $root "ComfyUI\models"
$files = @(
  @("Comfy-Org/Flux-2-Klein-4B", "split_files/diffusion_models/flux-2-klein-4b.safetensors", "diffusion_models"),
  @("Comfy-Org/Flux-2-Klein-4B", "split_files/vae/flux2-vae.safetensors", "vae"),
  @("Comfy-Org/Flux-2-Klein-4B", "split_files/text_encoders/qwen_3_4b.safetensors", "text_encoders"),
  @("Comfy-Org/z_image_turbo", "split_files/diffusion_models/z_image_turbo_bf16.safetensors", "diffusion_models"),
  @("Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors", "vae")
)
foreach ($f in $files) {
  $dir = Join-Path $m $f[2]; New-Item -ItemType Directory -Force $dir | Out-Null
  $out = Join-Path $dir (Split-Path $f[1] -Leaf)
  if (Test-Path $out) { Write-Host "있음: $out"; continue }
  Write-Host "다운로드: $($f[1])"
  & curl.exe -L --fail --retry 5 -C - -o "$out.part" "https://huggingface.co/$($f[0])/resolve/main/$($f[1])"
  if ($LASTEXITCODE -eq 0) { Move-Item "$out.part" $out -Force } else { Write-Host "실패: $($f[1])" }
}
Get-ChildItem $m -Recurse -Filter *.safetensors | ForEach-Object { "{0,-45} {1,6:N2} GB" -f $_.Name, ($_.Length/1GB) }
