# ============================================================
#   Made by Kieranmcm07 on GitHub
#   GitHub: https://github.com/Kieranmcm07
# ============================================================
"""
Bot entry point.

This file handles startup, logging, the custom context class, cog loading, and
global command errors. Keeping those pieces together makes the rest of the
project easier to reason about.
"""

# This is the one file I expect people to run directly.
import argparse
import asyncio
import atexit
import contextlib
import ctypes
import difflib
import json
import logging
import os
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import discord
from discord.ext import commands

from config import (
    BOT_TOKEN,
    OWNER_IDS,
    PREFIX,
)
from utils.db import get_custom_command, init_db
from utils.embeds import decorate_embed
from utils.errors import (
    log_exception,
    safe_context_send,
    send_command_feedback,
    send_unexpected_command_error,
    send_unexpected_interaction_error,
)

TOKEN_PLACEHOLDERS = {"YOUR_TOKEN_HERE", "YOUR_BOT_TOKEN_HERE"}
FAILURE_MODES = {"retry", "close"}


class StartupConfigurationError(RuntimeError):
    """Raised when the bot cannot start until local configuration is fixed."""


def parse_retry_delay(value: str) -> int:
    """Parse a positive retry delay from CLI/env input."""
    try:
        delay = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("retry delay must be a whole number") from exc

    if delay < 1:
        raise argparse.ArgumentTypeError("retry delay must be at least 1 second")

    return delay


def default_failure_mode() -> str:
    """Read the default failure mode without trusting misspelled env values."""
    mode = os.getenv("BOT_FAILURE_MODE", "retry").strip().lower()
    if mode in FAILURE_MODES:
        return mode
    return "retry"


def default_retry_delay() -> int:
    """Read the retry delay from env, falling back to the requested 5 seconds."""
    try:
        return parse_retry_delay(os.getenv("BOT_RETRY_DELAY_SECONDS", "5"))
    except argparse.ArgumentTypeError:
        return 5


def parse_args():
    """Parse a small set of startup flags used by the launcher scripts."""
    parser = argparse.ArgumentParser(description="Run the Discord moderation bot.")
    parser.add_argument(
        "--background",
        action="store_true",
        help="Run without console logging for background startup.",
    )
    parser.add_argument(
        "--status-file",
        help="Write launcher status updates to this file while booting.",
    )
    parser.add_argument(
        "--failure-mode",
        choices=sorted(FAILURE_MODES),
        default=default_failure_mode(),
        help="Choose whether unexpected bot failures should retry or close.",
    )
    parser.add_argument(
        "--retry-delay",
        type=parse_retry_delay,
        default=default_retry_delay(),
        help="Seconds to wait before retrying after an unexpected failure.",
    )

    if __name__ == "__main__":
        return parser.parse_args()

    # Tests and import-time tooling often add their own flags. Ignoring unknown
    # flags here lets those tools import main.py without pretending to run it.
    return parser.parse_known_args()[0]


ARGS = parse_args()
STATUS_FILE = Path(ARGS.status_file).resolve() if ARGS.status_file else None
LOCK_FILE = Path(tempfile.gettempdir()) / "discord_mod_bot.lock"
STOP_REQUEST_FILE = Path(tempfile.gettempdir()) / "discord_mod_bot_stop.json"
LOCK_ACQUIRED = False


class ColoredFormatter(logging.Formatter):
    """Add ANSI colors to console logs while keeping the file log plain."""

    RESET = "\033[0m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    WHITE = "\033[97m"
    DIM = "\033[90m"

    LEVEL_COLORS = {
        logging.DEBUG: DIM,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: RED,
    }

    def format(self, record):
        created = self.formatTime(record, self.datefmt)
        level_color = self.LEVEL_COLORS.get(record.levelno, self.WHITE)
        level = f"{level_color}[{record.levelname}]{self.RESET}"
        name = f"{self.BLUE}{record.name}:{self.RESET}"
        message = f"{self.WHITE}{record.getMessage()}{self.RESET}"
        line = f"{self.GREEN}{created}{self.RESET} {level} {name} {message}"

        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            line = f"{line}\n{self.formatStack(record.stack_info)}"
        return line


def enable_ansi():
    """Enable ANSI colors in Windows consoles when possible."""
    if os.name != "nt":
        return

    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def configure_logging():
    """Log to file every time, and to the console unless background mode is used."""
    file_handler = RotatingFileHandler(
        "bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    handlers = [file_handler]
    if not ARGS.background:
        enable_ansi()
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            ColoredFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        handlers.append(console_handler)

    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
    )


def write_status(state: str, message: str, **extra):
    """Write launcher-friendly boot state updates when a status file is supplied."""
    if not STATUS_FILE:
        return

    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "message": message}
    payload.update(extra)
    STATUS_FILE.write_text(
        json.dumps(payload, ensure_ascii=True),
        encoding="utf-8",
    )


