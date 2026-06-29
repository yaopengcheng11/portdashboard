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

:: Find Python with fastapi installed
set "PYTHON_EXE="

:: Try .venv in project directory first
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import fastapi, uvicorn" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
        goto :found
    )
)

:: Try system python
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import fastapi, uvicorn" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        goto :found
    )
)

:: Try python3
where python3 >nul 2>&1
if not errorlevel 1 (
    python3 -c "import fastapi, uvicorn" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=python3"
        goto :found
    )
)

echo [ERROR] No Python with fastapi+uvicorn found.
echo.
echo Install dependencies:
echo   pip install fastapi uvicorn psutil
echo.
echo Or create a venv:
echo   python -m venv .venv
echo   .venv\Scripts\pip install fastapi uvicorn psutil
echo.
exit /b 1

:found
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

cd /d "%~dp0"
"%PYTHON_EXE%" app.py
