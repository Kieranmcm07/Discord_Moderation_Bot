"""
Bot entry point.

This file handles startup, logging, the custom context class, cog loading, and
global command errors. Keeping those pieces together makes the rest of the
project easier to reason about.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

import discord
from discord.ext import commands

from config import BOT_TOKEN, OWNER_IDS, PREFIX
from utils.db import init_db
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


def configure_logging():
    """Log to file every time, and to the console unless background mode is used."""
    handlers = [logging.FileHandler("bot.log", encoding="utf-8")]
    if not ARGS.background:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
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


configure_logging()
log = logging.getLogger("bot")

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

    async def setup_hook(self):
        """Load all cogs before connecting so commands are ready immediately."""
        cogs_to_load = [
            "cogs.moderation",
            "cogs.cases",
            "cogs.invite_logger",
            "cogs.activity",
            "cogs.music",
            "cogs.server_management",
            "cogs.tickets",
            "cogs.configuration",
            "cogs.reaction_roles",
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
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        log.info("Serving %s guild(s)", len(self.guilds))
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

        log.error("Unhandled error in command %s: %s", ctx.command, error, exc_info=error)
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
        asyncio.run(main())
    except Exception as exc:
        log.exception("Bot failed to start")
        write_status("failed", str(exc))
        raise
