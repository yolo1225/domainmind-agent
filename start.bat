@echo off
setlocal

cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker was not found. Install and start Docker Desktop first.
    goto :fail
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running or is not ready.
    goto :fail
)

docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Compose v2 is not available.
    goto :fail
)

if not exist ".env" (
    if not exist ".env.example" (
        echo [ERROR] Neither .env nor .env.example exists.
        goto :fail
    )
    copy /Y ".env.example" ".env" >nul
    if errorlevel 1 (
        echo [ERROR] Failed to create .env from .env.example.
        goto :fail
    )
    echo [INFO] Created .env from .env.example.
    echo [INFO] Configure the OpenAI-compatible API values in .env for live model calls.
)

if not exist "storage" mkdir "storage"
set "START_LOG=%~dp0storage\start.log"

echo [INFO] Building and starting DomainMind...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "& { Start-Transcript -Path '%START_LOG%' -Force; try { & '%~dp0scripts\demo.ps1' start } finally { Stop-Transcript } }"
if errorlevel 1 (
    echo [ERROR] DomainMind failed to start. Review the output above.
    echo [INFO] Full log: %START_LOG%
    goto :fail
)

echo.
echo [OK] DomainMind is ready.
echo Frontend:    http://localhost:5173/
echo Backend API: http://localhost:8000/docs
echo Health:      http://localhost:8000/api/v1/health

endlocal
exit /b 0

:fail
echo.
echo Press any key to close this window.
pause >nul
endlocal
exit /b 1
