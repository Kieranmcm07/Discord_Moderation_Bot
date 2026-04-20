"""
cogs/server_management.py - utility commands for managing the server itself.
"""

import asyncio
from datetime import datetime

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS
from utils.db import (
    clear_autorole,
    clear_sticky_message,
    get_all_sticky_messages,
    get_autorole,
    get_sticky_message,
    set_autorole,
    set_sticky_message,
    update_sticky_message_id,
)


NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


class ServerManagement(commands.Cog, name="Server Management"):
    """Server info and management utilities."""

    def __init__(self, bot):
        self.bot = bot
        self._sticky_refresh_tasks: dict[int, asyncio.Task] = {}

    def cog_unload(self):
        for task in self._sticky_refresh_tasks.values():
            task.cancel()
        self._sticky_refresh_tasks.clear()

    def _schedule_sticky_refresh(self, channel: discord.TextChannel):
        existing_task = self._sticky_refresh_tasks.get(channel.id)
        if existing_task:
            existing_task.cancel()

        self._sticky_refresh_tasks[channel.id] = asyncio.create_task(
            self._refresh_sticky_message(channel)
        )

    async def _refresh_sticky_message(self, channel: discord.TextChannel):
        try:
            await asyncio.sleep(5)
            sticky = await get_sticky_message(channel.id)
            if not sticky:
                return

            previous_message_id = sticky.get("bot_message_id")
            if previous_message_id:
                try:
                    previous_message = await channel.fetch_message(previous_message_id)
                    await previous_message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            sticky_embed = discord.Embed(
                description=sticky["content"],
                color=COLOR_INFO,
                timestamp=datetime.utcnow(),
            )
            sticky_embed.set_footer(text="Sticky message")
            sticky_message = await channel.send(embed=sticky_embed)
            await update_sticky_message_id(channel.id, sticky_message.id)
        except asyncio.CancelledError:
            return
        finally:
            current_task = self._sticky_refresh_tasks.get(channel.id)
            if current_task is asyncio.current_task():
                self._sticky_refresh_tasks.pop(channel.id, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        role_id = await get_autorole(member.guild.id)
        if not role_id:
            return

        role = member.guild.get_role(role_id)
        if role is None:
            await clear_autorole(member.guild.id)
            return

        try:
            await member.add_roles(role, reason="Automatic role assignment")
        except discord.Forbidden:
            return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        sticky = await get_sticky_message(message.channel.id)
        if not sticky:
            return

        if isinstance(message.channel, discord.TextChannel):
            self._schedule_sticky_refresh(message.channel)

    @commands.command(
        name="serverinfo",
        aliases=["guildinfo", "si"],
        help="Shows info about the server.",
    )
    async def server_info(self, ctx):
        """Usage: ,serverinfo"""
        guild = ctx.guild
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        bots = sum(1 for member in guild.members if member.bot)
        humans = guild.member_count - bots

        embed = discord.Embed(
            title=guild.name,
            color=COLOR_INFO,
            timestamp=datetime.utcnow(),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)

        embed.add_field(name="Owner", value=str(guild.owner), inline=True)
        embed.add_field(name="Server ID", value=str(guild.id), inline=True)
        embed.add_field(
            name="Created",
            value=f"<t:{int(guild.created_at.timestamp())}:D>",
            inline=True,
        )
        embed.add_field(
            name="Members",
            value=(
                f"Total: **{guild.member_count}**\n"
                f"Humans: **{humans}** | Bots: **{bots}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Channels",
            value=(
                f"Text: **{text_channels}** | Voice: **{voice_channels}** | "
                f"Categories: **{categories}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Emoji",
            value=f"**{len(guild.emojis)}** / {guild.emoji_limit}",
            inline=True,
        )
        embed.add_field(
            name="Verification Level",
            value=str(guild.verification_level).title(),
            inline=True,
        )
        embed.add_field(
            name="Boosts",
            value=(
                f"**{guild.premium_subscription_count}** boosts "
                f"(Tier {guild.premium_tier})"
            ),
            inline=True,
        )
        embed.add_field(
            name="Roles",
            value=f"**{len(guild.roles) - 1}** roles",
            inline=True,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="userinfo",
        aliases=["whois", "ui"],
        help="Shows info about a user.",
    )
    async def user_info(self, ctx, member: discord.Member = None):
        """Usage: ,userinfo [@user]"""
        member = member or ctx.author
        roles = [
            role.mention for role in reversed(member.roles) if role.name != "@everyone"
        ]
        roles_str = ", ".join(roles[:15]) if roles else "None"
        if len(roles) > 15:
            roles_str += f" (+{len(roles) - 15} more)"

        embed = discord.Embed(
            title=str(member),
            color=member.color if member.color.value else COLOR_INFO,
            timestamp=datetime.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User ID", value=str(member.id), inline=True)
        embed.add_field(name="Bot?", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="Nickname", value=member.nick or "None", inline=True)
        embed.add_field(
            name="Account Created",
            value=(
                f"<t:{int(member.created_at.timestamp())}:D> "
                f"(<t:{int(member.created_at.timestamp())}:R>)"
            ),
            inline=False,
        )

        if member.joined_at:
            embed.add_field(
                name="Joined Server",
                value=(
                    f"<t:{int(member.joined_at.timestamp())}:D> "
                    f"(<t:{int(member.joined_at.timestamp())}:R>)"
                ),
                inline=False,
            )

        embed.add_field(name=f"Roles ({len(roles)})", value=roles_str, inline=False)
        if member.timed_out_until:
            embed.add_field(
                name="Timed Out Until",
                value=f"<t:{int(member.timed_out_until.timestamp())}:F>",
                inline=False,
            )

        await ctx.send(embed=embed)

    @commands.command(
        name="avatar", aliases=["av", "pfp"], help="Show a user's avatar."
    )
    async def avatar(self, ctx, member: discord.Member = None):
        """Usage: ,avatar [@user]"""
        member = member or ctx.author
        embed = discord.Embed(
            title=f"{member.display_name}'s Avatar",
            color=COLOR_INFO,
        )
        embed.set_image(url=member.display_avatar.url)

        avatar = member.display_avatar
        links = (
            f"[PNG]({avatar.with_format('png').url}) | "
            f"[JPG]({avatar.with_format('jpg').url}) | "
            f"[WEBP]({avatar.with_format('webp').url})"
        )
        if avatar.is_animated():
            links += f" | [GIF]({avatar.with_format('gif').url})"
        embed.description = links
        await ctx.send(embed=embed)

    @commands.command(name="roleinfo", aliases=["ri"], help="Shows info about a role.")
    async def role_info(self, ctx, *, role: discord.Role):
        """Usage: ,roleinfo <role name or mention>"""
        embed = discord.Embed(
            title=role.name,
            color=role.color if role.color.value else COLOR_INFO,
        )
        embed.add_field(name="Role ID", value=str(role.id), inline=True)
        embed.add_field(name="Colour", value=str(role.color), inline=True)
        embed.add_field(name="Position", value=str(role.position), inline=True)
        embed.add_field(name="Members", value=str(len(role.members)), inline=True)
        embed.add_field(
            name="Mentionable",
            value="Yes" if role.mentionable else "No",
            inline=True,
        )
        embed.add_field(
            name="Hoisted", value="Yes" if role.hoist else "No", inline=True
        )
        embed.add_field(
            name="Created",
            value=f"<t:{int(role.created_at.timestamp())}:D>",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="lock", help="Lock a channel so @everyone can't send messages."
    )
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(
        self, ctx, channel: discord.TextChannel = None, *, reason: str = None
    ):
        """Usage: ,lock [#channel] [reason]"""
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(
            ctx.guild.default_role,
            overwrite=overwrite,
            reason=reason,
        )
        await channel.send(
            embed=discord.Embed(
                description=(
                    "This channel has been locked."
                    f"{f' **Reason:** {reason}' if reason else ''}"
                ),
                color=COLOR_ERROR,
            )
        )

    @commands.command(name="unlock", help="Unlock a previously locked channel.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(
        self, ctx, channel: discord.TextChannel = None, *, reason: str = None
    ):
        """Usage: ,unlock [#channel] [reason]"""
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(
            ctx.guild.default_role,
            overwrite=overwrite,
            reason=reason,
        )
        await channel.send(
            embed=discord.Embed(
                description="This channel has been unlocked.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="announce",
        help="Send a formatted announcement embed to a channel.",
    )
    @commands.has_permissions(manage_messages=True)
    async def announce(self, ctx, channel: discord.TextChannel, *, message: str):
        """Usage: ,announce #channel <message>"""
        embed = discord.Embed(
            description=message,
            color=COLOR_INFO,
            timestamp=datetime.utcnow(),
        )
        embed.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None,
        )
        embed.set_footer(text=f"Announcement by {ctx.author}")
        await channel.send(embed=embed)

        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

    @commands.command(
        name="poll",
        aliases=["vote"],
        help="Create a reaction poll with up to 10 options.",
    )
    @commands.has_permissions(manage_messages=True)
    async def poll(self, ctx, *, prompt: str):
        """Usage: ,poll Question | Option 1 | Option 2 | [Option 3...]"""
        parts = [part.strip() for part in prompt.split("|") if part.strip()]
        if len(parts) < 3:
            return await ctx.send(
                embed=discord.Embed(
                    description="Use `,poll Question | Option 1 | Option 2` with at least two options.",
                    color=COLOR_ERROR,
                )
            )

        question, *options = parts
        if len(options) > 10:
            return await ctx.send(
                embed=discord.Embed(
                    description="Polls can have up to 10 options.",
                    color=COLOR_ERROR,
                )
            )

        embed = discord.Embed(
            title="Poll",
            description=question,
            color=COLOR_INFO,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"Poll by {ctx.author}")
        for index, option in enumerate(options):
            embed.add_field(
                name=f"{NUMBER_EMOJIS[index]} Option {index + 1}",
                value=option,
                inline=False,
            )

        poll_message = await ctx.send(embed=embed)
        for index in range(len(options)):
            await poll_message.add_reaction(NUMBER_EMOJIS[index])

    @commands.command(
        name="setautorole",
        help="Automatically give new members a role when they join.",
    )
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def setautorole_command(self, ctx, role: discord.Role):
        """Usage: ,setautorole <role>"""
        if role == ctx.guild.default_role:
            return await ctx.send(
                embed=discord.Embed(
                    description="You can't use @everyone as the autorole.",
                    color=COLOR_ERROR,
                )
            )

        if role >= ctx.guild.me.top_role:
            return await ctx.send(
                embed=discord.Embed(
                    description="I can't assign that role because it's equal to or higher than my top role.",
                    color=COLOR_ERROR,
                )
            )

        if role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(
                embed=discord.Embed(
                    description="You can't set an autorole that is equal to or higher than your top role.",
                    color=COLOR_ERROR,
                )
            )

        await set_autorole(ctx.guild.id, role.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"New members will now receive {role.mention} automatically.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="autorole",
        help="Show the currently configured autorole.",
    )
    @commands.has_permissions(manage_roles=True)
    async def autorole(self, ctx):
        role_id = await get_autorole(ctx.guild.id)
        if not role_id:
            return await ctx.send(
                embed=discord.Embed(
                    description="No autorole is configured.",
                    color=COLOR_INFO,
                )
            )

        role = ctx.guild.get_role(role_id)
        if role is None:
            await clear_autorole(ctx.guild.id)
            return await ctx.send(
                embed=discord.Embed(
                    description="The saved autorole no longer exists, so I cleared it.",
                    color=COLOR_ERROR,
                )
            )

        await ctx.send(
            embed=discord.Embed(
                description=f"New members currently receive {role.mention}.",
                color=COLOR_INFO,
            )
        )

    @commands.command(
        name="clearautorole",
        aliases=["removeautorole"],
        help="Disable automatic role assignment for new members.",
    )
    @commands.has_permissions(manage_roles=True)
    async def clearautorole_command(self, ctx):
        await clear_autorole(ctx.guild.id)
        await ctx.send(
            embed=discord.Embed(
                description="Autorole has been disabled.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="setsticky",
        help="Keep a sticky message at the bottom of a text channel.",
    )
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_messages=True, embed_links=True)
    async def setsticky(
        self,
        ctx,
        *,
        details: str,
    ):
        """Usage: ,setsticky [#channel] <message>"""
        channel = (
            ctx.message.channel_mentions[0]
            if ctx.message.channel_mentions
            else ctx.channel
        )
        content = details
        if ctx.message.channel_mentions:
            mention = ctx.message.channel_mentions[0].mention
            content = content.replace(mention, "", 1).strip()
        else:
            content = content.strip()

        if not content:
            return await ctx.send(
                embed=discord.Embed(
                    description="Give me a message to pin as a sticky.",
                    color=COLOR_ERROR,
                )
            )

        existing_sticky = await get_sticky_message(channel.id)
        if existing_sticky and existing_sticky.get("bot_message_id"):
            try:
                old_message = await channel.fetch_message(
                    existing_sticky["bot_message_id"]
                )
                await old_message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        existing_task = self._sticky_refresh_tasks.get(channel.id)
        if existing_task:
            existing_task.cancel()

        await set_sticky_message(ctx.guild.id, channel.id, content, ctx.author.id)
        sticky_embed = discord.Embed(
            description=content,
            color=COLOR_INFO,
            timestamp=datetime.utcnow(),
        )
        sticky_embed.set_footer(text="Sticky message")
        sticky_message = await channel.send(embed=sticky_embed)
        await update_sticky_message_id(channel.id, sticky_message.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"Sticky message set for {channel.mention}.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="sticky",
        help="Show the sticky message for a channel.",
    )
    @commands.has_permissions(manage_channels=True)
    async def sticky(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        sticky = await get_sticky_message(channel.id)
        if not sticky:
            return await ctx.send(
                embed=discord.Embed(
                    description=f"No sticky message is set for {channel.mention}.",
                    color=COLOR_INFO,
                )
            )

        embed = discord.Embed(
            title=f"Sticky Message - #{channel.name}",
            description=sticky["content"],
            color=COLOR_INFO,
        )
        await ctx.send(embed=embed)

    @commands.command(
        name="stickies",
        help="List every sticky message configured in this server.",
    )
    @commands.has_permissions(manage_channels=True)
    async def stickies(self, ctx):
        entries = await get_all_sticky_messages(ctx.guild.id)
        if not entries:
            return await ctx.send(
                embed=discord.Embed(
                    description="No sticky messages are configured.",
                    color=COLOR_INFO,
                )
            )

        embed = discord.Embed(title="Sticky Messages", color=COLOR_INFO)
        for entry in entries[:15]:
            channel = ctx.guild.get_channel(entry["channel_id"])
            channel_name = channel.mention if channel else f"`{entry['channel_id']}`"
            content = entry["content"]
            if len(content) > 100:
                content = f"{content[:97]}..."
            embed.add_field(name=channel_name, value=content, inline=False)

        if len(entries) > 15:
            embed.set_footer(text=f"Showing 15 of {len(entries)} sticky messages")

        await ctx.send(embed=embed)

    @commands.command(
        name="clearsticky",
        aliases=["removesticky"],
        help="Remove the sticky message from a text channel.",
    )
    @commands.has_permissions(manage_channels=True)
    async def clearsticky(self, ctx, channel: discord.TextChannel = None):
        """Usage: ,clearsticky [#channel]"""
        channel = channel or ctx.channel
        sticky = await get_sticky_message(channel.id)
        if not sticky:
            return await ctx.send(
                embed=discord.Embed(
                    description=f"No sticky message is set for {channel.mention}.",
                    color=COLOR_INFO,
                )
            )

        existing_task = self._sticky_refresh_tasks.get(channel.id)
        if existing_task:
            existing_task.cancel()

        if sticky.get("bot_message_id"):
            try:
                sticky_message = await channel.fetch_message(sticky["bot_message_id"])
                await sticky_message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        await clear_sticky_message(channel.id)
        await ctx.send(
            embed=discord.Embed(
                description=f"Sticky message removed from {channel.mention}.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="nick",
        aliases=["nickname"],
        help="Change a member's nickname.",
    )
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: str):
        """Usage: ,nick @user <new nickname>"""
        if member == ctx.guild.owner:
            return await ctx.send(
                embed=discord.Embed(
                    description="You can't change the server owner's nickname.",
                    color=COLOR_ERROR,
                )
            )

        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(
                embed=discord.Embed(
                    description="You can't change the nickname of someone with an equal or higher role.",
                    color=COLOR_ERROR,
                )
            )

        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(
                embed=discord.Embed(
                    description="I can't change that nickname because their top role is equal to or higher than mine.",
                    color=COLOR_ERROR,
                )
            )

        old_name = member.display_name
        await member.edit(nick=nickname[:32], reason=f"Changed by {ctx.author}")
        await ctx.send(
            embed=discord.Embed(
                description=(
                    f"Updated {member.mention}'s nickname from **{old_name}** to "
                    f"**{member.display_name}**."
                ),
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(
        name="resetnick",
        aliases=["clearnick"],
        help="Reset a member's nickname back to their username.",
    )
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def resetnick(self, ctx, member: discord.Member):
        """Usage: ,resetnick @user"""
        if member.nick is None:
            return await ctx.send(
                embed=discord.Embed(
                    description=f"{member.mention} does not have a server nickname set.",
                    color=COLOR_INFO,
                )
            )

        if member == ctx.guild.owner:
            return await ctx.send(
                embed=discord.Embed(
                    description="You can't reset the server owner's nickname.",
                    color=COLOR_ERROR,
                )
            )

        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(
                embed=discord.Embed(
                    description="You can't reset the nickname of someone with an equal or higher role.",
                    color=COLOR_ERROR,
                )
            )

        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(
                embed=discord.Embed(
                    description="I can't reset that nickname because their top role is equal to or higher than mine.",
                    color=COLOR_ERROR,
                )
            )

        old_name = member.display_name
        await member.edit(nick=None, reason=f"Reset by {ctx.author}")
        await ctx.send(
            embed=discord.Embed(
                description=(
                    f"Reset {member.mention}'s nickname from **{old_name}** back to "
                    f"**{member.name}**."
                ),
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="botinfo", help="Shows info about the bot itself.")
    async def show_bot_info(self, ctx):
        """Usage: ,botinfo"""
        bot = self.bot
        embed = discord.Embed(title=bot.user.name, color=COLOR_INFO)
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.add_field(name="Bot ID", value=str(bot.user.id), inline=True)
        embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
        embed.add_field(name="Users", value=str(len(bot.users)), inline=True)
        embed.add_field(name="Cogs", value=str(len(bot.cogs)), inline=True)
        embed.add_field(name="Commands", value=str(len(bot.commands)), inline=True)
        embed.add_field(name="Library", value="discord.py 2.x", inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ServerManagement(bot))
