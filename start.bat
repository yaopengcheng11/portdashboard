@echo off
chcp 65001 >nul 2>&1
setlocal

set "MODE=stable"
if /i "%~1"=="dev" (
    set "MODE=dev"
)

echo ======================================================
echo              P O R T   D A S H B O A R D
echo ======================================================
echo.

cd /d "%~dp0"

:: 与 start.sh 行为对齐：没有 .venv 就自动创建并安装依赖
if exist ".venv\Scripts\python.exe" goto :venv-ready

echo [setup] .venv 不存在，自动创建虚拟环境...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 python，无法自动创建虚拟环境。
    echo         请安装 Python 3.11+ 后重试，或手动: python -m venv .venv
    exit /b 1
)
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] 虚拟环境创建失败。
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] 依赖安装失败，请检查网络后重试。
    exit /b 1
)
echo.

:venv-ready
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if "%MODE%"=="dev" (
    set "PORT_DASHBOARD_RELOAD=1"
    set "MODE_LABEL=Dev mode (hot reload ON)"
) else (
    set "PORT_DASHBOARD_RELOAD=0"
    set "MODE_LABEL=Stable mode (hot reload OFF)"
)

echo [OK] Python: %PYTHON_EXE%
echo [OK] Mode: %MODE_LABEL%
echo.
echo Access the dashboard at:
echo   http://localhost:9229/
echo.
echo Press Ctrl+C to stop.
echo ------------------------------------------------------
echo.

"%PYTHON_EXE%" app.py
