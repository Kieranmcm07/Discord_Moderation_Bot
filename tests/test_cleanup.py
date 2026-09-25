"""Check that shared commands and helpers preserve the existing workflows."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands

from cogs.moderation import Moderation
from cogs.music import Music
from cogs.tickets import Tickets
from utils.moderation import get_action_label, send_mod_log
from utils.tickets import get_staff_roles, ticket_overwrites


class PurgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Call the command directly without starting the temporary-ban background loop.
        self.cog = SimpleNamespace(delete_after_delay=AsyncMock())
        self.ctx = SimpleNamespace(
            message=SimpleNamespace(id=100),
            channel=SimpleNamespace(purge=AsyncMock()),
            send=AsyncMock(),
        )

    async def test_all_messages_and_target_filter_share_one_command(self):
        target = SimpleNamespace(id=50, mention="<@50>")
        for selected in (None, target):
            with self.subTest(target=selected):
                self.ctx.channel.purge.return_value = [self.ctx.message, SimpleNamespace(id=101)]
                await Moderation.purge.callback(self.cog, self.ctx, 10, selected)
                kwargs = self.ctx.channel.purge.call_args.kwargs
                self.assertEqual(kwargs["limit"], 11)
                self.assertTrue(kwargs["check"](self.ctx.message))
                matching = SimpleNamespace(id=101, author=target)
                other = SimpleNamespace(id=102, author=SimpleNamespace(id=51))
                self.assertTrue(kwargs["check"](matching))
                self.assertEqual(kwargs["check"](other), selected is None)
                self.assertIn("**1**", self.ctx.send.call_args.kwargs["embed"].description)

    async def test_missing_command_message_does_not_undercount(self):
        self.ctx.channel.purge.return_value = [SimpleNamespace(id=101), SimpleNamespace(id=102)]
        await Moderation.purge.callback(self.cog, self.ctx, 10)
        self.assertIn("**2**", self.ctx.send.call_args.kwargs["embed"].description)

    async def test_invalid_limit_never_deletes_messages(self):
        for amount in (0, 501):
            await Moderation.purge.callback(self.cog, self.ctx, amount)
        self.ctx.channel.purge.assert_not_awaited()


class SharedHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_permissions_keep_owner_bot_and_staff_access(self):
        everyone, bot, owner, staff = Mock(), Mock(), Mock(), Mock()
        guild = SimpleNamespace(default_role=everyone)
        permissions = ticket_overwrites(guild, bot, owner, [staff])
        self.assertFalse(permissions[everyone].view_channel)
        self.assertTrue(permissions[bot].manage_channels)
        self.assertTrue(permissions[owner].attach_files)
        self.assertTrue(permissions[owner].read_message_history)
        self.assertIsNone(permissions[owner].manage_messages)
        self.assertTrue(permissions[staff].manage_messages)

    async def test_deleted_staff_role_is_skipped(self):
        staff = Mock()
        guild = SimpleNamespace(id=1, get_role=lambda role_id: staff if role_id == 2 else None)
        with patch("utils.tickets.get_ticket_roles", AsyncMock(return_value=[2, 3])):
            self.assertEqual(await get_staff_roles(guild), [staff])

    async def test_ticket_role_commands_use_the_shared_lookup(self):
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=1, get_channel=lambda _: None), send=AsyncMock(),
        )
        role = SimpleNamespace(mention="<@&2>")
        with (
            patch("cogs.tickets.get_staff_roles", AsyncMock(return_value=[role])),
            patch("cogs.tickets.get_ticket_settings", AsyncMock(return_value={})),
            patch("cogs.tickets.get_ticket_categories", AsyncMock(return_value=[])),
        ):
            await Tickets.ticket_roles.callback(None, ctx)
            self.assertEqual(ctx.send.call_args.kwargs["embed"].description, role.mention)
            await Tickets.ticket_settings.callback(None, ctx)
            fields = ctx.send.call_args.kwargs["embed"].fields
            self.assertEqual(next(f.value for f in fields if f.name == "Staff Roles"), role.mention)

    async def test_preferred_log_and_missing_channel_fallback(self):
        preferred = SimpleNamespace(id=10, send=AsyncMock())
        fallback = SimpleNamespace(id=20, send=AsyncMock())
        guild = SimpleNamespace(id=1, get_channel=lambda key: {10: preferred, 20: fallback}.get(key))
        embed = discord.Embed(title="Test action")
        with patch("utils.moderation.get_guild_settings", AsyncMock(return_value={"mod_log_channel_id": 20})) as settings:
            await send_mod_log(guild, embed, 10)
            preferred.send.assert_awaited_once_with(embed=embed)
            settings.assert_not_awaited()
            await send_mod_log(guild, embed, 99)
            fallback.send.assert_awaited_once_with(embed=embed)

    async def test_failed_log_does_not_raise_after_moderation(self):
        error = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "No access")
        channel = SimpleNamespace(id=10, send=AsyncMock(side_effect=error))
        guild = SimpleNamespace(id=1, get_channel=lambda _: channel)
        with self.assertLogs("utils.moderation", level="WARNING"):
            await send_mod_log(guild, discord.Embed(), 10)

    async def test_player_panel_can_open_when_idle(self):
        state = SimpleNamespace(now_playing=None, announce_channel_id=None, player_message=None)
        cog = SimpleNamespace(
            get_state=lambda _: state,
            deactivate_player_message=AsyncMock(),
            build_player_embed=Mock(return_value=discord.Embed(title="Idle")),
        )
        ctx = SimpleNamespace(guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=10), send=AsyncMock())
        await Music.now_playing.callback(cog, ctx)
        cog.deactivate_player_message.assert_awaited_once_with(state)
        self.assertEqual(state.announce_channel_id, 10)
        self.assertIs(state.player_message, ctx.send.return_value)
        ctx.send.call_args.kwargs["view"].stop()

    async def test_old_command_names_resolve_to_one_implementation(self):
        async with commands.Bot(command_prefix=",", intents=discord.Intents.none(), help_command=None) as bot:
            bot.add_command(Moderation.purge.copy())
            bot.add_command(Music.now_playing.copy())
            self.assertEqual(len(bot.commands), 2)
            for alias in ("clean", "clear", "purgeuser", "clearuser"):
                self.assertIs(bot.get_command(alias), bot.get_command("purge"))
            for alias in ("np", "controls", "musicpanel", "player"):
                self.assertIs(bot.get_command(alias), bot.get_command("nowplaying"))

    async def test_case_labels_support_old_and_unknown_actions(self):
        self.assertEqual(get_action_label("mute"), "Mute")
        self.assertEqual(get_action_label("clearwarns"), "Warnings Cleared")
        self.assertEqual(get_action_label("custom"), "Custom")


if __name__ == "__main__":
    unittest.main()
