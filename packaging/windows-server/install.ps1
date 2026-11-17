<#
로컬 AI 작업실 — Windows Server 설치 (Docker·WSL 없이 네이티브 Python venv + Ollama, 부팅 시 자동 시작)
사용 (관리자 PowerShell):
  powershell -ExecutionPolicy Bypass -File .\windows-server\install.ps1 [-옵션]
옵션:
  -InstallDir C:\LocalAIWorkspace   설치 위치
  -Port 8501                        웹 포트
  -Model auto|gemma4:26b|qwen3:14b  언어 모델 (auto: 메모리 32GB↑ gemma4:26b, 18GB↑ qwen3:14b, 그 외 qwen3:8b)
  -Password "..."                   접속 비밀번호 (여러 사람이 쓰는 서버라면 권장)
  -OpenFirewall                     Windows 방화벽에 포트 개방
  -WithImageGen -Gpu cuda|xpu|cpu   이미지 생성(ComfyUI) 설치
  -SkipOllama -OllamaUrl URL        이미 있는 Ollama 사용
  -OfflineWheels D:\wheels          인터넷 없는 서버: 미리 받은 pip 휠 폴더
  -NoService                        서비스(예약 작업) 등록 없이 설치만 (시험용)
#>
param(
    [string]$InstallDir = "C:\LocalAIWorkspace",
    [int]$Port = 8501,
    [string]$Model = "auto",
    [string]$Password = "",
    [switch]$OpenFirewall,
    [switch]$WithImageGen,
    [ValidateSet("cuda", "xpu", "cpu")][string]$Gpu = "cuda",
    [switch]$SkipOllama,
    [string]$OllamaUrl = "http://127.0.0.1:11434",
    [string]$OfflineWheels = "",
    [switch]$NoService
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Src = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)   # 압축을 푼 패키지 최상위
function Log($m) { Write-Host "`n[$(Get-Date -Format HH:mm:ss)] $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "오류: $m" -ForegroundColor Red; exit 1 }
function Run($exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { Die "$exe $($argv -join ' ') 실패 (코드 $LASTEXITCODE)" }
}
if (-not (Test-Path "$Src\app\app.py")) { Die "패키지 구조가 올바르지 않습니다 ($Src\app\app.py 없음)" }
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $NoService) { Die "관리자 권한 PowerShell 에서 실행하세요." }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# PyTorch 는 경로가 아주 긴 파일을 포함 → 260자 제한(긴 경로 미사용 시스템)에 걸리지 않게 설치 위치 길이 확인
$longOk = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled -eq 1
if (-not $longOk -and $InstallDir.Length -gt 40) {
    Die "설치 위치 경로가 너무 깁니다($($InstallDir.Length)자). C:\LocalAIWorkspace 처럼 짧은 경로를 쓰거나 Windows 긴 경로 지원을 켜세요."
}

