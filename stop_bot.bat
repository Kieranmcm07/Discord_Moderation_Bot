@REM ============================================================
@REM   Made by Kieranmcm07 on GitHub
@REM   GitHub: https://github.com/Kieranmcm07
@REM ============================================================
@echo off
setlocal EnableDelayedExpansion
title Stop Discord Moderation Bot
color 0C
cls

set "PAUSE_ON_EXIT=1"
if /I "%~1"=="/nopause" set "PAUSE_ON_EXIT=0"

echo.
echo      ____        _     _____                   _             _   _             
echo     ^| __ )  ___ ^| ^|_  ^|_   _^|__ _ __ _ __ ___ (_)_ __   __ _^| ^|_(_)_ __   __ _ 
echo     ^|  _ \ / _ \^| __^|   ^| ^|/ _ \ '__^| '_ ` _ \^| ^| '_ \ / _` ^| __^| ^| '_ \ / _` ^|
echo     ^| ^|_) ^| (_) ^| ^|_    ^| ^|  __/ ^|  ^| ^| ^| ^| ^| ^| ^| ^| ^| ^| (_^| ^| ^|_^| ^| ^| ^| ^| (_^| ^|
echo     ^|____/ \___/ \__^|   ^|_^|\___^|_^|  ^|_^| ^|_^| ^|_^|_^|_^| ^|_^|\__,_^|\__^|_^|_^| ^|_^|\__, ^|
echo                                                                          ^|___/ 
echo.
echo     Termination sequence armed.
echo.

REM The bot writes this lock file on startup, and older launches can also be
REM found by their Python command line.
set "LOCK_FILE=%TEMP%\discord_mod_bot.lock"

set "BOT_PIDS="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lockPath = Join-Path $env:TEMP 'discord_mod_bot.lock';" ^
  "$ids = New-Object 'System.Collections.Generic.HashSet[int]';" ^
  "if (Test-Path $lockPath) {" ^
  "  try { $data = Get-Content -Raw -Path $lockPath | ConvertFrom-Json; if ($null -ne $data.pid) { [void]$ids.Add([int]$data.pid) } } catch {}" ^
  "}" ^
  "$project = (Resolve-Path '.').Path;" ^
  "$escapedProject = [regex]::Escape($project);" ^
  "$processes = Get-CimInstance Win32_Process -Filter 'name = ''pythonw.exe'' or name = ''python.exe''';" ^
  "foreach ($process in $processes) {" ^
  "  $commandLine = [string]$process.CommandLine;" ^
  "  if ($commandLine -match ($escapedProject + '.*main\.py') -or $commandLine -match 'main\.py\s+--background\s+--status-file') { [void]$ids.Add([int]$process.ProcessId) }" ^
  "}" ^
  "$ids | Sort-Object"`) do (
    set "BOT_PIDS=!BOT_PIDS! %%P"
)

if not defined BOT_PIDS (
    echo No running bot process was found.
    if "%PAUSE_ON_EXIT%"=="1" pause
    exit /b 1
)

set "STOPPED_PIDS="
for %%P in (%BOT_PIDS%) do (
    tasklist /FI "PID eq %%P" | find "%%P" >nul
    if not errorlevel 1 (
        taskkill /PID %%P /T >nul 2>&1
        if errorlevel 1 (
            echo Bot process %%P needs a force stop. Retrying...
            taskkill /PID %%P /T /F >nul 2>&1
            if errorlevel 1 (
                echo Failed to stop bot process %%P.
                if "%PAUSE_ON_EXIT%"=="1" pause
                exit /b 1
            )
        )
        set "STOPPED_PIDS=!STOPPED_PIDS! %%P"
    )
)

for /L %%S in (1,1,15) do (
    set "STILL_RUNNING="
    for %%P in (!STOPPED_PIDS!) do (
        tasklist /FI "PID eq %%P" | find "%%P" >nul
        if not errorlevel 1 set "STILL_RUNNING=1"
    )
    if not defined STILL_RUNNING goto STOP_CONFIRMED
    timeout /t 1 /nobreak >nul
)

echo Bot process(es)%STOPPED_PIDS% did not fully exit in time.
if "%PAUSE_ON_EXIT%"=="1" pause
exit /b 1

:STOP_CONFIRMED
cls
echo.
echo      ____        _     _  ___ _ _          _ 
echo     ^| __ )  ___ ^| ^|_  ^| ^|/ (_) ^| ^| ___  __^| ^|
echo     ^|  _ \ / _ \^| __^| ^| ' /^| ^| ^| ^|/ _ \/ _` ^|
echo     ^| ^|_) ^| (_) ^| ^|_  ^| . \^| ^| ^| ^|  __/ (_^| ^|
echo     ^|____/ \___/ \__^| ^|_^|\_\_^|_^|_^|\___^|\__,_^|
echo.                                      
echo     Bot process(es)%STOPPED_PIDS% stopped.
del "%LOCK_FILE%" >nul 2>&1
if "%PAUSE_ON_EXIT%"=="1" pause
