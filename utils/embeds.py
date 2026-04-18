"""
Shared embed helpers so the bot uses a consistent look.
"""

from __future__ import annotations

import discord

from config import COLOR_INFO
from utils.db import get_guild_settings


async def themed_color(guild: discord.Guild | None, fallback: int = COLOR_INFO) -> int:
    if guild is None:
        return fallback

    settings = await get_guild_settings(guild.id)
    if settings and settings.get("embed_color") is not None:
        return settings["embed_color"]
    return fallback


async def make_embed(
    bot,
    *,
    guild: discord.Guild | None,
    title: str | None = None,
    description: str | None = None,
    color: int = COLOR_INFO,
    timestamp=None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=await themed_color(guild, color),
        timestamp=timestamp,
    )

    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.set_footer(text=bot.user.name, icon_url=bot.user.display_avatar.url)

    return embed
