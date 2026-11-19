<#
로컬 AI 작업실 — 개인 PC 설치 마무리 (setup.exe 가 파일을 복사한 뒤 자동으로 실행)
Python·라이브러리는 설치 파일에 들어 있으므로 여기서는 인터넷으로 받아야 하는 것만 처리:
  1) Ollama (언어 모델 실행기) — 이미 있으면 그대로 사용
  2) 언어 모델 — PC 메모리에 맞춰 자동 선택
  3) 문서 검색용 임베딩 모델
관리자 권한이 필요 없고, 진행 상황은 이 창에 표시된다. 실패해도 다시 실행하면 이어서 진행한다.
#>
param([string]$InstallDir = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)))
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "로컬 AI 작업실 설치 — 이 창을 닫지 마세요"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Py = Join-Path $InstallDir "python\python.exe"
$Ok = Join-Path $InstallDir "setup\install_ok"
Remove-Item $Ok -ErrorAction SilentlyContinue
try { Start-Transcript -Path (Join-Path $InstallDir "install.log") -Append | Out-Null } catch {}

function Step($n, $m) { Write-Host "`n[$n/4] $m" -ForegroundColor Cyan }
function Info($m) { Write-Host "      $m" }
function Fail($m) {
    Write-Host "`n설치를 마치지 못했습니다: $m" -ForegroundColor Red
    Write-Host "인터넷 연결을 확인한 뒤, 시작 메뉴 '로컬 AI 작업실 > 설치 다시 시도'를 누르면 이어서 진행합니다." -ForegroundColor Yellow
    Write-Host "기록 파일: $InstallDir\install.log"
    try { Stop-Transcript | Out-Null } catch {}
    Read-Host "`nEnter 키를 누르면 창이 닫힙니다" | Out-Null
    exit 1
}
function Ollama-Alive {
    try { return (Invoke-WebRequest "http://127.0.0.1:11434" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}

Write-Host "==============================================================" -ForegroundColor DarkGray
Write-Host "  로컬 AI 작업실 설치를 마무리합니다 (인터넷 필요)" -ForegroundColor White
Write-Host "  언어 모델을 받는 데 수십 분 걸릴 수 있습니다. 창을 닫지 마세요." -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor DarkGray

# ------------------------------------------------------------ 0. 내장 Python 확인
if (-not (Test-Path $Py)) { Fail "프로그램 파일이 손상되었습니다 ($Py 없음). 설치 파일을 다시 받아 실행해 주세요." }

# ------------------------------------------------------------ 언어 모델 고르기 (메모리 기준)
$memGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
if ($memGB -ge 30) { $Model = "gemma4:26b"; $needGB = 20 }
elseif ($memGB -ge 18) { $Model = "qwen3:14b"; $needGB = 12 }
else { $Model = "qwen3:8b"; $needGB = 8 }
$cfg = Join-Path $InstallDir "app\model.json"
if (Test-Path $cfg) {                                   # 다시 설치할 때는 쓰던 모델 유지
    try { $old = (Get-Content $cfg -Raw | ConvertFrom-Json).model; if ($old) { $Model = $old } } catch {}
}
$freeGB = [math]::Round((Get-PSDrive ($InstallDir.Substring(0, 1))).Free / 1GB)
Info "이 PC 메모리 ${memGB}GB → 언어 모델 $Model · 남은 디스크 ${freeGB}GB"

# ------------------------------------------------------------ 1. Ollama
Step 1 "Ollama(언어 모델 실행기) 확인"
$OllamaExe = $null
foreach ($c in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", "$env:ProgramFiles\Ollama\ollama.exe")) {
    if (Test-Path $c) { $OllamaExe = $c; break }
}
if (-not $OllamaExe) {
    $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($cmd) { $OllamaExe = $cmd.Source }
}
if (-not $OllamaExe) {
    Info "Ollama 공식 설치 파일을 받는 중 (약 1GB, 몇 분 걸립니다)…"
    $setup = Join-Path $env:TEMP "OllamaSetup.exe"
    $got = $false
    foreach ($u in @("https://ollama.com/download/OllamaSetup.exe",
                     "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe")) {
        try { Invoke-WebRequest $u -OutFile $setup -UseBasicParsing; $got = $true; break } catch { Info "받기 실패: $u" }
    }
    if (-not $got) { Fail "Ollama 설치 파일을 받지 못했습니다." }
    Info "Ollama 설치 중…"
    $p = Start-Process $setup -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -Wait -PassThru
    if ($p.ExitCode -ne 0) { Fail "Ollama 설치가 실패했습니다 (코드 $($p.ExitCode))." }
    Remove-Item $setup -ErrorAction SilentlyContinue
    $OllamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (-not (Test-Path $OllamaExe)) { Fail "Ollama 설치 위치를 찾지 못했습니다." }
} else { Info "이미 설치되어 있습니다: $OllamaExe" }
if (-not (Ollama-Alive)) {
    Info "Ollama 시작 중…"
    Start-Process $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 40 -and -not (Ollama-Alive); $i++) { Start-Sleep 1 }
    if (-not (Ollama-Alive)) { Fail "Ollama 가 시작되지 않았습니다." }
}

# ------------------------------------------------------------ 2. 언어 모델
Step 2 "언어 모델 $Model 받기 (수 GB — 인터넷 속도에 따라 수십 분)"
$have = & $OllamaExe list 2>$null | Select-String -SimpleMatch ($Model.Split(":")[0] + ":" + $Model.Split(":")[1])
if ($have) { Info "이미 받아 두었습니다." }
else {
    if ($freeGB -lt $needGB) { Fail "디스크 공간이 부족합니다 (필요 약 ${needGB}GB, 남은 ${freeGB}GB)." }
    $done = $false
    for ($t = 1; $t -le 3 -and -not $done; $t++) {
        & $OllamaExe pull $Model                         # 진행 막대가 이 창에 표시됨. 끊겨도 받은 만큼 이어 받음
        if ($LASTEXITCODE -eq 0) { $done = $true } else { Info "다시 시도합니다 ($t/3)…"; Start-Sleep 5 }
    }
    if (-not $done) { Fail "언어 모델 $Model 을 받지 못했습니다." }
}
[IO.File]::WriteAllText($cfg, "{`"model`": `"$Model`"}", (New-Object Text.UTF8Encoding $false))

# ------------------------------------------------------------ 3. 임베딩 모델
Step 3 "문서 검색용 임베딩 모델 받기 (약 0.5GB)"
$env:HF_HOME = Join-Path $InstallDir "hf"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
& $Py -c "from sentence_transformers import SentenceTransformer as S; S('paraphrase-multilingual-MiniLM-L12-v2', device='cpu'); print('      준비 완료')"
if ($LASTEXITCODE -ne 0) { Info "지금 받지 못했습니다. 처음 지식보관함을 쓸 때 자동으로 다시 받습니다." }

# ------------------------------------------------------------ 4. 확인
Step 4 "프로그램 동작 확인"
& $Py -c "import streamlit, chromadb, pymupdf; print('      프로그램 구성 요소 정상')"
if ($LASTEXITCODE -ne 0) { Fail "프로그램 구성 요소를 불러오지 못했습니다." }
Set-Content $Ok "ok" -Encoding ASCII
Write-Host "`n설치가 끝났습니다! 바탕화면의 '로컬 AI 작업실' 아이콘을 누르면 브라우저에서 열립니다." -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch {}
Start-Sleep 3
