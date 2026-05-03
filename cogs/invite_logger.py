"""
Invite tracking and join/leave logging.

This cog gives moderators a quick picture of where members came from and whether
an account looks brand new or more established.
"""

# This is handy when staff need context around new joins.
import logging

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

log = logging.getLogger(__name__)


def invite_uses(invite: discord.Invite) -> int:
    """Discord can return None for fresh invite counts, so compare as zero."""
    return int(invite.uses or 0)


class InviteLogger(commands.Cog, name="Invite Logger"):
    """Track invite usage and send join or leave logs."""

    def __init__(self, bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """Cache the current invite usage counts for every guild we can access."""
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    async def _cache_invites(self, guild: discord.Guild):
        """Store the current invite usage counts so later joins can be compared."""
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {
                invite.code: invite_uses(invite) for invite in invites
            }
            for invite in invites:
                await upsert_invite(
                    guild.id,
                    invite.code,
                    invite.inviter.id if invite.inviter else None,
                    invite_uses(invite),
                )
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            log.warning(
                "Could not cache invites for guild %s.", guild.id, exc_info=True
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Log a join event and try to identify which invite was used."""
        guild = member.guild
        await log_member_event(guild.id, member.id, "join")

        old_counts = self.invite_cache.get(guild.id, {})
        used_invite = None

        try:
            current_invites = await guild.invites()
        except discord.Forbidden:
            current_invites = []
        except discord.HTTPException:
            log.warning("Could not read invites for guild %s.", guild.id, exc_info=True)
            current_invites = []

        for invite in current_invites:
            old_uses = old_counts.get(invite.code, 0)
            if invite_uses(invite) > old_uses:
                used_invite = invite
                break

        self.invite_cache[guild.id] = {
            invite.code: invite_uses(invite) for invite in current_invites
        }

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
        embed.add_field(
            name="Account Age Check",
            value=(
                "New account"
                if (discord.utils.utcnow() - member.created_at).days < 7
                else "Established account"
            ),
            inline=True,
        )

        if used_invite:
            inviter = used_invite.inviter
            embed.add_field(
                name="Joined via Invite",
                value=f"`{used_invite.code}` by {inviter} ({invite_uses(used_invite)} total uses)",
                inline=False,
            )
            await upsert_invite(
                guild.id,
                used_invite.code,
                inviter.id if inviter else None,
                invite_uses(used_invite),
            )
        else:
            embed.add_field(
                name="Joined via Invite", value="Could not determine", inline=False
            )

        embed.add_field(name="Member Count", value=str(guild.member_count), inline=True)

        if JOIN_LOG_CHANNEL_ID:
            join_channel = guild.get_channel(JOIN_LOG_CHANNEL_ID)
            if join_channel:
                try:
                    await join_channel.send(embed=embed)
                except (discord.Forbidden, discord.HTTPException):
                    log.warning(
                        "Could not send join log in guild %s.", guild.id, exc_info=True
                    )

        if INVITE_LOG_CHANNEL_ID and INVITE_LOG_CHANNEL_ID != JOIN_LOG_CHANNEL_ID:
            invite_channel = guild.get_channel(INVITE_LOG_CHANNEL_ID)
            if invite_channel:
                try:
                    await invite_channel.send(embed=embed)
                except (discord.Forbidden, discord.HTTPException):
                    log.warning(
                        "Could not send invite log in guild %s.",
                        guild.id,
                        exc_info=True,
                    )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Log when a member leaves the server."""
        guild = member.guild
        await log_member_event(guild.id, member.id, "leave")

        if not JOIN_LOG_CHANNEL_ID:
            return

        channel = guild.get_channel(JOIN_LOG_CHANNEL_ID)
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
            value=(
                f"<t:{int(member.joined_at.timestamp())}:R>"
                if member.joined_at
                else "Unknown"
            ),
            inline=True,
        )
        embed.add_field(name="Member Count", value=str(guild.member_count), inline=True)
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            log.warning(
                "Could not send leave log in guild %s.", guild.id, exc_info=True
            )

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Update the cache when a new invite is created."""
        if invite.guild.id not in self.invite_cache:
            self.invite_cache[invite.guild.id] = {}
        self.invite_cache[invite.guild.id][invite.code] = invite_uses(invite)
        await upsert_invite(
            invite.guild.id,
            invite.code,
            invite.inviter.id if invite.inviter else None,
            invite_uses(invite),
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Drop deleted invites from the local cache."""
        cache = self.invite_cache.get(invite.guild.id, {})
        cache.pop(invite.code, None)

    @commands.command(name="invites", help="Show all active invites in the server.")
    @commands.has_permissions(manage_guild=True)
    async def show_invites(self, ctx):
        """Usage: ,invites"""
        try:
            invites = await ctx.guild.invites()
        except discord.Forbidden:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Cannot Read Invites",
                description="I need `Manage Server` permission to view invites.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)
        except discord.HTTPException:
            log.warning(
                "Could not read invites for guild %s.", ctx.guild.id, exc_info=True
            )
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Cannot Read Invites",
                description="Discord did not return the invite list. Try again in a moment.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        if not invites:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Active Invites",
                description="There are no active invites right now.",
                color=COLOR_INFO,
            )
            return await ctx.send(embed=embed)

        invites = sorted(invites, key=invite_uses, reverse=True)
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
                    f"Uses: {invite_uses(invite)}\n"
                    f"Max: {invite.max_uses or 'Unlimited'}"
                ),
                inline=True,
            )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(InviteLogger(bot))
