# ComfyUI 설치 스크립트 - 재설치 시에도 그대로 실행 가능
#   -Python <python.exe 경로>  -Gpu xpu(Intel Arc, 기본) | cuda(NVIDIA) | cpu
param([string]$Python = "", [ValidateSet("xpu", "cuda", "cpu")][string]$Gpu = "xpu")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = if ($Python) { $Python } else { "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" }
$tag = "v0.45.0"
$dst = Join-Path $root "ComfyUI"
if (-not (Test-Path (Join-Path $dst "main.py"))) {
    $zip = Join-Path $root "comfyui.zip"
    Write-Host "[1/4] ComfyUI $tag 다운로드"
    if (-not (Test-Path $zip) -or (Get-Item $zip).Length -lt 1MB) {
        & curl.exe -L --fail -s -o $zip "https://github.com/Comfy-Org/ComfyUI/archive/refs/tags/$tag.zip"
    }
    $tmp = Join-Path $root "_extract"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip $tmp
    Move-Item (Get-ChildItem $tmp | Select-Object -First 1).FullName $dst
}
Write-Host "[2/4] 가상환경 생성"
if (-not (Test-Path "$dst\.venv\Scripts\python.exe")) { & $py -m venv "$dst\.venv" }
$vpy = "$dst\.venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip | Out-Null
Write-Host "[3/4] PyTorch 설치 (GPU=$Gpu)"
switch ($Gpu) {
    "xpu" { & $vpy -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/xpu }
    "cpu" { & $vpy -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu }
    # NVIDIA: Windows 의 PyPI torch 는 CPU 판이므로 PyTorch 공식 CUDA 인덱스 사용 (서버 드라이버에 맞는 cuXXX 확인 필요)
    "cuda" { & $vpy -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 }
}
Write-Host "[4/4] ComfyUI 의존성 설치"
& $vpy -m pip install -r "$dst\requirements.txt"
& $vpy -c "import torch; print('torch', torch.__version__, '| xpu available:', torch.xpu.is_available(), '|', torch.xpu.get_device_name(0) if torch.xpu.is_available() else '')"
