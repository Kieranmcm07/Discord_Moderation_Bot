"""Small utility commands."""

# Tiny commands that do not need their own whole category.
import discord
from discord.ext import commands

from config import (
    COLOR_INFO,
    GITHUB_PROFILE_URL,
    PROJECT_CREATOR,
    PROJECT_REPO_URL,
)
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

    @commands.command(
        name="about",
        aliases=["creator", "credits", "github", "source"],
        help="Show who made the bot and where to find the project.",
    )
    async def about(self, ctx):
        """Usage: ,about"""
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"About {self.bot.user.name}",
            description=(
                f"Made by **{PROJECT_CREATOR}**.\n\n"
                f"GitHub: [@{PROJECT_CREATOR}]({GITHUB_PROFILE_URL})\n"
                f"Source code: [Discord_Moderation_Bot]({PROJECT_REPO_URL})"
            ),
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Project",
            value="A Discord moderation bot built with discord.py and SQLite.",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utility(bot))
