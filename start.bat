@echo off
setlocal
cd /d "%~dp0"
title Before Open

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv is required. See docs\QUICKSTART.md for installation.
    pause
    exit /b 1
)

echo [Before Open] Preparing Python 3.12 and backend dependencies...
pushd backend
call uv sync --locked --no-install-project --python 3.12
if errorlevel 1 (
    popd
    echo [ERROR] Backend setup failed. Check your network and the message above.
    pause
    exit /b 1
)
popd

"backend\.venv\Scripts\python.exe" -u "scripts\start_local.py"
set "BEFORE_OPEN_EXIT=%ERRORLEVEL%"
if not "%BEFORE_OPEN_EXIT%"=="0" pause
exit /b %BEFORE_OPEN_EXIT%