def _pid_is_running(pid: int) -> bool:
    """Check whether a stored process id still appears to be alive."""
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


def release_lock():
    """Remove the single-instance lock if this process owns it."""
    global LOCK_ACQUIRED

    if not LOCK_ACQUIRED:
        return

    try:
        payload = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        LOCK_ACQUIRED = False
        return

    if payload.get("pid") == os.getpid():
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass

    LOCK_ACQUIRED = False


def acquire_lock():
    """Prevent accidental double-starts from the launcher or startup scripts."""
    global LOCK_ACQUIRED

    payload = json.dumps(
        {"pid": os.getpid(), "project": str(Path(__file__).resolve().parent)},
        ensure_ascii=True,
    )

    try:
        with LOCK_FILE.open("x", encoding="utf-8") as handle:
            handle.write(payload)
        LOCK_ACQUIRED = True
        return
    except FileExistsError:
        pass

    try:
        existing = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = None

    try:
        existing_pid = int(existing.get("pid", 0)) if existing else 0
    except (TypeError, ValueError):
        existing_pid = 0

    if existing and _pid_is_running(existing_pid):
        raise RuntimeError(
            f"Another bot process is already running with PID {existing_pid}."
        )

    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass

    with LOCK_FILE.open("x", encoding="utf-8") as handle:
        handle.write(payload)
    LOCK_ACQUIRED = True


def render_custom_response(template: str, ctx: commands.Context) -> str:
    """Apply safe, simple placeholders to custom command responses."""
    guild_name = ctx.guild.name if ctx.guild else "this server"
    return (
        template.replace("{user}", ctx.author.mention)
        .replace("{username}", ctx.author.display_name)
        .replace("{server}", guild_name)
    )


configure_logging()
log = logging.getLogger("bot")
atexit.register(release_lock)

# The bot only enables the intents it actually uses.
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.invites = True


class BotContext(commands.Context):
    """Context subclass that automatically brands embeds before they are sent."""

    async def send(self, content=None, **kwargs):
        embed = kwargs.get("embed")
        embeds = kwargs.get("embeds")

        if embed is not None:
            kwargs["embed"] = await decorate_embed(self.bot, self.guild, embed)

        if embeds is not None:
            kwargs["embeds"] = [
                await decorate_embed(self.bot, self.guild, item) for item in embeds
            ]

        return await super().send(content=content, **kwargs)


