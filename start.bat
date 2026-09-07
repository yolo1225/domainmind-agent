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
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $p='.env'; $utf8=[System.Text.UTF8Encoding]::new($false); $c=[System.IO.File]::ReadAllText($p,$utf8); $b=New-Object byte[] 48; $rng=[Security.Cryptography.RandomNumberGenerator]::Create(); try { $rng.GetBytes($b) } finally { $rng.Dispose() }; $s=[Convert]::ToBase64String($b); $c=$c.Replace('JWT_SECRET_KEY=replace-with-a-long-random-secret','JWT_SECRET_KEY='+$s).Replace('INITIAL_ADMIN_PASSWORD=change-me-before-first-run','INITIAL_ADMIN_PASSWORD=12345678'); [System.IO.File]::WriteAllText($p,$c,$utf8)"
    if errorlevel 1 (
        echo [ERROR] Failed to initialize authentication settings in .env.
        goto :fail
    )
    echo [INFO] Generated a private JWT key and configured the initial local administrator.
    echo [WARN] Initial local login: admin / 12345678. Change it after first login.
    echo [INFO] Configure the OpenAI-compatible API values in .env for live model calls.
)

if not exist "storage" mkdir "storage"
set "START_LOG=%~dp0storage\start.log"

echo [INFO] Starting Cognivia with the complete competition fixture (75 knowledge items, 106 relations, 465 questions)...
echo [INFO] Existing ordinary seed data is not overwritten. Use an empty Docker volume for the first fixture startup.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $transcriptStarted=$false; try { Start-Transcript -Path '%START_LOG%' -Force; $transcriptStarted=$true; & '%~dp0scripts\demo.ps1' start-fixture } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 } finally { if ($transcriptStarted) { Stop-Transcript } }"
if errorlevel 1 (
    echo [ERROR] Cognivia failed to start. Review the output above.
    echo [INFO] Full log: %START_LOG%
    goto :fail
)

echo.
echo [OK] Cognivia is ready.
echo Frontend:    http://localhost:5173/
echo Backend API: http://localhost:8000/docs
echo Health:      http://localhost:8000/api/v1/health
echo Initial login on a fresh deployment: admin / 12345678
echo.
echo Press any key to close this window. Services will continue running in Docker.
pause >nul

endlocal
exit /b 0

:fail
echo.
echo Press any key to close this window.
pause >nul
endlocal
exit /b 1
