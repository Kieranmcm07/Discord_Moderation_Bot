"""
cogs/activity.py — tracks message counts and voice time, shows leaderboards.
I listen to every message to bump the daily counter and track voice channel
join/leave times to log minutes. Nothing personal is stored — just counts.
"""

import discord
from discord.ext import commands
from datetime import datetime, date
from utils.db import (
    increment_message_stat, get_top_chatters,
    add_voice_time, get_top_voice
)
from config import COLOR_INFO, COLOR_SUCCESS

# tracks when each user joined a voice channel so I can calc duration on leave
# format: {(guild_id, user_id): datetime}
voice_join_times: dict[tuple, datetime] = {}


class Activity(commands.Cog, name="Activity"):
    """Message and voice activity tracking + leaderboards."""

    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # Count every message (excluding bots and DMs)
    # ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Fires on every message. I only count real users in guild channels.
        Storing just the date + count so there's no message content saved at all.
        """
        if message.author.bot:
            return
        if not message.guild:
            return  # DMs don't count

        today = date.today().isoformat()  # 'YYYY-MM-DD'
        await increment_message_stat(message.guild.id, message.author.id, today)

    # ─────────────────────────────────────────────
    # Track voice time
    # ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """
        Tracks time spent in voice channels.
        - When someone joins a channel: record the timestamp.
        - When they leave: calculate the duration and save it.
        """
        key = (member.guild.id, member.id)

        if before.channel is None and after.channel is not None:
            # user joined a voice channel
            voice_join_times[key] = datetime.utcnow()

        elif before.channel is not None and after.channel is None:
            # user left — calculate how long they were in
            join_time = voice_join_times.pop(key, None)
            if join_time:
                minutes = int((datetime.utcnow() - join_time).total_seconds() / 60)
                if minutes > 0:
                    await add_voice_time(member.guild.id, member.id, minutes)

        elif before.channel is not None and after.channel is not None and before.channel != after.channel:
            # moved to a different channel — reset the timer
            join_time = voice_join_times.get(key)
            if join_time:
                minutes = int((datetime.utcnow() - join_time).total_seconds() / 60)
                if minutes > 0:
                    await add_voice_time(member.guild.id, member.id, minutes)
            voice_join_times[key] = datetime.utcnow()

    # ─────────────────────────────────────────────
    # ,topchat
    # ─────────────────────────────────────────────
    @commands.command(name="topchat", aliases=["chatleaderboard", "toplb"], help="Most active chatters in the server.")
    async def top_chat(self, ctx, limit: int = 10):
        """
        Usage: ,topchat [limit]
        Shows the all-time top chatters by message count.
        """
        limit = min(max(limit, 1), 25)
        data = await get_top_chatters(ctx.guild.id, limit)

        if not data:
            return await ctx.send(embed=discord.Embed(
                description="No message data yet — start chatting!", color=COLOR_INFO
            ))

        e = discord.Embed(title="💬 Top Chatters", color=COLOR_INFO)
        e.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else discord.Embed.Empty)

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(data):
            user = ctx.guild.get_member(row["user_id"])
            name = user.display_name if user else f"User {row['user_id']}"
            prefix = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{prefix} **{name}** — {row['total']:,} messages")

        e.description = "\n".join(lines)
        await ctx.send(embed=e)

    # ─────────────────────────────────────────────
    # ,topvoice
    # ─────────────────────────────────────────────
    @commands.command(name="topvoice", aliases=["voiceleaderboard", "toplv"], help="Most time spent in voice channels.")
    async def top_voice(self, ctx, limit: int = 10):
        """Usage: ,topvoice [limit]"""
        limit = min(max(limit, 1), 25)
        data = await get_top_voice(ctx.guild.id, limit)

        if not data:
            return await ctx.send(embed=discord.Embed(
                description="No voice data yet.", color=COLOR_INFO
            ))

        e = discord.Embed(title="🎙️ Top Voice Users", color=COLOR_INFO)
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(data):
            user = ctx.guild.get_member(row["user_id"])
            name = user.display_name if user else f"User {row['user_id']}"
            hours = row["minutes"] // 60
            mins  = row["minutes"] % 60
            time_str = f"{hours}h {mins}m" if hours else f"{mins}m"
            prefix = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{prefix} **{name}** — {time_str}")

        e.description = "\n".join(lines)
        await ctx.send(embed=e)

    # ─────────────────────────────────────────────
    # ,stats @user
    # ─────────────────────────────────────────────
    @commands.command(name="stats", aliases=["userstats"], help="Show activity stats for a user.")
    async def user_stats(self, ctx, member: discord.Member = None):
        """
        Usage: ,stats [@user]
        Shows message count and voice time for a user. Defaults to yourself.
        """
        member = member or ctx.author

        # grab their ranking in chat
        all_chat = await get_top_chatters(ctx.guild.id, 999)
        chat_rank = next((i + 1 for i, r in enumerate(all_chat) if r["user_id"] == member.id), None)
        chat_count = next((r["total"] for r in all_chat if r["user_id"] == member.id), 0)

        # grab their ranking in voice
        all_voice = await get_top_voice(ctx.guild.id, 999)
        voice_rank = next((i + 1 for i, r in enumerate(all_voice) if r["user_id"] == member.id), None)
        voice_mins = next((r["minutes"] for r in all_voice if r["user_id"] == member.id), 0)
        voice_hours = voice_mins // 60
        voice_rem   = voice_mins % 60

        e = discord.Embed(
            title=f"📊 Stats — {member.display_name}",
            color=COLOR_SUCCESS
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(
            name="💬 Messages",
            value=f"{chat_count:,} messages\nRank: #{chat_rank or 'N/A'}",
            inline=True
        )
        e.add_field(
            name="🎙️ Voice Time",
            value=f"{voice_hours}h {voice_rem}m\nRank: #{voice_rank or 'N/A'}",
            inline=True
        )
        e.add_field(
            name="📅 Joined Server",
            value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "Unknown",
            inline=True
        )
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Activity(bot))
