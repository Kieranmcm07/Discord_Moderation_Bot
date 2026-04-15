"""
cogs/moderation.py — all the moderation commands.
Ban, kick, mute, warn, unban, timeout. Each action logs a case automatically
so nothing gets lost. I also send a DM to the user when possible so they
know what happened and why.
"""

import discord
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta
from utils.db import (
    add_case,
    clear_recent_warns,
    get_escalation_rules,
    get_matching_escalation_rule,
    get_recent_warns,
    get_warn_count,
    init_db,
    remove_escalation_rule,
    upsert_escalation_rule,
)
from config import MOD_LOG_CHANNEL_ID, COLOR_MOD, COLOR_ERROR, COLOR_SUCCESS


def parse_duration(duration_str: str) -> int | None:
    """
    Convert strings like '10m', '2h', '1d' into seconds.
    Returns None if the format doesn't match — I treat that as permanent.
    """
    if not duration_str:
        return None
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = duration_str[-1].lower()
    if unit not in units:
        return None
    try:
        return int(duration_str[:-1]) * units[unit]
    except ValueError:
        return None


class Moderation(commands.Cog, name="Moderation"):
    """Commands for keeping the server in order."""

    def __init__(self, bot):
        self.bot = bot

    async def apply_escalation(self, ctx, target: discord.Member, warn_count: int):
        rule = await get_matching_escalation_rule(ctx.guild.id, warn_count)
        if not rule:
            return None

        if target == ctx.author:
            return None

        if target.top_role >= ctx.author.top_role:
            return discord.Embed(
                description=(
                    f"⚠️ Escalation matched at **{warn_count}** warns, but the target has an equal or higher role than the moderator."
                ),
                color=COLOR_ERROR,
            )

        if target.top_role >= ctx.guild.me.top_role:
            return discord.Embed(
                description=(
                    f"⚠️ Escalation matched at **{warn_count}** warns, but I can't moderate that user because their role is above mine."
                ),
                color=COLOR_ERROR,
            )

        action = rule["action"]
        duration = rule.get("duration")
        reason = f"Automatic escalation after {warn_count} warnings."

        if action == "timeout":
            seconds = parse_duration(duration or "")
            if seconds is None or seconds > 2419200:
                return discord.Embed(
                    description=f"⚠️ Escalation matched at **{warn_count}** warns, but the timeout duration is invalid.",
                    color=COLOR_ERROR,
                )

            until = discord.utils.utcnow() + timedelta(seconds=seconds)
            await target.timeout(until, reason=reason)
            case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "timeout", reason, duration)
            await self.try_dm(
                target,
                discord.Embed(
                    description=(
                        f"You were automatically **timed out** in **{ctx.guild.name}** for `{duration}`.\n**Reason:** {reason}"
                    ),
                    color=COLOR_MOD,
                ),
            )
            return self.mod_embed("Auto Timeout", target, ctx.author, reason, case_id, duration)

        if action == "kick":
            await self.try_dm(
                target,
                discord.Embed(
                    description=f"You were automatically **kicked** from **{ctx.guild.name}**.\n**Reason:** {reason}",
                    color=COLOR_MOD,
                ),
            )
            case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "kick", reason)
            await target.kick(reason=f"[Case #{case_id}] {reason} | Mod: {ctx.author}")
            return self.mod_embed("Auto Kick", target, ctx.author, reason, case_id)

        if action == "ban":
            await self.try_dm(
                target,
                discord.Embed(
                    description=f"You were automatically **banned** from **{ctx.guild.name}**.\n**Reason:** {reason}",
                    color=COLOR_MOD,
                ),
            )
            case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "ban", reason)
            await target.ban(reason=f"[Case #{case_id}] {reason} | Mod: {ctx.author}")
            return self.mod_embed("Auto Ban", target, ctx.author, reason, case_id)

        return None

    # ── helper to send a message to the mod-log channel ──
    async def send_mod_log(self, guild: discord.Guild, embed: discord.Embed):
        """Post an embed to the mod log channel if one is configured."""
        if not MOD_LOG_CHANNEL_ID:
            return
        ch = guild.get_channel(MOD_LOG_CHANNEL_ID)
        if ch:
            await ch.send(embed=embed)

    # ── helper to DM the target user ──
    async def try_dm(self, user: discord.User, embed: discord.Embed):
        """Try to DM the user — fail silently if they have DMs off."""
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass  # user has DMs locked, nothing I can do

    def mod_embed(self, action: str, target: discord.Member, mod: discord.Member,
                  reason: str, case_id: int, duration: str = None) -> discord.Embed:
        """Build a consistent embed for every mod action."""
        e = discord.Embed(
            title=f"🔨 {action}",
            color=COLOR_MOD,
            timestamp=datetime.utcnow()
        )
        e.add_field(name="User", value=f"{target} (`{target.id}`)", inline=True)
        e.add_field(name="Moderator", value=f"{mod} (`{mod.id}`)", inline=True)
        if duration:
            e.add_field(name="Duration", value=duration, inline=True)
        e.add_field(name="Reason", value=reason or "No reason given", inline=False)
        e.set_footer(text=f"Case #{case_id}")
        return e

    # ─────────────────────────────────────────────
    # ,ban
    # ─────────────────────────────────────────────
    @commands.command(name="ban", help="Ban a user from the server.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, target: discord.Member, *, reason: str = None):
        """
        Usage: ,ban @user [reason]
        Bans the user and logs the case. Tries to DM them first.
        """
        if target == ctx.author:
            return await ctx.send(embed=discord.Embed(description="❌ Can't ban yourself.", color=COLOR_ERROR))
        if target.top_role >= ctx.author.top_role:
            return await ctx.send(embed=discord.Embed(description="❌ You can't ban someone with an equal or higher role.", color=COLOR_ERROR))

        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "ban", reason)

        # try to DM before banning so the message actually reaches them
        dm_embed = discord.Embed(
            description=f"You were **banned** from **{ctx.guild.name}**.\n**Reason:** {reason or 'No reason given'}",
            color=COLOR_MOD
        )
        await self.try_dm(target, dm_embed)

        await target.ban(reason=f"[Case #{case_id}] {reason or 'No reason given'} | Mod: {ctx.author}")
        embed = self.mod_embed("Ban", target, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ─────────────────────────────────────────────
    # ,unban
    # ─────────────────────────────────────────────
    @commands.command(name="unban", help="Unban a user by their ID.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int, *, reason: str = None):
        """
        Usage: ,unban <user_id> [reason]
        Lifts a ban and logs the case.
        """
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            return await ctx.send(embed=discord.Embed(description="❌ User not found.", color=COLOR_ERROR))

        try:
            await ctx.guild.unban(user, reason=reason)
        except discord.NotFound:
            return await ctx.send(embed=discord.Embed(description="❌ That user isn't banned.", color=COLOR_ERROR))

        case_id = await add_case(ctx.guild.id, user.id, ctx.author.id, "unban", reason)
        embed = self.mod_embed("Unban", user, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ─────────────────────────────────────────────
    # ,kick
    # ─────────────────────────────────────────────
    @commands.command(name="kick", help="Kick a user from the server.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, target: discord.Member, *, reason: str = None):
        """Usage: ,kick @user [reason]"""
        if target == ctx.author:
            return await ctx.send(embed=discord.Embed(description="❌ Can't kick yourself.", color=COLOR_ERROR))
        if target.top_role >= ctx.author.top_role:
            return await ctx.send(embed=discord.Embed(description="❌ Can't kick someone with an equal or higher role.", color=COLOR_ERROR))

        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "kick", reason)
        dm_embed = discord.Embed(
            description=f"You were **kicked** from **{ctx.guild.name}**.\n**Reason:** {reason or 'No reason given'}",
            color=COLOR_MOD
        )
        await self.try_dm(target, dm_embed)
        await target.kick(reason=f"[Case #{case_id}] {reason or 'No reason given'} | Mod: {ctx.author}")
        embed = self.mod_embed("Kick", target, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ─────────────────────────────────────────────
    # ,warn
    # ─────────────────────────────────────────────
    @commands.command(name="warn", help="Issue a warning to a user.")
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx, target: discord.Member, *, reason: str = None):
        """
        Usage: ,warn @user [reason]
        Warnings are soft — no action taken, just logged and the user gets a DM.
        """
        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "warn", reason)
        dm_embed = discord.Embed(
            description=f"You received a **warning** in **{ctx.guild.name}**.\n**Reason:** {reason or 'No reason given'}",
            color=COLOR_MOD
        )
        await self.try_dm(target, dm_embed)
        embed = self.mod_embed("Warn", target, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

        warn_count = await get_warn_count(ctx.guild.id, target.id)
        escalation_embed = await self.apply_escalation(ctx, target, warn_count)
        if escalation_embed:
            await ctx.send(embed=escalation_embed)
            await self.send_mod_log(ctx.guild, escalation_embed)

    @commands.command(name="warnings", aliases=["warns"], help="Show a user's current warning count.")
    @commands.has_permissions(kick_members=True)
    async def warnings(self, ctx, target: discord.Member | discord.User):
        """
        Usage: ,warnings @user
        Shows the active warning count and the most recent warning reasons.
        """
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
            embed.add_field(name="Recent warnings", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Recent warnings", value="No active warnings on record.", inline=False)

        await ctx.send(embed=embed)

    @commands.command(
        name="clearwarns",
        aliases=["unwarn", "removewarns"],
        help="Remove one or more recent warnings from a user.",
    )
    @commands.has_permissions(kick_members=True)
    async def clearwarns(self, ctx, target: discord.Member | discord.User, *, details: str = None):
        """
        Usage: ,clearwarns @user [amount] [reason]
        Removes the user's most recent warning cases.
        """
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
            return await ctx.send(embed=discord.Embed(
                description="❌ Amount must be at least 1.",
                color=COLOR_ERROR,
            ))

        removed_case_ids = await clear_recent_warns(ctx.guild.id, target.id, amount)
        if not removed_case_ids:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ {target} has no warnings to remove.",
                color=COLOR_ERROR,
            ))

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
        embed.add_field(name="Moderator", value=f"{ctx.author} (`{ctx.author.id}`)", inline=True)
        embed.add_field(
            name="Removed cases",
            value=", ".join(f"`#{warn_id}`" for warn_id in removed_case_ids),
            inline=True,
        )
        embed.add_field(name="Reason", value=log_reason, inline=False)
        embed.set_footer(text=f"Case #{case_id}")

        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ─────────────────────────────────────────────
    # ,timeout (uses Discord's built-in timeout feature)
    # ─────────────────────────────────────────────
    @commands.command(name="timeout", aliases=["mute"], help="Timeout a user for a given duration.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout_user(self, ctx, target: discord.Member, duration: str = "10m", *, reason: str = None):
        """
        Usage: ,timeout @user [duration] [reason]
        Duration format: 10s, 5m, 2h, 1d — max 28 days (Discord limit).
        """
        seconds = parse_duration(duration)
        if seconds is None:
            return await ctx.send(embed=discord.Embed(
                description="❌ Bad duration format. Use something like `10m`, `2h`, `1d`.",
                color=COLOR_ERROR
            ))
        if seconds > 2419200:  # 28 days
            return await ctx.send(embed=discord.Embed(
                description="❌ Discord limits timeouts to 28 days max.",
                color=COLOR_ERROR
            ))

        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await target.timeout(until, reason=reason)

        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "timeout", reason, duration)
        dm_embed = discord.Embed(
            description=f"You were **timed out** in **{ctx.guild.name}** for `{duration}`.\n**Reason:** {reason or 'No reason given'}",
            color=COLOR_MOD
        )
        await self.try_dm(target, dm_embed)
        embed = self.mod_embed("Timeout", target, ctx.author, reason, case_id, duration)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ─────────────────────────────────────────────
    # ,untimeout
    # ─────────────────────────────────────────────
    @commands.command(name="untimeout", aliases=["unmute"], help="Remove a timeout from a user.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout_user(self, ctx, target: discord.Member, *, reason: str = None):
        """Usage: ,untimeout @user [reason]"""
        await target.timeout(None, reason=reason)
        case_id = await add_case(ctx.guild.id, target.id, ctx.author.id, "untimeout", reason)
        embed = self.mod_embed("Untimeout", target, ctx.author, reason, case_id)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ─────────────────────────────────────────────
    # ,purge
    # ─────────────────────────────────────────────
    @commands.command(name="purge", aliases=["clear"], help="Bulk delete messages from the current channel.")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int):
        """
        Usage: ,purge <amount>
        Deletes the last N messages. Discord only allows bulk-deleting
        messages younger than 14 days, so very old messages get skipped.
        """
        if amount < 1 or amount > 500:
            return await ctx.send(embed=discord.Embed(
                description="❌ Amount must be between 1 and 500.", color=COLOR_ERROR
            ))

        # +1 to also delete the command message itself
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(embed=discord.Embed(
            description=f"✅ Deleted **{len(deleted) - 1}** messages.",
            color=COLOR_SUCCESS
        ))
        # auto-delete the confirmation after 3 seconds so it doesn't clutter
        await asyncio.sleep(3)
        await msg.delete()

    # ─────────────────────────────────────────────
    # ,slowmode
    # ─────────────────────────────────────────────
    @commands.command(name="slowmode", help="Set slowmode on the current channel.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int = 0):
        """
        Usage: ,slowmode [seconds]
        Set to 0 to disable. Max is 21600 (6 hours) — Discord's limit.
        """
        if seconds < 0 or seconds > 21600:
            return await ctx.send(embed=discord.Embed(description="❌ Value must be 0–21600 seconds.", color=COLOR_ERROR))
        await ctx.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            desc = f"✅ Slowmode disabled in {ctx.channel.mention}."
        else:
            desc = f"✅ Slowmode set to **{seconds}s** in {ctx.channel.mention}."
        await ctx.send(embed=discord.Embed(description=desc, color=COLOR_SUCCESS))


    @commands.command(name="setescalation", help="Set an automatic punishment for a warn threshold.")
    @commands.has_permissions(manage_guild=True)
    async def set_escalation(self, ctx, warn_count: int, action: str, duration: str = None):
        """
        Usage: ,setescalation <warn_count> <timeout|kick|ban> [duration]
        Example: ,setescalation 3 timeout 30m
        """
        action = action.lower()
        if warn_count < 1:
            return await ctx.send(embed=discord.Embed(description="âŒ Warn count must be at least 1.", color=COLOR_ERROR))

        if action not in {"timeout", "kick", "ban"}:
            return await ctx.send(embed=discord.Embed(description="âŒ Action must be `timeout`, `kick`, or `ban`.", color=COLOR_ERROR))

        if action == "timeout":
            seconds = parse_duration(duration or "")
            if seconds is None or seconds > 2419200:
                return await ctx.send(embed=discord.Embed(description="âŒ Timeout rules need a valid duration like `30m`, `2h`, `1d`.", color=COLOR_ERROR))
        else:
            duration = None

        await upsert_escalation_rule(ctx.guild.id, warn_count, action, duration)
        action_text = f"{action} (`{duration}`)" if duration else action
        await ctx.send(embed=discord.Embed(description=f"âœ… Escalation set: **{warn_count}** warns -> **{action_text}**", color=COLOR_SUCCESS))

    @commands.command(name="removeescalation", help="Remove an automatic punishment for a warn threshold.")
    @commands.has_permissions(manage_guild=True)
    async def remove_escalation(self, ctx, warn_count: int):
        await remove_escalation_rule(ctx.guild.id, warn_count)
        await ctx.send(embed=discord.Embed(description=f"âœ… Removed the escalation rule for **{warn_count}** warns.", color=COLOR_SUCCESS))

    @commands.command(name="escalations", aliases=["listescalations"], help="Show all configured warn escalation rules.")
    @commands.has_permissions(manage_guild=True)
    async def list_escalations(self, ctx):
        rules = await get_escalation_rules(ctx.guild.id)
        if not rules:
            return await ctx.send(embed=discord.Embed(description="No punishment escalation rules are configured yet.", color=COLOR_SUCCESS))

        embed = discord.Embed(title="Punishment Escalation Rules", color=COLOR_MOD)
        for rule in rules:
            action_text = rule["action"].title()
            if rule.get("duration"):
                action_text += f" ({rule['duration']})"
            embed.add_field(name=f"{rule['warn_count']} Warns", value=action_text, inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    """Required for discord.py to load the cog."""
    await init_db()
    await bot.add_cog(Moderation(bot))
