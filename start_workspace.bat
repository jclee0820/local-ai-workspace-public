@echo off
title Local AI Workspace
cd /d "%~dp0"

rem ---- Ollama settings (use Arc iGPU, protect memory) ----
set OLLAMA_FLASH_ATTENTION=1
set OLLAMA_NUM_PARALLEL=1
set OLLAMA_MAX_LOADED_MODELS=1
set OLLAMA_IGPU_ENABLE=1
set OLLAMA_VULKAN=1
set OLLAMA_CONTEXT_LENGTH=8192
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYTHONIOENCODING=utf-8

set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA_EXE%" set "OLLAMA_EXE=ollama"

echo [1/3] Restarting Ollama with GPU settings...
taskkill /F /IM "ollama app.exe" >nul 2>&1
taskkill /F /IM ollama.exe >nul 2>&1
timeout /t 2 /nobreak >nul
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%OLLAMA_EXE%' -ArgumentList 'serve' -WindowStyle Hidden"

set /a tries=0
:wait
curl -s http://localhost:11434 >nul 2>&1
if %errorlevel%==0 goto ready
set /a tries+=1
if %tries% GEQ 30 goto fail
timeout /t 1 /nobreak >nul
goto wait

:fail
echo Ollama did not start. Please check that Ollama is installed.
pause
exit /b 1

:ready
echo [2/3] Ollama is ready.
echo [3/3] Starting workspace. Browser opens in a few seconds. Close this window to quit.
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --browser.gatherUsageStats false --server.port 8501
pause