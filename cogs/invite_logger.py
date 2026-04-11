"""
cogs/invite_logger.py — tracks which invite link each new member used to join.
The trick here is that Discord doesn't tell you which invite was used
directly, so I snapshot all invite use counts when the bot starts
and when someone joins I diff them to figure out which one went up.
It's a bit of a hack but it works reliably.
"""

import discord
from discord.ext import commands
from utils.db import upsert_invite, get_invites, log_member_event
from config import INVITE_LOG_CHANNEL_ID, JOIN_LOG_CHANNEL_ID, COLOR_SUCCESS, COLOR_ERROR, COLOR_INFO


class InviteLogger(commands.Cog, name="Invite Logger"):
    """Tracks invite usage and logs member joins/leaves."""

    def __init__(self, bot):
        self.bot = bot
        # in-memory invite cache: guild_id -> {code: uses}
        # I populate this on ready and keep it up to date
        self.invite_cache: dict[int, dict[str, int]] = {}

    # ─────────────────────────────────────────────
    # Build the initial cache when the bot connects
    # ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        """Snapshot all invite use counts for every guild."""
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    async def _cache_invites(self, guild: discord.Guild):
        """Pull all invites for a guild and save them to memory + DB."""
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            # also persist to DB so we have a baseline even after restarts
            for inv in invites:
                await upsert_invite(guild.id, inv.code, inv.inviter.id if inv.inviter else None, inv.uses)
        except discord.Forbidden:
            pass  # bot doesn't have manage_guild permissions, skip this server

    # ─────────────────────────────────────────────
    # When someone joins, figure out which invite they used
    # ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Fired every time someone joins. I compare the new invite counts
        against my cached snapshot to find the invite that went up.
        """
        guild = member.guild
        await log_member_event(guild.id, member.id, "join")

        old_counts = self.invite_cache.get(guild.id, {})
        used_invite = None

        try:
            current_invites = await guild.invites()
        except discord.Forbidden:
            current_invites = []

        for inv in current_invites:
            old_uses = old_counts.get(inv.code, 0)
            if inv.uses > old_uses:
                used_invite = inv
                break  # found it

        # update the cache with the new counts
        self.invite_cache[guild.id] = {inv.code: inv.uses for inv in current_invites}

        # build the join embed
        e = discord.Embed(
            title="📥 Member Joined",
            color=COLOR_SUCCESS
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="User",    value=f"{member} (`{member.id}`)", inline=False)
        e.add_field(name="Account Created",
                    value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)

        if used_invite:
            inviter = used_invite.inviter
            e.add_field(
                name="Joined via Invite",
                value=f"`{used_invite.code}` by {inviter} ({used_invite.uses} total uses)",
                inline=False
            )
            await upsert_invite(guild.id, used_invite.code, inviter.id if inviter else None, used_invite.uses)
        else:
            e.add_field(name="Joined via Invite", value="Could not determine", inline=False)

        # total member count
        e.set_footer(text=f"Member #{guild.member_count}")

        # send to join log channel
        if JOIN_LOG_CHANNEL_ID:
            ch = guild.get_channel(JOIN_LOG_CHANNEL_ID)
            if ch:
                await ch.send(embed=e)

        # also send to invite log channel if it's different
        if INVITE_LOG_CHANNEL_ID and INVITE_LOG_CHANNEL_ID != JOIN_LOG_CHANNEL_ID:
            ch = guild.get_channel(INVITE_LOG_CHANNEL_ID)
            if ch:
                await ch.send(embed=e)

    # ─────────────────────────────────────────────
    # Member leave
    # ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Log when someone leaves or gets kicked/banned."""
        guild = member.guild
        await log_member_event(guild.id, member.id, "leave")

        if not JOIN_LOG_CHANNEL_ID:
            return

        ch = guild.get_channel(JOIN_LOG_CHANNEL_ID)
        if not ch:
            return

        e = discord.Embed(
            title="📤 Member Left",
            color=COLOR_ERROR
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="User",  value=f"{member} (`{member.id}`)", inline=False)
        e.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown", inline=True)
        e.set_footer(text=f"Now at {guild.member_count} members")
        await ch.send(embed=e)

    # ─────────────────────────────────────────────
    # Update cache when a new invite is created
    # ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Keep the cache fresh when a new invite is made."""
        if invite.guild.id not in self.invite_cache:
            self.invite_cache[invite.guild.id] = {}
        self.invite_cache[invite.guild.id][invite.code] = invite.uses
        await upsert_invite(invite.guild.id, invite.code,
                            invite.inviter.id if invite.inviter else None, invite.uses)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Remove deleted invites from the cache."""
        cache = self.invite_cache.get(invite.guild.id, {})
        cache.pop(invite.code, None)

    # ─────────────────────────────────────────────
    # ,invites command
    # ─────────────────────────────────────────────
    @commands.command(name="invites", help="Show all active invites in the server.")
    @commands.has_permissions(manage_guild=True)
    async def show_invites(self, ctx):
        """Usage: ,invites — lists all active invite links and their use counts."""
        try:
            invites = await ctx.guild.invites()
        except discord.Forbidden:
            return await ctx.send(embed=discord.Embed(
                description="❌ I need `Manage Server` permission to view invites.",
                color=COLOR_ERROR
            ))

        if not invites:
            return await ctx.send(embed=discord.Embed(description="No active invites.", color=COLOR_INFO))

        # sort by uses descending
        invites = sorted(invites, key=lambda i: i.uses, reverse=True)

        e = discord.Embed(title="📬 Active Invites", color=COLOR_INFO)
        for inv in invites[:20]:  # cap at 20 so the embed doesn't explode
            inviter = str(inv.inviter) if inv.inviter else "Unknown"
            e.add_field(
                name=f"`{inv.code}`",
                value=f"**Created by:** {inviter}\n**Uses:** {inv.uses}\n**Max:** {inv.max_uses or '∞'}",
                inline=True
            )
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(InviteLogger(bot))
