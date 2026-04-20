"""
Custom help command.

The bot has enough commands now that grouping and presentation matter more than
just dumping a plain command list.
"""

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, PREFIX
from utils.embeds import make_embed


class Help(commands.Cog, name="Help"):
    """Friendly grouped help output."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", help="Show the command guide.")
    async def help_command(self, ctx, *, command_name: str = None):
        """Show either the grouped command list or one command's details."""
        if command_name:
            cmd = self.bot.get_command(command_name)
            if not cmd:
                embed = await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    title="Command Not Found",
                    description=f"I could not find a command named `{command_name}`.",
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
            usage = cmd.usage or f"{PREFIX}{cmd.qualified_name}"
            embed.add_field(name="Usage", value=f"`{usage}`", inline=False)
            if cmd.aliases:
                embed.add_field(
                    name="Aliases",
                    value=", ".join(f"`{alias}`" for alias in cmd.aliases),
                    inline=False,
                )
            if cmd.cog_name:
                embed.add_field(name="Category", value=cmd.cog_name, inline=True)
            await ctx.send(embed=embed)
            return

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"{self.bot.user.name} Help",
            description=f"Prefix: `{PREFIX}`\nUse `{PREFIX}help <command>` for more detail on one command.",
            color=COLOR_INFO,
        )
        embed.set_author(
            name=ctx.guild.name,
            icon_url=(
                ctx.guild.icon.url
                if ctx.guild.icon
                else self.bot.user.display_avatar.url
            ),
        )

        for cog_name, cog in self.bot.cogs.items():
            cog_commands = [cmd for cmd in cog.get_commands() if not cmd.hidden]
            if not cog_commands:
                continue

            command_list = ", ".join(
                f"`{PREFIX}{command.name}`" for command in cog_commands
            )
            embed.add_field(
                name=f"{cog_name} ({len(cog_commands)})",
                value=command_list,
                inline=False,
            )

        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
