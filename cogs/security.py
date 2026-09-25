"""Private, read-only server security reports and permission explanations."""

import asyncio
import io
from collections import Counter, defaultdict

import discord
from discord.ext import commands

from config import COLOR_INFO, COLOR_WARN, PREFIX, resolve_mod_log_channel_id
from utils.db import (
    get_autorole,
    get_guild_settings,
    get_reaction_roles,
    get_sentinel_settings,
    get_ticket_settings,
)
from utils.errors import SafeView
from utils.security import (
    ACCESS_PERMISSIONS,
    audit_permissions,
    build_report,
    explain_access,
    label,
    safe_name,
)


class SecurityView(SafeView):
    """Paginate a private report; recheck guild membership and permissions on use."""

    def __init__(self, cog, guild_id, author_id, findings):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id
        self.findings = findings
        self.generated_at = discord.utils.utcnow()
        self.page = 0
        self.lock = asyncio.Lock()
        self.update_buttons()

    @property
    def pages(self):
        return max(1, (len(self.findings) + 3) // 4)

    def update_buttons(self):
        self.previous.disabled = self.page == 0
        self.next_page.disabled = self.page >= self.pages - 1

    async def interaction_check(self, interaction):
        # This panel lives in a DM; permissions must come from the original server.
        guild = self.cog.bot.get_guild(self.guild_id)
        member = guild.get_member(interaction.user.id) if guild else None
        if (
            interaction.user.id == self.author_id
            and member
            and member.guild_permissions.manage_guild
        ):
            return True
        await interaction.response.send_message(
            "Only the requester, while still a member with Manage Server, can use this report.",
            ephemeral=True,
        )
        return False

    def embed(self, guild):
        counts = Counter(f.severity for f in self.findings)
        embed = discord.Embed(
            title="Server Security Center",
            description=(
                f"**{safe_name(guild.name)}**\n"
                f"Critical: **{counts['CRITICAL']}** · Warning: **{counts['WARNING']}** · "
                f"Review: **{counts['REVIEW']}**\n"
                "Checks configured public roles, staff logs, and text-channel send-deny exceptions. "
                "Review items may be intentional."
            ),
            color=COLOR_WARN if counts['CRITICAL'] or counts['WARNING'] else COLOR_INFO,
            timestamp=self.generated_at,
        )
        for finding in self.findings[self.page * 4:(self.page + 1) * 4]:
            value = f"{finding.detail}\n**Suggested action:** {finding.recommendation}"
            embed.add_field(
                name=f"{finding.severity} · {finding.title}",
                value=value[:1020] + ("…" if len(value) > 1020 else ""), inline=False,
            )
        if not self.findings:
            embed.add_field(name="Checks complete", value="No findings in this scope; this is not a security certification.")
        embed.set_footer(text=f"Page {self.page + 1}/{self.pages} · Controls expire after 5 minutes · Export includes full details")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        async with self.lock:
            self.page = max(0, self.page - 1)
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embed(self.cog.bot.get_guild(self.guild_id)), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        async with self.lock:
            self.page = min(self.pages - 1, self.page + 1)
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embed(self.cog.bot.get_guild(self.guild_id)), view=self)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction, button):
        await interaction.response.defer()
        async with self.lock:
            guild = self.cog.bot.get_guild(self.guild_id)
            self.findings = await self.cog.scan(guild)
            self.generated_at = discord.utils.utcnow()
            self.page = 0
            self.update_buttons()
            await interaction.edit_original_response(embed=self.embed(guild), view=self)

    @discord.ui.button(label="Export report", style=discord.ButtonStyle.secondary)
    async def export(self, interaction, button):
        guild = self.cog.bot.get_guild(self.guild_id)
        payload = build_report(guild, self.findings, self.generated_at).encode("utf-8")
        await interaction.response.send_message(
            file=discord.File(io.BytesIO(payload), filename=f"security-{guild.id}.txt"),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )


