"""
cogs/help.py - custom help command with cleaner branded embeds.
"""

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, PREFIX
from utils.embeds import make_embed


class Help(commands.Cog, name="Help"):
    """The help command."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", help="Shows this help message.")
    async def help_command(self, ctx, *, command_name: str = None):
        """
        Usage: ,help [command]
        Without an argument it shows all commands grouped by category.
        With a command name it shows detailed usage for that command.
        """
        if command_name:
            cmd = self.bot.get_command(command_name)
            if not cmd:
                embed = await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    description=f"Command `{command_name}` not found.",
                    color=COLOR_ERROR,
                )
                return await ctx.send(embed=embed)

            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title=f"{PREFIX}{cmd.name}",
                description=cmd.help or "No description provided.",
                color=COLOR_INFO,
            )
            if cmd.aliases:
                embed.add_field(
                    name="Aliases",
                    value=", ".join(f"`{alias}`" for alias in cmd.aliases),
                    inline=False,
                )
            await ctx.send(embed=embed)
            return

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"{self.bot.user.name} Help",
            description=f"Prefix: `{PREFIX}` | Use `{PREFIX}help <command>` for more details.",
            color=COLOR_INFO,
        )
        embed.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon.url if ctx.guild.icon else self.bot.user.display_avatar.url,
        )

        for cog_name, cog in self.bot.cogs.items():
            cog_commands = [cmd for cmd in cog.get_commands() if not cmd.hidden]
            if not cog_commands:
                continue
            command_list = " ".join(f"`{PREFIX}{command.name}`" for command in cog_commands)
            embed.add_field(name=cog_name, value=command_list, inline=False)

        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
