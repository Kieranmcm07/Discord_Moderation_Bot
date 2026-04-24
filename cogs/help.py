"""
Custom help command.

The bot has enough commands now that grouping and presentation matter more than
just dumping a plain command list.
"""

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, PREFIX
from utils.embeds import make_embed


def command_usage(command: commands.Command) -> str:
    """Return the command usage line, falling back to the qualified name."""
    return command.usage or f"{PREFIX}{command.qualified_name}"


class Help(commands.Cog, name="Help"):
    """Friendly grouped help output."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", help="Show the command guide.")
    async def help_command(self, ctx, *, command_name: str = None):
        """Show either the grouped command list or one command's details."""
        if command_name and command_name.lower().startswith(("search ", "find ")):
            _, _, query = command_name.partition(" ")
            return await self.search_help(ctx, query.strip())

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
            embed.add_field(name="Usage", value=f"`{command_usage(cmd)}`", inline=False)
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
            description=(
                f"Prefix: `{PREFIX}`\n"
                f"Use `{PREFIX}help <command>` for details or `{PREFIX}help search <word>` to find commands."
            ),
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

    async def search_help(self, ctx, query: str):
        """Search commands by name, alias, category, usage, or description."""
        if not query:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Search Help",
                description=f"Use `{PREFIX}help search <word>` to find matching commands.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        query_lower = query.lower()
        matches = []
        for command in self.bot.walk_commands():
            if command.hidden:
                continue

            haystack = " ".join(
                [
                    command.qualified_name,
                    " ".join(command.aliases),
                    command.cog_name or "",
                    command.help or "",
                    command_usage(command),
                ]
            ).lower()
            if query_lower in haystack:
                matches.append(command)

        if not matches:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="No Commands Found",
                description=f"No commands matched `{query}`.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Help Search: {query}",
            description=f"Showing {min(len(matches), 12)} of {len(matches)} matching command(s).",
            color=COLOR_INFO,
        )
        for command in matches[:12]:
            embed.add_field(
                name=f"{PREFIX}{command.qualified_name}",
                value=f"{command.help or 'No description provided.'}\n`{command_usage(command)}`",
                inline=False,
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
