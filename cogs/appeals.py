"""
Case appeal workflow.

Appeals reuse the ticket staff roles and ticket category so servers do not need
another setup flow before members can ask staff to review a moderation case.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import aiosqlite
import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, COLOR_MOD, COLOR_SUCCESS, PREFIX
from utils.db import (
    add_case,
    close_ticket,
    create_ticket,
    get_case,
    get_open_ticket_for_user,
    get_ticket_by_channel,
    get_ticket_roles,
    get_ticket_settings,
    get_user_cases,
)
from utils.embeds import make_embed


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9-]+", "-", value.lower()).strip("-")
    return value or "appeal"


def short_text(value: str | None, limit: int = 500) -> str:
    value = value or "No reason given"
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


class AppealCreateButton(discord.ui.Button):
    def __init__(self, cog: "Appeals"):
        super().__init__(
            label="Open Appeal",
            style=discord.ButtonStyle.primary,
            custom_id="appeals:create",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AppealModal(self.cog))


class AppealModal(discord.ui.Modal, title="Open a Case Appeal"):
    case_id = discord.ui.TextInput(
        label="Case ID",
        placeholder="Example: 42",
        min_length=1,
        max_length=12,
    )
    reason = discord.ui.TextInput(
        label="Why should staff review this case?",
        style=discord.TextStyle.paragraph,
        min_length=10,
        max_length=1200,
    )

    def __init__(self, cog: "Appeals"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.handle_appeal_submit(
            interaction,
            str(self.case_id.value).strip(),
            str(self.reason.value).strip(),
        )


class Appeals(commands.Cog, name="Appeals"):
    """Case appeal tickets for members and staff."""

    def __init__(self, bot):
        self.bot = bot
        self._appeal_locks: dict[tuple[int, int], asyncio.Lock] = {}

    async def cog_load(self):
        self.bot.add_view(self._build_panel_view())

    def _build_panel_view(self) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        view.add_item(AppealCreateButton(self))
        return view

    async def _get_staff_roles(self, guild: discord.Guild) -> list[discord.Role]:
        roles = []
        for role_id in await get_ticket_roles(guild.id):
            role = guild.get_role(role_id)
            if role:
                roles.append(role)
        return roles

    async def _is_appeal_staff(self, member: discord.Member) -> bool:
        if (
            member.guild_permissions.manage_guild
            or member.guild_permissions.kick_members
            or member.guild_permissions.administrator
        ):
            return True

        role_ids = set(await get_ticket_roles(member.guild.id))
        return any(role.id in role_ids for role in member.roles)

    async def _log_appeal_event(
        self,
        guild: discord.Guild,
        *,
        title: str,
        description: str,
        color: int,
    ):
        settings = await get_ticket_settings(guild.id)
        if not settings or not settings.get("log_channel_id"):
            return

        channel = guild.get_channel(settings["log_channel_id"])
        if not channel:
            return

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow(),
        )
        await channel.send(embed=embed)

    async def handle_appeal_submit(
        self,
        interaction: discord.Interaction,
        case_id_text: str,
        appeal_reason: str,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Appeals can only be opened inside a server.",
                ephemeral=True,
            )

        if not case_id_text.isdigit():
            return await interaction.response.send_message(
                "Use the number from the case, like `42`.",
                ephemeral=True,
            )

        case_id = int(case_id_text)
        case = await get_case(interaction.guild.id, case_id)
        if not case:
            return await interaction.response.send_message(
                f"I could not find case `#{case_id}` in this server.",
                ephemeral=True,
            )

        if case["user_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "You can only appeal cases that belong to your account.",
                ephemeral=True,
            )

        settings = await get_ticket_settings(interaction.guild.id)
        if not settings or not settings.get("category_id"):
            return await interaction.response.send_message(
                f"Appeals use the ticket category. Ask an admin to run `{PREFIX}setticketcategory <category>` first.",
                ephemeral=True,
            )

        parent = interaction.guild.get_channel(settings["category_id"])
        if not isinstance(parent, discord.CategoryChannel):
            return await interaction.response.send_message(
                "The configured ticket category no longer exists.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        lock_key = (interaction.guild.id, interaction.user.id)
        appeal_lock = self._appeal_locks.setdefault(lock_key, asyncio.Lock())

        try:
            async with appeal_lock:
                existing = await get_open_ticket_for_user(
                    interaction.guild.id, interaction.user.id
                )
                if existing:
                    channel = interaction.guild.get_channel(existing["channel_id"])
                    if channel:
                        return await interaction.followup.send(
                            f"You already have an open ticket: {channel.mention}",
                            ephemeral=True,
                        )
                    await close_ticket(
                        existing["channel_id"],
                        self.bot.user.id if self.bot.user else 0,
                    )

                me = interaction.guild.me
                if me is None:
                    return await interaction.followup.send(
                        "I am not ready yet. Try again in a moment.",
                        ephemeral=True,
                    )

                staff_roles = await self._get_staff_roles(interaction.guild)
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(
                        view_channel=False
                    ),
                    me: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_channels=True,
                    ),
                    interaction.user: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        attach_files=True,
                        embed_links=True,
                        read_message_history=True,
                    ),
                }
                for role in staff_roles:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        attach_files=True,
                        embed_links=True,
                        read_message_history=True,
                        manage_messages=True,
                    )

                channel = await interaction.guild.create_text_channel(
                    name=f"appeal-{case_id}-{slugify(interaction.user.display_name)}"[
                        :95
                    ],
                    category=parent,
                    overwrites=overwrites,
                    topic=f"Appeal for case #{case_id} | {interaction.user}",
                    reason=f"Appeal opened by {interaction.user}",
                )

                try:
                    ticket_id = await create_ticket(
                        interaction.guild.id,
                        channel.id,
                        interaction.user.id,
                        "Appeal",
                    )
                except aiosqlite.IntegrityError:
                    await channel.delete(reason="Duplicate appeal prevented")
                    return await interaction.followup.send(
                        "You already have an open ticket.",
                        ephemeral=True,
                    )

                history = await get_user_cases(interaction.guild.id, interaction.user.id)
                moderator = self.bot.get_user(case["mod_id"]) or f"ID: {case['mod_id']}"
                created_at = int(datetime.fromisoformat(case["created_at"]).timestamp())

                embed = discord.Embed(
                    title=f"Case Appeal #{ticket_id}",
                    description=(
                        f"{interaction.user.mention} opened an appeal for case `#{case_id}`."
                    ),
                    color=COLOR_MOD,
                    timestamp=datetime.utcnow(),
                )
                embed.add_field(name="Case", value=f"#{case_id}", inline=True)
                embed.add_field(name="Action", value=case["action"].title(), inline=True)
                embed.add_field(name="Case Date", value=f"<t:{created_at}:F>", inline=True)
                embed.add_field(name="Original Moderator", value=str(moderator), inline=True)
                embed.add_field(
                    name="Total User Cases",
                    value=str(len(history)),
                    inline=True,
                )
                if case.get("duration"):
                    embed.add_field(name="Duration", value=case["duration"], inline=True)
                embed.add_field(
                    name="Original Reason",
                    value=short_text(case.get("reason"), 700),
                    inline=False,
                )
                embed.add_field(
                    name="Appeal Reason",
                    value=short_text(appeal_reason, 1000),
                    inline=False,
                )
                embed.set_footer(
                    text=f"Staff: {PREFIX}appeal accept <note> or {PREFIX}appeal deny <note>"
                )

                staff_ping = " ".join(role.mention for role in staff_roles)
                await channel.send(content=staff_ping or None, embed=embed)
                await interaction.followup.send(
                    f"Your appeal has been opened: {channel.mention}",
                    ephemeral=True,
                )

                await self._log_appeal_event(
                    interaction.guild,
                    title="Appeal Opened",
                    description=(
                        f"{interaction.user.mention} opened appeal ticket #{ticket_id} "
                        f"for case `#{case_id}` in {channel.mention}."
                    ),
                    color=COLOR_SUCCESS,
                )
        finally:
            if not appeal_lock.locked():
                self._appeal_locks.pop(lock_key, None)

    @commands.command(
        name="appealpanel",
        help="Post the case appeal panel with an appeal button.",
    )
    @commands.has_permissions(manage_guild=True)
    async def appeal_panel(self, ctx, channel: discord.TextChannel = None):
        """Usage: ,appealpanel [#channel]"""
        channel = channel or ctx.channel
        settings = await get_ticket_settings(ctx.guild.id)
        if not settings or not settings.get("category_id"):
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    title="Appeal Setup Missing",
                    description=f"Appeals use the ticket category. Run `{PREFIX}setticketcategory <category>` first.",
                    color=COLOR_ERROR,
                )
            )

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Appeal a Case",
            description=(
                "Use the button below to ask staff to review one of your moderation cases."
            ),
            color=COLOR_INFO,
        )
        embed.add_field(
            name="What You Need",
            value="Your case ID and a clear reason for the appeal.",
            inline=False,
        )
        embed.set_footer(text="Appeals create a private channel with staff.")
        await channel.send(embed=embed, view=self._build_panel_view())

        if channel != ctx.channel:
            await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    description=f"Appeal panel sent to {channel.mention}.",
                    color=COLOR_SUCCESS,
                )
            )

    @commands.group(
        name="appeal",
        invoke_without_command=True,
        help="Accept, deny, or close the current appeal ticket.",
    )
    async def appeal(self, ctx):
        """Usage: ,appeal <accept|deny|close> [note]"""
        await ctx.send(
            embed=await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Appeal Commands",
                description=(
                    f"`{PREFIX}appeal accept <note>`\n"
                    f"`{PREFIX}appeal deny <note>`\n"
                    f"`{PREFIX}appeal close`"
                ),
                color=COLOR_INFO,
            )
        )

    async def _decide_appeal(self, ctx, decision: str, note: str):
        if not isinstance(ctx.author, discord.Member) or not await self._is_appeal_staff(
            ctx.author
        ):
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    description="Only appeal staff can decide appeals.",
                    color=COLOR_ERROR,
                )
            )

        ticket = await get_ticket_by_channel(ctx.channel.id)
        if not ticket or ticket["status"] != "open" or ticket["category_name"] != "Appeal":
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    description="This command only works inside an open appeal ticket.",
                    color=COLOR_ERROR,
                )
            )

        note = note.strip()
        if not note:
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    description="Add a short decision note for the case history.",
                    color=COLOR_ERROR,
                )
            )

        case_id = await add_case(
            ctx.guild.id,
            ticket["user_id"],
            ctx.author.id,
            "note",
            f"Appeal {decision} in ticket #{ticket['id']}: {note}",
        )
        color = COLOR_SUCCESS if decision == "accepted" else COLOR_ERROR
        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title=f"Appeal {decision.title()}",
            description=f"Decision saved as case `#{case_id}`.",
            color=color,
        )
        embed.add_field(name="Decision Note", value=short_text(note, 900), inline=False)
        await ctx.send(embed=embed)
        await self._log_appeal_event(
            ctx.guild,
            title=f"Appeal {decision.title()}",
            description=(
                f"Appeal ticket #{ticket['id']} was {decision} by {ctx.author.mention}. "
                f"Decision saved as case `#{case_id}`."
            ),
            color=color,
        )

    @appeal.command(name="accept", help="Accept the current appeal and log a note.")
    async def appeal_accept(self, ctx, *, note: str):
        """Usage: ,appeal accept <note>"""
        await self._decide_appeal(ctx, "accepted", note)

    @appeal.command(name="deny", help="Deny the current appeal and log a note.")
    async def appeal_deny(self, ctx, *, note: str):
        """Usage: ,appeal deny <note>"""
        await self._decide_appeal(ctx, "denied", note)

    @appeal.command(name="close", help="Close the current appeal ticket.")
    async def appeal_close(self, ctx):
        """Usage: ,appeal close"""
        if not isinstance(ctx.author, discord.Member) or not await self._is_appeal_staff(
            ctx.author
        ):
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    description="Only appeal staff can close appeals.",
                    color=COLOR_ERROR,
                )
            )

        ticket = await get_ticket_by_channel(ctx.channel.id)
        if not ticket or ticket["status"] != "open" or ticket["category_name"] != "Appeal":
            return await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    description="This command only works inside an open appeal ticket.",
                    color=COLOR_ERROR,
                )
            )

        tickets_cog = self.bot.get_cog("Tickets")
        if tickets_cog and hasattr(tickets_cog, "_close_ticket_channel"):
            await ctx.send(
                embed=await make_embed(
                    self.bot,
                    guild=ctx.guild,
                    description="Closing appeal and saving transcript...",
                    color=COLOR_INFO,
                )
            )
            await tickets_cog._close_ticket_channel(ctx.channel, ctx.author, ticket)
            return

        await close_ticket(ctx.channel.id, ctx.author.id)
        await ctx.channel.delete(reason=f"Appeal closed by {ctx.author}")


async def setup(bot):
    await bot.add_cog(Appeals(bot))
