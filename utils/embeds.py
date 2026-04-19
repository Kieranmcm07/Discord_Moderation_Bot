"""
Shared embed helpers.

These helpers keep the bot's responses visually consistent without forcing each
command to repeat the same thumbnail, footer, and optional image setup.
"""

from __future__ import annotations

import discord

from config import COLOR_INFO
from utils.db import get_guild_settings


async def themed_color(guild: discord.Guild | None, fallback: int = COLOR_INFO) -> int:
    """Return the saved guild color when one exists, otherwise use the fallback."""
    if guild is None:
        return fallback

    settings = await get_guild_settings(guild.id)
    if settings and settings.get("embed_color") is not None:
        return settings["embed_color"]
    return fallback


async def get_embed_image(guild: discord.Guild | None) -> str | None:
    """Return the optional shared image or GIF configured for guild embeds."""
    if guild is None:
        return None

    settings = await get_guild_settings(guild.id)
    if not settings:
        return None

    image_url = settings.get("embed_image_url") or None
    return image_url or None


async def decorate_embed(bot, guild: discord.Guild | None, embed: discord.Embed) -> discord.Embed:
    """
    Apply the shared bot branding to an existing embed.

    This lets older commands keep their own embed-building logic while still
    inheriting the improved project-wide visual style.
    """
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

        if not embed.footer.text:
            embed.set_footer(text=bot.user.name, icon_url=bot.user.display_avatar.url)

    image_url = await get_embed_image(guild)
    if image_url and not embed.image.url:
        embed.set_image(url=image_url)

    return embed


async def make_embed(
    bot,
    *,
    guild: discord.Guild | None,
    title: str | None = None,
    description: str | None = None,
    color: int = COLOR_INFO,
    timestamp=None,
) -> discord.Embed:
    """Create a branded embed in one place so command code stays readable."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=await themed_color(guild, color),
        timestamp=timestamp,
    )
    return await decorate_embed(bot, guild, embed)
