"""
cogs/server_management.py — utility commands for managing the server itself.
Things like server info, user info, role management, and locking channels.
Nothing crazy, just quality of life stuff I always end up wanting.
"""

import discord
from discord.ext import commands
from datetime import datetime
from config import COLOR_INFO, COLOR_SUCCESS, COLOR_ERROR


class ServerManagement(commands.Cog, name="Server Management"):
    """Server info and management utilities."""

    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # ,serverinfo
    # ─────────────────────────────────────────────
    @commands.command(name="serverinfo", aliases=["guildinfo", "si"], help="Shows info about the server.")
    async def server_info(self, ctx):
        """Usage: ,serverinfo"""
        guild = ctx.guild

        # count different channel types
        text_channels  = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories     = len(guild.categories)

        # split members into bots vs humans
        bots    = sum(1 for m in guild.members if m.bot)
        humans  = guild.member_count - bots

        e = discord.Embed(
            title=guild.name,
            color=COLOR_INFO,
            timestamp=datetime.utcnow()
        )
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            e.set_image(url=guild.banner.url)

        e.add_field(name="👑 Owner",     value=str(guild.owner), inline=True)
        e.add_field(name="🆔 Server ID", value=str(guild.id),    inline=True)
        e.add_field(name="📅 Created",   value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)

        e.add_field(name="👥 Members",
                    value=f"Total: **{guild.member_count}**\nHumans: **{humans}** | Bots: **{bots}**",
                    inline=True)

        e.add_field(name="📺 Channels",
                    value=f"Text: **{text_channels}** | Voice: **{voice_channels}** | Categories: **{categories}**",
                    inline=True)

        e.add_field(name="😀 Emoji",
                    value=f"**{len(guild.emojis)}** / {guild.emoji_limit}",
                    inline=True)

        e.add_field(name="🛡️ Verification Level",
                    value=str(guild.verification_level).title(),
                    inline=True)

        e.add_field(name="✨ Boosts",
                    value=f"**{guild.premium_subscription_count}** boosts (Tier {guild.premium_tier})",
                    inline=True)

        e.add_field(name="🎭 Roles",
                    value=f"**{len(guild.roles) - 1}** roles",  # -1 to exclude @everyone
                    inline=True)

        await ctx.send(embed=e)

    # ─────────────────────────────────────────────
    # ,userinfo
    # ─────────────────────────────────────────────
    @commands.command(name="userinfo", aliases=["whois", "ui"], help="Shows info about a user.")
    async def user_info(self, ctx, member: discord.Member = None):
        """
        Usage: ,userinfo [@user]
        Defaults to yourself. Shows account info, roles, and join date.
        """
        member = member or ctx.author

        # list roles, skip @everyone, highest first
        roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        roles_str = ", ".join(roles[:15]) if roles else "None"
        if len(roles) > 15:
            roles_str += f" (+{len(roles) - 15} more)"

        e = discord.Embed(
            title=f"👤 {member}",
            color=member.color if member.color.value else COLOR_INFO,
            timestamp=datetime.utcnow()
        )
        e.set_thumbnail(url=member.display_avatar.url)

        e.add_field(name="🆔 User ID",      value=str(member.id), inline=True)
        e.add_field(name="🤖 Bot?",          value="Yes" if member.bot else "No", inline=True)
        e.add_field(name="📛 Nickname",      value=member.nick or "None", inline=True)

        e.add_field(name="📅 Account Created",
                    value=f"<t:{int(member.created_at.timestamp())}:D> (<t:{int(member.created_at.timestamp())}:R>)",
                    inline=False)

        if member.joined_at:
            e.add_field(name="📥 Joined Server",
                        value=f"<t:{int(member.joined_at.timestamp())}:D> (<t:{int(member.joined_at.timestamp())}:R>)",
                        inline=False)

        e.add_field(name=f"🎭 Roles ({len(roles)})", value=roles_str, inline=False)

        # show current timeout status if they're timed out
        if member.timed_out_until:
            e.add_field(name="🔇 Timed Out Until",
                        value=f"<t:{int(member.timed_out_until.timestamp())}:F>",
                        inline=False)

        await ctx.send(embed=e)

    # ─────────────────────────────────────────────
    # ,avatar
    # ─────────────────────────────────────────────
    @commands.command(name="avatar", aliases=["av", "pfp"], help="Show a user's avatar.")
    async def avatar(self, ctx, member: discord.Member = None):
        """Usage: ,avatar [@user]"""
        member = member or ctx.author
        e = discord.Embed(title=f"🖼️ {member.display_name}'s Avatar", color=COLOR_INFO)
        e.set_image(url=member.display_avatar.url)

        # link to different formats
        av = member.display_avatar
        links = f"[PNG]({av.with_format('png').url}) | [JPG]({av.with_format('jpg').url}) | [WEBP]({av.with_format('webp').url})"
        if av.is_animated():
            links += f" | [GIF]({av.with_format('gif').url})"
        e.description = links
        await ctx.send(embed=e)

    # ─────────────────────────────────────────────
    # ,roleinfo
    # ─────────────────────────────────────────────
    @commands.command(name="roleinfo", aliases=["ri"], help="Shows info about a role.")
    async def role_info(self, ctx, *, role: discord.Role):
        """Usage: ,roleinfo <role name or mention>"""
        e = discord.Embed(
            title=f"🎭 {role.name}",
            color=role.color if role.color.value else COLOR_INFO
        )
        e.add_field(name="🆔 Role ID",      value=str(role.id),             inline=True)
        e.add_field(name="🎨 Colour",       value=str(role.color),          inline=True)
        e.add_field(name="📌 Position",     value=str(role.position),       inline=True)
        e.add_field(name="👥 Members",      value=str(len(role.members)),   inline=True)
        e.add_field(name="🔒 Mentionable",  value="Yes" if role.mentionable else "No", inline=True)
        e.add_field(name="📢 Hoisted",      value="Yes" if role.hoist else "No", inline=True)
        e.add_field(name="📅 Created",
                    value=f"<t:{int(role.created_at.timestamp())}:D>", inline=False)
        await ctx.send(embed=e)

    # ─────────────────────────────────────────────
    # ,lock / ,unlock
    # ─────────────────────────────────────────────
    @commands.command(name="lock", help="Lock a channel so @everyone can't send messages.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None, *, reason: str = None):
        """Usage: ,lock [#channel] [reason]"""
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=reason)
        await channel.send(embed=discord.Embed(
            description=f"🔒 This channel has been locked.{f' **Reason:** {reason}' if reason else ''}",
            color=COLOR_ERROR
        ))

    @commands.command(name="unlock", help="Unlock a previously locked channel.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None, *, reason: str = None):
        """Usage: ,unlock [#channel] [reason]"""
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None  # reset to inherited
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=reason)
        await channel.send(embed=discord.Embed(
            description=f"🔓 This channel has been unlocked.",
            color=COLOR_SUCCESS
        ))

    # ─────────────────────────────────────────────
    # ,announce
    # ─────────────────────────────────────────────
    @commands.command(name="announce", help="Send a formatted announcement embed to a channel.")
    @commands.has_permissions(manage_messages=True)
    async def announce(self, ctx, channel: discord.TextChannel, *, message: str):
        """
        Usage: ,announce #channel <message>
        Sends a nice embed announcement. The original command message gets deleted.
        """
        e = discord.Embed(
            description=message,
            color=COLOR_INFO,
            timestamp=datetime.utcnow()
        )
        e.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        e.set_footer(text=f"Announcement by {ctx.author}")
        await channel.send(embed=e)

        # delete the command so the channel doesn't show the raw command
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

    # ─────────────────────────────────────────────
    # ,botinfo
    # ─────────────────────────────────────────────
    @commands.command(name="botinfo", help="Shows info about the bot itself.")
    async def show_bot_info(self, ctx):
        """Usage: ,botinfo"""
        bot = self.bot
        e = discord.Embed(title=f"ℹ️ {bot.user.name}", color=COLOR_INFO)
        e.set_thumbnail(url=bot.user.display_avatar.url)
        e.add_field(name="🆔 Bot ID",    value=str(bot.user.id),         inline=True)
        e.add_field(name="🏠 Servers",   value=str(len(bot.guilds)),     inline=True)
        e.add_field(name="👥 Users",     value=str(len(bot.users)),      inline=True)
        e.add_field(name="📦 Cogs",      value=str(len(bot.cogs)),       inline=True)
        e.add_field(name="⚡ Commands",  value=str(len(bot.commands)),   inline=True)
        e.add_field(name="🐍 Library",   value="discord.py 2.x",         inline=True)
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(ServerManagement(bot))
