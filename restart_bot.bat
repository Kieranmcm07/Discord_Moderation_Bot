@REM ============================================================
@REM   Made by Kieranmcm07 on GitHub
@REM   GitHub: https://github.com/Kieranmcm07
@REM ============================================================
@echo off
setlocal
title Restart Discord Moderation Bot
cd /d "%~dp0"

REM Restart is just stop first, then start again if stopping worked.
call "%~dp0stop_bot.bat" /nopause
set "STOP_EXIT=%ERRORLEVEL%"

if not "%STOP_EXIT%"=="0" (
    echo.
    echo Restart cancelled because the stop step failed.
    pause
    exit /b %STOP_EXIT%
)

echo.
echo Starting Bot Again...
call "%~dp0start_bot.bat"
exit /b %ERRORLEVEL%
