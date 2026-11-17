<#
로컬 AI 작업실 제거 (관리자 PowerShell). 기본은 프로그램만 지우고 사용자 데이터(작업 보관함·지식보관함·양식)는 남김.
  -RemoveData   데이터까지 모두 삭제
#>
param([switch]$RemoveData)
$ErrorActionPreference = "Continue"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path "$Dir\app\app.py")) { Write-Host "설치 폴더에서 실행하세요: $Dir"; exit 1 }
foreach ($t in "LocalAI-Workspace", "LocalAI-Ollama") {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}
Get-NetFirewallRule -DisplayName "Local AI Workspace" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
# 이 설치 폴더에서 실행 중인 프로세스만 종료
Get-Process python, ollama -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Dir*" } | Stop-Process -Force
Start-Sleep 2
if (-not $RemoveData) {
    $bk = "$Dir-data-$(Get-Date -Format yyyyMMddHHmm)"
    New-Item -ItemType Directory -Force $bk | Out-Null
    foreach ($d in "outputs", "chroma_db", "templates", "model.json") {
        if (Test-Path "$Dir\app\$d") { Move-Item "$Dir\app\$d" $bk }
    }
    Write-Host "사용자 데이터를 $bk 에 남겨 두었습니다."
}
Set-Location $env:TEMP
Remove-Item $Dir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "제거했습니다. (남은 파일이 있으면 재부팅 후 $Dir 폴더를 지우세요)"
