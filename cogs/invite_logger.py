"""
cogs/invite_logger.py - invite tracking and join/leave logging.
"""

import discord
from discord.ext import commands

from config import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    INVITE_LOG_CHANNEL_ID,
    JOIN_LOG_CHANNEL_ID,
)
from utils.db import log_member_event, upsert_invite
from utils.embeds import make_embed


class InviteLogger(commands.Cog, name="Invite Logger"):
    """Tracks invite usage and logs member joins/leaves."""

    def __init__(self, bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
            for invite in invites:
                await upsert_invite(
                    guild.id,
                    invite.code,
                    invite.inviter.id if invite.inviter else None,
                    invite.uses,
                )
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        await log_member_event(guild.id, member.id, "join")

        old_counts = self.invite_cache.get(guild.id, {})
        used_invite = None

        try:
            current_invites = await guild.invites()
        except discord.Forbidden:
            current_invites = []

        for invite in current_invites:
            old_uses = old_counts.get(invite.code, 0)
            if invite.uses > old_uses:
                used_invite = invite
                break

        self.invite_cache[guild.id] = {invite.code: invite.uses for invite in current_invites}

        embed = await make_embed(
            self.bot,
            guild=guild,
            title="Member Joined",
            color=COLOR_SUCCESS,
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(
            name="Account Created",
            value=f"<t:{int(member.created_at.timestamp())}:R>",
            inline=True,
        )

        if used_invite:
            inviter = used_invite.inviter
            embed.add_field(
                name="Joined via Invite",
                value=f"`{used_invite.code}` by {inviter} ({used_invite.uses} total uses)",
                inline=False,
            )
            await upsert_invite(
                guild.id,
                used_invite.code,
                inviter.id if inviter else None,
                used_invite.uses,
            )
        else:
            embed.add_field(name="Joined via Invite", value="Could not determine", inline=False)

        embed.add_field(name="Member Count", value=str(guild.member_count), inline=True)

        join_channel_id = JOIN_LOG_CHANNEL_ID
        invite_channel_id = INVITE_LOG_CHANNEL_ID

        if join_channel_id:
            channel = guild.get_channel(join_channel_id)
            if channel:
                await channel.send(embed=embed)

        if invite_channel_id and invite_channel_id != join_channel_id:
            channel = guild.get_channel(invite_channel_id)
            if channel:
                await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        await log_member_event(guild.id, member.id, "leave")

        leave_channel_id = JOIN_LOG_CHANNEL_ID
        if not leave_channel_id:
            return

        channel = guild.get_channel(leave_channel_id)
        if not channel:
            return

        embed = await make_embed(
            self.bot,
            guild=guild,
            title="Member Left",
            color=COLOR_ERROR,
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(
            name="Joined",
            value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown",
            inline=True,
        )
        embed.add_field(name="Member Count", value=str(guild.member_count), inline=True)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild.id not in self.invite_cache:
            self.invite_cache[invite.guild.id] = {}
        self.invite_cache[invite.guild.id][invite.code] = invite.uses
        await upsert_invite(
            invite.guild.id,
            invite.code,
            invite.inviter.id if invite.inviter else None,
            invite.uses,
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        cache = self.invite_cache.get(invite.guild.id, {})
        cache.pop(invite.code, None)

    @commands.command(name="invites", help="Show all active invites in the server.")
    @commands.has_permissions(manage_guild=True)
    async def show_invites(self, ctx):
        try:
            invites = await ctx.guild.invites()
        except discord.Forbidden:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                description="I need `Manage Server` permission to view invites.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        if not invites:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                description="No active invites.",
                color=COLOR_INFO,
            )
            return await ctx.send(embed=embed)

        invites = sorted(invites, key=lambda invite: invite.uses, reverse=True)
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Active Invites",
            color=COLOR_INFO,
        )
        for invite in invites[:20]:
            inviter = str(invite.inviter) if invite.inviter else "Unknown"
            embed.add_field(
                name=f"`{invite.code}`",
                value=(
                    f"Created by: {inviter}\n"
                    f"Uses: {invite.uses}\n"
                    f"Max: {invite.max_uses or 'Unlimited'}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(InviteLogger(bot))