class Security(commands.Cog, name="Server Security"):
    """Explain access and review server permissions without changing them."""

    def __init__(self, bot):
        self.bot = bot

    async def scan(self, guild):
        settings = await get_guild_settings(guild.id) or {}
        tickets = await get_ticket_settings(guild.id) or {}
        sentinel = await get_sentinel_settings(guild.id)
        reaction_roles = await get_reaction_roles(guild.id)
        autorole = await get_autorole(guild.id)
        public_ids = {entry['role_id'] for entry in reaction_roles}
        if autorole:
            public_ids.add(autorole)
        logs = defaultdict(list)
        mod_log = resolve_mod_log_channel_id(settings)
        for channel_id, purpose in (
            (mod_log, "Moderation log"),
            (settings.get('message_log_channel_id'), "Message audit"),
            (tickets.get('log_channel_id'), "Ticket transcripts"),
            (sentinel.get('log_channel_id') or mod_log, "Sentinel alerts"),
        ):
            if channel_id:
                logs[channel_id].append(purpose)
        return audit_permissions(guild, public_role_ids=public_ids, log_channels=logs)

    async def send_private(self, ctx, **kwargs):
        try:
            await ctx.author.send(**kwargs, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await ctx.send("I couldn't DM your report. Enable direct messages from this server and run the command again.")
            return False
        await ctx.send("Sent your private security report by DM.", allowed_mentions=discord.AllowedMentions.none())
        return True

    @commands.command(
        name="securityaudit",
        aliases=["security"],
        help="Privately audit public roles, staff logs, and channel lock exceptions.",
        usage=f"{PREFIX}securityaudit",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def security_audit(self, ctx):
        findings = await self.scan(ctx.guild)
        view = SecurityView(self, ctx.guild.id, ctx.author.id, findings)
        if not await self.send_private(ctx, embed=view.embed(ctx.guild), view=view):
            view.stop()

    @commands.command(
        name="access",
        help="Privately explain a member's effective text-channel permissions.",
        usage=f"{PREFIX}access @member [#channel]",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.cooldown(2, 10, commands.BucketType.user)
    async def access(self, ctx, member: discord.Member, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != ctx.guild.id:
            return await ctx.send("Choose a text channel in this server, for example " + f"`{PREFIX}access @member #general`.")
        effective, trace = explain_access(member, channel)
        embed = discord.Embed(
            title="Channel Access Explained",
            description=f"**{safe_name(member.display_name)}** in **#{safe_name(channel.name)}**\n"
                        "Effective permissions from the bot's current Discord state.",
            color=COLOR_INFO,
        )
        embed.add_field(name="Effective access", value="\n".join(
            f"{'Allowed' if getattr(effective, p) else 'Denied'} — {label(p)}" for p in ACCESS_PERMISSIONS
        ), inline=False)
        for index, line in enumerate(trace[:8], 1):
            embed.add_field(name=f"Permission trace {index}", value=line[:1000], inline=False)
        # Detailed role lists can exceed Discord's total embed limit; the file is complete.
        while len(embed) > 5500:
            embed.remove_field(len(embed.fields) - 1)
        embed.set_footer(text="Full trace in attachment · Text channels only · AutoMod and slowmode can still prevent messages")
        report = (
            f"Access report: {member} ({member.id}) in #{channel.name} ({channel.id})\n"
            f"Server: {ctx.guild.name} ({ctx.guild.id})\nGenerated: {discord.utils.utcnow().isoformat()}\n\n"
            + "\n".join(f"{label(p)}: {'allowed' if getattr(effective, p) else 'denied'}" for p in ACCESS_PERMISSIONS)
            + "\n\nOverwrite trace (inputs, followed by timeout/implicit restrictions):\n" + "\n".join(trace)
            + "\n\nRole allows beat role denies; member overwrites apply afterwards. Role position does not decide channel access."
            + "\nThis explains permissions, not AutoMod, slowmode, verification, or Discord service restrictions."
        )
        await self.send_private(ctx, embed=embed, file=discord.File(
            io.BytesIO(report.encode('utf-8')), filename=f"access-{member.id}-{channel.id}.txt",
        ))


async def setup(bot):
    await bot.add_cog(Security(bot))
