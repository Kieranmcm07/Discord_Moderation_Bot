"""
cogs/cases.py — case tracking commands.
Every mod action creates a case automatically. These commands let you
look up cases, view a user's history, and see recent mod activity.
It's basically an audit log you can query from Discord.
"""

import discord
from discord.ext import commands
from datetime import datetime
from utils.db import get_case, get_user_cases, get_recent_cases
from config import COLOR_MOD, COLOR_ERROR, COLOR_INFO

# emoji map so the embed looks nice at a glance
ACTION_EMOJI = {
    "ban":      "🔨",
    "unban":    "🔓",
    "kick":     "👢",
    "warn":     "⚠️",
    "timeout":  "🔇",
    "untimeout":"🔊",
    "mute":     "🔇",
    "unmute":   "🔊",
}


class Cases(commands.Cog, name="Cases"):
    """Look up moderation cases and user histories."""

    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # ,case <id>
    # ─────────────────────────────────────────────
    @commands.command(name="case", help="Look up a specific case by its ID.")
    @commands.has_permissions(kick_members=True)
    async def case(self, ctx, case_id: int):
        """
        Usage: ,case <case_id>
        Shows all the details for a single case number.
        """
        data = await get_case(ctx.guild.id, case_id)
        if not data:
            return await ctx.send(embed=discord.Embed(
                description=f"❌ Case #{case_id} not found.", color=COLOR_ERROR
            ))

        emoji = ACTION_EMOJI.get(data["action"], "📋")
        e = discord.Embed(
            title=f"{emoji} Case #{case_id} — {data['action'].title()}",
            color=COLOR_MOD,
            timestamp=datetime.fromisoformat(data["created_at"])
        )

        # try to resolve IDs to usernames — show raw ID if they left the server
        target = self.bot.get_user(data["user_id"]) or f"Unknown ({data['user_id']})"
        mod = self.bot.get_user(data["mod_id"]) or f"Unknown ({data['mod_id']})"

        e.add_field(name="User",       value=str(target), inline=True)
        e.add_field(name="Moderator",  value=str(mod),    inline=True)
        if data["duration"]:
            e.add_field(name="Duration", value=data["duration"], inline=True)
        e.add_field(name="Reason", value=data["reason"] or "No reason given", inline=False)
        e.set_footer(text=f"Created at")

        await ctx.send(embed=e)

    # ─────────────────────────────────────────────
    # ,history @user
    # ─────────────────────────────────────────────
    @commands.command(name="history", aliases=["cases", "infractions"], help="View a user's moderation history.")
    @commands.has_permissions(kick_members=True)
    async def history(self, ctx, target: discord.Member | discord.User):
        """
        Usage: ,history @user
        Shows all cases linked to that user in this server.
        Works on users who have left the server too — just paste their ID.
        """
        data = await get_user_cases(ctx.guild.id, target.id)
        if not data:
            return await ctx.send(embed=discord.Embed(
                description=f"✅ No cases on record for {target}.",
                color=COLOR_INFO
            ))

        # split into pages of 10 if there are lots of cases
        e = discord.Embed(
            title=f"📋 Moderation History — {target}",
            color=COLOR_MOD,
            description=f"**{len(data)}** total case(s)"
        )
        e.set_thumbnail(url=target.display_avatar.url)

        # show up to 15 most recent cases before it gets too long
        for case in data[:15]:
            emoji = ACTION_EMOJI.get(case["action"], "📋")
            mod = self.bot.get_user(case["mod_id"]) or f"ID: {case['mod_id']}"
            reason = (case["reason"] or "No reason given")[:80]  # truncate long reasons
            e.add_field(
                name=f"{emoji} Case #{case['id']} — {case['action'].title()}",
                value=f"**Mod:** {mod}\n**Reason:** {reason}\n**Date:** <t:{int(datetime.fromisoformat(case['created_at']).timestamp())}:D>",
                inline=False
            )

        if len(data) > 15:
            e.set_footer(text=f"Showing 15 of {len(data)} cases")

        await ctx.send(embed=e)

    # ─────────────────────────────────────────────
    # ,recentcases
    # ─────────────────────────────────────────────
    @commands.command(name="recentcases", aliases=["modlog", "recent"], help="See the latest 10 mod actions.")
    @commands.has_permissions(kick_members=True)
    async def recent_cases(self, ctx, limit: int = 10):
        """
        Usage: ,recentcases [limit]
        Quick way to see what's been happening without digging through the log channel.
        """
        limit = min(max(limit, 1), 25)  # clamp between 1 and 25
        data = await get_recent_cases(ctx.guild.id, limit)

        if not data:
            return await ctx.send(embed=discord.Embed(
                description="No cases logged yet.", color=COLOR_INFO
            ))

        e = discord.Embed(title=f"📋 Recent {len(data)} Cases", color=COLOR_MOD)
        for case in data:
            emoji = ACTION_EMOJI.get(case["action"], "📋")
            target = self.bot.get_user(case["user_id"]) or f"ID: {case['user_id']}"
            mod = self.bot.get_user(case["mod_id"]) or f"ID: {case['mod_id']}"
            e.add_field(
                name=f"#{case['id']} {emoji} {case['action'].title()} — {target}",
                value=f"By {mod} | {case['reason'] or 'No reason'}",
                inline=False
            )

        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Cases(bot))
