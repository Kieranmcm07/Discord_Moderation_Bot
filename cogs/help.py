"""
cogs/help.py — custom help command.
The default discord.py one is ugly. This one groups commands by cog
and shows them in a clean embed. Way easier to read.
"""

import discord
from discord.ext import commands
from config import COLOR_INFO, PREFIX


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
            # show help for a specific command
            cmd = self.bot.get_command(command_name)
            if not cmd:
                return await ctx.send(embed=discord.Embed(
                    description=f"❌ Command `{command_name}` not found.",
                    color=discord.Color.red()
                ))
            e = discord.Embed(
                title=f"📖 {PREFIX}{cmd.name}",
                description=cmd.help or "No description.",
                color=COLOR_INFO
            )
            if cmd.aliases:
                e.add_field(name="Aliases", value=", ".join(f"`{a}`" for a in cmd.aliases))
            await ctx.send(embed=e)
            return

        # build the full help embed grouped by cog
        e = discord.Embed(
            title=f"📖 {self.bot.user.name} — Help",
            description=f"Prefix: `{PREFIX}` | Use `{PREFIX}help <command>` for more details.",
            color=COLOR_INFO
        )
        e.set_thumbnail(url=self.bot.user.display_avatar.url)

        # go through each cog and list its commands
        for cog_name, cog in self.bot.cogs.items():
            cog_commands = [
                cmd for cmd in cog.get_commands()
                if not cmd.hidden
            ]
            if not cog_commands:
                continue
            cmd_list = " ".join(f"`{PREFIX}{c.name}`" for c in cog_commands)
            e.add_field(name=f"📁 {cog_name}", value=cmd_list, inline=False)

        e.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Help(bot))
