# 로컬 AI 작업실 종료 (이 설치 폴더의 내장 Python 으로 띄운 작업실만 끔. Ollama 는 그대로 둠)
param([switch]$Quiet)
$ErrorActionPreference = "SilentlyContinue"
$InstallDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pyDir = Join-Path $InstallDir "python"
$n = 0
Get-Process python, pythonw | Where-Object { $_.Path -and $_.Path.StartsWith($pyDir, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Stop-Process -Id $_.Id -Force; $n++ }
if (-not $Quiet) {
    Add-Type -AssemblyName PresentationFramework
    $m = if ($n) { "로컬 AI 작업실을 종료했습니다." } else { "실행 중인 로컬 AI 작업실이 없습니다." }
    [System.Windows.MessageBox]::Show($m, "로컬 AI 작업실") | Out-Null
}
