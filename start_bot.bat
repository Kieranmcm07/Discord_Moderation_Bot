@echo off
title Discord Moderation Bot
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 launcher.py
) else (
    python launcher.py
)
