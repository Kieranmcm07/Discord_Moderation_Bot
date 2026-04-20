"""
cogs/tickets.py - private support ticket system.
Users open tickets from a button panel, the bot creates a private channel,
and staff can manage or close it with transcript logging.
"""

from __future__ import annotations

import asyncio
import io
import re
from datetime import datetime

import aiosqlite
import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS
from utils.db import (
    add_ticket_category,
    add_ticket_role,
    close_ticket,
    create_ticket,
    get_open_ticket_for_user,
    get_ticket_by_channel,
    get_ticket_categories,
    get_ticket_roles,
    get_ticket_settings,
    remove_ticket_category,
    remove_ticket_role,
    upsert_ticket_settings,
)


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9-]+", "-", value.lower()).strip("-")
    return value or "ticket"


class TicketCreateButton(discord.ui.Button):
    def __init__(self, cog: "Tickets", category: dict):
        label = category["name"][:80]
        emoji = category.get("emoji") or None
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.primary,
            custom_id=f"tickets:create:{category['guild_id']}:{category['id']}",
        )
        self.cog = cog
        self.category = category

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_ticket_create(interaction, self.category)


class TicketCloseButton(discord.ui.Button):
    def __init__(self, cog: "Tickets"):
        super().__init__(
            label="Close Ticket",
            emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id="tickets:close",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_ticket_close(interaction)


class Tickets(commands.Cog, name="Tickets"):
    """Private support ticket system."""

    def __init__(self, bot):
        self.bot = bot
        self._registered_create_buttons: set[tuple[int, int]] = set()
        self._ticket_creation_locks: dict[tuple[int, int], asyncio.Lock] = {}

    async def cog_load(self):
        self.bot.add_view(self._build_close_view())
        await self._register_ticket_buttons()

    @commands.Cog.listener()
    async def on_ready(self):
        await self._register_ticket_buttons()

    def _build_close_view(self) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        view.add_item(TicketCloseButton(self))
        return view

    async def _register_ticket_buttons(self):
        for guild in self.bot.guilds:
            categories = await get_ticket_categories(guild.id)
            for category in categories:
                key = (category["guild_id"], category["id"])
                if key in self._registered_create_buttons:
                    continue

                view = discord.ui.View(timeout=None)
                view.add_item(TicketCreateButton(self, category))
                self.bot.add_view(view)
                self._registered_create_buttons.add(key)

    async def _refresh_ticket_buttons_for_guild(self, guild_id: int):
        categories = await get_ticket_categories(guild_id)
        for category in categories:
            key = (category["guild_id"], category["id"])
            if key in self._registered_create_buttons:
                continue

            view = discord.ui.View(timeout=None)
            view.add_item(TicketCreateButton(self, category))
            self.bot.add_view(view)
            self._registered_create_buttons.add(key)

    async def _get_staff_roles(self, guild: discord.Guild) -> list[discord.Role]:
        role_ids = await get_ticket_roles(guild.id)
        roles = []
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role:
                roles.append(role)
        return roles

    async def _is_ticket_staff(self, member: discord.Member) -> bool:
        if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
            return True

        role_ids = set(await get_ticket_roles(member.guild.id))
        return any(role.id in role_ids for role in member.roles)

    async def _build_ticket_panel_view(self, guild_id: int) -> discord.ui.View | None:
        categories = await get_ticket_categories(guild_id)
        if not categories:
            return None

        view = discord.ui.View(timeout=None)
        for category in categories[:5]:
            view.add_item(TicketCreateButton(self, category))
        return view

    async def _get_live_ticket_category(self, guild_id: int, category_id: int) -> dict | None:
        """Return the current saved category config for a ticket button click."""
        categories = await get_ticket_categories(guild_id)
        return next((item for item in categories if item["id"] == category_id), None)

    async def _build_transcript(self, channel: discord.TextChannel) -> discord.File:
        lines = [f"Transcript for #{channel.name}", ""]

        async for message in channel.history(limit=None, oldest_first=True):
            created = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            author = f"{message.author} ({message.author.id})"
            content = message.content or ""

            if message.attachments:
                attachment_urls = ", ".join(att.url for att in message.attachments)
                content = f"{content}\n[Attachments] {attachment_urls}".strip()

            if message.embeds and not content:
                content = "[Embed]"

            lines.append(f"[{created}] {author}: {content}")

        payload = "\n".join(lines).encode("utf-8")
        return discord.File(io.BytesIO(payload), filename=f"{channel.name}-transcript.txt")

    async def _log_ticket_event(
        self,
        guild: discord.Guild,
        *,
        title: str,
        description: str,
        color: int,
        ticket: dict | None = None,
        file: discord.File | None = None,
    ):
        settings = await get_ticket_settings(guild.id)
        if not settings or not settings.get("log_channel_id"):
            return

        log_channel = guild.get_channel(settings["log_channel_id"])
        if not log_channel:
            return

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow(),
        )

        if ticket:
            embed.add_field(name="Ticket ID", value=f"#{ticket['id']}", inline=True)
            embed.add_field(name="Category", value=ticket["category_name"], inline=True)

        await log_channel.send(embed=embed, file=file)

    async def handle_ticket_create(self, interaction: discord.Interaction, category: dict):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Tickets can only be created inside a server.",
                ephemeral=True,
            )
        lock_key = (interaction.guild.id, interaction.user.id)
        ticket_lock = self._ticket_creation_locks.setdefault(lock_key, asyncio.Lock())

        try:
            async with ticket_lock:
                live_category = await self._get_live_ticket_category(
                    interaction.guild.id,
                    category["id"],
                )
                if not live_category:
                    return await interaction.response.send_message(
                        "That ticket button is no longer active. Ask a staff member to post a fresh ticket panel.",
                        ephemeral=True,
                    )

                settings = await get_ticket_settings(interaction.guild.id)
                if not settings or not settings.get("category_id"):
                    return await interaction.response.send_message(
                        "Ticket setup is incomplete. Ask an admin to set a ticket category first.",
                        ephemeral=True,
                    )

                ticket_parent = interaction.guild.get_channel(settings["category_id"])
                if not isinstance(ticket_parent, discord.CategoryChannel):
                    return await interaction.response.send_message(
                        "The configured ticket category no longer exists.",
                        ephemeral=True,
                    )

                existing = await get_open_ticket_for_user(interaction.guild.id, interaction.user.id)
                if existing:
                    existing_channel = interaction.guild.get_channel(existing["channel_id"])
                    if not existing_channel:
                        await close_ticket(
                            existing["channel_id"],
                            self.bot.user.id if self.bot.user else 0,
                        )
                        existing = None

                if existing:
                    existing_channel = interaction.guild.get_channel(existing["channel_id"])
                    mention = existing_channel.mention if existing_channel else f"`{existing['channel_id']}`"
                    return await interaction.response.send_message(
                        f"You already have an open ticket: {mention}",
                        ephemeral=True,
                    )

                me = interaction.guild.me
                if me is None:
                    return await interaction.response.send_message(
                        "I am not ready yet. Try again in a moment.",
                        ephemeral=True,
                    )

                staff_roles = await self._get_staff_roles(interaction.guild)
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
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

                safe_user = slugify(interaction.user.display_name)
                safe_category = slugify(live_category["name"])
                channel_name = f"{safe_category}-{safe_user}"[:95]

                channel = await interaction.guild.create_text_channel(
                    name=channel_name,
                    category=ticket_parent,
                    overwrites=overwrites,
                    topic=f"Ticket for {interaction.user} | Category: {live_category['name']}",
                    reason=f"Ticket opened by {interaction.user}",
                )

                try:
                    ticket_id = await create_ticket(
                        interaction.guild.id,
                        channel.id,
                        interaction.user.id,
                        live_category["name"],
                    )
                except aiosqlite.IntegrityError:
                    await channel.delete(reason="Duplicate open ticket prevented")
                    existing = await get_open_ticket_for_user(interaction.guild.id, interaction.user.id)
                    existing_channel = (
                        interaction.guild.get_channel(existing["channel_id"])
                        if existing
                        else None
                    )
                    mention = existing_channel.mention if existing_channel else "your existing ticket"
                    return await interaction.response.send_message(
                        f"You already have an open ticket: {mention}",
                        ephemeral=True,
                    )

                ticket = await get_ticket_by_channel(channel.id)

                embed = discord.Embed(
                    title="Support Ticket Opened",
                    description=(
                        f"{interaction.user.mention}, thanks for opening a ticket.\n"
                        f"A member of staff will be with you soon.\n\n"
                        f"**Category:** {live_category['name']}\n"
                        f"**Ticket ID:** #{ticket_id}"
                    ),
                    color=COLOR_INFO,
                    timestamp=datetime.utcnow(),
                )
                if live_category.get("description"):
                    embed.add_field(
                        name="Details",
                        value=live_category["description"],
                        inline=False,
                    )
                embed.add_field(name="Opened By", value=interaction.user.mention, inline=True)
                embed.add_field(
                    name="Staff Roles",
                    value=", ".join(role.mention for role in staff_roles) if staff_roles else "None configured",
                    inline=True,
                )
                embed.set_footer(text="Use the button below or ,closeticket to close this ticket.")

                view = self._build_close_view()
                staff_ping = " ".join(role.mention for role in staff_roles)
                await channel.send(content=staff_ping or None, embed=embed, view=view)

                await interaction.response.send_message(
                    f"Your ticket has been created: {channel.mention}",
                    ephemeral=True,
                )

                await self._log_ticket_event(
                    interaction.guild,
                    title="Ticket Opened",
                    description=(
                        f"Ticket #{ticket_id} opened by {interaction.user.mention} in {channel.mention}."
                    ),
                    color=COLOR_SUCCESS,
                    ticket=ticket,
                )
        finally:
            if not ticket_lock.locked():
                self._ticket_creation_locks.pop(lock_key, None)

    async def handle_ticket_close(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                "This button only works inside ticket channels.",
                ephemeral=True,
            )

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Only server members can close tickets.",
                ephemeral=True,
            )

        ticket = await get_ticket_by_channel(interaction.channel.id)
        if not ticket or ticket["status"] != "open":
            return await interaction.response.send_message(
                "This channel is not an open ticket.",
                ephemeral=True,
            )

        if not await self._is_ticket_staff(interaction.user):
            return await interaction.response.send_message(
                "Only ticket staff can close tickets.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "Closing ticket and saving transcript...",
            ephemeral=True,
        )
        await self._close_ticket_channel(interaction.channel, interaction.user, ticket)

    async def _close_ticket_channel(
        self,
        channel: discord.TextChannel,
        closer: discord.Member,
        ticket: dict | None = None,
    ):
        ticket = ticket or await get_ticket_by_channel(channel.id)
        if not ticket or ticket["status"] != "open":
            return

        await close_ticket(channel.id, closer.id)
        transcript = await self._build_transcript(channel)
        owner = channel.guild.get_member(ticket["user_id"]) or self.bot.get_user(ticket["user_id"])

        await self._log_ticket_event(
            channel.guild,
            title="Ticket Closed",
            description=(
                f"Ticket #{ticket['id']} closed by {closer.mention}.\n"
                f"**Owner:** {owner or ticket['user_id']}\n"
                f"**Channel:** #{channel.name}"
            ),
            color=COLOR_ERROR,
            ticket=ticket,
            file=transcript,
        )

        await channel.send(
            embed=discord.Embed(
                description=f"🔒 Ticket closed by {closer.mention}. This channel will be deleted in 5 seconds.",
                color=COLOR_ERROR,
            )
        )
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket closed by {closer}")

    @commands.command(name="setticketcategory", help="Set the category where ticket channels are created.")
    @commands.has_permissions(manage_guild=True)
    async def set_ticket_category(self, ctx, category: discord.CategoryChannel):
        await upsert_ticket_settings(ctx.guild.id, category_id=category.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ Ticket channels will be created in **{category.name}**.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="setticketlog", help="Set the channel used for ticket logs and transcripts.")
    @commands.has_permissions(manage_guild=True)
    async def set_ticket_log(self, ctx, channel: discord.TextChannel):
        await upsert_ticket_settings(ctx.guild.id, log_channel_id=channel.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ Ticket logs will be sent to {channel.mention}.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="ticketroleadd", help="Allow a role to view and manage tickets.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_role_add(self, ctx, role: discord.Role):
        await add_ticket_role(ctx.guild.id, role.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ {role.mention} can now access tickets.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="ticketroleremove", help="Remove a role from ticket access.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_role_remove(self, ctx, role: discord.Role):
        await remove_ticket_role(ctx.guild.id, role.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ {role.mention} no longer has automatic ticket access.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="ticketroles", help="Show which roles currently have ticket access.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_roles(self, ctx):
        roles = await self._get_staff_roles(ctx.guild)
        description = "\n".join(role.mention for role in roles) if roles else "No ticket roles configured yet."
        await ctx.send(
            embed=discord.Embed(
                title="Ticket Staff Roles",
                description=description,
                color=COLOR_INFO,
            )
        )

    @commands.command(name="ticketcategoryadd", help="Add a ticket category button. Use | to split name, emoji, description.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_category_add(self, ctx, *, payload: str):
        parts = [part.strip() for part in payload.split("|")]
        name = parts[0] if parts else ""
        emoji = parts[1] if len(parts) > 1 and parts[1] else None
        description = parts[2] if len(parts) > 2 and parts[2] else None

        if not name:
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ Use `,ticketcategoryadd Name | Emoji | Description`.",
                    color=COLOR_ERROR,
                )
            )

        categories = await get_ticket_categories(ctx.guild.id)
        if len(categories) >= 5:
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ You can have up to 5 ticket categories because Discord button rows are limited.",
                    color=COLOR_ERROR,
                )
            )

        try:
            category_id = await add_ticket_category(ctx.guild.id, name, emoji, description)
        except aiosqlite.IntegrityError:
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ That ticket category already exists.",
                    color=COLOR_ERROR,
                )
            )

        await self._refresh_ticket_buttons_for_guild(ctx.guild.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ Added ticket category **{name}** with ID `{category_id}`.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="ticketcategoryremove", help="Remove a ticket category by its ID.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_category_remove(self, ctx, category_id: int):
        await remove_ticket_category(ctx.guild.id, category_id)
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ Removed ticket category `{category_id}`.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="ticketcategories", help="List the configured ticket categories.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_categories(self, ctx):
        categories = await get_ticket_categories(ctx.guild.id)
        if not categories:
            return await ctx.send(
                embed=discord.Embed(
                    description="No ticket categories configured yet.",
                    color=COLOR_INFO,
                )
            )

        embed = discord.Embed(title="Ticket Categories", color=COLOR_INFO)
        for category in categories:
            summary = category.get("description") or "No description"
            emoji = f"{category['emoji']} " if category.get("emoji") else ""
            embed.add_field(
                name=f"{emoji}{category['name']} (`{category['id']}`)",
                value=summary[:200],
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="ticketpanel", help="Post the ticket panel with category buttons.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_panel(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        settings = await get_ticket_settings(ctx.guild.id)
        categories = await get_ticket_categories(ctx.guild.id)

        if not settings or not settings.get("category_id"):
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ Set a ticket channel category first with `,setticketcategory #category`.",
                    color=COLOR_ERROR,
                )
            )

        if not categories:
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ Add at least one ticket category first with `,ticketcategoryadd`.",
                    color=COLOR_ERROR,
                )
            )

        view = await self._build_ticket_panel_view(ctx.guild.id)
        embed = discord.Embed(
            title="Create a Ticket",
            description=(
                "Press one of the buttons below to open a private ticket.\n"
                "You will get a channel only you and the configured staff roles can see."
            ),
            color=COLOR_INFO,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text="One open ticket per user.")
        await channel.send(embed=embed, view=view)

        await upsert_ticket_settings(ctx.guild.id, panel_channel_id=channel.id)
        if channel != ctx.channel:
            await ctx.send(
                embed=discord.Embed(
                    description=f"✅ Ticket panel sent to {channel.mention}.",
                    color=COLOR_SUCCESS,
                )
            )

    @commands.command(name="ticketsettings", help="Show the current ticket system setup.")
    @commands.has_permissions(manage_guild=True)
    async def ticket_settings(self, ctx):
        settings = await get_ticket_settings(ctx.guild.id) or {}
        roles = await self._get_staff_roles(ctx.guild)
        categories = await get_ticket_categories(ctx.guild.id)

        category_channel = ctx.guild.get_channel(settings.get("category_id", 0))
        log_channel = ctx.guild.get_channel(settings.get("log_channel_id", 0))
        panel_channel = ctx.guild.get_channel(settings.get("panel_channel_id", 0))

        embed = discord.Embed(title="Ticket Settings", color=COLOR_INFO)
        embed.add_field(
            name="Ticket Channel Category",
            value=category_channel.mention if category_channel else "Not set",
            inline=False,
        )
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "Not set",
            inline=False,
        )
        embed.add_field(
            name="Panel Channel",
            value=panel_channel.mention if panel_channel else "Not set",
            inline=False,
        )
        embed.add_field(
            name="Staff Roles",
            value=", ".join(role.mention for role in roles) if roles else "None",
            inline=False,
        )
        embed.add_field(
            name="Ticket Categories",
            value="\n".join(f"`{cat['id']}` {cat['name']}" for cat in categories) if categories else "None",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="ticketadd", help="Give another user access to the current ticket.")
    async def ticket_add(self, ctx, member: discord.Member):
        ticket = await get_ticket_by_channel(ctx.channel.id)
        if not ticket or ticket["status"] != "open":
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ This command only works inside an open ticket.",
                    color=COLOR_ERROR,
                )
            )

        if not await self._is_ticket_staff(ctx.author):
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ Only ticket staff can add users to a ticket.",
                    color=COLOR_ERROR,
                )
            )

        await ctx.channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            read_message_history=True,
            reason=f"Added to ticket by {ctx.author}",
        )
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ Added {member.mention} to this ticket.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="ticketremove", help="Remove a user's access from the current ticket.")
    async def ticket_remove(self, ctx, member: discord.Member):
        ticket = await get_ticket_by_channel(ctx.channel.id)
        if not ticket or ticket["status"] != "open":
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ This command only works inside an open ticket.",
                    color=COLOR_ERROR,
                )
            )

        if not await self._is_ticket_staff(ctx.author):
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ Only ticket staff can remove users from a ticket.",
                    color=COLOR_ERROR,
                )
            )

        if member.id == ticket["user_id"]:
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ You can't remove the ticket owner.",
                    color=COLOR_ERROR,
                )
            )

        await ctx.channel.set_permissions(member, overwrite=None, reason=f"Removed from ticket by {ctx.author}")
        await ctx.send(
            embed=discord.Embed(
                description=f"✅ Removed {member.mention} from this ticket.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="closeticket", help="Close the current ticket.")
    async def close_ticket_command(self, ctx):
        ticket = await get_ticket_by_channel(ctx.channel.id)
        if not ticket or ticket["status"] != "open":
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ This command only works inside an open ticket.",
                    color=COLOR_ERROR,
                )
            )

        if not await self._is_ticket_staff(ctx.author):
            return await ctx.send(
                embed=discord.Embed(
                    description="❌ Only ticket staff can close tickets.",
                    color=COLOR_ERROR,
                )
            )

        await ctx.send(
            embed=discord.Embed(
                description="Saving transcript and closing this ticket...",
                color=COLOR_INFO,
            )
        )
        await self._close_ticket_channel(ctx.channel, ctx.author, ticket)

    @commands.command(
        name="ticketrename",
        aliases=["renameticket"],
        help="Rename the current open ticket channel.",
    )
    async def ticket_rename(self, ctx, *, new_name: str):
        ticket = await get_ticket_by_channel(ctx.channel.id)
        if not ticket or ticket["status"] != "open":
            return await ctx.send(
                embed=discord.Embed(
                    description="This command only works inside an open ticket.",
                    color=COLOR_ERROR,
                )
            )

        if not await self._is_ticket_staff(ctx.author):
            return await ctx.send(
                embed=discord.Embed(
                    description="Only ticket staff can rename tickets.",
                    color=COLOR_ERROR,
                )
            )

        cleaned_name = slugify(new_name)
        if not cleaned_name:
            return await ctx.send(
                embed=discord.Embed(
                    description="Give the ticket a valid name using letters or numbers.",
                    color=COLOR_ERROR,
                )
            )

        old_name = ctx.channel.name
        updated_name = f"{slugify(ticket['category_name'])}-{cleaned_name}"[:95]
        await ctx.channel.edit(
            name=updated_name,
            reason=f"Ticket renamed by {ctx.author}",
        )
        await ctx.send(
            embed=discord.Embed(
                description=f"Renamed this ticket from **{old_name}** to **{updated_name}**.",
                color=COLOR_SUCCESS,
            )
        )
        await self._log_ticket_event(
            ctx.guild,
            title="Ticket Renamed",
            description=(
                f"Ticket #{ticket['id']} was renamed by {ctx.author.mention}.\n"
                f"**Old Name:** #{old_name}\n"
                f"**New Name:** #{updated_name}"
            ),
            color=COLOR_INFO,
            ticket=ticket,
        )


async def setup(bot):
    await bot.add_cog(Tickets(bot))
