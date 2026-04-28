@echo off
setlocal
title Install Discord Moderation Bot Startup
color 0D
mode con: cols=120 lines=30
cls

echo.
echo      ____  _             _                 ___           _        _ _ 
echo     / ___^|^| ^|_ __ _ _ __^| ^|_ _   _ _ __   ^|_ _^|_ __  ___^| ^|_ __ _^| ^| ^|
echo     \___ \^| __/ _` ^| '__^| __^| ^| ^| ^| '_ \   ^| ^|^| '_ \/ __^| __/ _` ^| ^| ^|
echo      ___) ^| ^|^| (_^| ^| ^|  ^| ^|_^| ^|_^| ^| ^|_) ^|  ^| ^|^| ^| ^| \__ \ ^|^| (_^| ^| ^| ^|
echo     ^|____/ \__\__,_^|_^|   \__^|\__,_^| .__/  ^|___^|_^| ^|_^|___/\__\__,_^|_^|_^|
echo                                   ^|_^|                                 
echo.
echo        [ STARTUP BOOT ]   Preparing Windows autostart link...
echo        [ SHORTCUT     ]   Targeting start_bot.bat...
echo        [ CREDITS      ]   Made by Kieranmcm07
echo        [ GITHUB       ]   https://github.com/Kieranmcm07
echo.
timeout /t 2 /nobreak >nul

REM Adds a Windows startup shortcut so the bot can come back after a PC restart.
set "PROJECT_DIR=%~dp0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\Discord Moderation Bot.lnk"
set "START_TARGET=%PROJECT_DIR%start_bot.bat"
set "ICON_PATH=%SystemRoot%\System32\cmd.exe,0"
set "ERROR_FILE=%TEMP%\discord_mod_bot_startup_error.txt"
del "%ERROR_FILE%" >nul 2>&1

if exist "%SHORTCUT_PATH%" goto already_installed

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$startupDir = $env:STARTUP_DIR;" ^
  "$shortcutPath = $env:SHORTCUT_PATH;" ^
  "$targetPath = $env:START_TARGET;" ^
  "$workingDir = ($env:PROJECT_DIR).TrimEnd('\');" ^
  "New-Item -ItemType Directory -Force -Path $startupDir | Out-Null;" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$shortcut = $ws.CreateShortcut($shortcutPath);" ^
  "$shortcut.TargetPath = $targetPath;" ^
  "$shortcut.WorkingDirectory = $workingDir;" ^
  "$shortcut.IconLocation = $env:ICON_PATH;" ^
  "$shortcut.Save();" ^
  "if (-not (Test-Path -LiteralPath $shortcutPath)) { throw 'Shortcut file was not created.' }" 2>"%ERROR_FILE%"

if errorlevel 1 goto install_failed
del "%ERROR_FILE%" >nul 2>&1

color 0A
cls
echo.
echo      ____  _             _                 ___           _        _ _          _ 
echo     / ___^|^| ^|_ __ _ _ __^| ^|_ _   _ _ __   ^|_ _^|_ __  ___^| ^|_ __ _^| ^| ^| ___  __^| ^|
echo     \___ \^| __/ _` ^| '__^| __^| ^| ^| ^| '_ \   ^| ^|^| '_ \/ __^| __/ _` ^| ^| ^|/ _ \/ _` ^|
echo      ___) ^| ^|^| (_^| ^| ^|  ^| ^|_^| ^|_^| ^| ^|_) ^|  ^| ^|^| ^| ^| \__ \ ^|^| (_^| ^| ^| ^|  __/ (_^| ^|
echo     ^|____/ \__\__,_^|_^|   \__^|\__,_^| .__/  ^|___^|_^| ^|_^|___/\__\__,_^|_^|_^|\___^|\__,_^|
echo                                   ^|_^|                                                                                  
echo.
echo        ^>^>^> AUTOBOOT LINK ESTABLISHED
echo        ^>^>^> WINDOWS STARTUP ARMED
echo.
echo        Startup shortcut created:
echo        %SHORTCUT_PATH%
echo.
echo        The bot will launch after you sign in to Windows.
pause
exit /b 0

:install_failed
color 0C
cls
echo.
echo      ____  _             _                 _____     _ _          _ 
echo     / ___^|^| ^|_ __ _ _ __^| ^|_ _   _ _ __   ^|  ___^|_ _(_) ^| ___  __^| ^|
echo     \___ \^| __/ _` ^| '__^| __^| ^| ^| ^| '_ \  ^| ^|_ / _` ^| ^| ^|/ _ \/ _` ^|
echo      ___) ^| ^|^| (_^| ^| ^|  ^| ^|_^| ^|_^| ^| ^|_) ^| ^|  _^| (_^| ^| ^| ^|  __/ (_^| ^|
echo     ^|____/ \__\__,_^|_^|   \__^|\__,_^| .__/  ^|_^|  \__,_^|_^|_^|\___^|\__,_^|
echo                                   ^|_^|                               
echo.
echo        Startup install failed.
echo        Try running this file again, or check Windows permissions.
if exist "%ERROR_FILE%" (
    echo.
    type "%ERROR_FILE%"
)
pause
exit /b 1

:already_installed
color 0E
cls
echo.
echo      ____  _             _                 _____      _     _       
echo     / ___^|^| ^|_ __ _ _ __^| ^|_ _   _ _ __   ^| ____^|_  _(_)___^| ^|_ ___ 
echo     \___ \^| __/ _` ^| '__^| __^| ^| ^| ^| '_ \  ^|  _^| \ \/ / / __^| __/ __^|
echo      ___) ^| ^|^| (_^| ^| ^|  ^| ^|_^| ^|_^| ^| ^|_) ^| ^| ^|___ ^>  ^<^| \__ \ ^|_\__ \
echo     ^|____/ \__\__,_^|_^|   \__^|\__,_^| .__/  ^|_____/_/\_\_^|___/\__^|___/
echo                                   ^|_^|                               
echo.
echo        Startup shortcut already exists.
echo.
echo        Existing shortcut:
echo        %SHORTCUT_PATH%
echo.
echo        Nothing was changed.
pause
exit /b 0
