"""
main.py — the heart of the bot, this is where everything boots up.
I kept it clean so it's easy to add or remove cogs without breaking anything.
"""

import discord
from discord.ext import commands
import asyncio
import os
import logging
from config import BOT_TOKEN, PREFIX, OWNER_IDS

# set up logging so I can actually see what's happening when things go wrong
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
log = logging.getLogger("bot")

# intents — discord requires me to opt in to the events I want to listen to
intents = discord.Intents.default()
intents.members = True  # needed for join/leave events and member lookups
intents.message_content = True  # needed to read message content for commands
intents.guilds = True
intents.invites = True  # needed for invite tracking


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            owner_ids=set(OWNER_IDS),
            help_command=None,  # I wrote my own help command so removing the default
            case_insensitive=True,
        )

    async def setup_hook(self):
        """
        This runs before the bot connects — perfect place to load cogs
        and set up the database before anyone can use commands.
        """
        # load all my cogs (each file handles a different feature area)
        cogs_to_load = [
            "cogs.moderation",
            "cogs.cases",
            "cogs.invite_logger",
            "cogs.activity",
            "cogs.server_management",
            "cogs.help",
        ]

        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
            except Exception as e:
                log.error(f"Failed to load cog {cog}: {e}")

        # sync slash commands globally
        # I comment this out after first run so it doesn't slow boot
        # await self.tree.sync()
        log.info("setup_hook complete")

    async def on_ready(self):
        """Fires when the bot is connected and ready to go."""
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        log.info(f"Serving {len(self.guilds)} guild(s)")

        # set a custom status so people know it's alive
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers | {PREFIX}help",
            )
        )

    async def on_command_error(self, ctx: commands.Context, error):
        """
        Global error handler — catches anything that slips through
        the cog-level handlers so the bot never just silently fails.
        """
        if isinstance(error, commands.CommandNotFound):
            return  # don't spam the chat with "command not found" every typo

        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=discord.Embed(
                    description="❌ You don't have permission to use that command.",
                    color=discord.Color.red(),
                )
            )
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(
                embed=discord.Embed(
                    description=f"❌ I'm missing permissions: `{', '.join(error.missing_permissions)}`",
                    color=discord.Color.red(),
                )
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                embed=discord.Embed(
                    description=f"❌ Missing argument: `{error.param.name}` — use `{PREFIX}help {ctx.command}` for usage.",
                    color=discord.Color.orange(),
                )
            )
        elif isinstance(error, commands.BadArgument):
            await ctx.send(
                embed=discord.Embed(
                    description="❌ Bad argument — make sure you're passing the right type (e.g. a valid user mention).",
                    color=discord.Color.orange(),
                )
            )
        else:
            # log anything unexpected so I can debug it later
            log.error(
                f"Unhandled error in command {ctx.command}: {error}", exc_info=error
            )
            await ctx.send(
                embed=discord.Embed(
                    description="❌ Something went wrong. Check the logs.",
                    color=discord.Color.red(),
                )
            )


async def main():
    """Start the bot."""
    bot = MyBot()
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
