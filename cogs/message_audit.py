# ============================================================
#   Made by Kieranmcm07 on GitHub
#   GitHub: https://github.com/Kieranmcm07
# ============================================================
"""
Deleted and edited message audit logs.

This cog keeps lightweight, server-configurable message visibility for staff
without storing message content in the database.
"""

import logging

import discord
from discord.ext import commands

from config import COLOR_INFO, COLOR_WARN
from utils.db import get_guild_settings

MAX_FIELD_LENGTH = 1024
log = logging.getLogger(__name__)


def short_text(value: str | None, limit: int = MAX_FIELD_LENGTH) -> str:
    """Keep audit embed fields inside Discord's limits."""
    if not value:
        return "*No text content*"

    cleaned = value.strip()
    if not cleaned:
        return "*No text content*"

    if len(cleaned) <= limit:
        return cleaned

    return f"{cleaned[: limit - 15]}... *(truncated)*"


def attachment_summary(message: discord.Message) -> str | None:
    if not message.attachments:
        return None

    summary = "\n".join(
        f"[{attachment.filename}]({attachment.url})"
        for attachment in message.attachments[:5]
    )
    return short_text(summary)


class MessageAudit(commands.Cog, name="Message Audit"):
    """Log deleted and edited messages to a configured staff channel."""

    def __init__(self, bot):
        self.bot = bot

    async def get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        settings = await get_guild_settings(guild.id) or {}
        channel_id = settings.get("message_log_channel_id")
        if not channel_id:
            return None

        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        return None

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        log_channel = await self.get_log_channel(message.guild)
        if not log_channel or message.channel.id == log_channel.id:
            return

        embed = discord.Embed(
            title="Message Deleted",
            color=COLOR_WARN,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(
            name=str(message.author), icon_url=message.author.display_avatar.url
        )
        embed.add_field(name="Author", value=message.author.mention, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Content", value=short_text(message.content), inline=False)

        attachments = attachment_summary(message)
        if attachments:
            embed.add_field(name="Attachments", value=attachments, inline=False)

        embed.set_footer(
            text=f"User ID: {message.author.id} | Message ID: {message.id}"
        )
        try:
            await log_channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            log.warning(
                "Could not send deleted-message audit log in guild %s.",
                message.guild.id,
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return

        if before.content == after.content:
            return

        log_channel = await self.get_log_channel(before.guild)
        if not log_channel or before.channel.id == log_channel.id:
            return

        jump_link = f"[Jump to message]({after.jump_url})"
        embed = discord.Embed(
            title="Message Edited",
            description=jump_link,
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(
            name=str(before.author), icon_url=before.author.display_avatar.url
        )
        embed.add_field(name="Author", value=before.author.mention, inline=True)
        embed.add_field(name="Channel", value=before.channel.mention, inline=True)
        embed.add_field(name="Before", value=short_text(before.content), inline=False)
        embed.add_field(name="After", value=short_text(after.content), inline=False)
        embed.set_footer(text=f"User ID: {before.author.id} | Message ID: {before.id}")
        try:
            await log_channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            log.warning(
                "Could not send edited-message audit log in guild %s.",
                before.guild.id,
                exc_info=True,
            )


async def setup(bot):
    await bot.add_cog(MessageAudit(bot))
