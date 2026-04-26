"""
Command Center.

This cog is the high-level operating layer for the bot. It turns the existing
moderation, tickets, activity, and Sentinel data into staff dashboards that are
quick to scan during real server work.
"""

from __future__ import annotations

from datetime import datetime

import discord
from discord.ext import commands

from config import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_MOD,
    COLOR_SUCCESS,
    COLOR_WARN,
    PREFIX,
    resolve_mod_log_channel_id,
)
from utils.db import (
    get_active_temp_ban,
    get_all_sticky_messages,
    get_autorole,
    get_case_action_counts,
    get_guild_settings,
    get_member_event_counts,
    get_open_tickets,
    get_reaction_roles,
    get_sentinel_incident_count,
    get_sentinel_settings,
    get_ticket_categories,
    get_ticket_roles,
    get_ticket_settings,
    get_ticket_summary,
    get_top_chatters,
    get_top_voice,
    get_user_cases,
    get_user_message_total,
    get_user_voice_minutes,
    get_warn_count,
)
from utils.embeds import make_embed


ACTION_LABELS = {
    "ban": "Ban",
    "softban": "Softban",
    "unban": "Unban",
    "kick": "Kick",
    "tempban": "Tempban",
    "warn": "Warn",
    "note": "Note",
    "clearwarns": "Clear Warns",
    "timeout": "Timeout",
    "untimeout": "Untimeout",
}

CORE_PERMISSIONS = {
    "view_channel": "View Channels",
    "send_messages": "Send Messages",
    "embed_links": "Embed Links",
    "read_message_history": "Read Message History",
    "manage_messages": "Manage Messages",
    "manage_channels": "Manage Channels",
    "manage_roles": "Manage Roles",
    "kick_members": "Kick Members",
    "ban_members": "Ban Members",
    "moderate_members": "Moderate Members",
    "manage_guild": "Manage Server",
}


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def truncate(value: str, limit: int = 120) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


