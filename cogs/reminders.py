"""
Personal staff reminders and follow-ups.

Reminders are stored in SQLite so they survive restarts, then delivered by a
small background loop when they become due.
"""

# Useful for staff follow-ups that would otherwise get forgotten.
import logging
import re
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from config import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS, PREFIX
from utils.db import (
    add_reminder,
    delete_reminder,
    get_due_reminders,
    get_user_reminders,
)
from utils.embeds import make_embed

log = logging.getLogger(__name__)

DURATION_PART = re.compile(
    r"(?P<amount>\d+)\s*(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)",
    re.IGNORECASE,
)
NUMBER_TOKEN = re.compile(r"^\d+$")
UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}


def parse_compact_duration(value: str) -> int | None:
    """Convert a single compact token like 1h30m into seconds."""
    total = 0
    position = 0
    for match in DURATION_PART.finditer(value):
        if value[position : match.start()].strip():
            return None

        amount = int(match.group("amount"))
        unit = match.group("unit").lower()
        total += amount * UNITS[unit]
        position = match.end()

    if value[position:].strip() or total <= 0:
        return None

    return total


def parse_duration_prefix(payload: str) -> tuple[int | None, str]:
    """Read a leading duration from text and return seconds plus the remainder."""
    tokens = payload.strip().split()
    if not tokens:
        return None, ""

    total = 0
    index = 0
    while index < len(tokens):
        token = tokens[index].rstrip(",")
        compact_seconds = parse_compact_duration(token)

        if compact_seconds is not None:
            total += compact_seconds
            index += 1
            continue

        if (
            NUMBER_TOKEN.fullmatch(token)
            and index + 1 < len(tokens)
            and tokens[index + 1].lower().rstrip(",") in UNITS
        ):
            unit = tokens[index + 1].lower().rstrip(",")
            total += int(token) * UNITS[unit]
            index += 2
            continue

        break

    if total <= 0:
        return None, payload.strip()

    return total, " ".join(tokens[index:]).strip()


def compact_duration(seconds: int) -> str:
    """Render seconds as a short human-readable duration."""
    parts = []
    for label, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value}{label}")

    if seconds and not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts[:2]) or "now"


class Reminders(commands.Cog, name="Reminders"):
    """Create and manage personal follow-up reminders."""

    def __init__(self, bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        due = await get_due_reminders(discord.utils.utcnow().isoformat())
        for reminder in due:
            try:
                await self.deliver_reminder(reminder)
            except Exception:
                log.exception("Failed to deliver reminder %s", reminder["id"])
                continue
            await delete_reminder(reminder["guild_id"], reminder["id"])

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()

    async def deliver_reminder(self, reminder: dict):
        """Send a due reminder to its original channel, falling back to DM."""
        guild = self.bot.get_guild(reminder["guild_id"])
        user = self.bot.get_user(reminder["user_id"])
        if user is None:
            try:
                user = await self.bot.fetch_user(reminder["user_id"])
            except discord.NotFound:
                return
            except discord.HTTPException:
                log.warning(
                    "Could not fetch reminder user %s.",
                    reminder["user_id"],
                    exc_info=True,
                )
                raise

        embed = await make_embed(
            self.bot,
            guild=guild,
            title="Reminder",
            description=reminder["message"],
            color=COLOR_INFO,
        )
        embed.add_field(name="For", value=user.mention, inline=True)
        embed.add_field(name="Reminder ID", value=f"`{reminder['id']}`", inline=True)

        channel = guild.get_channel(reminder["channel_id"]) if guild else None
        if channel:
            try:
                await channel.send(content=user.mention, embed=embed)
                return
            except (discord.Forbidden, discord.HTTPException):
                pass

        try:
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.command(
        name="remind",
        aliases=["reminder", "remindme"],
        help="Create a reminder for yourself.",
    )
    @commands.guild_only()
    async def remind(self, ctx, *, payload: str = None):
        """Usage: ,remind <duration> <message>"""
        if not payload:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Reminder",
                description=f"Use `{PREFIX}remind 2h check the ticket`.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        seconds, message = parse_duration_prefix(payload)
        if seconds is None or not message:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Invalid Reminder",
                description=(
                    "Start with a duration, then the reminder text. "
                    f"Example: `{PREFIX}remind 1d review the warning`."
                ),
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        if seconds > 365 * 86400:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Reminder Too Far Away",
                description="Please keep reminders within one year.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        due_at = discord.utils.utcnow() + timedelta(seconds=seconds)
        reminder_id = await add_reminder(
            ctx.guild.id,
            ctx.channel.id,
            ctx.author.id,
            message,
            due_at.isoformat(),
        )

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Reminder Set",
            description=message,
            color=COLOR_SUCCESS,
        )
        embed.add_field(
            name="When", value=f"<t:{int(due_at.timestamp())}:R>", inline=True
        )
        embed.add_field(name="Reminder ID", value=f"`{reminder_id}`", inline=True)
        await ctx.send(embed=embed)

    @commands.command(
        name="reminders",
        aliases=["myreminders"],
        help="List your active reminders.",
    )
    @commands.guild_only()
    async def reminders(self, ctx):
        """Usage: ,reminders"""
        reminders = await get_user_reminders(ctx.guild.id, ctx.author.id, 10)
        if not reminders:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Your Reminders",
                description="You do not have any active reminders.",
                color=COLOR_INFO,
            )
            return await ctx.send(embed=embed)

        lines = []
        now = discord.utils.utcnow()
        for reminder in reminders:
            due_at = discord.utils.parse_time(reminder["due_at"])
            timestamp = int(due_at.timestamp()) if due_at else 0
            remaining = int((due_at - now).total_seconds()) if due_at else 0
            text = reminder["message"]
            if len(text) > 90:
                text = f"{text[:87]}..."
            lines.append(
                f"`{reminder['id']}` <t:{timestamp}:R> ({compact_duration(max(remaining, 0))}) - {text}"
            )

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Your Reminders",
            description="\n".join(lines),
            color=COLOR_INFO,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="delreminder",
        aliases=["deletereminder", "removereminder"],
        help="Delete one of your reminders.",
    )
    @commands.guild_only()
    async def delete_reminder_command(self, ctx, reminder_id: int):
        """Usage: ,delreminder <id>"""
        deleted = await delete_reminder(ctx.guild.id, reminder_id, ctx.author.id)
        if not deleted:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Reminder Not Found",
                description="I could not find one of your reminders with that ID.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Reminder Deleted",
            description=f"Removed reminder `{reminder_id}`.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Reminders(bot))
