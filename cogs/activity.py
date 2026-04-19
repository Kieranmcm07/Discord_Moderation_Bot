"""
Activity tracking and leaderboards.

Only aggregate counts are stored here. The bot does not save message content,
which keeps this feature useful without feeling invasive.
"""

from datetime import date, datetime

import discord
from discord.ext import commands

from config import COLOR_INFO, COLOR_SUCCESS
from utils.db import add_voice_time, get_top_chatters, get_top_voice, increment_message_stat
from utils.embeds import make_embed


# Voice joins are only tracked while the bot is online, which is fine for a
# lightweight local project. The next voice event starts a fresh timer cleanly.
voice_join_times: dict[tuple[int, int], datetime] = {}


class Activity(commands.Cog, name="Activity"):
    """Track chat and voice activity, then present it as simple leaderboards."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Count normal guild messages without storing their content."""
        if message.author.bot or not message.guild:
            return

        today = date.today().isoformat()
        await increment_message_stat(message.guild.id, message.author.id, today)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Track minutes spent in voice channels."""
        key = (member.guild.id, member.id)

        if before.channel is None and after.channel is not None:
            voice_join_times[key] = datetime.utcnow()
            return

        if before.channel is not None and after.channel is None:
            join_time = voice_join_times.pop(key, None)
            if join_time:
                minutes = int((datetime.utcnow() - join_time).total_seconds() / 60)
                if minutes > 0:
                    await add_voice_time(member.guild.id, member.id, minutes)
            return

        if before.channel is not None and after.channel is not None and before.channel != after.channel:
            join_time = voice_join_times.get(key)
            if join_time:
                minutes = int((datetime.utcnow() - join_time).total_seconds() / 60)
                if minutes > 0:
                    await add_voice_time(member.guild.id, member.id, minutes)
            voice_join_times[key] = datetime.utcnow()

    @commands.command(name="topchat", aliases=["chatleaderboard", "toplb"], help="Show the top chatters in the server.")
    async def top_chat(self, ctx, limit: int = 10):
        """Usage: ,topchat [limit]"""
        limit = min(max(limit, 1), 25)
        data = await get_top_chatters(ctx.guild.id, limit)

        if not data:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Top Chatters",
                description="No message data yet. Start chatting and this leaderboard will fill up.",
                color=COLOR_INFO,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Top Chatters",
            color=COLOR_INFO,
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for index, row in enumerate(data):
            user = ctx.guild.get_member(row["user_id"])
            name = user.display_name if user else f"User {row['user_id']}"
            prefix = medals[index] if index < 3 else f"`{index + 1}.`"
            lines.append(f"{prefix} **{name}** - {row['total']:,} messages")

        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.command(name="topvoice", aliases=["voiceleaderboard", "toplv"], help="Show who has spent the most time in voice chat.")
    async def top_voice(self, ctx, limit: int = 10):
        """Usage: ,topvoice [limit]"""
        limit = min(max(limit, 1), 25)
        data = await get_top_voice(ctx.guild.id, limit)

        if not data:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Top Voice Users",
                description="No voice activity has been recorded yet.",
                color=COLOR_INFO,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Top Voice Users",
            color=COLOR_INFO,
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for index, row in enumerate(data):
            user = ctx.guild.get_member(row["user_id"])
            name = user.display_name if user else f"User {row['user_id']}"
            hours = row["minutes"] // 60
            minutes = row["minutes"] % 60
            time_value = f"{hours}h {minutes}m" if hours else f"{minutes}m"
            prefix = medals[index] if index < 3 else f"`{index + 1}.`"
            lines.append(f"{prefix} **{name}** - {time_value}")

        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.command(name="stats", aliases=["userstats"], help="Show a member's activity stats.")
    async def user_stats(self, ctx, member: discord.Member = None):
        """Usage: ,stats [@user]"""
        member = member or ctx.author

        all_chat = await get_top_chatters(ctx.guild.id, 999)
        chat_rank = next((index + 1 for index, row in enumerate(all_chat) if row["user_id"] == member.id), None)
        chat_count = next((row["total"] for row in all_chat if row["user_id"] == member.id), 0)

        all_voice = await get_top_voice(ctx.guild.id, 999)
        voice_rank = next((index + 1 for index, row in enumerate(all_voice) if row["user_id"] == member.id), None)
        voice_minutes = next((row["minutes"] for row in all_voice if row["user_id"] == member.id), 0)
        voice_hours = voice_minutes // 60
        voice_remainder = voice_minutes % 60

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Stats - {member.display_name}",
            color=COLOR_SUCCESS,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Messages",
            value=f"{chat_count:,} messages\nRank: #{chat_rank or 'N/A'}",
            inline=True,
        )
        embed.add_field(
            name="Voice Time",
            value=f"{voice_hours}h {voice_remainder}m\nRank: #{voice_rank or 'N/A'}",
            inline=True,
        )
        embed.add_field(
            name="Joined Server",
            value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "Unknown",
            inline=True,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Activity(bot))
