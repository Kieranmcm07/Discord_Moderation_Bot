"""
Self-assignable role buttons.

This feature gives members a clean way to opt into roles without needing staff
to manage those role changes manually.
"""

from __future__ import annotations

from datetime import datetime

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS
from utils.db import add_reaction_role, get_reaction_roles, remove_reaction_role
from utils.embeds import make_embed


class ReactionRoleButton(discord.ui.Button):
    """Persistent button that toggles one configured role."""

    def __init__(self, cog: "ReactionRoles", guild_id: int, role_id: int, label: str, emoji: str | None):
        super().__init__(
            label=label[:80],
            emoji=emoji or None,
            style=discord.ButtonStyle.secondary,
            custom_id=f"reaction-role:{guild_id}:{role_id}",
        )
        self.cog = cog
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_button(interaction, self.role_id)


class ReactionRoles(commands.Cog, name="Reaction Roles"):
    """Commands and button handlers for self-assignable roles."""

    def __init__(self, bot):
        self.bot = bot
        self._registered_guilds: set[int] = set()

    async def cog_load(self):
        await self._register_views()

    @commands.Cog.listener()
    async def on_ready(self):
        await self._register_views()

    async def _register_views(self):
        """Register persistent views so role buttons survive bot restarts."""
        for guild in self.bot.guilds:
            if guild.id in self._registered_guilds:
                continue

            entries = await get_reaction_roles(guild.id)
            if not entries:
                continue

            view = discord.ui.View(timeout=None)
            for entry in entries[:25]:
                view.add_item(
                    ReactionRoleButton(
                        self,
                        guild.id,
                        entry["role_id"],
                        entry["label"],
                        entry.get("emoji"),
                    )
                )
            self.bot.add_view(view)
            self._registered_guilds.add(guild.id)

    async def handle_button(self, interaction: discord.Interaction, role_id: int):
        """Add or remove the selected role for the clicking member."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "This button only works inside a server.",
                ephemeral=True,
            )

        configured_role_ids = {
            entry["role_id"] for entry in await get_reaction_roles(interaction.guild.id)
        }
        if role_id not in configured_role_ids:
            return await interaction.response.send_message(
                "That role button is no longer active. Ask a staff member to post a fresh panel.",
                ephemeral=True,
            )

        role = interaction.guild.get_role(role_id)
        if role is None:
            return await interaction.response.send_message(
                "That role no longer exists.",
                ephemeral=True,
            )

        me = interaction.guild.me
        if me is None or role >= me.top_role:
            return await interaction.response.send_message(
                "I cannot manage that role because it is above my highest role.",
                ephemeral=True,
            )

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="Reaction role toggle")
            return await interaction.response.send_message(
                f"Removed {role.mention}.",
                ephemeral=True,
            )

        await interaction.user.add_roles(role, reason="Reaction role toggle")
        await interaction.response.send_message(
            f"Added {role.mention}.",
            ephemeral=True,
        )

    @commands.command(name="rradd", help="Add or update a self-assignable role option.")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rradd(self, ctx, role: discord.Role, *, details: str | None = None):
        """
        Usage: ,rradd @role [Label | Emoji]

        The label defaults to the role name. The emoji is optional.
        """
        if role == ctx.guild.default_role:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Invalid Role",
                description="`@everyone` cannot be used as a self-assignable role.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        if role >= ctx.guild.me.top_role:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Role Too High",
                description="Move my role above that role first so I can assign it.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        label = role.name
        emoji = None
        if details:
            parts = [part.strip() for part in details.split("|")]
            if parts and parts[0]:
                label = parts[0]
            if len(parts) > 1 and parts[1]:
                emoji = parts[1]

        await add_reaction_role(ctx.guild.id, role.id, label, emoji)
        self._registered_guilds.discard(ctx.guild.id)
        await self._register_views()

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Reaction Role Saved",
            description=f"{role.mention} is ready to be used in a role panel.",
            color=COLOR_SUCCESS,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Label", value=label, inline=True)
        embed.add_field(name="Emoji", value=emoji or "None", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="rrremove", help="Remove a self-assignable role option.")
    @commands.has_permissions(manage_roles=True)
    async def rrremove(self, ctx, role: discord.Role):
        await remove_reaction_role(ctx.guild.id, role.id)
        self._registered_guilds.discard(ctx.guild.id)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Reaction Role Removed",
            description=f"{role.mention} was removed from the self-assignable role list.",
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(name="rrlist", help="List the configured self-assignable roles.")
    @commands.has_permissions(manage_roles=True)
    async def rrlist(self, ctx):
        entries = await get_reaction_roles(ctx.guild.id)
        if not entries:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Reaction Roles",
                description="No self-assignable roles are configured yet.",
                color=COLOR_INFO,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Reaction Roles",
            description=f"{len(entries)} role option(s) configured.",
            color=COLOR_INFO,
        )
        for entry in entries[:20]:
            role = ctx.guild.get_role(entry["role_id"])
            role_name = role.mention if role else f"`{entry['role_id']}`"
            emoji = f"{entry['emoji']} " if entry.get("emoji") else ""
            embed.add_field(
                name=f"{emoji}{entry['label']}",
                value=f"Role: {role_name}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="rrpanel", help="Post a self-assignable role panel with buttons.")
    @commands.has_permissions(manage_roles=True)
    async def rrpanel(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        entries = await get_reaction_roles(ctx.guild.id)
        if not entries:
            embed = await make_embed(
                self.bot,
                guild=ctx.guild,
                title="Nothing To Post",
                description="Add at least one role first with `,rradd @role [Label | Emoji]`.",
                color=COLOR_ERROR,
            )
            return await ctx.send(embed=embed)

        embed = await make_embed(
            self.bot,
            guild=ctx.guild,
            title="Choose Your Roles",
            description=(
                "Use the buttons below to add or remove roles from yourself.\n"
                "Pressing the same button again removes the role."
            ),
            color=COLOR_INFO,
            timestamp=datetime.utcnow(),
        )

        view = discord.ui.View(timeout=None)
        for entry in entries[:25]:
            view.add_item(
                ReactionRoleButton(
                    self,
                    ctx.guild.id,
                    entry["role_id"],
                    entry["label"],
                    entry.get("emoji"),
                )
            )

        await channel.send(embed=embed, view=view)
        if channel != ctx.channel:
            confirm = await make_embed(
                self.bot,
                guild=ctx.guild,
                description=f"Reaction-role panel sent to {channel.mention}.",
                color=COLOR_SUCCESS,
            )
            await ctx.send(embed=confirm)


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
