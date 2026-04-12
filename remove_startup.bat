@echo off
set "SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Discord Moderation Bot.lnk"

if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%"
    echo Startup shortcut removed.
) else (
    echo No startup shortcut was found.
)

pause
