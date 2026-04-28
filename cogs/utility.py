"""Small utility commands."""

# Tiny commands that do not need their own whole category.
import discord
from discord.ext import commands

from config import COLOR_INFO
from utils.embeds import make_embed


class Utility(commands.Cog, name="Utility"):
    """General bot utility commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping", help="Check the bot's websocket latency.")
    async def ping(self, ctx):
        """Usage: ,ping"""
        latency_ms = round(self.bot.latency * 1000)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Pong",
            description=f"Websocket latency: **{latency_ms}ms**",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow(),
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utility(bot))
