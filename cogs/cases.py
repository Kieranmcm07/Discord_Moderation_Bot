"""
Case tracking commands.

Cases are one of the most useful moderation tools in the bot, so these
commands aim to stay quick to scan during busy moderation sessions.
"""

from datetime import datetime

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, COLOR_MOD
from utils.db import (
    add_case,
    get_active_temp_ban,
    get_case,
    get_recent_cases,
    get_user_cases,
    get_warn_count,
)
from utils.embeds import make_embed


ACTION_LABELS = {
    "ban": "Ban",
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
}


def get_action_label(action: str) -> str:
    """Return a friendly label for a stored action value."""
    return ACTION_LABELS.get(action, action.title())


def format_case_reason(case: dict) -> str:
    """Render a readable reason string for case embeds."""
    reason = case["reason"] or "No reason given"
    if case["action"] == "clearwarns" and case.get("duration"):
        return f"Removed {case['duration']} warning(s). Note: {reason}"
    return reason


class Cases(commands.Cog, name="Cases"):
    """Look up moderation cases and browse member histories."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="case", help="Look up a specific case by its ID.")
    @commands.has_permissions(kick_members=True)
    async def case(self, ctx, case_id: int):
        """Usage: ,case <case_id>"""
        data = await get_case(ctx.guild.id, case_id)
        if not data:
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    title="Case Not Found",
                    description=f"I could not find case `#{case_id}` in this server.",
                    color=COLOR_ERROR,
                )
            )

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Case #{case_id} - {get_action_label(data['action'])}",
            color=COLOR_MOD,
            timestamp=datetime.fromisoformat(data["created_at"]),
        )

        target = self.bot.get_user(data["user_id"]) or f"Unknown ({data['user_id']})"
        moderator = self.bot.get_user(data["mod_id"]) or f"Unknown ({data['mod_id']})"

        embed.add_field(name="User", value=str(target), inline=True)
        embed.add_field(name="Moderator", value=str(moderator), inline=True)
        if data["duration"] and data["action"] != "clearwarns":
            embed.add_field(name="Duration", value=data["duration"], inline=True)
        embed.add_field(name="Reason", value=format_case_reason(data), inline=False)
        await ctx.send(embed=embed)

    @commands.command(
        name="history",
        aliases=["cases", "infractions"],
        help="View a user's moderation history.",
    )
    @commands.has_permissions(kick_members=True)
    async def history(self, ctx, target: discord.Member | discord.User):
        """Usage: ,history @user"""
        data = await get_user_cases(ctx.guild.id, target.id)
        if not data:
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    title="No Case History",
                    description=f"There are no cases on record for {target}.",
                    color=COLOR_INFO,
                )
            )

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Moderation History - {target}",
            description=f"**{len(data)}** total case(s)",
            color=COLOR_MOD,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        for case in data[:15]:
            moderator = self.bot.get_user(case["mod_id"]) or f"ID: {case['mod_id']}"
            reason = format_case_reason(case)
            if len(reason) > 100:
                reason = f"{reason[:97]}..."
            embed.add_field(
                name=f"#{case['id']} - {get_action_label(case['action'])}",
                value=(
                    f"**Mod:** {moderator}\n"
                    f"**Reason:** {reason}\n"
                    f"**Date:** <t:{int(datetime.fromisoformat(case['created_at']).timestamp())}:D>"
                ),
                inline=False,
            )

        if len(data) > 15:
            embed.set_footer(text=f"Showing 15 of {len(data)} cases")

        await ctx.send(embed=embed)

    @commands.command(
        name="modsummary",
        aliases=["summary", "usersummary"],
        help="Show a quick moderation summary for a user.",
    )
    @commands.has_permissions(kick_members=True)
    async def modsummary(self, ctx, target: discord.Member | discord.User):
        """Usage: ,modsummary @user"""
        cases = await get_user_cases(ctx.guild.id, target.id)
        warn_count = await get_warn_count(ctx.guild.id, target.id)
        active_tempban = await get_active_temp_ban(ctx.guild.id, target.id)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Moderation Summary - {target}",
            description="Quick snapshot of the member's moderation history.",
            color=COLOR_MOD,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Total Cases", value=str(len(cases)), inline=True)
        embed.add_field(name="Active Warnings", value=str(warn_count), inline=True)
        embed.add_field(
            name="Temp Ban",
            value=(
                f"Active until <t:{int(datetime.fromisoformat(active_tempban['expires_at']).timestamp())}:F>"
                if active_tempban
                else "Not active"
            ),
            inline=False,
        )

        if cases:
            lines = []
            for case in cases[:5]:
                reason = format_case_reason(case)
                if len(reason) > 60:
                    reason = f"{reason[:57]}..."
                lines.append(
                    f"`#{case['id']}` {get_action_label(case['action'])} - {reason}"
                )
            embed.add_field(
                name="Recent Cases",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="Recent Cases",
                value="No recorded moderation actions for this member.",
                inline=False,
            )

        await ctx.send(embed=embed)

    @commands.command(
        name="recentcases",
        aliases=["modlog", "recent"],
        help="See the latest moderation actions.",
    )
    @commands.has_permissions(kick_members=True)
    async def recent_cases(self, ctx, limit: int = 10):
        """Usage: ,recentcases [limit]"""
        limit = min(max(limit, 1), 25)
        data = await get_recent_cases(ctx.guild.id, limit)

        if not data:
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    title="No Cases Yet",
                    description="Nothing has been logged yet for this server.",
                    color=COLOR_INFO,
                )
            )

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Recent {len(data)} Cases",
            color=COLOR_MOD,
        )
        for case in data:
            target = self.bot.get_user(case["user_id"]) or f"ID: {case['user_id']}"
            moderator = self.bot.get_user(case["mod_id"]) or f"ID: {case['mod_id']}"
            embed.add_field(
                name=f"#{case['id']} - {get_action_label(case['action'])}",
                value=f"User: {target}\nBy: {moderator}\nReason: {format_case_reason(case)}",
                inline=False,
            )

        await ctx.send(embed=embed)

    @commands.command(
        name="searchcases",
        aliases=["findcases"],
        help="Search recent cases by action or text in the reason.",
    )
    @commands.has_permissions(kick_members=True)
    async def searchcases(self, ctx, *, query: str):
        """Usage: ,searchcases <keyword>"""
        query_lower = query.lower()
        recent = await get_recent_cases(ctx.guild.id, 100)
        matches = [
            case
            for case in recent
            if query_lower in case["action"].lower()
            or query_lower in (case["reason"] or "").lower()
        ]

        if not matches:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="No Matching Cases",
                description=f"No recent cases matched `{query}`.",
                color=COLOR_INFO,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Case Search: {query}",
            description=f"Showing {min(len(matches), 10)} of {len(matches)} matching recent cases.",
            color=COLOR_MOD,
        )
        for case in matches[:10]:
            target = self.bot.get_user(case["user_id"]) or f"ID: {case['user_id']}"
            reason = format_case_reason(case)
            if len(reason) > 120:
                reason = f"{reason[:117]}..."
            embed.add_field(
                name=f"#{case['id']} - {get_action_label(case['action'])}",
                value=f"{target}\n{reason}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(
        name="casecomment",
        aliases=["case_note"],
        help="Add a follow-up moderator note referencing an existing case ID.",
    )
    @commands.has_permissions(kick_members=True)
    async def casecomment(self, ctx, case_id: int, *, note: str):
        """Usage: ,casecomment <case_id> <note>"""
        original = await get_case(ctx.guild.id, case_id)
        if not original:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Case Not Found",
                description=f"I could not find case `#{case_id}` in this server.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        new_case_id = await add_case(
            ctx.guild.id,
            original["user_id"],
            ctx.author.id,
            "note",
            f"Follow-up for case #{case_id}: {note}",
        )
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Case Comment Added",
            description=f"Added a follow-up note to case `#{case_id}` as new case `#{new_case_id}`.",
            color=COLOR_MOD,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Cases(bot))