class MyBot(commands.Bot):
    """Custom bot class so shared behaviour lives in one obvious place."""

    def __init__(self):
        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            owner_ids=set(OWNER_IDS),
            help_command=None,
            case_insensitive=True,
        )
        self.started_at = discord.utils.utcnow()
        self._stop_watcher_task: asyncio.Task | None = None
        self.tree.on_error = self.on_app_command_error

    async def bot_check(self, ctx: commands.Context) -> bool:
        """Keep server-only commands from crashing when used in DMs."""
        if ctx.guild is not None:
            return True

        root_command = None
        if ctx.command:
            root_command = ctx.command.root_parent or ctx.command

        if root_command and root_command.name in {"ping", "about", "help"}:
            return True

        raise commands.NoPrivateMessage()

    async def setup_hook(self):
        """Load all cogs before connecting so commands are ready immediately."""
        cogs_to_load = [
            "cogs.moderation",
            "cogs.cases",
            "cogs.invite_logger",
            "cogs.message_audit",
            "cogs.activity",
            "cogs.sentinel",
            "cogs.automod",
            "cogs.command_center",
            "cogs.custom_commands",
            "cogs.music",
            "cogs.server_management",
            "cogs.tickets",
            "cogs.appeals",
            "cogs.configuration",
            "cogs.reaction_roles",
            "cogs.reminders",
            "cogs.afk",
            "cogs.utility",
            "cogs.fun",
            "cogs.help",
        ]

        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception:
                log.exception("Failed to load cog: %s", cog)

        log.info("setup_hook complete")
        self._stop_watcher_task = asyncio.create_task(
            self.watch_stop_requests(),
            name="stop-request-watcher",
        )

    async def get_context(self, origin, /, *, cls=commands.Context):
        """Always return our branded context subclass."""
        return await super().get_context(origin, cls=BotContext)

    def stop_request_matches_this_process(self) -> bool:
        """Return whether the launcher asked this bot process to stop."""
        try:
            payload = json.loads(STOP_REQUEST_FILE.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return False

        raw_ids = payload.get("pids")
        if raw_ids is None:
            raw_ids = [payload.get("pid")]
        elif not isinstance(raw_ids, list):
            raw_ids = [raw_ids]

        requested_ids = set()
        for raw_id in raw_ids:
            try:
                requested_ids.add(int(raw_id))
            except (TypeError, ValueError):
                continue

        return os.getpid() in requested_ids

    async def watch_stop_requests(self):
        """Watch for the Windows helper script's graceful shutdown request."""
        try:
            await self.wait_until_ready()
            while not self.is_closed():
                if self.stop_request_matches_this_process():
                    log.info("Graceful stop request received from stop_bot.bat")
                    write_status("stopping", "Graceful shutdown requested...")
                    try:
                        STOP_REQUEST_FILE.unlink()
                    except FileNotFoundError:
                        pass
                    await self.close()
                    return

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Stop request watcher failed")

    async def close(self):
        """Shut down background helpers before disconnecting."""

        current_task = asyncio.current_task()
        if self._stop_watcher_task and self._stop_watcher_task is not current_task:
            self._stop_watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stop_watcher_task

        await super().close()

    async def on_ready(self):
        """Log a clean ready message and refresh the public presence text."""
        log.info(
            "Bot online as %s (ID: %s). Serving %s guild(s).",
            self.user,
            self.user.id,
            len(self.guilds),
        )
        write_status(
            "ready",
            f"Logged in as {self.user} across {len(self.guilds)} guild(s)",
        )

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | {PREFIX}help",
            )
        )

    async def on_error(self, event_method: str, *args, **kwargs):
        """Log listener/background event crashes with searchable error IDs."""
        _, error, _ = sys.exc_info()
        if error is None:
            log.error("Unhandled event error in %s, but no exception was available", event_method)
            return

        first_arg = args[0] if args else None
        guild = getattr(first_arg, "guild", None)
        channel = getattr(first_arg, "channel", None)
        user = getattr(first_arg, "author", None) or getattr(first_arg, "user", None)

        log_exception(
            log,
            f"Unhandled event error in {event_method}",
            error,
            event=event_method,
            guild_id=getattr(guild, "id", None),
            channel_id=getattr(channel, "id", None),
            user_id=getattr(user, "id", None),
            arg_count=len(args),
            kwarg_keys=",".join(kwargs.keys()),
        )

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        """Give slash/app command crashes the same error-ID treatment."""
        error = getattr(error, "original", error)
        command = getattr(interaction, "command", None)
        error_id = log_exception(
            log,
            "Unhandled app command error",
            error,
            command=getattr(command, "qualified_name", None),
            guild_id=getattr(interaction.guild, "id", None),
            channel_id=getattr(interaction.channel, "id", None),
            user_id=getattr(interaction.user, "id", None),
        )
        await send_unexpected_interaction_error(interaction, error_id)

    async def on_command_error(self, ctx: commands.Context, error):
        """Keep user-facing errors friendly while still logging real failures."""
        error = getattr(error, "original", error)

        if isinstance(error, commands.CommandNotFound):
            attempted = (ctx.invoked_with or "").strip()
            if not attempted:
                return

            if ctx.guild:
                custom = await get_custom_command(ctx.guild.id, attempted.lower())
                if custom:
                    await safe_context_send(
                        ctx,
                        render_custom_response(custom["response"], ctx),
                    )
                    return

            visible_commands = [
                command
                for command in self.walk_commands()
                if not command.hidden and command.enabled
            ]
            names = sorted(
                {
                    name
                    for command in visible_commands
                    for name in (command.qualified_name, *command.aliases)
                }
            )
            matches = difflib.get_close_matches(attempted, names, n=3, cutoff=0.55)
            if not matches:
                return

            suggestions = "\n".join(f"`{PREFIX}{name}`" for name in matches)
            await send_command_feedback(
                ctx,
                self,
                title="Unknown Command",
                description=(
                    f"I do not have `{PREFIX}{attempted}`.\n\n"
                    f"Did you mean:\n{suggestions}"
                ),
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.NoPrivateMessage):
            await send_command_feedback(
                ctx,
                self,
                title="Server Only",
                description=(
                    "That command needs to be used inside a server where I can "
                    "read roles, channels, and permissions."
                ),
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.MissingPermissions):
            await send_command_feedback(
                ctx,
                self,
                title="Permission Required",
                description="You do not have permission to use that command.",
                color=discord.Color.red(),
            )
            return

        if isinstance(error, commands.BotMissingPermissions):
            await send_command_feedback(
                ctx,
                self,
                title="Missing Bot Permissions",
                description=f"I need these permissions first: `{', '.join(error.missing_permissions)}`",
                color=discord.Color.red(),
            )
            return

        if isinstance(error, commands.MissingRequiredArgument):
            await send_command_feedback(
                ctx,
                self,
                title="Missing Argument",
                description=f"`{error.param.name}` is required. Try `{PREFIX}help {ctx.command}` for usage.",
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.BadUnionArgument):
            await send_command_feedback(
                ctx,
                self,
                title="Bad Argument",
                description=(
                    "I could not find that member or user. Try a mention, "
                    "user ID, or exact username."
                ),
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.BadArgument):
            await send_command_feedback(
                ctx,
                self,
                title="Bad Argument",
                description="That input does not match what the command expects. Try a valid mention, role, channel, or number.",
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.UserInputError):
            usage_hint = (
                f" Try `{PREFIX}help {ctx.command.qualified_name}` for usage."
                if ctx.command
                else ""
            )
            await send_command_feedback(
                ctx,
                self,
                title="Bad Input",
                description=(
                    "That input does not match what the command expects."
                    f"{usage_hint}"
                ),
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.CommandOnCooldown):
            retry_after = max(1, round(error.retry_after))
            await send_command_feedback(
                ctx,
                self,
                title="Slow Down",
                description=f"That command is on cooldown. Try again in `{retry_after}` second(s).",
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.DisabledCommand):
            await send_command_feedback(
                ctx,
                self,
                title="Command Disabled",
                description="That command is currently disabled.",
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.NotOwner):
            await send_command_feedback(
                ctx,
                self,
                title="Owner Only",
                description="Only the bot owner can use that command.",
                color=discord.Color.red(),
            )
            return

        if isinstance(error, commands.MaxConcurrencyReached):
            await send_command_feedback(
                ctx,
                self,
                title="Already Running",
                description="That command is already running. Wait for it to finish before starting another one.",
                color=discord.Color.orange(),
            )
            return

        if isinstance(error, commands.CheckFailure):
            await send_command_feedback(
                ctx,
                self,
                title="Cannot Use That Here",
                description="That command cannot be used in this context.",
                color=discord.Color.orange(),
            )
            return

        error_id = log_exception(
            log,
            "Unhandled command error",
            error,
            command=getattr(ctx.command, "qualified_name", None),
            guild_id=getattr(ctx.guild, "id", None),
            channel_id=getattr(ctx.channel, "id", None),
            author_id=getattr(ctx.author, "id", None),
            message_id=getattr(ctx.message, "id", None),
        )
        await send_unexpected_command_error(ctx, self, error_id)


