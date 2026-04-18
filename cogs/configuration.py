"""
cogs/configuration.py - guild customization commands.
"""

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS
from utils.db import (
    get_all_sticky_messages,
    get_autorole,
    get_escalation_rules,
    get_guild_settings,
    get_ticket_settings,
    init_db,
    upsert_guild_settings,
)
from utils.embeds import make_embed


def render_template(template: str, member: discord.Member) -> str:
    return (
        template.replace("{user}", member.mention)
        .replace("{username}", member.name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


class Configuration(commands.Cog, name="Configuration"):
    """Commands for welcome messages, leave messages, and visual settings."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        settings = await get_guild_settings(member.guild.id) or {}
        channel_id = settings.get("welcome_channel_id")
        message_template = settings.get("welcome_message")

        if not channel_id or not message_template:
            return

        channel = member.guild.get_channel(channel_id)
        if channel is None:
            return

        embed = await make_embed(
            self.bot,
            guild=member.guild,
            title="Welcome",
            description=render_template(message_template, member),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        settings = await get_guild_settings(member.guild.id) or {}
        channel_id = settings.get("leave_channel_id")
        message_template = settings.get("leave_message")

        if not channel_id or not message_template:
            return

        channel = member.guild.get_channel(channel_id)
        if channel is None:
            return

        embed = await make_embed(
            self.bot,
            guild=member.guild,
            title="Goodbye",
            description=render_template(message_template, member),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        await channel.send(embed=embed)

    @commands.command(name="settings", help="Show the current server configuration.")
    @commands.has_permissions(manage_guild=True)
    async def settings(self, ctx):
        settings = await get_guild_settings(ctx.guild.id) or {}
        autorole_id = await get_autorole(ctx.guild.id)
        escalations = await get_escalation_rules(ctx.guild.id)
        stickies = await get_all_sticky_messages(ctx.guild.id)
        ticket_settings = await get_ticket_settings(ctx.guild.id) or {}

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"{ctx.guild.name} Settings",
            description="Quick overview of your server's bot setup.",
        )
        embed.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon.url if ctx.guild.icon else self.bot.user.display_avatar.url,
        )

        welcome_channel = (
            ctx.guild.get_channel(settings["welcome_channel_id"]).mention
            if settings.get("welcome_channel_id") and ctx.guild.get_channel(settings["welcome_channel_id"])
            else "Not set"
        )
        leave_channel = (
            ctx.guild.get_channel(settings["leave_channel_id"]).mention
            if settings.get("leave_channel_id") and ctx.guild.get_channel(settings["leave_channel_id"])
            else "Not set"
        )
        autorole = (
            ctx.guild.get_role(autorole_id).mention
            if autorole_id and ctx.guild.get_role(autorole_id)
            else "Not set"
        )
        embed_color = settings.get("embed_color")
        embed_color_value = f"`#{embed_color:06X}`" if embed_color is not None else "Default"

        embed.add_field(
            name="Welcome",
            value=f"Channel: {welcome_channel}\nMessage: {'Set' if settings.get('welcome_message') else 'Not set'}",
            inline=False,
        )
        embed.add_field(
            name="Leave",
            value=f"Channel: {leave_channel}\nMessage: {'Set' if settings.get('leave_message') else 'Not set'}",
            inline=False,
        )
        embed.add_field(name="Autorole", value=autorole, inline=True)
        embed.add_field(name="Embed Color", value=embed_color_value, inline=True)
        embed.add_field(name="Sticky Messages", value=str(len(stickies)), inline=True)
        embed.add_field(name="Escalation Rules", value=str(len(escalations)), inline=True)
        embed.add_field(
            name="Ticket Setup",
            value="Configured" if ticket_settings.get("category_id") else "Not set",
            inline=True,
        )
        await ctx.send(embed=embed)

    @commands.command(name="setwelcomechannel", help="Set the channel for welcome messages.")
    @commands.has_permissions(manage_guild=True)
    async def setwelcomechannel(self, ctx, channel: discord.TextChannel):
        await upsert_guild_settings(ctx.guild.id, welcome_channel_id=channel.id)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            description=f"Welcome messages will now be sent in {channel.mention}.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(name="setwelcomemessage", help="Set the welcome message template.")
    @commands.has_permissions(manage_guild=True)
    async def setwelcomemessage(self, ctx, *, message: str):
        await upsert_guild_settings(ctx.guild.id, welcome_message=message)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Welcome Message Updated",
            description=(
                "Placeholders: `{user}`, `{username}`, `{server}`, `{count}`\n\n"
                f"Preview:\n{render_template(message, ctx.author)}"
            ),
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(name="setleavechannel", help="Set the channel for leave messages.")
    @commands.has_permissions(manage_guild=True)
    async def setleavechannel(self, ctx, channel: discord.TextChannel):
        await upsert_guild_settings(ctx.guild.id, leave_channel_id=channel.id)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            description=f"Leave messages will now be sent in {channel.mention}.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(name="setleavemessage", help="Set the leave message template.")
    @commands.has_permissions(manage_guild=True)
    async def setleavemessage(self, ctx, *, message: str):
        await upsert_guild_settings(ctx.guild.id, leave_message=message)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Leave Message Updated",
            description=(
                "Placeholders: `{user}`, `{username}`, `{server}`, `{count}`\n\n"
                f"Preview:\n{render_template(message, ctx.author)}"
            ),
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="setembedcolor",
        aliases=["embedcolor"],
        help="Set the bot embed theme color using hex.",
    )
    @commands.has_permissions(manage_guild=True)
    async def setembedcolor(self, ctx, hex_color: str):
        hex_color = hex_color.strip().lstrip("#")
        if len(hex_color) != 6:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                description="Use a 6-digit hex color like `#5865F2`.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        try:
            color_value = int(hex_color, 16)
        except ValueError:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                description="That isn't a valid hex color.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        await upsert_guild_settings(ctx.guild.id, embed_color=color_value)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Embed Color Updated",
            description=f"The bot's themed embeds now use `#{hex_color.upper()}`.",
            color=color_value,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await init_db()
    await bot.add_cog(Configuration(bot))