# ---------------------------------------------------------------- 1. Python
Log "1/8 Python 3.10~3.13 확인"
function Test-Py($p) {
    try { & $p -c "import sys; exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" 2>$null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
$Py = $null
foreach ($c in @("$env:ProgramFiles\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                 "$env:ProgramFiles\Python311\python.exe", "$env:ProgramFiles\Python313\python.exe")) {
    if ((Test-Path $c) -and (Test-Py $c)) { $Py = $c; break }
}
if (-not $Py) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*" -and (Test-Py $cmd.Source)) { $Py = $cmd.Source }
}
if (-not $Py) {
    Log "Python 3.12.10 설치 (python.org 공식 설치 파일, 모든 사용자용)"
    $pyExe = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $pyExe -UseBasicParsing
    $p = Start-Process $pyExe -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0" -Wait -PassThru
    if ($p.ExitCode -ne 0) { Die "Python 설치 실패 (코드 $($p.ExitCode))" }
    $Py = "$env:ProgramFiles\Python312\python.exe"
}
Write-Host "Python: $Py ($(& $Py -V))"

# ---------------------------------------------------------------- 2. 파일 복사
Log "2/8 $InstallDir 에 프로그램 복사 (사용자 데이터는 보존)"
New-Item -ItemType Directory -Force "$InstallDir\app", "$InstallDir\bin", "$InstallDir\hf" | Out-Null
robocopy "$Src\app" "$InstallDir\app" /E /NFL /NDL /NJH /NJS /NP /XD outputs chroma_db __pycache__ /XF model.json settings.json | Out-Null
if ($LASTEXITCODE -ge 8) { Die "파일 복사 실패 (robocopy $LASTEXITCODE)" }
Copy-Item "$Src\docs" $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "$Src\windows-server\uninstall.ps1" $InstallDir -Force
New-Item -ItemType Directory -Force "$InstallDir\app\outputs" | Out-Null

# ---------------------------------------------------------------- 3. 가상환경
Log "3/8 Python 가상환경과 라이브러리 설치 (수 분 소요)"
$VPy = "$InstallDir\venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) { Run $Py @("-m", "venv", "$InstallDir\venv") }
$pipBase = @("-m", "pip", "install", "--disable-pip-version-check")
if ($OfflineWheels) { $pipBase += @("--no-index", "--find-links", $OfflineWheels) }
Run $VPy ($pipBase + @("--upgrade", "pip", "wheel"))
$tv = (Get-Content "$Src\TORCH_VERSION" -ErrorAction SilentlyContinue | Select-Object -First 1)
$tspec = if ($tv) { "torch==$($tv.Trim())" } else { "torch" }
if ($OfflineWheels) { Run $VPy ($pipBase + @($tspec)) }
else { Run $VPy ($pipBase + @($tspec, "--index-url", "https://download.pytorch.org/whl/cpu")) }   # 임베딩은 CPU 전용
Run $VPy ($pipBase + @("-r", "$Src\requirements-windows.txt"))

# ---------------------------------------------------------------- 4. Ollama
$gpuNames = (Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object Name) -join "; "
$intelIgpu = ($gpuNames -match "Intel") -and ($gpuNames -notmatch "NVIDIA")
$OllamaExe = "$InstallDir\ollama\ollama.exe"
if (-not $SkipOllama) {
    Log "4/8 Ollama (서비스용 단독 실행판) 설치 · 127.0.0.1 에서만 열림"
    $alive = $false
    try { $alive = (Invoke-WebRequest "http://127.0.0.1:11434" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch {}
    if ($alive -and -not (Test-Path $OllamaExe)) {
        Write-Host "이 서버에서 이미 Ollama 가 실행 중이라 그것을 사용합니다."
        $SkipOllamaTask = $true
        $existing = Get-Command ollama.exe -ErrorAction SilentlyContinue
        if ($existing) { $OllamaExe = $existing.Source }
    } else {
        $SkipOllamaTask = $false
        if (-not (Test-Path $OllamaExe)) {
            $zip = Join-Path $env:TEMP "ollama-windows-amd64.zip"
            $ok = $false
            foreach ($u in @("https://ollama.com/download/ollama-windows-amd64.zip",
                             "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip")) {
                try { Invoke-WebRequest $u -OutFile $zip -UseBasicParsing; $ok = $true; break } catch { Write-Host "다운로드 실패: $u" }
            }
            if (-not $ok) { Die "Ollama 를 받지 못했습니다. 인터넷 연결을 확인하거나 -SkipOllama -OllamaUrl 로 다른 Ollama 를 지정하세요." }
            Expand-Archive $zip "$InstallDir\ollama" -Force
        }
        $gpuLines = if ($intelIgpu) { "set OLLAMA_IGPU_ENABLE=1`r`nset OLLAMA_VULKAN=1`r`n" } else { "" }
        [IO.File]::WriteAllText("$InstallDir\bin\start-ollama.cmd", (
            "@echo off`r`nset OLLAMA_HOST=127.0.0.1:11434`r`nset OLLAMA_MODELS=$InstallDir\ollama\models`r`n" +
            "set OLLAMA_KEEP_ALIVE=10m`r`n$gpuLines`"$OllamaExe`" serve >> `"$InstallDir\ollama\server.log`" 2>&1`r`n"),
            (New-Object Text.UTF8Encoding $false))
        if (-not $alive) {
            Start-Process "$env:ComSpec" -ArgumentList "/c", "`"$InstallDir\bin\start-ollama.cmd`"" -WindowStyle Hidden
            for ($i = 0; $i -lt 30; $i++) {
                try { if ((Invoke-WebRequest "http://127.0.0.1:11434" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { break } } catch {}
                Start-Sleep 1
            }
        }
    }
    if ($Model -eq "auto") {
        $mem = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
        $Model = if ($mem -ge 30) { "gemma4:26b" } elseif ($mem -ge 18) { "qwen3:14b" } else { "qwen3:8b" }
        Write-Host "메모리 ${mem}GB → 언어 모델 $Model"
    }
    Log "언어 모델 $Model 받는 중 (수 GB, 수십 분 걸릴 수 있음)"
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:11434/api/pull" -Method Post -TimeoutSec 14400 `
            -Body (@{ model = $Model; stream = $false } | ConvertTo-Json) -ContentType "application/json"
        Write-Host "모델 받기: $($r.status)"
    } catch { Die "언어 모델 $Model 을 받지 못했습니다: $_" }
} else {
    Log "4/8 Ollama 설치 생략 ($OllamaUrl 사용)"
    $SkipOllamaTask = $true
    if ($Model -eq "auto") { $Model = "gemma4:26b" }
}
if ($PSBoundParameters.ContainsKey("Model") -or -not (Test-Path "$InstallDir\app\model.json")) {
    Set-Content "$InstallDir\app\model.json" -Encoding ASCII -Value "{`"model`": `"$Model`"}"
}

# ---------------------------------------------------------------- 5. 임베딩 모델
Log "5/8 문서 검색용 임베딩 모델 미리 받기 (CPU)"
$env:HF_HOME = "$InstallDir\hf"
& $VPy -c "from sentence_transformers import SentenceTransformer as S; S('paraphrase-multilingual-MiniLM-L12-v2', device='cpu'); print('ok')"
if ($LASTEXITCODE -ne 0) { Write-Host "임베딩 모델을 지금 받지 못했습니다. 처음 지식보관함을 쓸 때 다시 받습니다." }

# ---------------------------------------------------------------- 6. 이미지 생성 (선택)
if ($WithImageGen) {
    Log "6/8 이미지 생성(ComfyUI, GPU=$Gpu) 설치 — 모델 포함 약 20GB"
    & powershell -ExecutionPolicy Bypass -File "$InstallDir\app\imagegen\setup_comfyui.ps1" -Python $Py -Gpu $Gpu
    & powershell -ExecutionPolicy Bypass -File "$InstallDir\app\imagegen\download_models.ps1"
} else { Log "6/8 이미지 생성 설치 생략 (나중에 -WithImageGen 으로 다시 실행)" }

# ---------------------------------------------------------------- 7. 실행 파일 · 자동 시작
Log "7/8 실행 스크립트와 자동 시작(예약 작업) 등록"
$pwFile = "$InstallDir\bin\start-workspace.cmd"
if (-not $Password -and (Test-Path $pwFile)) {          # 재설치 때 기존 비밀번호 유지
    $m = Select-String -Path $pwFile -Pattern '^set "LAI_PASSWORD=(.*)"$' | Select-Object -First 1
    if ($m) { $Password = $m.Matches[0].Groups[1].Value }
}
$pwLine = if ($Password) { "set `"LAI_PASSWORD=$Password`"`r`n" } else { "" }
function Write-Cmd($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false)) }   # BOM 없이 (BOM 이 있으면 첫 줄이 깨짐)
Write-Cmd $pwFile (
    "@echo off`r`nchcp 65001 >nul`r`ncd /d `"$InstallDir\app`"`r`nset OLLAMA_URL=$OllamaUrl`r`nset HF_HOME=$InstallDir\hf`r`n" +
    "set PYTHONIOENCODING=utf-8`r`n$pwLine" +
    "`"$VPy`" -m streamlit run app.py --server.address 0.0.0.0 --server.port $Port --server.headless true " +
    "--browser.gatherUsageStats false --server.maxUploadSize 500 >> `"$InstallDir\workspace.log`" 2>&1`r`n")
# 비밀번호가 든 실행 파일은 관리자·SYSTEM 만 읽도록
if (-not $NoService) { icacls $pwFile /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null }
if (-not $NoService) {
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $trigger = New-ScheduledTaskTrigger -AtStartup
    if (-not $SkipOllamaTask) {
        $a = New-ScheduledTaskAction -Execute "$env:ComSpec" -Argument "/c `"$InstallDir\bin\start-ollama.cmd`""
        Register-ScheduledTask -TaskName "LocalAI-Ollama" -Action $a -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    }
    $a = New-ScheduledTaskAction -Execute "$env:ComSpec" -Argument "/c `"$pwFile`""
    Register-ScheduledTask -TaskName "LocalAI-Workspace" -Action $a -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    # 설치 중 임시로 띄운 Ollama 를 정리하고 예약 작업으로 다시 시작
    if (-not $SkipOllamaTask) {
        Get-Process ollama -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$InstallDir*" } | Stop-Process -Force
        Start-ScheduledTask -TaskName "LocalAI-Ollama"
    }
    Start-ScheduledTask -TaskName "LocalAI-Workspace"
    if ($OpenFirewall) {
        Get-NetFirewallRule -DisplayName "Local AI Workspace" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName "Local AI Workspace" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
    }
}

# ---------------------------------------------------------------- 8. 확인
Log "8/8 동작 확인"
if ($NoService) {
    Write-Host "서비스 등록 없이 설치했습니다. 실행: $pwFile" -ForegroundColor Yellow
    exit 0
}
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try { if ((Invoke-WebRequest "http://127.0.0.1:$Port/_stcore/health" -UseBasicParsing -TimeoutSec 2).Content -match "ok") { $ok = $true; break } } catch {}
    Start-Sleep 2
}
$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
if ($ok) {
    Write-Host "`n설치 완료! 브라우저에서 http://$($ip):$Port 로 접속하세요." -ForegroundColor Green
    if (-not $Password) { Write-Host "※ 접속 비밀번호가 없습니다. 여러 사람이 접근하는 서버라면 -Password 로 다시 실행하세요." -ForegroundColor Yellow }
} else {
    Write-Host "웹 화면이 아직 응답하지 않습니다. 로그: $InstallDir\workspace.log" -ForegroundColor Yellow
}
Write-Host "관리: 작업 스케줄러의 LocalAI-Workspace / LocalAI-Ollama · 제거: $InstallDir\uninstall.ps1"
