import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


BOOT_BANNER = r"""
                                                                                                                                 
88888888ba                           88888888ba                                     88                                           
88      "8b                ,d        88      "8b                             ,d     ""                                           
88      ,8P                88        88      ,8P                             88                                                  
88aaaaaa8P'   ,adPPYba,  MM88MMM     88aaaaaa8P'   ,adPPYba,    ,adPPYba,  MM88MMM  88  8b,dPPYba,    ,adPPYb,d8                 
88""""""8b,  a8"     "8a   88        88""""""8b,  a8"     "8a  a8"     "8a   88     88  88P'   `"8a  a8"    `Y88                 
88      `8b  8b       d8   88        88      `8b  8b       d8  8b       d8   88     88  88       88  8b       88                 
88      a8P  "8a,   ,a8"   88,       88      a8P  "8a,   ,a8"  "8a,   ,a8"   88,    88  88       88  "8a,   ,d88  888  888  888  
88888888P"    `"YbbdP"'    "Y888     88888888P"    `"YbbdP"'    `"YbbdP"'    "Y888  88  88       88   `"YbbdP"Y8  888  888  888  
                                                                                                      aa,    ,88                 
                                                                                                       "Y8bbdP"                  
"""

SUCCESS_BANNER = r"""
                                                                                                   
88888888ba                             ,ad8888ba,                 88  88                           
88      "8b                ,d         d8"'    `"8b                88  ""                           
88      ,8P                88        d8'        `8b               88                               
88aaaaaa8P'   ,adPPYba,  MM88MMM     88          88  8b,dPPYba,   88  88  8b,dPPYba,    ,adPPYba,  
88""""""8b,  a8"     "8a   88        88          88  88P'   `"8a  88  88  88P'   `"8a  a8P_____88  
88      `8b  8b       d8   88        Y8,        ,8P  88       88  88  88  88       88  8PP"""""""  
88      a8P  "8a,   ,a8"   88,        Y8a.    .a8P   88       88  88  88  88       88  "8b,   ,aa  
88888888P"    `"YbbdP"'    "Y888       `"Y8888Y"'    88       88  88  88  88       88   `"Ybbd8"'  
                                                                                                   
                                                                                                   
"""

FAIL_BANNER = r'''
                                                                                           
88888888ba                           88888888888          88  88                       88  
88      "8b                ,d        88                   ""  88                       88  
88      ,8P                88        88                       88                       88  
88aaaaaa8P'   ,adPPYba,  MM88MMM     88aaaaa  ,adPPYYba,  88  88   ,adPPYba,   ,adPPYb,88  
88""""""8b,  a8"     "8a   88        88"""""  ""     `Y8  88  88  a8P_____88  a8"    `Y88  
88      `8b  8b       d8   88        88       ,adPPPPP88  88  88  8PP"""""""  8b       88  
88      a8P  "8a,   ,a8"   88,       88       88,    ,88  88  88  "8b,   ,aa  "8a,   ,d88  
88888888P"    `"YbbdP"'    "Y888     88       `"8bbdP"Y8  88  88   `"Ybbd8"'   `"8bbdP"Y8  
                                                                                           
                                                                                           
'''


def enable_ansi():
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)


def clear_screen():
    os.system("cls")


def paint(text: str, colour: str) -> str:
    return f"\033[{colour}m{text}\033[0m"


def show_banner(banner: str, colour: str, message: str):
    clear_screen()
    print(paint(banner, colour))
    print(paint(message, colour))


def read_status(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def find_pythonw():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if pythonw.exists():
        return str(pythonw)
    return sys.executable


def main():
    enable_ansi()
    show_banner(BOOT_BANNER, "36", "Starting Discord moderation bot...")

    status_file = Path(tempfile.gettempdir()) / "discord_mod_bot_status.json"
    if status_file.exists():
        status_file.unlink()

    python_exe = find_pythonw()
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    process = subprocess.Popen(
        [python_exe, "main.py", "--background", "--status-file", str(status_file)],
        cwd=Path(__file__).resolve().parent,
        creationflags=creation_flags,
    )

    deadline = time.time() + 45
    while time.time() < deadline:
        status = read_status(status_file)
        if status:
            state = status.get("state")
            message = status.get("message", "")

            if state == "ready":
                show_banner(
                    SUCCESS_BANNER,
                    "92",
                    "Bot online. Running quietly in the background.",
                )
                time.sleep(2)
                return 0

            if state == "failed":
                show_banner(FAIL_BANNER, "91", f"Startup failed: {message}")
                input("\nPress Enter to close this window...")
                return 1

        if process.poll() is not None:
            status = read_status(status_file) or {}
            message = status.get(
                "message", "Bot process exited before it came online."
            )
            show_banner(FAIL_BANNER, "91", f"Startup failed: {message}")
            input("\nPress Enter to close this window...")
            return 1

        time.sleep(1)

    try:
        process.terminate()
    except OSError:
        pass

    show_banner(
        FAIL_BANNER,
        "91",
        "Startup timed out before the bot reported ready. Check bot.log for details.",
    )
    input("\nPress Enter to close this window...")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
