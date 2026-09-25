"""Case labels and log delivery shared by the moderation cogs."""

import logging

import discord

from config import resolve_mod_log_channel_id
from utils.db import get_guild_settings

log = logging.getLogger(__name__)

ACTION_LABELS = {
    "ban": "Ban",
    "softban": "Softban",
    "unban": "Unban",
    "kick": "Kick",
    "tempban": "Temporary Ban",
    "warn": "Warning",
    "note": "Moderator Note",
    "clearwarns": "Warnings Cleared",
    "timeout": "Timeout",
    "untimeout": "Timeout Removed",
    "mute": "Mute",
    "unmute": "Unmute",
    "automod": "AutoMod",
}


def get_action_label(action: str) -> str:
    # Older databases can contain actions that no longer have a command.
    return ACTION_LABELS.get(action, action.title())


async def send_mod_log(
    guild: discord.Guild,
    embed: discord.Embed,
    preferred_channel_id: int | None = None,
) -> None:
    """Send to the requested channel, falling back to the guild's mod log."""
    channel = guild.get_channel(preferred_channel_id) if preferred_channel_id else None
    if channel is None:
        settings = await get_guild_settings(guild.id) or {}
        channel_id = resolve_mod_log_channel_id(settings)
        channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        return

    try:
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        # The moderation action has already happened; a failed log must not undo it.
        log.warning(
            "Could not send moderation log in guild %s to channel %s.",
            guild.id, channel.id, exc_info=True,
        )
