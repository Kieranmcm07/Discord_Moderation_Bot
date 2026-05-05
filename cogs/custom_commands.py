# ============================================================
#   Made by Kieranmcm07 on GitHub
#   GitHub: https://github.com/Kieranmcm07
# ============================================================
"""
Guild custom commands.

Admins can create simple reusable responses such as ,rules, ,socials, or
,appeal without editing the bot code.
"""

# These are deliberately simple: name in, saved response out.
import re

from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS, PREFIX
from utils.db import (
    delete_custom_command,
    get_custom_commands,
    upsert_custom_command,
)
from utils.embeds import make_embed

CUSTOM_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")


def normalize_custom_name(name: str) -> str:
    """Normalize a custom command name to the token users type after the prefix."""
    return name.removeprefix(PREFIX).strip().lower()


class CustomCommands(commands.Cog, name="Custom Commands"):
    """Manage simple custom server replies."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="customadd",
        aliases=["ccadd", "addcustom"],
        help="Add or update a custom server command.",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def custom_add(self, ctx, name: str = None, *, response: str = None):
        """Usage: ,customadd <name> <response>"""
        if not name or not response:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Custom Command",
                description=f"Use `{PREFIX}customadd rules Please read #rules first.`",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        normalized = normalize_custom_name(name)
        if not CUSTOM_NAME.fullmatch(normalized):
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Invalid Command Name",
                description="Use 1-32 characters: letters, numbers, `_`, or `-`.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        if self.bot.get_command(normalized):
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Command Already Exists",
                description=f"`{PREFIX}{normalized}` is already a built-in command.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        if len(response) > 1800:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Response Too Long",
                description="Keep custom command responses under 1,800 characters.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        await upsert_custom_command(ctx.guild.id, normalized, response, ctx.author.id)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Custom Command Saved",
            description=f"`{PREFIX}{normalized}` is ready to use.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="customremove",
        aliases=["ccremove", "customdelete", "ccdelete"],
        help="Remove a custom server command.",
    )
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def custom_remove(self, ctx, name: str = None):
        """Usage: ,customremove <name>"""
        if not name:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Custom Command",
                description=f"Use `{PREFIX}customremove rules`.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        normalized = normalize_custom_name(name)
        deleted = await delete_custom_command(ctx.guild.id, normalized)
        if not deleted:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Custom Command Not Found",
                description=f"I could not find `{PREFIX}{normalized}`.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Custom Command Removed",
            description=f"Removed `{PREFIX}{normalized}`.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="customlist",
        aliases=["cclist", "customcommands"],
        help="List this server's custom commands.",
    )
    @commands.guild_only()
    async def custom_list(self, ctx):
        """Usage: ,customlist"""
        custom_commands = await get_custom_commands(ctx.guild.id)
        if not custom_commands:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Custom Commands",
                description=f"No custom commands yet. Add one with `{PREFIX}customadd`.",
                color=COLOR_INFO,
            )
            return await ctx.send(embed=embed)

        names = ", ".join(f"`{PREFIX}{item['name']}`" for item in custom_commands[:50])
        if len(custom_commands) > 50:
            names += f"\n...and {len(custom_commands) - 50} more."

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Custom Commands",
            description=names,
            color=COLOR_INFO,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(CustomCommands(bot))
