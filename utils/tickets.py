"""Channel access shared by support tickets and case appeals."""

import discord

from utils.db import get_ticket_roles


async def get_staff_roles(guild: discord.Guild) -> list[discord.Role]:
    # Deleted roles can still be in the saved settings; skip them when opening a ticket.
    roles = [guild.get_role(role_id) for role_id in await get_ticket_roles(guild.id)]
    return [role for role in roles if role is not None]


def ticket_overwrites(guild, bot_member, owner, staff_roles):
    """Build the same private channel permissions for tickets and appeals."""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        bot_member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, manage_channels=True,
        ),
        owner: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True,
            embed_links=True, read_message_history=True,
        ),
    }
    for role in staff_roles:
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True,
            embed_links=True, read_message_history=True, manage_messages=True,
        )
    return overwrites
