@echo off
setlocal
title Remove Discord Moderation Bot Startup
color 0C
mode con: cols=120 lines=30
cls

echo.
echo      ____  _             _                 ____                               
echo     / ___^|^| ^|_ __ _ _ __^| ^|_ _   _ _ __   ^|  _ \ ___ _ __ ___   _____   _____ 
echo     \___ \^| __/ _` ^| '__^| __^| ^| ^| ^| '_ \  ^| ^|_) / _ \ '_ ` _ \ / _ \ \ / / _ \
echo      ___) ^| ^|^| (_^| ^| ^|  ^| ^|_^| ^|_^| ^| ^|_) ^| ^|  _ ^<  __/ ^| ^| ^| ^| ^| (_) \ V /  __/
echo     ^|____/ \__\__,_^|_^|   \__^|\__,_^| .__/  ^|_^| \_\___^|_^| ^|_^| ^|_^|\___/ \_/ \___^|
echo                                   ^|_^|                                         
echo.
echo        [ STARTUP BOOT ]  Locating Windows autostart link...
echo        [ DISARM       ]  Preparing shortcut removal...
echo.
timeout /t 2 /nobreak >nul

REM Removes the startup shortcut made by install_startup.bat.
set "SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Discord Moderation Bot.lnk"
set "ERROR_FILE=%TEMP%\discord_mod_bot_remove_startup_error.txt"
set "RESULT_FILE=%TEMP%\discord_mod_bot_remove_startup_result.txt"
del "%ERROR_FILE%" >nul 2>&1
del "%RESULT_FILE%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$shortcutPath = $env:SHORTCUT_PATH;" ^
  "$resultPath = $env:RESULT_FILE;" ^
  "if (Test-Path -LiteralPath $shortcutPath) {" ^
  "  Remove-Item -LiteralPath $shortcutPath -Force;" ^
  "  'removed' | Set-Content -LiteralPath $resultPath -Encoding ASCII;" ^
  "} else {" ^
  "  'missing' | Set-Content -LiteralPath $resultPath -Encoding ASCII;" ^
  "}" 2>"%ERROR_FILE%"

if errorlevel 1 goto remove_failed

set /p REMOVE_RESULT=<"%RESULT_FILE%"
del "%ERROR_FILE%" >nul 2>&1
del "%RESULT_FILE%" >nul 2>&1

if /I "%REMOVE_RESULT%"=="removed" goto removed
goto missing

pause

:remove_failed
cls
echo.
echo      ____                                 _____     _ _          _ 
echo     ^|  _ \ ___ _ __ ___   _____   _____  ^|  ___^|_ _(_) ^| ___  __^| ^|
echo     ^| ^|_) / _ \ '_ ` _ \ / _ \ \ / / _ \ ^| ^|_ / _` ^| ^| ^|/ _ \/ _` ^|
echo     ^|  _ ^<  __/ ^| ^| ^| ^| ^| (_) \ V /  __/ ^|  _^| (_^| ^| ^| ^|  __/ (_^| ^|
echo     ^|_^| \_\___^|_^| ^|_^| ^|_^|\___/ \_/ \___^| ^|_^|  \__,_^|_^|_^|\___^|\__,_^|
echo.                                                            
echo        Startup remove failed.
if exist "%ERROR_FILE%" (
    echo.
    type "%ERROR_FILE%"
)
pause
exit /b 1

:removed
cls
echo.
echo      ____  _             _                 ____                                   _ 
echo     / ___^|^| ^|_ __ _ _ __^| ^|_ _   _ _ __   ^|  _ \ ___ _ __ ___   _____   _____  __^| ^|
echo     \___ \^| __/ _` ^| '__^| __^| ^| ^| ^| '_ \  ^| ^|_) / _ \ '_ ` _ \ / _ \ \ / / _ \/ _` ^|
echo      ___) ^| ^|^| (_^| ^| ^|  ^| ^|_^| ^|_^| ^| ^|_) ^| ^|  _ ^<  __/ ^| ^| ^| ^| ^| (_) \ V /  __/ (_^| ^|
echo     ^|____/ \__\__,_^|_^|   \__^|\__,_^| .__/  ^|_^| \_\___^|_^| ^|_^| ^|_^|\___/ \_/ \___^|\__,_^|
echo                                   ^|_^|                                               
echo.
echo        ^>^>^> AUTOBOOT LINK DESTROYED
echo        ^>^>^> WINDOWS STARTUP DISARMED
echo.
echo        Startup shortcut removed.
pause
exit /b 0

:missing
color 0E
cls
echo.
echo      _   _         ____  _             _               
echo     ^| \ ^| ^| ___   / ___^|^| ^|_ __ _ _ __^| ^|_ _   _ _ __  
echo     ^|  \^| ^|/ _ \  \___ \^| __/ _` ^| '__^| __^| ^| ^| ^| '_ \ 
echo     ^| ^|\  ^| (_) ^|  ___) ^| ^|^| (_^| ^| ^|  ^| ^|_^| ^|_^| ^| ^|_) ^|
echo     ^|_^| \_^|\___/  ^|____/ \__\__,_^|_^|   \__^|\__,_^| .__/ 
echo                                                 ^|_^|    
echo.
echo        No startup shortcut was found.
pause
exit /b 0
