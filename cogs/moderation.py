"""
cogs/moderation.py - moderation commands and warn escalation rules.
"""

import asyncio
import re
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks

from config import COLOR_ERROR, COLOR_MOD, COLOR_SUCCESS, resolve_mod_log_channel_id
from utils.db import (
    add_case,
    add_temp_ban,
    clear_recent_warns,
    get_expired_temp_bans,
    get_escalation_rules,
    get_guild_settings,
    get_matching_escalation_rule,
    get_recent_warns,
    get_temp_bans_for_guild,
    get_warn_count,
    remove_temp_ban,
    remove_escalation_rule,
    upsert_escalation_rule,
)


LINK_PATTERN = re.compile(
    r"(https?://\S+|discord(?:app)?\.com/invite/\S+|discord\.gg/\S+)",
    re.IGNORECASE,
)


def parse_duration(duration_str: str) -> int | None:
    """Convert strings like 10m, 1h30m, or 2 days into seconds."""
    if not duration_str:
        return None

    normalized = duration_str.strip().lower()
    units = {
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
    }
    pattern = re.compile(
        r"(?P<amount>\d+)\s*(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)"
    )

    total = 0
    position = 0
    for match in pattern.finditer(normalized):
        between = normalized[position : match.start()]
        if between.strip():
            return None

        total += int(match.group("amount")) * units[match.group("unit")]
        position = match.end()

    if normalized[position:].strip() or total <= 0:
        return None

    return total


