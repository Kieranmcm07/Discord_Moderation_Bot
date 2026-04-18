"""
cogs/server_management.py - utility commands for managing the server itself.
"""

from datetime import datetime

import discord
from discord.ext import commands

from config import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS


class ServerManagement(commands.Cog, name="Server Management"):
    """Server info and management utilities."""

    def __init__(self, bot):
        self.bot = bot

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
        roles = [role.mention for role in reversed(member.roles) if role.name != "@everyone"]
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

    @commands.command(name="avatar", aliases=["av", "pfp"], help="Show a user's avatar.")
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
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(
            name="Created",
            value=f"<t:{int(role.created_at.timestamp())}:D>",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="lock", help="Lock a channel so @everyone can't send messages.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None, *, reason: str = None):
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
    async def unlock(self, ctx, channel: discord.TextChannel = None, *, reason: str = None):
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
