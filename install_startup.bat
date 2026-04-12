@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_DIR%\Discord Moderation Bot.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$shortcut = $ws.CreateShortcut('%SHORTCUT_PATH%'); " ^
  "$shortcut.TargetPath = '%PROJECT_DIR%start_bot.bat'; " ^
  "$shortcut.WorkingDirectory = '%PROJECT_DIR%'; " ^
  "$shortcut.IconLocation = '%SystemRoot%\System32\cmd.exe,0'; " ^
  "$shortcut.Save()"

echo Startup shortcut created:
echo %SHORTCUT_PATH%
pause
