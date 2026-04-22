@echo off
setlocal
title Stop Discord Moderation Bot

set "LOCK_FILE=%TEMP%\discord_mod_bot.lock"

if not exist "%LOCK_FILE%" (
    echo No running bot lock file was found.
    echo If the bot is still running, stop it manually and then start it again once.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lockPath = Join-Path $env:TEMP 'discord_mod_bot.lock';" ^
  "if (-not (Test-Path $lockPath)) { exit 1 }" ^
  "$data = Get-Content -Raw -Path $lockPath | ConvertFrom-Json;" ^
  "if ($null -eq $data.pid) { exit 1 }" ^
  "[string]$data.pid"`) do (
    set "BOT_PID=%%P"
)

if not defined BOT_PID (
    echo Could not read a bot process ID from:
    echo %LOCK_FILE%
    pause
    exit /b 1
)

tasklist /FI "PID eq %BOT_PID%" | find "%BOT_PID%" >nul
if errorlevel 1 (
    echo The saved bot process is not running anymore.
    del "%LOCK_FILE%" >nul 2>&1
    pause
    exit /b 0
)

taskkill /PID %BOT_PID% /T >nul 2>&1
if errorlevel 1 (
    echo Bot process %BOT_PID% needs a force stop. Retrying...
    taskkill /PID %BOT_PID% /T /F >nul 2>&1
    if errorlevel 1 (
        echo Failed to stop bot process %BOT_PID%.
        pause
        exit /b 1
    )
)

echo Bot process %BOT_PID% stopped.
del "%LOCK_FILE%" >nul 2>&1
pause
