# 로컬 AI 작업실 실행 (바탕화면 아이콘 → start.vbs → 이 파일, 창 없이)
# 이미 켜져 있으면 브라우저만 열고, 아니면 Ollama 와 작업실을 띄운 뒤 준비되면 브라우저를 연다.
$ErrorActionPreference = "SilentlyContinue"
$InstallDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = Join-Path $InstallDir "python\python.exe"
$Url = "http://localhost:8501"
Add-Type -AssemblyName PresentationFramework
function Say($m, $icon = "Information") { [System.Windows.MessageBox]::Show($m, "로컬 AI 작업실", "OK", $icon) | Out-Null }
function Up($u) { try { return (Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { return $false } }

if (Up "$Url/_stcore/health") { Start-Process $Url; exit 0 }
if (-not (Test-Path (Join-Path $InstallDir "setup\install_ok"))) {
    Say "설치가 아직 끝나지 않았습니다.`n시작 메뉴 '로컬 AI 작업실 > 설치 다시 시도'를 먼저 실행해 주세요." "Warning"; exit 1
}

# Ollama (언어 모델 실행기)
if (-not (Up "http://127.0.0.1:11434")) {
    $o = @("$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe", "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
           "$env:ProgramFiles\Ollama\ollama.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $o) { $c = Get-Command ollama.exe; if ($c) { $o = $c.Source } }
    if (-not $o) { Say "Ollama 를 찾지 못했습니다. 시작 메뉴 '로컬 AI 작업실 > 설치 다시 시도'를 실행해 주세요." "Error"; exit 1 }
    if ($o -like "*ollama app.exe") { Start-Process $o } else { Start-Process $o -ArgumentList "serve" -WindowStyle Hidden }
    for ($i = 0; $i -lt 40 -and -not (Up "http://127.0.0.1:11434"); $i++) { Start-Sleep 1 }
}

# 작업실 (Streamlit)
$env:HF_HOME = Join-Path $InstallDir "hf"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:PYTHONIOENCODING = "utf-8"
$log = Join-Path $InstallDir "workspace.log"
Start-Process $Py -WorkingDirectory (Join-Path $InstallDir "app") -WindowStyle Hidden `
    -ArgumentList "-m", "streamlit", "run", "app.py", "--server.port", "8501", "--server.headless", "true",
                  "--browser.gatherUsageStats", "false", "--server.maxUploadSize", "500" `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"
for ($i = 0; $i -lt 120; $i++) {
    if (Up "$Url/_stcore/health") { Start-Process $Url; exit 0 }
    Start-Sleep 1
}
Say "작업실이 2분 안에 열리지 않았습니다.`n기록 파일: $log.err" "Error"
exit 1
