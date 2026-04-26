"""
Sentinel live threat radar.

This cog watches short-lived behaviour patterns rather than single messages.
It is intentionally local and explainable: no external AI API, no hidden model,
just transparent signals staff can act on.
"""

import json
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta

import discord
from discord.ext import commands

from config import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_WARN,
    PREFIX,
    resolve_mod_log_channel_id,
)
from utils.db import (
    add_sentinel_incident,
    get_guild_settings,
    get_recent_sentinel_incidents,
    get_sentinel_settings,
    upsert_sentinel_settings,
)
from utils.embeds import make_embed


LINK_PATTERN = re.compile(
    r"https?://\S+|discord(?:app)?\.com/invite/\S+|discord\.gg/\S+",
    re.I,
)
MENTION_PATTERN = re.compile(r"<@!?\d+>|<@&\d+>")


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def normalize_message(content: str) -> str:
    """Normalize content for repeat/spam detection without preserving exact text."""
    content = LINK_PATTERN.sub("<link>", content.lower())
    content = MENTION_PATTERN.sub("<mention>", content)
    return re.sub(r"\s+", " ", content).strip()


def short_reason_list(reasons: list[str]) -> str:
    return "\n".join(f"- {reason}" for reason in reasons[:6])


class Sentinel(commands.Cog, name="Sentinel"):
    """Explainable raid and spam intelligence for staff."""

    def __init__(self, bot):
        self.bot = bot
        self.message_windows: dict[tuple[int, int], deque] = defaultdict(
            lambda: deque(maxlen=30)
        )
        self.join_windows: dict[int, deque] = defaultdict(lambda: deque(maxlen=80))
        self.alert_cooldowns: dict[tuple[int, int], datetime] = {}
        self.join_alert_cooldowns: dict[int, datetime] = {}

    def recent_messages(self, guild_id: int, user_id: int, seconds: int) -> list[dict]:
        now = discord.utils.utcnow()
        return [
            entry
            for entry in self.message_windows[(guild_id, user_id)]
            if (now - entry["created_at"]).total_seconds() <= seconds
        ]

    def recent_joins(self, guild_id: int, seconds: int) -> list[dict]:
        now = discord.utils.utcnow()
        return [
            entry
            for entry in self.join_windows[guild_id]
            if (now - entry["created_at"]).total_seconds() <= seconds
        ]

    def score_message(self, message: discord.Message) -> tuple[int, list[str]]:
        recent_15 = self.recent_messages(message.guild.id, message.author.id, 15)
        recent_60 = self.recent_messages(message.guild.id, message.author.id, 60)
        normalized = normalize_message(message.content)
        reasons = []
        score = 0

        if len(recent_15) >= 6:
            score += min(35, len(recent_15) * 4)
            reasons.append(f"{len(recent_15)} messages in 15 seconds")

        repeated = sum(1 for entry in recent_60 if entry["normalized"] == normalized)
        if normalized and repeated >= 3:
            score += min(35, repeated * 8)
            reasons.append(f"repeated the same message {repeated} times")

        link_count = sum(1 for entry in recent_60 if entry["has_link"])
        if link_count >= 3:
            score += min(30, link_count * 8)
            reasons.append(f"{link_count} link or invite messages in 60 seconds")

        mention_count = sum(entry["mention_count"] for entry in recent_15)
        if mention_count >= 6:
            score += min(25, mention_count * 2)
            reasons.append(f"{mention_count} mentions in 15 seconds")

        letters = [char for char in message.content if char.isalpha()]
        if len(letters) >= 12:
            upper_ratio = sum(1 for char in letters if char.isupper()) / len(letters)
            if upper_ratio >= 0.75:
                score += 12
                reasons.append("mostly uppercase message burst")

        joined_at = getattr(message.author, "joined_at", None)
        if joined_at:
            account_minutes = (discord.utils.utcnow() - joined_at).total_seconds() / 60
            if account_minutes < 20 and score >= 35:
                score += 15
                reasons.append("very new server member")

        return clamp(score, 0, 100), reasons

    async def send_sentinel_log(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        preferred_channel_id: int | None,
    ):
        channel = (
            guild.get_channel(preferred_channel_id) if preferred_channel_id else None
        )

        if channel is None:
            guild_settings = await get_guild_settings(guild.id) or {}
            mod_log_id = resolve_mod_log_channel_id(guild_settings)
            channel = guild.get_channel(mod_log_id) if mod_log_id else None

        if channel:
            await channel.send(embed=embed)

    async def create_message_incident(
        self,
        message: discord.Message,
        score: int,
        reasons: list[str],
        settings: dict,
    ):
        key = (message.guild.id, message.author.id)
        now = discord.utils.utcnow()
        cooldown_until = self.alert_cooldowns.get(key)
        if cooldown_until and cooldown_until > now:
            return

        self.alert_cooldowns[key] = now + timedelta(minutes=3)
        incident_id = await add_sentinel_incident(
            message.guild.id,
            message.author.id,
            message.channel.id,
            score,
            json.dumps(reasons, ensure_ascii=True),
        )

        embed = await make_embed(
            self.bot,
            guild=message.guild,
            title=f"Sentinel Incident #{incident_id}",
            description=(
                f"Risk score: **{score}/100**\n"
                f"Member: {message.author.mention}\n"
                f"Channel: {message.channel.mention}"
            ),
            color=COLOR_WARN,
        )
        embed.add_field(
            name="Why it fired",
            value=short_reason_list(reasons),
            inline=False,
        )

        recent = self.recent_messages(message.guild.id, message.author.id, 20)
        if recent:
            channels = sorted({entry["channel_id"] for entry in recent})
            embed.add_field(
                name="Live pattern",
                value=(
                    f"{len(recent)} message(s) in the last 20 seconds across "
                    f"{len(channels)} channel(s)."
                ),
                inline=False,
            )

        timeout_seconds = int(settings.get("auto_timeout_seconds") or 0)
        if timeout_seconds > 0:
            try:
                until = now + timedelta(seconds=timeout_seconds)
                await message.author.timeout(
                    until,
                    reason=f"Sentinel incident #{incident_id}",
                )
                embed.add_field(
                    name="Auto Action",
                    value=f"Timed out for {timeout_seconds // 60 or 1} minute(s).",
                    inline=False,
                )
            except (discord.Forbidden, discord.HTTPException):
                embed.add_field(
                    name="Auto Action",
                    value="Timeout failed because my role or permissions are too low.",
                    inline=False,
                )

        await self.send_sentinel_log(
            message.guild,
            embed,
            settings.get("log_channel_id"),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        settings = await get_sentinel_settings(member.guild.id)
        if not settings.get("enabled"):
            return

        now = discord.utils.utcnow()
        account_age_hours = (now - member.created_at).total_seconds() / 3600
        self.join_windows[member.guild.id].append(
            {
                "user_id": member.id,
                "created_at": now,
                "account_age_hours": account_age_hours,
            }
        )

        recent = self.recent_joins(member.guild.id, 90)
        very_new = sum(1 for entry in recent if entry["account_age_hours"] < 24)
        score = 0
        reasons = []

        if len(recent) >= 6:
            score += min(45, len(recent) * 6)
            reasons.append(f"{len(recent)} members joined in 90 seconds")

        if very_new >= 3:
            score += min(35, very_new * 8)
            reasons.append(f"{very_new} joins are accounts under 24 hours old")

        if account_age_hours < 2:
            score += 15
            reasons.append("new join is a very fresh Discord account")

        score = clamp(score, 0, 100)
        if score < int(settings.get("alert_threshold") or 70):
            return

        cooldown_until = self.join_alert_cooldowns.get(member.guild.id)
        if cooldown_until and cooldown_until > now:
            return
        self.join_alert_cooldowns[member.guild.id] = now + timedelta(minutes=3)

        incident_id = await add_sentinel_incident(
            member.guild.id,
            member.id,
            None,
            score,
            json.dumps(reasons, ensure_ascii=True),
        )
        embed = await make_embed(
            self.bot,
            guild=member.guild,
            title=f"Sentinel Raid Watch #{incident_id}",
            description=f"Risk score: **{score}/100**\nNewest join: {member.mention}",
            color=COLOR_WARN,
        )
        embed.add_field(
            name="Why it fired",
            value=short_reason_list(reasons),
            inline=False,
        )
        embed.add_field(
            name="Recommended move",
            value=f"Use `{PREFIX}lock` on busy public channels if the wave continues.",
            inline=False,
        )
        await self.send_sentinel_log(
            member.guild, embed, settings.get("log_channel_id")
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        settings = await get_sentinel_settings(message.guild.id)
        if not settings.get("enabled"):
            return

        self.message_windows[(message.guild.id, message.author.id)].append(
            {
                "channel_id": message.channel.id,
                "created_at": discord.utils.utcnow(),
                "normalized": normalize_message(message.content),
                "has_link": bool(LINK_PATTERN.search(message.content)),
                "mention_count": len(message.mentions) + len(message.role_mentions),
            }
        )

        score, reasons = self.score_message(message)
        if score >= int(settings.get("alert_threshold") or 70):
            await self.create_message_incident(message, score, reasons, settings)

    @commands.group(
        name="sentinel",
        invoke_without_command=True,
        help="Show or configure the live raid/spam intelligence panel.",
    )
    @commands.has_permissions(manage_guild=True)
    async def sentinel(self, ctx):
        """Usage: ,sentinel"""
        settings = await get_sentinel_settings(ctx.guild.id)
        log_channel = (
            ctx.guild.get_channel(settings.get("log_channel_id"))
            if settings.get("log_channel_id")
            else None
        )
        recent_joins = self.recent_joins(ctx.guild.id, 90)
        watched_users = sum(
            1 for guild_id, _ in self.message_windows if guild_id == ctx.guild.id
        )

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Sentinel Live Radar",
            description=(
                "Explainable local detection for raids, spam bursts, repeated messages, "
                "link floods, and mention storms."
            ),
            color=COLOR_INFO,
        )
        embed.add_field(
            name="Status",
            value="Enabled" if settings.get("enabled") else "Disabled",
            inline=True,
        )
        embed.add_field(
            name="Alert Threshold",
            value=f"{settings.get('alert_threshold', 70)}/100",
            inline=True,
        )
        embed.add_field(
            name="Auto Timeout",
            value=(
                f"{settings['auto_timeout_seconds']}s"
                if settings.get("auto_timeout_seconds")
                else "Off"
            ),
            inline=True,
        )
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "Mod log fallback",
            inline=False,
        )
        embed.add_field(
            name="Live Window",
            value=(
                f"{len(recent_joins)} recent join(s) tracked\n"
                f"{watched_users} member message pattern(s) in memory"
            ),
            inline=False,
        )
        embed.add_field(
            name="Commands",
            value=(
                f"`{PREFIX}sentinel on/off`\n"
                f"`{PREFIX}sentinel threshold <40-95>`\n"
                f"`{PREFIX}sentinel log #channel`\n"
                f"`{PREFIX}sentinel autotimeout <seconds|off>`\n"
                f"`{PREFIX}sentinelprofile @user`\n"
                f"`{PREFIX}sentinelincidents [limit]`"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @sentinel.command(name="on", help="Enable Sentinel detection.")
    @commands.has_permissions(manage_guild=True)
    async def sentinel_on(self, ctx):
        await upsert_sentinel_settings(ctx.guild.id, enabled=1)
        await ctx.send(
            embed=discord.Embed(
                description="Sentinel is now enabled.",
                color=COLOR_SUCCESS,
            )
        )

    @sentinel.command(name="off", help="Disable Sentinel detection.")
    @commands.has_permissions(manage_guild=True)
    async def sentinel_off(self, ctx):
        await upsert_sentinel_settings(ctx.guild.id, enabled=0)
        await ctx.send(
            embed=discord.Embed(
                description="Sentinel is now disabled.",
                color=COLOR_SUCCESS,
            )
        )

    @sentinel.command(name="threshold", help="Set the risk score needed for alerts.")
    @commands.has_permissions(manage_guild=True)
    async def sentinel_threshold(self, ctx, score: int):
        """Usage: ,sentinel threshold <40-95>"""
        if score < 40 or score > 95:
            return await ctx.send(
                embed=discord.Embed(
                    description="Choose a threshold between 40 and 95.",
                    color=COLOR_ERROR,
                )
            )

        await upsert_sentinel_settings(ctx.guild.id, alert_threshold=score)
        await ctx.send(
            embed=discord.Embed(
                description=f"Sentinel alerts now trigger at **{score}/100**.",
                color=COLOR_SUCCESS,
            )
        )

    @sentinel.command(name="log", help="Set the Sentinel alert channel.")
    @commands.has_permissions(manage_guild=True)
    async def sentinel_log(self, ctx, channel: discord.TextChannel):
        await upsert_sentinel_settings(ctx.guild.id, log_channel_id=channel.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"Sentinel alerts will go to {channel.mention}.",
                color=COLOR_SUCCESS,
            )
        )

    @sentinel.command(name="autotimeout", help="Automatically timeout high-risk users.")
    @commands.has_permissions(manage_guild=True)
    async def sentinel_autotimeout(self, ctx, value: str):
        """Usage: ,sentinel autotimeout <seconds|off>"""
        if value.lower() in {"off", "0", "disable", "disabled"}:
            await upsert_sentinel_settings(ctx.guild.id, auto_timeout_seconds=0)
            return await ctx.send(
                embed=discord.Embed(
                    description="Sentinel auto-timeout is now off.",
                    color=COLOR_SUCCESS,
                )
            )

        if not value.isdigit():
            return await ctx.send(
                embed=discord.Embed(
                    description="Use a number of seconds, or `off`.",
                    color=COLOR_ERROR,
                )
            )

        seconds = int(value)
        if seconds < 10 or seconds > 3600:
            return await ctx.send(
                embed=discord.Embed(
                    description="Auto-timeout must be between 10 and 3600 seconds.",
                    color=COLOR_ERROR,
                )
            )

        await upsert_sentinel_settings(ctx.guild.id, auto_timeout_seconds=seconds)
        await ctx.send(
            embed=discord.Embed(
                description=f"Sentinel will timeout high-risk users for **{seconds} seconds**.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="sentinelprofile",
        aliases=["threatprofile"],
        help="Show a member's live Sentinel behaviour profile.",
    )
    @commands.has_permissions(kick_members=True)
    async def sentinel_profile(self, ctx, member: discord.Member):
        """Usage: ,sentinelprofile @user"""
        recent_60 = self.recent_messages(ctx.guild.id, member.id, 60)
        recent_300 = self.recent_messages(ctx.guild.id, member.id, 300)
        links = sum(1 for entry in recent_300 if entry["has_link"])
        mentions = sum(entry["mention_count"] for entry in recent_300)
        channels = sorted({entry["channel_id"] for entry in recent_300})

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Sentinel Profile - {member.display_name}",
            color=COLOR_INFO,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Last 60s",
            value=f"{len(recent_60)} message(s)",
            inline=True,
        )
        embed.add_field(
            name="Last 5m",
            value=f"{len(recent_300)} message(s)",
            inline=True,
        )
        embed.add_field(name="Links", value=str(links), inline=True)
        embed.add_field(name="Mentions", value=str(mentions), inline=True)
        embed.add_field(name="Channels", value=str(len(channels)), inline=True)
        embed.add_field(
            name="Account Created",
            value=f"<t:{int(member.created_at.timestamp())}:R>",
            inline=True,
        )

        if recent_300:
            repeated = defaultdict(int)
            for entry in recent_300:
                if entry["normalized"]:
                    repeated[entry["normalized"]] += 1
            max_repeat = max(repeated.values(), default=0)
            embed.add_field(
                name="Repeat Signal",
                value=f"Highest repeated normalized message: {max_repeat}x",
                inline=False,
            )
        else:
            embed.description = (
                "No live behaviour has been observed for this member yet."
            )

        await ctx.send(embed=embed)

    @commands.command(
        name="sentinelincidents",
        aliases=["incidents"],
        help="Show recent Sentinel incidents.",
    )
    @commands.has_permissions(kick_members=True)
    async def sentinel_incidents(self, ctx, limit: int = 8):
        """Usage: ,sentinelincidents [limit]"""
        limit = clamp(limit, 1, 20)
        incidents = await get_recent_sentinel_incidents(ctx.guild.id, limit)

        if not incidents:
            return await ctx.send(
                embed=discord.Embed(
                    description="No Sentinel incidents have been recorded yet.",
                    color=COLOR_SUCCESS,
                )
            )

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Recent Sentinel Incidents",
            color=COLOR_INFO,
        )
        for incident in incidents:
            member = (
                ctx.guild.get_member(incident["user_id"])
                if incident["user_id"]
                else None
            )
            channel = (
                ctx.guild.get_channel(incident["channel_id"])
                if incident["channel_id"]
                else None
            )
            try:
                reasons = json.loads(incident["reasons"])
            except json.JSONDecodeError:
                reasons = [incident["reasons"]]
            timestamp = int(datetime.fromisoformat(incident["created_at"]).timestamp())
            embed.add_field(
                name=f"#{incident['id']} - {incident['score']}/100",
                value=(
                    f"Member: {member.mention if member else incident['user_id'] or 'Join wave'}\n"
                    f"Channel: {channel.mention if channel else 'N/A'}\n"
                    f"When: <t:{timestamp}:R>\n"
                    f"Signal: {reasons[0] if reasons else 'No reason stored'}"
                ),
                inline=False,
            )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Sentinel(bot))
