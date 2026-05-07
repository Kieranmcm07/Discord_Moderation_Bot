# ============================================================
#   Made by Kieranmcm07 on GitHub
#   GitHub: https://github.com/Kieranmcm07
# ============================================================
"""
Shared error-handling helpers.

Commands, button views, modals, and background events all fail in slightly
different ways in discord.py. These helpers keep the user-facing response calm
while making the log entry easy to find with a short error ID.
"""

from __future__ import annotations

import logging
import secrets

import discord
from discord.ext import commands

from config import COLOR_ERROR
from utils.embeds import make_embed

log = logging.getLogger(__name__)


def make_error_id() -> str:
    """Return a short ID that can be shown to users and searched in bot.log."""
    return secrets.token_hex(3).upper()


def _snowflake_id(value) -> int | None:
    """Safely pull a Discord snowflake ID from an object when one exists."""
    return getattr(value, "id", None)


def log_exception(
    logger: logging.Logger,
    message: str,
    error: BaseException,
    *,
    error_id: str | None = None,
    **context,
) -> str:
    """Log an exception with a stable error ID and compact Discord context."""
    error_id = error_id or make_error_id()
    context_bits = [
        f"{key}={value}"
        for key, value in context.items()
        if value is not None and value != ""
    ]
    suffix = f" {' '.join(context_bits)}" if context_bits else ""
    logger.error(
        "%s [error_id=%s]%s",
        message,
        error_id,
        suffix,
        exc_info=(type(error), error, error.__traceback__),
    )
    return error_id


async def make_feedback_embed(
    bot,
    *,
    guild: discord.Guild | None,
    title: str,
    description: str,
    color: int = COLOR_ERROR,
) -> discord.Embed:
    """Build a branded embed, falling back if branding/database lookup fails."""
    try:
        return await make_embed(
            bot,
            guild=guild,
            title=title,
            description=description,
            color=color,
        )
    except Exception:
        log.exception("Failed to build branded error embed")
        return discord.Embed(title=title, description=description, color=color)


async def safe_context_send(
    ctx: commands.Context,
    content: str | None = None,
    **kwargs,
) -> bool:
    """Send a command response without letting Discord API failures cascade."""
    try:
        await ctx.send(content=content, **kwargs)
        return True
    except (discord.Forbidden, discord.NotFound) as exc:
        log.warning(
            "Could not send command feedback: guild_id=%s channel_id=%s author_id=%s error=%s",
            _snowflake_id(ctx.guild),
            _snowflake_id(ctx.channel),
            _snowflake_id(ctx.author),
            exc,
        )
    except discord.HTTPException as exc:
        log.warning(
            "Discord rejected command feedback: guild_id=%s channel_id=%s author_id=%s status=%s code=%s text=%s",
            _snowflake_id(ctx.guild),
            _snowflake_id(ctx.channel),
            _snowflake_id(ctx.author),
            getattr(exc, "status", None),
            getattr(exc, "code", None),
            getattr(exc, "text", None),
        )
    return False


async def send_command_feedback(
    ctx: commands.Context,
    bot,
    *,
    title: str,
    description: str,
    color: int = COLOR_ERROR,
) -> bool:
    """Send a branded command error/warning embed safely."""
    embed = await make_feedback_embed(
        bot,
        guild=ctx.guild,
        title=title,
        description=description,
        color=color,
    )
    return await safe_context_send(ctx, embed=embed)


async def send_unexpected_command_error(
    ctx: commands.Context,
    bot,
    error_id: str,
) -> bool:
    """Tell a command user about an unexpected error without exposing internals."""
    return await send_command_feedback(
        ctx,
        bot,
        title="Something Went Wrong",
        description=(
            "That command hit an unexpected error. I logged the details in "
            f"`bot.log`.\n\nError ID: `{error_id}`"
        ),
        color=COLOR_ERROR,
    )


async def safe_interaction_send(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    ephemeral: bool = True,
) -> bool:
    """Reply to an interaction whether the original response was used or not."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                content=content,
                embed=embed,
                ephemeral=ephemeral,
            )
        else:
            await interaction.response.send_message(
                content=content,
                embed=embed,
                ephemeral=ephemeral,
            )
        return True
    except (discord.Forbidden, discord.NotFound) as exc:
        log.warning(
            "Could not send interaction feedback: guild_id=%s channel_id=%s user_id=%s error=%s",
            _snowflake_id(interaction.guild),
            _snowflake_id(interaction.channel),
            _snowflake_id(interaction.user),
            exc,
        )
    except discord.HTTPException as exc:
        log.warning(
            "Discord rejected interaction feedback: guild_id=%s channel_id=%s user_id=%s status=%s code=%s text=%s",
            _snowflake_id(interaction.guild),
            _snowflake_id(interaction.channel),
            _snowflake_id(interaction.user),
            getattr(exc, "status", None),
            getattr(exc, "code", None),
            getattr(exc, "text", None),
        )
    return False


async def send_unexpected_interaction_error(
    interaction: discord.Interaction,
    error_id: str,
) -> bool:
    """Tell a button/modal user about an unexpected error."""
    embed = await make_feedback_embed(
        interaction.client,
        guild=interaction.guild,
        title="Something Went Wrong",
        description=(
            "That interaction hit an unexpected error. I logged the details in "
            f"`bot.log`.\n\nError ID: `{error_id}`"
        ),
        color=COLOR_ERROR,
    )
    return await safe_interaction_send(interaction, embed=embed, ephemeral=True)


class SafeView(discord.ui.View):
    """View base class that logs callback crashes and replies with an error ID."""

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        logger = logging.getLogger(type(self).__module__)
        error_id = log_exception(
            logger,
            "Unhandled UI view error",
            error,
            view=type(self).__name__,
            item=type(item).__name__,
            custom_id=getattr(item, "custom_id", None),
            guild_id=_snowflake_id(interaction.guild),
            channel_id=_snowflake_id(interaction.channel),
            user_id=_snowflake_id(interaction.user),
        )
        await send_unexpected_interaction_error(interaction, error_id)


class SafeModal(discord.ui.Modal):
    """Modal base class that gives submit failures the same error-ID treatment."""

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
    ) -> None:
        logger = logging.getLogger(type(self).__module__)
        error_id = log_exception(
            logger,
            "Unhandled UI modal error",
            error,
            modal=type(self).__name__,
            guild_id=_snowflake_id(interaction.guild),
            channel_id=_snowflake_id(interaction.channel),
            user_id=_snowflake_id(interaction.user),
        )
        await send_unexpected_interaction_error(interaction, error_id)
