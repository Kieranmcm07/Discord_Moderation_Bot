"""Friendly Windows launcher for starting the bot in one visible console."""

# This is mostly quality-of-life for running my own bot from a double-click.
import ctypes
import os
import subprocess
import sys
from pathlib import Path


BOOT_BANNER = r"""
 ____  _                       _   ____        _
|  _ \(_)___  ___ ___  _ __ __| | | __ )  ___ | |_
| | | | / __|/ __/ _ \| '__/ _` | |  _ \ / _ \| __|
| |_| | \__ \ (_| (_) | | | (_| | | |_) | (_) | |_
|____/|_|___/\___\___/|_|  \__,_| |____/ \___/ \__|

Booting...
"""

SUCCESS_BANNER = r"""
 ____        _      ___        _ _
| __ )  ___ | |_   / _ \ _ __ | (_)_ __   ___
|  _ \ / _ \| __| | | | | '_ \| | | '_ \ / _ \
| |_) | (_) | |_  | |_| | | | | | | | | |  __/
|____/ \___/ \__|  \___/|_| |_|_|_|_| |_|\___|
"""

FAIL_BANNER = r"""
 ____        _      _____     _ _
| __ )  ___ | |_   |  ___|_ _(_) |
|  _ \ / _ \| __|  | |_ / _` | | |
| |_) | (_) | |_   |  _| (_| | | |
|____/ \___/ \__|  |_|  \__,_|_|_|
"""


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


def main():
    enable_ansi()
    show_banner(
        BOOT_BANNER,
        "36",
        "Starting Discord Moderation bot. Logs will appear below.\n",
    )

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        exit_code = subprocess.call(
            [sys.executable, "main.py"],
            cwd=Path(__file__).resolve().parent,
            env=env,
        )
    except KeyboardInterrupt:
        print(paint("\nShutdown requested from the console.", "93"))
        return 130

    if exit_code == 0:
        print(paint("\nBot stopped cleanly.", "92"))
        return 0

    print(paint(FAIL_BANNER, "91"))
    print(
        paint(
            f"\nBot stopped with exit code {exit_code}. Check bot.log for details.",
            "91",
        )
    )
    input("\nPress Enter to close this window...")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