class Moderation(commands.Cog, name="Moderation"):
    """Commands for keeping the server in order."""

    def __init__(self, bot):
        self.bot = bot
        self.tempban_loop.start()

    def cog_unload(self):
        self.tempban_loop.cancel()

    async def can_moderate(
        self,
        ctx: commands.Context,
        target: discord.Member,
        action: str,
    ) -> discord.Embed | None:
        """Validate common moderation edge cases before taking action."""
        if target == ctx.author:
            return discord.Embed(
                description=f"You can't {action} yourself.",
                color=COLOR_ERROR,
            )

        if target == ctx.guild.owner:
            return discord.Embed(
                description=f"You can't {action} the server owner.",
                color=COLOR_ERROR,
            )

        if target.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return discord.Embed(
                description=f"You can't {action} someone with an equal or higher role.",
                color=COLOR_ERROR,
            )

        me = ctx.guild.me
        if me and target.top_role >= me.top_role:
            return discord.Embed(
                description=(
                    f"I can't {action} that user because their top role is equal to "
                    "or higher than mine."
                ),
                color=COLOR_ERROR,
            )

        return None

    async def apply_escalation(
        self,
        ctx: commands.Context,
        target: discord.Member,
        warn_count: int,
    ) -> discord.Embed | None:
        rule = await get_matching_escalation_rule(ctx.guild.id, warn_count)
        if not rule or target == ctx.author:
            return None

        blocked = await self.can_moderate(ctx, target, rule["action"])
        if blocked:
            blocked.description = f"Escalation matched at **{warn_count}** warns, but {blocked.description}"
            return blocked

        action = rule["action"]
        duration = rule.get("duration")
        reason = f"Automatic escalation after {warn_count} warnings."

        if action == "timeout":
            seconds = parse_duration(duration or "")
            if seconds is None or seconds > 2419200:
                return discord.Embed(
                    description=(
                        f"Escalation matched at **{warn_count}** warns, but the timeout "
                        "duration is invalid."
                    ),
                    color=COLOR_ERROR,
                )

            until = discord.utils.utcnow() + timedelta(seconds=seconds)
            await target.timeout(until, reason=reason)
            case_id = await add_case(
                ctx.guild.id,
                target.id,
                ctx.author.id,
                "timeout",
                reason,
                duration,
            )
            await self.send_action_dm(
                target,
                guild_name=ctx.guild.name,
                action_text="automatically timed out",
                reason=reason,
                duration=duration,
            )
            return self.mod_embed(
                "Auto Timeout",
                target,
                ctx.author,
                reason,
                case_id,
                duration,
            )

        if action == "kick":
            await self.send_action_dm(
                target,
                guild_name=ctx.guild.name,
                action_text="automatically kicked",
                reason=reason,
            )
            await target.kick(reason=f"{reason} | Mod: {ctx.author}")
            case_id = await add_case(
                ctx.guild.id, target.id, ctx.author.id, "kick", reason
            )
            return self.mod_embed("Auto Kick", target, ctx.author, reason, case_id)

        if action == "ban":
            await self.send_action_dm(
                target,
                guild_name=ctx.guild.name,
                action_text="automatically banned",
                reason=reason,
            )
            await target.ban(reason=f"{reason} | Mod: {ctx.author}")
            case_id = await add_case(
                ctx.guild.id, target.id, ctx.author.id, "ban", reason
            )
            return self.mod_embed("Auto Ban", target, ctx.author, reason, case_id)

        return None

    async def send_mod_log(self, guild: discord.Guild, embed: discord.Embed):
        """Post an embed to the mod log channel if one is configured."""
        settings = await get_guild_settings(guild.id) or {}
        channel_id = resolve_mod_log_channel_id(settings)
        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(embed=embed)

    async def try_dm(self, user: discord.abc.User, embed: discord.Embed):
        """Try to DM the user and ignore closed DMs."""
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

    async def send_action_dm(
        self,
        user: discord.abc.User,
        *,
        guild_name: str,
        action_text: str,
        reason: str | None = None,
        duration: str | None = None,
    ):
        """Send a consistent moderation DM for actions that affect a user."""
        description = f"You were {action_text} in **{guild_name}**."
        if duration:
            description = (
                f"You were {action_text} in **{guild_name}** for `{duration}`."
            )

        await self.try_dm(
            user,
            discord.Embed(
                description=f"{description}\n**Reason:** {reason or 'No reason given'}",
                color=COLOR_MOD,
            ),
        )

    def mod_embed(
        self,
        action: str,
        target: discord.abc.User,
        mod: discord.abc.User,
        reason: str | None,
        case_id: int,
        duration: str | None = None,
    ) -> discord.Embed:
        """Build a consistent embed for every moderation action."""
        embed = discord.Embed(
            title=action,
            color=COLOR_MOD,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="User", value=f"{target} (`{target.id}`)", inline=True)
        embed.add_field(name="Moderator", value=f"{mod} (`{mod.id}`)", inline=True)
        if duration:
            embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Reason", value=reason or "No reason given", inline=False)
        embed.set_footer(text=f"Case #{case_id}")
        return embed

    @tasks.loop(minutes=1)
    async def tempban_loop(self):
        expired_bans = await get_expired_temp_bans(discord.utils.utcnow().isoformat())
        for entry in expired_bans:
            guild = self.bot.get_guild(entry["guild_id"])
            if guild is None:
                await remove_temp_ban(entry["guild_id"], entry["user_id"])
                continue

            try:
                user = await self.bot.fetch_user(entry["user_id"])
                await guild.unban(user, reason="Temporary ban expired.")
                case_id = await add_case(
                    guild.id,
                    user.id,
                    self.bot.user.id,
                    "unban",
                    "Temporary ban expired.",
                )
                embed = self.mod_embed(
                    "Tempban Expired",
                    user,
                    self.bot.user,
                    "Temporary ban expired.",
                    case_id,
                )
                await self.send_mod_log(guild, embed)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                continue
            finally:
                await remove_temp_ban(entry["guild_id"], entry["user_id"])

    @tempban_loop.before_loop
    async def before_tempban_loop(self):
        await self.bot.wait_until_ready()

    @commands.command(name="ban", help="Ban a user from the server.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, target: discord.Member, *, reason: str = None):
        """Usage: ,ban @user [reason]"""
        blocked = await self.can_moderate(ctx, target, "ban")
        if blocked:
            return await ctx.send(embed=blocked)

        await self.send_action_dm(
            target,
            guild_name=ctx.guild.name,
            action_text="banned",
            reason=reason,
        )
        await target.ban(reason=f"{reason or 'No reason given'} | Mod: {ctx.author}")
        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "ban", reason)
        embed = self.mod_embed("Ban", target, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(
        name="tempban",
        help="Ban a user for a limited duration and unban them automatically.",
    )
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def tempban(
        self,
        ctx,
        target: discord.Member,
        duration: str,
        *,
        reason: str = None,
    ):
        """Usage: ,tempban @user <duration> [reason]"""
        seconds = parse_duration(duration)
        if seconds is None:
            return await ctx.send(
                embed=discord.Embed(
                    description="Bad duration format. Use something like `30m`, `1h30m`, `12 hours`, or `7d`.",
                    color=COLOR_ERROR,
                )
            )

        blocked = await self.can_moderate(ctx, target, "tempban")
        if blocked:
            return await ctx.send(embed=blocked)

        expires_at = discord.utils.utcnow() + timedelta(seconds=seconds)
        await self.send_action_dm(
            target,
            guild_name=ctx.guild.name,
            action_text="temporarily banned",
            reason=reason,
            duration=duration,
        )
        await target.ban(
            reason=f"{reason or 'No reason given'} | Tempban by {ctx.author}"
        )
        await add_temp_ban(
            ctx.guild.id,
            target.id,
            ctx.author.id,
            expires_at.isoformat(),
            reason,
        )
        case_id = await add_case(
            ctx.guild.id,
            target.id,
            ctx.author.id,
            "tempban",
            reason,
            duration,
        )
        embed = self.mod_embed("Tempban", target, ctx.author, reason, case_id, duration)
        embed.add_field(
            name="Expires",
            value=f"<t:{int(expires_at.timestamp())}:F>",
            inline=False,
        )
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(name="unban", help="Unban a user by their ID.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int, *, reason: str = None):
        """Usage: ,unban <user_id> [reason]"""
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            return await ctx.send(
                embed=discord.Embed(description="User not found.", color=COLOR_ERROR)
            )

        try:
            await ctx.guild.unban(user, reason=reason)
        except discord.NotFound:
            return await ctx.send(
                embed=discord.Embed(
                    description="That user is not banned.",
                    color=COLOR_ERROR,
                )
            )

        await self.send_action_dm(
            user,
            guild_name=ctx.guild.name,
            action_text="unbanned",
            reason=reason,
        )
        case_id = await add_case(ctx.guild.id, user.id, ctx.author.id, "unban", reason)
        embed = self.mod_embed("Unban", user, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(name="kick", help="Kick a user from the server.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, target: discord.Member, *, reason: str = None):
        """Usage: ,kick @user [reason]"""
        blocked = await self.can_moderate(ctx, target, "kick")
        if blocked:
            return await ctx.send(embed=blocked)

        await self.send_action_dm(
            target,
            guild_name=ctx.guild.name,
            action_text="kicked",
            reason=reason,
        )
        await target.kick(reason=f"{reason or 'No reason given'} | Mod: {ctx.author}")
        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "kick", reason)
        embed = self.mod_embed("Kick", target, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(
        name="softban",
        aliases=["sb"],
        help="Ban then immediately unban a user to clear recent messages.",
    )
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(self, ctx, target: discord.Member, *, details: str = None):
        """Usage: ,softban @user [delete_days] [reason]"""
        delete_days = 1
        reason = details
        if details:
            first_word, _, remainder = details.partition(" ")
            if first_word.isdigit():
                delete_days = int(first_word)
                reason = remainder.strip() or None

        if delete_days < 0 or delete_days > 7:
            return await ctx.send(
                embed=discord.Embed(
                    description="Delete days must be between 0 and 7.",
                    color=COLOR_ERROR,
                )
            )

        blocked = await self.can_moderate(ctx, target, "softban")
        if blocked:
            return await ctx.send(embed=blocked)

        await self.send_action_dm(
            target,
            guild_name=ctx.guild.name,
            action_text="softbanned",
            reason=reason,
        )
        audit_reason = f"{reason or 'No reason given'} | Softban by {ctx.author}"
        await target.ban(
            reason=audit_reason,
            delete_message_seconds=delete_days * 86400,
        )
        await ctx.guild.unban(target, reason=f"Softban complete | Mod: {ctx.author}")
        case_id = await add_case(
            ctx.guild.id,
            target.id,
            ctx.author.id,
            "softban",
            reason,
            f"{delete_days} day(s)",
        )
        embed = self.mod_embed(
            "Softban",
            target,
            ctx.author,
            reason,
            case_id,
            f"{delete_days} day(s) deleted",
        )
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(name="warn", help="Issue a warning to a user.")
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx, target: discord.Member, *, reason: str = None):
        """Usage: ,warn @user [reason]"""
        blocked = await self.can_moderate(ctx, target, "warn")
        if blocked:
            return await ctx.send(embed=blocked)

        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "warn", reason)
        await self.send_action_dm(
            target,
            guild_name=ctx.guild.name,
            action_text="warned",
            reason=reason,
        )
        embed = self.mod_embed("Warn", target, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

        warn_count = await get_warn_count(ctx.guild.id, target.id)
        escalation_embed = await self.apply_escalation(ctx, target, warn_count)
        if escalation_embed:
            await ctx.send(embed=escalation_embed)
            await self.send_mod_log(ctx.guild, escalation_embed)

    @commands.command(
        name="note",
        aliases=["modnote"],
        help="Add a private moderation note to a user's case history.",
    )
    @commands.has_permissions(kick_members=True)
    async def note(self, ctx, target: discord.Member | discord.User, *, note: str):
        """Usage: ,note @user <note>"""
        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "note", note)
        embed = discord.Embed(
            title="Moderation Note Added",
            color=COLOR_MOD,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="User", value=f"{target} (`{target.id}`)", inline=True)
        embed.add_field(
            name="Moderator",
            value=f"{ctx.author} (`{ctx.author.id}`)",
            inline=True,
        )
        embed.add_field(name="Note", value=note, inline=False)
        embed.set_footer(text=f"Case #{case_id}")
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(
        name="warnings",
        aliases=["warns"],
        help="Show a user's current warning count.",
    )
    @commands.has_permissions(kick_members=True)
    async def warnings(self, ctx, target: discord.Member | discord.User):
        """Usage: ,warnings @user"""
        warn_count = await get_warn_count(ctx.guild.id, target.id)
        recent_warns = await get_recent_warns(ctx.guild.id, target.id, limit=5)

        embed = discord.Embed(
            title=f"Warnings - {target}",
            description=f"Current warnings: **{warn_count}**",
            color=COLOR_MOD,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        if recent_warns:
            lines = []
            for warn in recent_warns:
                timestamp = int(datetime.fromisoformat(warn["created_at"]).timestamp())
                reason = warn["reason"] or "No reason given"
                if len(reason) > 90:
                    reason = f"{reason[:87]}..."
                lines.append(f"`#{warn['id']}` <t:{timestamp}:d> - {reason}")
            embed.add_field(
                name="Recent warnings", value="\n".join(lines), inline=False
            )
        else:
            embed.add_field(
                name="Recent warnings",
                value="No active warnings on record.",
                inline=False,
            )

        await ctx.send(embed=embed)

    @commands.command(
        name="clearwarns",
        aliases=["unwarn", "removewarns"],
        help="Remove one or more recent warnings from a user.",
    )
    @commands.has_permissions(kick_members=True)
    async def clearwarns(
        self,
        ctx,
        target: discord.Member | discord.User,
        *,
        details: str = None,
    ):
        """Usage: ,clearwarns @user [amount] [reason]"""
        amount = 1
        reason = None
        if details:
            first_word, _, remainder = details.partition(" ")
            if first_word.isdigit():
                amount = int(first_word)
                reason = remainder.strip() or None
            else:
                reason = details

        if amount < 1:
            return await ctx.send(
                embed=discord.Embed(
                    description="Amount must be at least 1.",
                    color=COLOR_ERROR,
                )
            )

        removed_case_ids = await clear_recent_warns(ctx.guild.id, target.id, amount)
        if not removed_case_ids:
            return await ctx.send(
                embed=discord.Embed(
                    description=f"{target} has no warnings to remove.",
                    color=COLOR_ERROR,
                )
            )

        log_reason = reason or f"Removed {len(removed_case_ids)} warning(s)."
        case_id = await add_case(
            ctx.guild.id,
            target.id,
            ctx.author.id,
            "clearwarns",
            log_reason,
            str(len(removed_case_ids)),
        )
        remaining_warns = await get_warn_count(ctx.guild.id, target.id)

        embed = discord.Embed(
            title="Warnings Cleared",
            description=(
                f"Removed **{len(removed_case_ids)}** warning(s) from {target}.\n"
                f"Remaining warnings: **{remaining_warns}**"
            ),
            color=COLOR_SUCCESS,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(
            name="Moderator",
            value=f"{ctx.author} (`{ctx.author.id}`)",
            inline=True,
        )
        embed.add_field(
            name="Removed cases",
            value=", ".join(f"`#{warn_id}`" for warn_id in removed_case_ids),
            inline=True,
        )
        embed.add_field(name="Reason", value=log_reason, inline=False)
        embed.set_footer(text=f"Case #{case_id}")

        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(
        name="timeout",
        aliases=["mute"],
        help="Timeout a user for a given duration.",
    )
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout_user(
        self,
        ctx,
        target: discord.Member,
        duration: str = "10m",
        *,
        reason: str = None,
    ):
        """Usage: ,timeout @user [duration] [reason]"""
        seconds = parse_duration(duration)
        if seconds is None:
            return await ctx.send(
                embed=discord.Embed(
                    description="Bad duration format. Use something like `10m`, `1h30m`, `2 hours`, or `1d`.",
                    color=COLOR_ERROR,
                )
            )
        if seconds > 2419200:
            return await ctx.send(
                embed=discord.Embed(
                    description="Discord limits timeouts to 28 days max.",
                    color=COLOR_ERROR,
                )
            )

        blocked = await self.can_moderate(ctx, target, "timeout")
        if blocked:
            return await ctx.send(embed=blocked)

        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await target.timeout(until, reason=reason)
        case_id = await add_case(
            ctx.guild.id,
            target.id,
            ctx.author.id,
            "timeout",
            reason,
            duration,
        )
        await self.send_action_dm(
            target,
            guild_name=ctx.guild.name,
            action_text="timed out",
            reason=reason,
            duration=duration,
        )
        embed = self.mod_embed("Timeout", target, ctx.author, reason, case_id, duration)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(
        name="untimeout",
        aliases=["unmute"],
        help="Remove a timeout from a user.",
    )
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout_user(self, ctx, target: discord.Member, *, reason: str = None):
        """Usage: ,untimeout @user [reason]"""
        blocked = await self.can_moderate(ctx, target, "remove the timeout from")
        if blocked:
            return await ctx.send(embed=blocked)

        await target.timeout(None, reason=reason)
        await self.send_action_dm(
            target,
            guild_name=ctx.guild.name,
            action_text="removed from timeout",
            reason=reason,
        )
        case_id = await add_case(
            ctx.guild.id, target.id, ctx.author.id, "untimeout", reason
        )
        embed = self.mod_embed("Untimeout", target, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(
        name="purge",
        aliases=["clear"],
        help="Bulk delete messages from the current channel.",
    )
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int):
        """Usage: ,purge <amount>"""
        if amount < 1 or amount > 500:
            return await ctx.send(
                embed=discord.Embed(
                    description="Amount must be between 1 and 500.",
                    color=COLOR_ERROR,
                )
            )

        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(
            embed=discord.Embed(
                description=f"Deleted **{len(deleted) - 1}** messages.",
                color=COLOR_SUCCESS,
            )
        )
        await asyncio.sleep(3)
        await msg.delete()

    @commands.command(
        name="clean",
        aliases=["purgeuser", "clearuser"],
        help="Delete recent messages, optionally only from one user.",
    )
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clean(
        self,
        ctx,
        amount: int,
        target: discord.Member | discord.User = None,
    ):
        """Usage: ,clean <amount> [@user]"""
        if amount < 1 or amount > 500:
            return await ctx.send(
                embed=discord.Embed(
                    description="Amount must be between 1 and 500.",
                    color=COLOR_ERROR,
                )
            )

        def check(message: discord.Message) -> bool:
            if message.id == ctx.message.id:
                return True
            if target is None:
                return True
            return message.author.id == target.id

        deleted = await ctx.channel.purge(limit=amount + 1, check=check)
        removed = max(0, len(deleted) - 1)
        scope = f" from {target.mention}" if target else ""
        msg = await ctx.send(
            embed=discord.Embed(
                description=f"Deleted **{removed}** messages{scope}.",
                color=COLOR_SUCCESS,
            )
        )
        await asyncio.sleep(3)
        await msg.delete()

    @commands.command(
        name="purgelinks",
        aliases=["clearlinks", "linkpurge"],
        help="Delete recent messages that contain links or Discord invites.",
    )
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purgelinks(self, ctx, amount: int = 100):
        """Usage: ,purgelinks [amount]"""
        if amount < 1 or amount > 1000:
            return await ctx.send(
                embed=discord.Embed(
                    description="Amount must be between 1 and 1000.",
                    color=COLOR_ERROR,
                )
            )

        deleted = await ctx.channel.purge(
            limit=amount + 1,
            check=lambda message: message.id == ctx.message.id
            or bool(LINK_PATTERN.search(message.content)),
        )
        removed = max(0, len(deleted) - 1)
        msg = await ctx.send(
            embed=discord.Embed(
                description=(
                    f"Deleted **{removed}** recent message(s) containing links or invites."
                ),
                color=COLOR_SUCCESS,
            )
        )
        await asyncio.sleep(3)
        await msg.delete()

    @commands.command(
        name="purgebots",
        aliases=["clearbots", "botpurge"],
        help="Delete recent messages sent by bots in the current channel.",
    )
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purgebots(self, ctx, amount: int = 100):
        """Usage: ,purgebots [amount]"""
        if amount < 1 or amount > 1000:
            return await ctx.send(
                embed=discord.Embed(
                    description="Amount must be between 1 and 1000.",
                    color=COLOR_ERROR,
                )
            )

        deleted = await ctx.channel.purge(
            limit=amount + 1,
            check=lambda message: message.id == ctx.message.id or message.author.bot,
        )
        removed = max(0, len(deleted) - 1)
        msg = await ctx.send(
            embed=discord.Embed(
                description=f"Deleted **{removed}** recent bot message(s).",
                color=COLOR_SUCCESS,
            )
        )
        await asyncio.sleep(3)
        await msg.delete()

    @commands.command(name="slowmode", help="Set slowmode on the current channel.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int = 0):
        """Usage: ,slowmode [seconds]"""
        if seconds < 0 or seconds > 21600:
            return await ctx.send(
                embed=discord.Embed(
                    description="Value must be between 0 and 21600 seconds.",
                    color=COLOR_ERROR,
                )
            )

        await ctx.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            description = f"Slowmode disabled in {ctx.channel.mention}."
        else:
            description = f"Slowmode set to **{seconds}s** in {ctx.channel.mention}."
        await ctx.send(
            embed=discord.Embed(description=description, color=COLOR_SUCCESS)
        )

    @commands.command(
        name="setescalation",
        help="Set an automatic punishment for a warn threshold.",
    )
    @commands.has_permissions(manage_guild=True)
    async def set_escalation(
        self,
        ctx,
        warn_count: int,
        action: str,
        duration: str = None,
    ):
        """Usage: ,setescalation <warn_count> <timeout|kick|ban> [duration]"""
        action = action.lower()
        if warn_count < 1:
            return await ctx.send(
                embed=discord.Embed(
                    description="Warn count must be at least 1.",
                    color=COLOR_ERROR,
                )
            )

        if action not in {"timeout", "kick", "ban"}:
            return await ctx.send(
                embed=discord.Embed(
                    description="Action must be `timeout`, `kick`, or `ban`.",
                    color=COLOR_ERROR,
                )
            )

        if action == "timeout":
            seconds = parse_duration(duration or "")
            if seconds is None or seconds > 2419200:
                return await ctx.send(
                    embed=discord.Embed(
                        description=(
                            "Timeout rules need a valid duration like `30m`, `1h30m`, `2h`, or `1d`."
                        ),
                        color=COLOR_ERROR,
                    )
                )
        else:
            duration = None

        await upsert_escalation_rule(ctx.guild.id, warn_count, action, duration)
        action_text = f"{action} (`{duration}`)" if duration else action
        await ctx.send(
            embed=discord.Embed(
                description=(
                    f"Escalation set: **{warn_count}** warns -> **{action_text}**"
                ),
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="removeescalation",
        help="Remove an automatic punishment for a warn threshold.",
    )
    @commands.has_permissions(manage_guild=True)
    async def remove_escalation(self, ctx, warn_count: int):
        await remove_escalation_rule(ctx.guild.id, warn_count)
        await ctx.send(
            embed=discord.Embed(
                description=f"Removed the escalation rule for **{warn_count}** warns.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="escalations",
        aliases=["listescalations"],
        help="Show all configured warn escalation rules.",
    )
    @commands.has_permissions(manage_guild=True)
    async def list_escalations(self, ctx):
        rules = await get_escalation_rules(ctx.guild.id)
        if not rules:
            return await ctx.send(
                embed=discord.Embed(
                    description="No punishment escalation rules are configured yet.",
                    color=COLOR_SUCCESS,
                )
            )

        embed = discord.Embed(title="Punishment Escalation Rules", color=COLOR_MOD)
        for rule in rules:
            action_text = rule["action"].title()
            if rule.get("duration"):
                action_text += f" ({rule['duration']})"
            embed.add_field(
                name=f"{rule['warn_count']} Warns",
                value=action_text,
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.command(
        name="tempbans",
        help="Show currently active temporary bans.",
    )
    @commands.has_permissions(ban_members=True)
    async def tempbans(self, ctx):
        entries = await get_temp_bans_for_guild(ctx.guild.id)
        if not entries:
            return await ctx.send(
                embed=discord.Embed(
                    description="There are no active temporary bans.",
                    color=COLOR_SUCCESS,
                )
            )

        embed = discord.Embed(title="Active Temporary Bans", color=COLOR_MOD)
        for entry in entries[:15]:
            user = self.bot.get_user(entry["user_id"]) or f"User ID {entry['user_id']}"
            embed.add_field(
                name=str(user),
                value=(
                    f"Expires: <t:{int(datetime.fromisoformat(entry['expires_at']).timestamp())}:R>\n"
                    f"Reason: {entry['reason'] or 'No reason given'}"
                ),
                inline=False,
            )

        if len(entries) > 15:
            embed.set_footer(text=f"Showing 15 of {len(entries)} temp bans")

        await ctx.send(embed=embed)


async def setup(bot):
    """Required for discord.py to load the cog."""
    await bot.add_cog(Moderation(bot))
