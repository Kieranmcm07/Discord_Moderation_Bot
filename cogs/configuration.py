"""
Guild customization commands.

These commands shape how the bot feels in each server: welcome messages, leave
messages, embed theming, and the optional shared image or GIF for branded embeds.
"""

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_SUCCESS
from utils.db import (
    get_all_sticky_messages,
    get_autorole,
    get_escalation_rules,
    get_guild_settings,
    get_reaction_roles,
    get_sentinel_settings,
    get_ticket_settings,
    clear_mod_log_channel,
    remove_embed_image,
    upsert_guild_settings,
)
from utils.embeds import make_embed


def render_template(template: str, member: discord.Member) -> str:
    """Render the supported placeholders in welcome and leave templates."""
    return (
        template.replace("{user}", member.mention)
        .replace("{username}", member.name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


class Configuration(commands.Cog, name="Configuration"):
    """Commands and listeners for guild-level bot customization."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Send a branded welcome embed when the guild has one configured."""
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
        """Send a branded leave embed when the guild has one configured."""
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
        """Give admins a quick overview of the bot's current guild setup."""
        settings = await get_guild_settings(ctx.guild.id) or {}
        autorole_id = await get_autorole(ctx.guild.id)
        escalations = await get_escalation_rules(ctx.guild.id)
        stickies = await get_all_sticky_messages(ctx.guild.id)
        ticket_settings = await get_ticket_settings(ctx.guild.id) or {}
        reaction_roles = await get_reaction_roles(ctx.guild.id)
        sentinel_settings = await get_sentinel_settings(ctx.guild.id)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"{ctx.guild.name} Settings",
            description="Quick overview of the current bot setup for this server.",
        )

        welcome_channel = (
            ctx.guild.get_channel(settings["welcome_channel_id"]).mention
            if settings.get("welcome_channel_id")
            and ctx.guild.get_channel(settings["welcome_channel_id"])
            else "Not set"
        )
        leave_channel = (
            ctx.guild.get_channel(settings["leave_channel_id"]).mention
            if settings.get("leave_channel_id")
            and ctx.guild.get_channel(settings["leave_channel_id"])
            else "Not set"
        )
        autorole = (
            ctx.guild.get_role(autorole_id).mention
            if autorole_id and ctx.guild.get_role(autorole_id)
            else "Not set"
        )
        embed_color = settings.get("embed_color")
        embed_color_value = (
            f"`#{embed_color:06X}`" if embed_color is not None else "Default"
        )
        embed_image_value = settings.get("embed_image_url") or "Not set"
        mod_log_channel = (
            ctx.guild.get_channel(settings["mod_log_channel_id"]).mention
            if settings.get("mod_log_channel_id")
            and ctx.guild.get_channel(settings["mod_log_channel_id"])
            else "Not set"
        )

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
        embed.add_field(name="Embed Image", value=embed_image_value, inline=False)
        embed.add_field(name="Mod Log Channel", value=mod_log_channel, inline=False)
        embed.add_field(name="Sticky Messages", value=str(len(stickies)), inline=True)
        embed.add_field(
            name="Escalation Rules", value=str(len(escalations)), inline=True
        )
        embed.add_field(
            name="Reaction Roles", value=str(len(reaction_roles)), inline=True
        )
        embed.add_field(
            name="Ticket Setup",
            value="Configured" if ticket_settings.get("category_id") else "Not set",
            inline=True,
        )
        embed.add_field(
            name="Sentinel",
            value=(
                "Enabled"
                if sentinel_settings.get("enabled")
                else "Disabled"
            ),
            inline=True,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="setwelcomechannel", help="Set the channel for welcome messages."
    )
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

    @commands.command(
        name="setwelcomemessage", help="Set the welcome message template."
    )
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

    @commands.command(
        name="setleavechannel", help="Set the channel for leave messages."
    )
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
        """Let guild admins theme the bot without editing source code."""
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
                description="That is not a valid hex color.",
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

    @commands.command(
        name="setmodlog",
        aliases=["modlogchannel"],
        help="Set the channel used for moderation action logs.",
    )
    @commands.has_permissions(manage_guild=True)
    async def setmodlog(self, ctx, channel: discord.TextChannel):
        await upsert_guild_settings(ctx.guild.id, mod_log_channel_id=channel.id)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Mod Log Updated",
            description=f"Moderation logs will now be sent to {channel.mention}.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="viewmodlog",
        aliases=["modlogstatus"],
        help="Show the current moderation log channel.",
    )
    @commands.has_permissions(manage_guild=True)
    async def viewmodlog(self, ctx):
        settings = await get_guild_settings(ctx.guild.id) or {}
        channel_id = settings.get("mod_log_channel_id")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None

        if not channel:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Mod Log",
                description="No moderation log channel is configured.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Mod Log",
            description=f"Moderation logs are currently sent to {channel.mention}.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="clearmodlog",
        aliases=["removemodlog"],
        help="Disable moderation action logging.",
    )
    @commands.has_permissions(manage_guild=True)
    async def clearmodlog(self, ctx):
        await clear_mod_log_channel(ctx.guild.id)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Mod Log Cleared",
            description="Moderation logging has been disabled for this server.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="setembedimage",
        aliases=["embedimage", "setembedgif"],
        help="Set a shared image or GIF that appears under bot embeds.",
    )
    @commands.has_permissions(manage_guild=True)
    async def setembedimage(self, ctx, image_url: str):
        """Save a global image or GIF that branded embeds can reuse."""
        image_url = image_url.strip()
        if not image_url.startswith(("http://", "https://")):
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                description="Use a direct `http://` or `https://` image URL.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        await upsert_guild_settings(ctx.guild.id, embed_image_url=image_url)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Embed Image Updated",
            description="New bot embeds will include that shared image or GIF when they do not already have one.",
            color=COLOR_SUCCESS,
        )
        embed.set_image(url=image_url)
        await ctx.send(embed=embed)

    @commands.command(
        name="clearembedimage",
        aliases=["removeembedimage"],
        help="Remove the shared image or GIF from bot embeds.",
    )
    @commands.has_permissions(manage_guild=True)
    async def clearembedimage(self, ctx):
        await remove_embed_image(ctx.guild.id)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            description="The shared embed image has been cleared.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Configuration(bot))
