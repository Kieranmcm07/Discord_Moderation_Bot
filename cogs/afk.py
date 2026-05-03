"""
AFK status tracking.

Members can mark themselves away, and the bot will give a small context note
when someone mentions them.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import discord
from discord.ext import commands

from config import COLOR_INFO, COLOR_SUCCESS, PREFIX
from utils.db import clear_afk_status, get_afk_status, set_afk_status
from utils.embeds import make_embed


def parse_sqlite_timestamp(value: str) -> datetime | None:
    """Read SQLite CURRENT_TIMESTAMP values as UTC datetimes."""
    if not value:
        return None

    if "T" not in value:
        value = value.replace(" ", "T", 1)
    if not value.endswith(("+00:00", "Z")):
        value = f"{value}+00:00"
    return discord.utils.parse_time(value)


class AFK(commands.Cog, name="AFK"):
    """Let members mark themselves as away from keyboard."""

    def __init__(self, bot):
        self.bot = bot
        self._mention_cooldowns: dict[tuple[int, int, int], datetime] = {}

    def _is_afk_command(self, message: discord.Message) -> bool:
        content = message.content.strip().lower()
        prefixes = [PREFIX.lower()]
        if self.bot.user:
            prefixes.extend([f"<@{self.bot.user.id}> ", f"<@!{self.bot.user.id}> "])
        return any(
            content.startswith(f"{prefix}{name}")
            for prefix in prefixes
            for name in ("afk", "brb")
        )

    def _can_notify(self, guild_id: int, channel_id: int, user_id: int) -> bool:
        key = (guild_id, channel_id, user_id)
        now = discord.utils.utcnow()
        last_sent = self._mention_cooldowns.get(key)
        if last_sent and now - last_sent < timedelta(minutes=2):
            return False

        self._mention_cooldowns[key] = now
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if not self._is_afk_command(message):
            status = await clear_afk_status(message.guild.id, message.author.id)
            if status:
                await message.channel.send(
                    embed=await make_embed(
                        self.bot,
                        guild=message.guild,
                        title="Welcome Back",
                        description=f"Cleared your AFK status, {message.author.mention}.",
                        color=COLOR_SUCCESS,
                    ),
                    delete_after=12,
                )

        mentioned_members = {
            member.id: member
            for member in message.mentions
            if not member.bot and member.id != message.author.id
        }
        if not mentioned_members:
            return

        lines = []
        for member in mentioned_members.values():
            status = await get_afk_status(message.guild.id, member.id)
            if not status:
                continue

            if not self._can_notify(message.guild.id, message.channel.id, member.id):
                continue

            created_at = parse_sqlite_timestamp(status["created_at"])
            since = f" <t:{int(created_at.timestamp())}:R>" if created_at else ""
            reason = status["reason"]
            if len(reason) > 120:
                reason = f"{reason[:117]}..."
            lines.append(f"**{member.display_name}** is AFK{since}: {reason}")

        if lines:
            await message.reply(
                embed=await make_embed(
                    self.bot,
                    guild=message.guild,
                    title="AFK Notice",
                    description="\n".join(lines[:5]),
                    color=COLOR_INFO,
                ),
                mention_author=False,
            )

    @commands.command(
        name="afk",
        aliases=["brb"],
        help="Mark yourself as AFK until you send another message.",
    )
    @commands.guild_only()
    async def afk(self, ctx, *, reason: str = None):
        """Usage: ,afk [reason]"""
        reason = (reason or "AFK").strip()
        if len(reason) > 180:
            reason = f"{reason[:177]}..."

        await set_afk_status(ctx.guild.id, ctx.author.id, reason)
        await ctx.send(
            embed=await make_embed(
                self.bot,
                guild=ctx.guild,
                title="AFK Set",
                description=(
                    f"{ctx.author.mention}, I will let people know you are AFK.\n"
                    f"**Reason:** {reason}"
                ),
                color=COLOR_SUCCESS,
            )
        )


async def setup(bot):
    await bot.add_cog(AFK(bot))
