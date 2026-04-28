@echo off
title Discord Moderation Bot
cd /d "%~dp0"

REM Small launcher wrapper so I can double-click the bot on Windows.
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 launcher.py
) else (
    python launcher.py
)