class CommandCenterView(discord.ui.View):
    """Small refreshable control strip for the command center dashboard."""

    def __init__(self, cog: "CommandCenter", author_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True

        await interaction.response.send_message(
            "Only the staff member who opened this panel can use these controls.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary)
    async def refresh(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ):
        embed = await self.cog.build_mission_control_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Bot Doctor", style=discord.ButtonStyle.secondary)
    async def doctor(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ):
        embed = await self.cog.build_doctor_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Open Tickets", style=discord.ButtonStyle.secondary)
    async def tickets(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ):
        embed = await self.cog.build_open_tickets_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)


class CommandCenter(commands.Cog, name="Command Center"):
    """Premium dashboards and staff intelligence commands."""

    def __init__(self, bot):
        self.bot = bot

    def uptime_text(self) -> str:
        started_at = getattr(self.bot, "started_at", None)
        if not started_at:
            return "Unknown"
        return format_duration((discord.utils.utcnow() - started_at).total_seconds())

    async def health_checks(self, guild: discord.Guild) -> list[tuple[str, bool, str]]:
        settings = await get_guild_settings(guild.id) or {}
        mod_log_channel_id = resolve_mod_log_channel_id(settings)
        ticket_settings = await get_ticket_settings(guild.id) or {}
        ticket_categories = await get_ticket_categories(guild.id)
        ticket_roles = await get_ticket_roles(guild.id)
        sentinel_settings = await get_sentinel_settings(guild.id)
        autorole_id = await get_autorole(guild.id)

        me = guild.me
        permissions = me.guild_permissions if me else discord.Permissions.none()
        missing = [
            label
            for permission, label in CORE_PERMISSIONS.items()
            if not getattr(permissions, permission, False)
        ]

        checks = [
            (
                "Core permissions",
                not missing,
                "Ready" if not missing else f"Missing: {', '.join(missing[:4])}",
            ),
            (
                "Moderation log",
                bool(mod_log_channel_id),
                "Configured" if mod_log_channel_id else "Not set",
            ),
            (
                "Tickets",
                bool(ticket_settings.get("category_id") and ticket_categories),
                (
                    f"{len(ticket_categories)} categories, {len(ticket_roles)} staff roles"
                    if ticket_settings.get("category_id") and ticket_categories
                    else "Needs category and at least one button"
                ),
            ),
            (
                "Sentinel",
                bool(sentinel_settings.get("enabled")),
                (
                    f"Threshold {sentinel_settings.get('alert_threshold', 70)}/100"
                    if sentinel_settings.get("enabled")
                    else "Disabled"
                ),
            ),
            (
                "Branding",
                bool(settings.get("embed_color") or settings.get("embed_image_url")),
                "Custom theme set"
                if settings.get("embed_color") or settings.get("embed_image_url")
                else "Default theme",
            ),
        ]

        if autorole_id:
            role = guild.get_role(autorole_id)
            assignable = bool(role and me and role < me.top_role)
            checks.append(
                (
                    "Autorole",
                    assignable,
                    role.mention if assignable else "Role missing or above bot role",
                )
            )

        return checks

    async def health_score(self, guild: discord.Guild) -> tuple[int, list[tuple[str, bool, str]]]:
        checks = await self.health_checks(guild)
        passed = sum(1 for _, ok, _ in checks if ok)
        score = round((passed / len(checks)) * 100) if checks else 100
        return score, checks

    async def build_mission_control_embed(self, guild: discord.Guild) -> discord.Embed:
        case_counts = await get_case_action_counts(guild.id, days=7)
        member_events = await get_member_event_counts(guild.id, days=7)
        ticket_summary = await get_ticket_summary(guild.id)
        sentinel_count = await get_sentinel_incident_count(guild.id, days=7)
        sentinel_settings = await get_sentinel_settings(guild.id)
        top_chat = await get_top_chatters(guild.id, 3)
        top_voice = await get_top_voice(guild.id, 3)
        score, checks = await self.health_score(guild)

        embed = await make_embed(
            self.bot,
            guild=guild,
            title=f"{guild.name} Mission Control",
            description=(
                f"Health score: **{score}/100**\n"
                f"Latency: **{round(self.bot.latency * 1000)}ms** | "
                f"Uptime: **{self.uptime_text()}**"
            ),
            color=COLOR_INFO if score >= 70 else COLOR_WARN,
            timestamp=datetime.utcnow(),
        )
        if guild.icon:
            embed.set_author(name=guild.name, icon_url=guild.icon.url)

        mod_total = sum(row["total"] for row in case_counts)
        mod_lines = [
            f"{ACTION_LABELS.get(row['action'], row['action'].title())}: {row['total']}"
            for row in case_counts[:5]
        ]
        embed.add_field(
            name="Moderation Load",
            value=(
                f"{mod_total} case(s) in 7 days\n"
                + ("\n".join(mod_lines) if mod_lines else "No recent actions")
            ),
            inline=True,
        )
        embed.add_field(
            name="Community Flow",
            value=(
                f"Joins: {member_events.get('join', 0)}\n"
                f"Leaves: {member_events.get('leave', 0)}\n"
                f"Members: {guild.member_count}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Tickets",
            value=(
                f"Open: {ticket_summary['open']}\n"
                f"Closed: {ticket_summary['closed']}\n"
                f"Total: {ticket_summary['total']}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Sentinel",
            value=(
                f"Status: {'Enabled' if sentinel_settings.get('enabled') else 'Disabled'}\n"
                f"7d incidents: {sentinel_count}\n"
                f"Threshold: {sentinel_settings.get('alert_threshold', 70)}/100"
            ),
            inline=True,
        )

        chatter_lines = []
        for index, row in enumerate(top_chat, start=1):
            member = guild.get_member(row["user_id"])
            name = member.display_name if member else f"User {row['user_id']}"
            chatter_lines.append(f"{index}. {name} - {row['total']:,}")
        embed.add_field(
            name="Top Chat",
            value="\n".join(chatter_lines) if chatter_lines else "No chat data",
            inline=True,
        )

        voice_lines = []
        for index, row in enumerate(top_voice, start=1):
            member = guild.get_member(row["user_id"])
            name = member.display_name if member else f"User {row['user_id']}"
            voice_lines.append(f"{index}. {name} - {format_duration(row['minutes'] * 60)}")
        embed.add_field(
            name="Top Voice",
            value="\n".join(voice_lines) if voice_lines else "No voice data",
            inline=True,
        )

        fixes = [f"{name}: {detail}" for name, ok, detail in checks if not ok]
        embed.add_field(
            name="Recommended Next Actions",
            value=(
                "\n".join(f"- {truncate(item, 80)}" for item in fixes[:4])
                if fixes
                else "Everything important is configured. Keep an eye on Sentinel."
            ),
            inline=False,
        )
        embed.set_footer(text=f"Use {PREFIX}doctor for the full setup diagnosis")
        return embed

    async def build_doctor_embed(self, guild: discord.Guild) -> discord.Embed:
        score, checks = await self.health_score(guild)
        settings = await get_guild_settings(guild.id) or {}
        stickies = await get_all_sticky_messages(guild.id)
        reaction_roles = await get_reaction_roles(guild.id)

        color = COLOR_SUCCESS if score >= 85 else COLOR_WARN if score >= 60 else COLOR_ERROR
        embed = await make_embed(
            self.bot,
            guild=guild,
            title="Bot Doctor",
            description=f"Setup health: **{score}/100**",
            color=color,
            timestamp=datetime.utcnow(),
        )

        lines = []
        for name, ok, detail in checks:
            status = "OK" if ok else "FIX"
            lines.append(f"`{status}` **{name}:** {detail}")

        embed.add_field(name="Diagnosis", value="\n".join(lines), inline=False)
        embed.add_field(
            name="Extras",
            value=(
                f"Sticky messages: {len(stickies)}\n"
                f"Reaction roles: {len(reaction_roles)}\n"
                f"Embed image: {'Set' if settings.get('embed_image_url') else 'Not set'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="Fast Fix Commands",
            value=(
                f"`{PREFIX}setmodlog #channel`\n"
                f"`{PREFIX}sentinel log #channel`\n"
                f"`{PREFIX}setticketcategory <category>`\n"
                f"`{PREFIX}ticketcategoryadd Support | | General help`"
            ),
            inline=False,
        )
        return embed

    async def build_open_tickets_embed(self, guild: discord.Guild) -> discord.Embed:
        tickets = await get_open_tickets(guild.id)
        embed = await make_embed(
            self.bot,
            guild=guild,
            title="Open Tickets",
            color=COLOR_INFO,
            timestamp=datetime.utcnow(),
        )

        if not tickets:
            embed.description = "There are no open tickets right now."
            return embed

        for ticket in tickets[:12]:
            channel = guild.get_channel(ticket["channel_id"])
            owner = guild.get_member(ticket["user_id"])
            created = int(datetime.fromisoformat(ticket["created_at"]).timestamp())
            embed.add_field(
                name=f"Ticket #{ticket['id']} - {ticket['category_name']}",
                value=(
                    f"Owner: {owner.mention if owner else ticket['user_id']}\n"
                    f"Channel: {channel.mention if channel else ticket['channel_id']}\n"
                    f"Opened: <t:{created}:R>"
                ),
                inline=False,
            )

        if len(tickets) > 12:
            embed.set_footer(text=f"Showing 12 of {len(tickets)} open tickets")
        return embed

    @commands.command(
        name="missioncontrol",
        aliases=["dashboard", "commandcenter", "overview"],
        help="Open the premium staff dashboard for this server.",
    )
    @commands.has_permissions(manage_guild=True)
    async def mission_control(self, ctx):
        """Usage: ,missioncontrol"""
        embed = await self.build_mission_control_embed(ctx.guild)
        await ctx.send(embed=embed, view=CommandCenterView(self, ctx.author.id))

    @commands.command(
        name="doctor",
        aliases=["botdoctor", "setupcheck"],
        help="Diagnose bot permissions and server setup gaps.",
    )
    @commands.has_permissions(manage_guild=True)
    async def doctor(self, ctx):
        """Usage: ,doctor"""
        embed = await self.build_doctor_embed(ctx.guild)
        await ctx.send(embed=embed)

    @commands.command(
        name="member360",
        aliases=["profile360", "user360"],
        help="Show a complete staff intelligence profile for a member.",
    )
    @commands.has_permissions(kick_members=True)
    async def member360(self, ctx, member: discord.Member = None):
        """Usage: ,member360 [@user]"""
        member = member or ctx.author
        cases = await get_user_cases(ctx.guild.id, member.id)
        warnings = await get_warn_count(ctx.guild.id, member.id)
        active_tempban = await get_active_temp_ban(ctx.guild.id, member.id)
        message_total = await get_user_message_total(ctx.guild.id, member.id)
        voice_minutes = await get_user_voice_minutes(ctx.guild.id, member.id)
        top_chat = await get_top_chatters(ctx.guild.id, 999)
        top_voice = await get_top_voice(ctx.guild.id, 999)

        chat_rank = next(
            (index + 1 for index, row in enumerate(top_chat) if row["user_id"] == member.id),
            None,
        )
        voice_rank = next(
            (index + 1 for index, row in enumerate(top_voice) if row["user_id"] == member.id),
            None,
        )

        sentinel_cog = self.bot.get_cog("Sentinel")
        live_messages = (
            sentinel_cog.recent_messages(ctx.guild.id, member.id, 300)
            if sentinel_cog
            else []
        )
        live_links = sum(1 for entry in live_messages if entry["has_link"])
        live_mentions = sum(entry["mention_count"] for entry in live_messages)

        account_age_days = (discord.utils.utcnow() - member.created_at).days
        joined_age_days = (
            (discord.utils.utcnow() - member.joined_at).days
            if member.joined_at
            else None
        )
        risk_notes = []
        if account_age_days < 7:
            risk_notes.append("Discord account is under 7 days old")
        if joined_age_days is not None and joined_age_days < 1:
            risk_notes.append("Joined this server within the last day")
        if warnings >= 3:
            risk_notes.append(f"{warnings} active warning(s)")
        if len(live_messages) >= 8:
            risk_notes.append(f"{len(live_messages)} live messages in 5 minutes")
        if live_mentions >= 6:
            risk_notes.append(f"{live_mentions} live mentions")

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Member 360 - {member.display_name}",
            description=(
                "Complete staff-facing profile built from moderation, activity, "
                "account age, and Sentinel live context."
            ),
            color=COLOR_MOD,
            timestamp=datetime.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(
            name="Account",
            value=(
                f"Created: <t:{int(member.created_at.timestamp())}:R>\n"
                f"Joined: "
                f"{f'<t:{int(member.joined_at.timestamp())}:R>' if member.joined_at else 'Unknown'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Moderation",
            value=(
                f"Cases: {len(cases)}\n"
                f"Warnings: {warnings}\n"
                f"Tempban: {'Active' if active_tempban else 'No'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Activity",
            value=(
                f"Messages: {message_total:,} (rank #{chat_rank or 'N/A'})\n"
                f"Voice: {format_duration(voice_minutes * 60)} "
                f"(rank #{voice_rank or 'N/A'})"
            ),
            inline=True,
        )
        embed.add_field(
            name="Sentinel Live",
            value=(
                f"5m messages: {len(live_messages)}\n"
                f"Links: {live_links}\n"
                f"Mentions: {live_mentions}"
            ),
            inline=True,
        )

        if cases:
            recent_lines = []
            for case in cases[:5]:
                reason = truncate(case["reason"] or "No reason given", 70)
                label = ACTION_LABELS.get(case["action"], case["action"].title())
                recent_lines.append(f"`#{case['id']}` {label} - {reason}")
            embed.add_field(
                name="Recent Cases",
                value="\n".join(recent_lines),
                inline=False,
            )

        embed.add_field(
            name="Risk Notes",
            value="\n".join(f"- {note}" for note in risk_notes)
            if risk_notes
            else "No obvious risk signals in the current data.",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(CommandCenter(bot))
