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
import ctypes
import difflib
import json
import logging
import os
import tempfile
from pathlib import Path

import discord
from discord.ext import commands

from config import BOT_TOKEN, OWNER_IDS, PREFIX
from utils.db import get_custom_command, init_db
from utils.embeds import decorate_embed, make_embed


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
    return parser.parse_args()


ARGS = parse_args()
STATUS_FILE = Path(ARGS.status_file).resolve() if ARGS.status_file else None
LOCK_FILE = Path(tempfile.gettempdir()) / "discord_mod_bot.lock"
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
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
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


def write_status(state: str, message: str):
    """Write launcher-friendly boot state updates when a status file is supplied."""
    if not STATUS_FILE:
        return

    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(
        json.dumps({"state": state, "message": message}, ensure_ascii=True),
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

    if existing and _pid_is_running(int(existing.get("pid", 0))):
        raise RuntimeError(
            f"Another bot process is already running with PID {existing['pid']}."
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

    async def setup_hook(self):
        """Load all cogs before connecting so commands are ready immediately."""
        cogs_to_load = [
            "cogs.moderation",
            "cogs.cases",
            "cogs.invite_logger",
            "cogs.activity",
            "cogs.sentinel",
            "cogs.command_center",
            "cogs.custom_commands",
            "cogs.music",
            "cogs.server_management",
            "cogs.tickets",
            "cogs.configuration",
            "cogs.reaction_roles",
            "cogs.reminders",
            "cogs.utility",
            "cogs.fun",
            "cogs.help",
        ]

        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception as exc:
                log.error("Failed to load cog %s: %s", cog, exc)

        log.info("setup_hook complete")

    async def get_context(self, origin, /, *, cls=commands.Context):
        """Always return our branded context subclass."""
        return await super().get_context(origin, cls=BotContext)

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

    async def on_command_error(self, ctx: commands.Context, error):
        """Keep user-facing errors friendly while still logging real failures."""
        if isinstance(error, commands.CommandNotFound):
            attempted = (ctx.invoked_with or "").strip()
            if not attempted:
                return

            if ctx.guild:
                custom = await get_custom_command(ctx.guild.id, attempted.lower())
                if custom:
                    await ctx.send(render_custom_response(custom["response"], ctx))
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
            await ctx.send(
                embed=await make_embed(
                    self,
                    guild=ctx.guild,
                    title="Unknown Command",
                    description=(
                        f"I do not have `{PREFIX}{attempted}`.\n\n"
                        f"Did you mean:\n{suggestions}"
                    ),
                    color=discord.Color.orange(),
                )
            )
            return

        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=await make_embed(
                    self,
                    guild=ctx.guild,
                    title="Permission Required",
                    description="You do not have permission to use that command.",
                    color=discord.Color.red(),
                )
            )
            return

        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(
                embed=await make_embed(
                    self,
                    guild=ctx.guild,
                    title="Missing Bot Permissions",
                    description=f"I need these permissions first: `{', '.join(error.missing_permissions)}`",
                    color=discord.Color.red(),
                )
            )
            return

        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                embed=await make_embed(
                    self,
                    guild=ctx.guild,
                    title="Missing Argument",
                    description=f"`{error.param.name}` is required. Try `{PREFIX}help {ctx.command}` for usage.",
                    color=discord.Color.orange(),
                )
            )
            return

        if isinstance(error, commands.BadArgument):
            await ctx.send(
                embed=await make_embed(
                    self,
                    guild=ctx.guild,
                    title="Bad Argument",
                    description="That input does not match what the command expects. Try a valid mention, role, channel, or number.",
                    color=discord.Color.orange(),
                )
            )
            return

        log.error(
            "Unhandled error in command %s: %s", ctx.command, error, exc_info=error
        )
        await ctx.send(
            embed=await make_embed(
                self,
                guild=ctx.guild,
                title="Something Went Wrong",
                description="That command hit an unexpected error. I logged the details in `bot.log` for debugging.",
                color=discord.Color.red(),
            )
        )


async def main():
    """Create the bot instance and connect to Discord."""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TOKEN_HERE":
        raise RuntimeError(
            "BOT_TOKEN is missing. Add your real bot token to the .env file before starting the bot."
        )

    await init_db()
    bot = MyBot()
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    try:
        write_status("starting", "Booting bot...")
        acquire_lock()
        asyncio.run(main())
    except Exception as exc:
        log.exception("Bot failed to start")
        write_status("failed", str(exc))
        raise
    finally:
        release_lock()
