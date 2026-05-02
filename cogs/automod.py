"""
cogs/automod.py - persistent server-level message filtering.
"""

# AutoMod handles deterministic rules; Sentinel handles live behaviour patterns.
import logging
import re
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
    add_case,
    add_automod_blocked_term,
    get_automod_blocked_terms,
    get_automod_settings,
    get_guild_settings,
    remove_automod_blocked_term,
    upsert_automod_settings,
)
from utils.embeds import make_embed


log = logging.getLogger(__name__)

INVITE_PATTERN = re.compile(
    r"(discord(?:app)?\.com/invite/\S+|discord\.gg/\S+)",
    re.IGNORECASE,
)
LINK_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


def bool_text(value: int | bool) -> str:
    return "On" if value else "Off"


def normalize_toggle(value: str) -> int | None:
    lowered = value.lower()
    if lowered in {"on", "yes", "true", "enable", "enabled"}:
        return 1
    if lowered in {"off", "no", "false", "disable", "disabled"}:
        return 0
    return None


class AutoMod(commands.Cog, name="AutoMod"):
    """Persistent automatic moderation rules for messages."""

    def __init__(self, bot):
        self.bot = bot
        self._term_cache: dict[int, list[str]] = {}

    async def blocked_terms(self, guild_id: int) -> list[str]:
        if guild_id not in self._term_cache:
            rows = await get_automod_blocked_terms(guild_id)
            self._term_cache[guild_id] = [row["term"] for row in rows]
        return self._term_cache[guild_id]

    def clear_term_cache(self, guild_id: int):
        self._term_cache.pop(guild_id, None)

    async def send_mod_log(self, guild: discord.Guild, embed: discord.Embed):
        settings = await get_guild_settings(guild.id) or {}
        channel_id = resolve_mod_log_channel_id(settings)
        channel = guild.get_channel(channel_id) if channel_id else None
        if channel:
            try:
                await channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                log.warning(
                    "Could not send AutoMod log in guild %s.",
                    guild.id,
                    exc_info=True,
                )

    def detect_triggers(
        self,
        message: discord.Message,
        settings: dict,
        blocked_terms: list[str],
    ) -> list[str]:
        content = message.content or ""
        lowered = content.lower()
        triggers = []

        if settings.get("delete_invites") and INVITE_PATTERN.search(content):
            triggers.append("Discord invite link")

        if settings.get("delete_links") and LINK_PATTERN.search(content):
            triggers.append("External link")

        mention_limit = int(settings.get("mass_mention_limit") or 0)
        mention_count = len(message.mentions) + len(message.role_mentions)
        if mention_limit > 0 and mention_count >= mention_limit:
            triggers.append(f"Mass mention ({mention_count} mentions)")

        for term in blocked_terms:
            if term and term in lowered:
                triggers.append(f"Blocked term: {term}")
                break

        return triggers

    async def handle_trigger(self, message: discord.Message, triggers: list[str], settings: dict):
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

        reason = "AutoMod: " + ", ".join(triggers)
        action = "warn" if settings.get("warn_on_trigger") else "automod"
        case_id = await add_case(
            message.guild.id,
            message.author.id,
            self.bot.user.id,
            action,
            reason,
        )

        embed = discord.Embed(
            title="AutoMod Action",
            description=f"Deleted a message from {message.author.mention}.",
            color=COLOR_WARN,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)
        embed.add_field(name="Trigger", value="\n".join(triggers[:5]), inline=False)
        if message.content:
            content = message.content
            if len(content) > 700:
                content = f"{content[:697]}..."
            embed.add_field(name="Message", value=content, inline=False)

        await self.send_mod_log(message.guild, embed)

        try:
            warning = (
                f"Your message in **{message.guild.name}** was removed by AutoMod."
            )
            if settings.get("warn_on_trigger"):
                warning += " A warning was also added to your moderation history."
            await message.author.send(
                embed=discord.Embed(
                    description=f"{warning}\n**Reason:** {', '.join(triggers)}",
                    color=COLOR_MOD,
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        if isinstance(message.author, discord.Member):
            if message.author.guild_permissions.manage_messages:
                return

        settings = await get_automod_settings(message.guild.id)
        if not settings.get("enabled"):
            return

        terms = await self.blocked_terms(message.guild.id)
        triggers = self.detect_triggers(message, settings, terms)
        if triggers:
            await self.handle_trigger(message, triggers, settings)

    @commands.group(
        name="automod",
        invoke_without_command=True,
        help="Show or configure persistent automatic moderation rules.",
    )
    @commands.has_permissions(manage_guild=True)
    async def automod(self, ctx):
        """Usage: ,automod"""
        settings = await get_automod_settings(ctx.guild.id)
        terms = await self.blocked_terms(ctx.guild.id)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="AutoMod",
            description="Persistent rules for blocked terms, invites, links, and mass mentions.",
            color=COLOR_INFO,
        )
        embed.add_field(name="Status", value=bool_text(settings["enabled"]), inline=True)
        embed.add_field(
            name="Invites", value=bool_text(settings["delete_invites"]), inline=True
        )
        embed.add_field(name="Links", value=bool_text(settings["delete_links"]), inline=True)
        embed.add_field(
            name="Mass Mentions",
            value=(
                f"{settings['mass_mention_limit']}+ mentions"
                if settings["mass_mention_limit"]
                else "Off"
            ),
            inline=True,
        )
        embed.add_field(
            name="Warn On Trigger",
            value=bool_text(settings["warn_on_trigger"]),
            inline=True,
        )
        embed.add_field(name="Blocked Terms", value=str(len(terms)), inline=True)
        embed.add_field(
            name="Commands",
            value=(
                f"`{PREFIX}automod on/off`\n"
                f"`{PREFIX}automod invites on/off`\n"
                f"`{PREFIX}automod links on/off`\n"
                f"`{PREFIX}automod mentions <number|off>`\n"
                f"`{PREFIX}automod warn on/off`\n"
                f"`{PREFIX}automod addword <term>`\n"
                f"`{PREFIX}automod removeword <term>`\n"
                f"`{PREFIX}automod words`"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @automod.command(name="on", help="Enable AutoMod.")
    @commands.has_permissions(manage_guild=True)
    async def automod_on(self, ctx):
        await upsert_automod_settings(ctx.guild.id, enabled=1)
        await ctx.send(
            embed=discord.Embed(description="AutoMod is now enabled.", color=COLOR_SUCCESS)
        )

    @automod.command(name="off", help="Disable AutoMod.")
    @commands.has_permissions(manage_guild=True)
    async def automod_off(self, ctx):
        await upsert_automod_settings(ctx.guild.id, enabled=0)
        await ctx.send(
            embed=discord.Embed(description="AutoMod is now disabled.", color=COLOR_SUCCESS)
        )

    @automod.command(name="invites", help="Delete Discord invite links on or off.")
    @commands.has_permissions(manage_guild=True)
    async def automod_invites(self, ctx, value: str):
        toggle = normalize_toggle(value)
        if toggle is None:
            return await ctx.send(
                embed=discord.Embed(description="Use `on` or `off`.", color=COLOR_ERROR)
            )

        await upsert_automod_settings(ctx.guild.id, delete_invites=toggle)
        await ctx.send(
            embed=discord.Embed(
                description=f"Invite filtering is now **{bool_text(toggle)}**.",
                color=COLOR_SUCCESS,
            )
        )

    @automod.command(name="links", help="Delete external links on or off.")
    @commands.has_permissions(manage_guild=True)
    async def automod_links(self, ctx, value: str):
        toggle = normalize_toggle(value)
        if toggle is None:
            return await ctx.send(
                embed=discord.Embed(description="Use `on` or `off`.", color=COLOR_ERROR)
            )

        await upsert_automod_settings(ctx.guild.id, delete_links=toggle)
        await ctx.send(
            embed=discord.Embed(
                description=f"Link filtering is now **{bool_text(toggle)}**.",
                color=COLOR_SUCCESS,
            )
        )

    @automod.command(name="mentions", help="Set the mass mention delete threshold.")
    @commands.has_permissions(manage_guild=True)
    async def automod_mentions(self, ctx, value: str):
        if value.lower() in {"off", "0", "disable", "disabled"}:
            await upsert_automod_settings(ctx.guild.id, mass_mention_limit=0)
            return await ctx.send(
                embed=discord.Embed(
                    description="Mass mention filtering is now off.",
                    color=COLOR_SUCCESS,
                )
            )

        if not value.isdigit():
            return await ctx.send(
                embed=discord.Embed(
                    description="Use a number from 2 to 25, or `off`.",
                    color=COLOR_ERROR,
                )
            )

        limit = int(value)
        if limit < 2 or limit > 25:
            return await ctx.send(
                embed=discord.Embed(
                    description="Mass mention limit must be between 2 and 25.",
                    color=COLOR_ERROR,
                )
            )

        await upsert_automod_settings(ctx.guild.id, mass_mention_limit=limit)
        await ctx.send(
            embed=discord.Embed(
                description=f"Messages with **{limit}+ mentions** will be deleted.",
                color=COLOR_SUCCESS,
            )
        )

    @automod.command(name="warn", help="Choose whether AutoMod actions add warnings.")
    @commands.has_permissions(manage_guild=True)
    async def automod_warn(self, ctx, value: str):
        toggle = normalize_toggle(value)
        if toggle is None:
            return await ctx.send(
                embed=discord.Embed(description="Use `on` or `off`.", color=COLOR_ERROR)
            )

        await upsert_automod_settings(ctx.guild.id, warn_on_trigger=toggle)
        await ctx.send(
            embed=discord.Embed(
                description=f"AutoMod warning cases are now **{bool_text(toggle)}**.",
                color=COLOR_SUCCESS,
            )
        )

    @automod.command(name="addword", aliases=["blockword"], help="Add a blocked term.")
    @commands.has_permissions(manage_guild=True)
    async def automod_addword(self, ctx, *, term: str):
        term = term.strip().lower()
        if len(term) < 2 or len(term) > 80:
            return await ctx.send(
                embed=discord.Embed(
                    description="Blocked terms must be between 2 and 80 characters.",
                    color=COLOR_ERROR,
                )
            )

        added = await add_automod_blocked_term(ctx.guild.id, term, ctx.author.id)
        self.clear_term_cache(ctx.guild.id)
        await ctx.send(
            embed=discord.Embed(
                description=(
                    f"Blocked `{term}`."
                    if added
                    else f"`{term}` is already blocked."
                ),
                color=COLOR_SUCCESS if added else COLOR_INFO,
            )
        )

    @automod.command(
        name="removeword", aliases=["unblockword"], help="Remove a blocked term."
    )
    @commands.has_permissions(manage_guild=True)
    async def automod_removeword(self, ctx, *, term: str):
        removed = await remove_automod_blocked_term(ctx.guild.id, term)
        self.clear_term_cache(ctx.guild.id)
        await ctx.send(
            embed=discord.Embed(
                description=(
                    f"Removed `{term.strip().lower()}` from the blocked terms."
                    if removed
                    else "That term was not blocked."
                ),
                color=COLOR_SUCCESS if removed else COLOR_ERROR,
            )
        )

    @automod.command(name="words", aliases=["blocklist"], help="List blocked terms.")
    @commands.has_permissions(manage_guild=True)
    async def automod_words(self, ctx):
        terms = await self.blocked_terms(ctx.guild.id)
        if not terms:
            return await ctx.send(
                embed=discord.Embed(
                    description="No blocked terms are configured.",
                    color=COLOR_INFO,
                )
            )

        shown = ", ".join(f"`{term}`" for term in terms[:40])
        embed = discord.Embed(
            title="AutoMod Blocked Terms",
            description=shown,
            color=COLOR_INFO,
        )
        if len(terms) > 40:
            embed.set_footer(text=f"Showing 40 of {len(terms)} blocked terms")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
