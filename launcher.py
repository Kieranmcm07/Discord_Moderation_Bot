# ============================================================
#   Made by Kieranmcm07 on GitHub
#   GitHub: https://github.com/Kieranmcm07
# ============================================================
"""Friendly Windows launcher that shows boot logs, then leaves the bot running."""

# This is mostly quality-of-life for running my own bot from a double-click.
import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BOOT_BANNER = r"""
    ____  _                       _   ____        _   
   |  _ \(_)___  ___ ___  _ __ __| | | __ )  ___ | |_ 
   | | | | / __|/ __/ _ \| '__/ _` | |  _ \ / _ \| __|
   | |_| | \__ \ (_| (_) | | | (_| | | |_) | (_) | |_ 
   |____/|_|___/\___\___/|_|  \__,_| |____/ \___/ \__|                                              

        [ SYSTEM BOOT ]  Initializing moderation core...
        [ ACCESS NODE ]  Loading guild security modules...
        [ NETLINK     ]  Connecting to Discord gateway...
"""

SUCCESS_BANNER = r"""
     ____        _      ___        _ _            
    | __ )  ___ | |_   / _ \ _ __ | (_)_ __   ___ 
    |  _ \ / _ \| __| | | | | '_ \| | | '_ \ / _ \
    | |_) | (_) | |_  | |_| | | | | | | | | |  __/
    |____/ \___/ \__|  \___/|_| |_|_|_|_| |_|\___|                                                                

        >>> ACCESS GRANTED
        >>> MODERATION SYSTEM ONLINE
"""

FAIL_BANNER = r"""
     ____        _     _____     _ _          _ 
    | __ )  ___ | |_  |  ___|_ _(_) | ___  __| |
    |  _ \ / _ \| __| | |_ / _` | | |/ _ \/ _` |
    | |_) | (_) | |_  |  _| (_| | | |  __/ (_| |
    |____/ \___/ \__| |_|  \__,_|_|_|\___|\__,_|                                                                      
"""

CREDITS_BANNER = r"""
        Built by Kieranmcm07
        GitHub: https://github.com/Kieranmcm07
        Like the bot? Star the project, open an issue, or send a pull request.
"""

STAR_BANNER = r"""
                .        .       .
           .        *        .        *
                .        .       .
            ____  _               ___ _   
           / ___|| |_ __ _ _ __  |_ _| |_ 
           \___ \| __/ _` | '__|  | || __|
            ___) | || (_| | |     | || |_ 
           |____/ \__\__,_|_|    |___|\__|

        Project link: https://github.com/Kieranmcm07
"""


def enable_ansi():
    if os.name != "nt":
        return

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


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


def pid_is_running(pid: int) -> bool:
    """Return whether a process id currently appears to be alive."""
    if pid <= 0:
        return False

    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        process_query_limited_information = 0x1000
        still_active = 259

        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False

        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def running_pid_from_lock(lock_file: Path):
    """Read the bot lock file and return its pid if that process is running."""
    try:
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    try:
        pid = int(payload.get("pid", 0))
    except (TypeError, ValueError):
        pid = 0

    if pid_is_running(pid):
        return pid

    try:
        lock_file.unlink()
    except FileNotFoundError:
        pass
    return None


def find_pythonw():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if pythonw.exists():
        return str(pythonw)
    return sys.executable


def color_log_line(line: str) -> str:
    match = re.match(
        r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
        r"\[(?P<level>[A-Z]+)\] (?P<name>[^:]+): (?P<message>.*)$",
        line.rstrip(),
    )
    if not match:
        return line.rstrip()

    level = match.group("level")
    level_colour = {
        "DEBUG": "90",
        "INFO": "92",
        "WARNING": "93",
        "ERROR": "91",
        "CRITICAL": "91",
    }.get(level, "97")

    return (
        f"{paint(match.group('time'), '92')} "
        f"{paint(f'[{level}]', level_colour)} "
        f"{paint(match.group('name') + ':', '94')} "
        f"{paint(match.group('message'), '97')}"
    )


def print_new_log_lines(log_file: Path, offset: int) -> int:
    if not log_file.exists():
        return offset

    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        for line in handle:
            print(color_log_line(line), flush=True)
        return handle.tell()


def main():
    enable_ansi()
    show_banner(
        BOOT_BANNER,
        "36",
        "Starting Discord Moderation bot. Logs will appear below.\n",
    )
    print(paint(CREDITS_BANNER, "95"))

    project_dir = Path(__file__).resolve().parent
    log_file = project_dir / "bot.log"
    log_offset = log_file.stat().st_size if log_file.exists() else 0
    status_file = Path(tempfile.gettempdir()) / "discord_mod_bot_status.json"
    lock_file = Path(tempfile.gettempdir()) / "discord_mod_bot.lock"

    running_pid = running_pid_from_lock(lock_file)
    if running_pid:
        clear_screen()
        print(paint(SUCCESS_BANNER, "92"))
        print(paint(STAR_BANNER, "95"))
        print(paint(f"Bot is already running with PID {running_pid}.", "92"))
        time.sleep(2)
        return 0

    if status_file.exists():
        status_file.unlink()

    python_exe = find_pythonw()
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    process = subprocess.Popen(
        [
            python_exe,
            str(project_dir / "main.py"),
            "--background",
            "--status-file",
            str(status_file),
        ],
        cwd=project_dir,
        creationflags=creation_flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 60
    while time.time() < deadline:
        log_offset = print_new_log_lines(log_file, log_offset)
        status = read_status(status_file)
        if status:
            state = status.get("state")
            message = status.get("message", "")

            if state == "ready":
                log_offset = print_new_log_lines(log_file, log_offset)
                clear_screen()
                print(paint(SUCCESS_BANNER, "92"))
                print(paint(STAR_BANNER, "95"))
                print(paint(f"Bot online. {message}", "92"))
                time.sleep(2)
                return 0

            if state == "failed":
                log_offset = print_new_log_lines(log_file, log_offset)
                clear_screen()
                print(paint(FAIL_BANNER, "91"))
                print(paint(f"Startup failed: {message}", "91"))
                input("\nPress Enter to close this window...")
                return 1

        if process.poll() is not None:
            log_offset = print_new_log_lines(log_file, log_offset)
            status = read_status(status_file) or {}
            message = status.get("message", "Bot process exited before it came online.")
            clear_screen()
            print(paint(FAIL_BANNER, "91"))
            print(paint(f"Startup failed: {message}", "91"))
            input("\nPress Enter to close this window...")
            return 1

        time.sleep(0.5)

    try:
        process.terminate()
    except OSError:
        pass

    log_offset = print_new_log_lines(log_file, log_offset)
    clear_screen()
    print(paint(FAIL_BANNER, "91"))
    print(paint("Startup timed out before the bot reported ready.", "91"))
    input("\nPress Enter to close this window...")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