NON_RETRYABLE_STARTUP_ERRORS = (
    StartupConfigurationError,
    discord.LoginFailure,
    discord.PrivilegedIntentsRequired,
)


async def run_bot_once():
    """Create the bot instance and connect to Discord."""
    if not BOT_TOKEN or BOT_TOKEN in TOKEN_PLACEHOLDERS:
        raise StartupConfigurationError(
            "BOT_TOKEN is missing. Add your real bot token to the .env file before starting the bot."
        )

    await init_db()
    bot = MyBot()
    async with bot:
        await bot.start(BOT_TOKEN)


async def main():
    """Run the bot, optionally retrying unexpected top-level failures."""
    attempt = 1
    while True:
        attempt_message = (
            f"Booting bot... (attempt {attempt})"
            if ARGS.failure_mode == "retry"
            else "Booting bot..."
        )
        write_status("starting", attempt_message)
        if attempt > 1:
            log.info("Retrying bot startup (attempt %s)", attempt)

        try:
            await run_bot_once()
            return
        except asyncio.CancelledError:
            raise
        except NON_RETRYABLE_STARTUP_ERRORS:
            raise
        except Exception as exc:
            if ARGS.failure_mode != "retry":
                raise

            retry_at = time.time() + ARGS.retry_delay
            log.exception(
                "Bot failed; retrying in %s second(s)",
                ARGS.retry_delay,
            )
            write_status(
                "retrying",
                f"{exc}. Retrying in {ARGS.retry_delay} second(s)...",
                retry_delay=ARGS.retry_delay,
                retry_at=retry_at,
                attempt=attempt,
            )
            await asyncio.sleep(ARGS.retry_delay)
            attempt += 1


if __name__ == "__main__":
    try:
        acquire_lock()
        asyncio.run(main())
    except Exception as exc:
        log.exception("Bot failed to start")
        write_status("failed", str(exc))
        raise
    finally:
        release_lock()
