@echo off
setlocal
title Restart Discord Moderation Bot
cd /d "%~dp0"

call "%~dp0stop_bot.bat"
set "STOP_EXIT=%ERRORLEVEL%"

if not "%STOP_EXIT%"=="0" (
    echo.
    echo Restart cancelled because the stop step failed.
    pause
    exit /b %STOP_EXIT%
)

echo.
echo Starting bot again...
call "%~dp0start_bot.bat"
exit /b %ERRORLEVEL%
