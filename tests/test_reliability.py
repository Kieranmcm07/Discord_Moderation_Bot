"""Regression checks for disconnects, failed delivery, and durable startup state."""

import asyncio
import sqlite3
import tempfile
import unittest
from collections import deque
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import discord

import main
from cogs.moderation import Moderation
from cogs.music import Music
from cogs.reminders import Reminders
from cogs.sentinel import Sentinel


class CounterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "startup_count.txt"
        patcher = patch.object(main, "STARTUP_COUNT_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_new_and_existing_counter(self):
        self.assertEqual(main.increment_startup_count(), 1)
        self.path.write_text("1436", encoding="utf-8")
        self.assertEqual(main.increment_startup_count(), 1437)
        self.assertEqual(self.path.read_text(), "1437")

    def test_invalid_count_is_preserved_instead_of_reset(self):
        for value in ("", "broken", "-1"):
            with self.subTest(value=value):
                self.path.write_text(value, encoding="utf-8")
                with self.assertRaises(main.StartupConfigurationError):
                    main.increment_startup_count()
                self.assertEqual(self.path.read_text(), value)

    def test_failed_replace_preserves_previous_count(self):
        self.path.write_text("1436", encoding="utf-8")
        with patch.object(Path, "replace", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                main.increment_startup_count()
        self.assertEqual(self.path.read_text(), "1436")
        self.assertFalse(self.path.with_suffix(".tmp").exists())


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_presence_recovers_after_transport_reset(self):
        bot = SimpleNamespace(
            wait_until_ready=AsyncMock(),
            is_closed=Mock(side_effect=[False, False, True]),
            build_presence_rotation=lambda: [discord.Game("test")],
            change_presence=AsyncMock(
                side_effect=[aiohttp.ClientConnectionResetError(), None]
            ),
            presence_log_text=lambda activity: activity.name,
        )
        with (
            patch("main.asyncio.sleep", AsyncMock()),
            self.assertLogs("bot", level="WARNING"),
        ):
            await main.MyBot.rotate_presence(bot)
        self.assertEqual(bot.change_presence.await_count, 2)

    async def test_resumed_session_restarts_presence_helper(self):
        bot = SimpleNamespace(ensure_presence_task=Mock())
        await main.MyBot.on_resumed(bot)
        bot.ensure_presence_task.assert_called_once()

    async def test_database_failure_does_not_escape_scheduled_jobs(self):
        for loop, query, logger in (
            (
                Reminders.reminder_loop,
                "cogs.reminders.get_due_reminders",
                "cogs.reminders",
            ),
            (
                Moderation.tempban_loop,
                "cogs.moderation.get_expired_temp_bans",
                "cogs.moderation",
            ),
        ):
            with (
                self.subTest(query=query),
                patch(query, AsyncMock(side_effect=sqlite3.OperationalError("locked"))),
                self.assertLogs(logger),
            ):
                await loop.coro(SimpleNamespace())

    async def test_one_bad_tempban_does_not_block_later_entries(self):
        entries = [{"user_id": 1}, {"user_id": 2}]
        cog = SimpleNamespace(
            expire_tempban=AsyncMock(
                side_effect=[sqlite3.OperationalError("locked"), None]
            )
        )
        with (
            patch(
                "cogs.moderation.get_expired_temp_bans", AsyncMock(return_value=entries)
            ),
            self.assertLogs("cogs.moderation"),
        ):
            await Moderation.tempban_loop.coro(cog)
        self.assertEqual(cog.expire_tempban.await_count, 2)

    async def test_missing_guild_keeps_temporary_ban(self):
        cog = SimpleNamespace(bot=SimpleNamespace(get_guild=lambda _: None))
        with patch("cogs.moderation.remove_temp_ban", AsyncMock()) as remove:
            await Moderation.expire_tempban(cog, {"guild_id": 1, "user_id": 2})
        remove.assert_not_awaited()

    async def test_music_cleanup_survives_disconnect_failure(self):
        task = asyncio.create_task(asyncio.sleep(3600))
        failed_voice = SimpleNamespace(
            disconnect=AsyncMock(side_effect=RuntimeError("offline"))
        )
        healthy_voice = SimpleNamespace(disconnect=AsyncMock())
        session = SimpleNamespace(closed=False, close=AsyncMock())
        cog = SimpleNamespace(
            states={1: SimpleNamespace(player_task=task)},
            http_session=session,
            bot=SimpleNamespace(
                guilds=[
                    SimpleNamespace(id=1, voice_client=failed_voice),
                    SimpleNamespace(id=2, voice_client=healthy_voice),
                ]
            ),
        )
        with self.assertLogs("cogs.music"):
            await Music.cog_unload(cog)
        self.assertTrue(task.cancelled())
        healthy_voice.disconnect.assert_awaited_once()
        session.close.assert_awaited_once()

    async def test_late_audio_completion_cannot_change_another_track(self):
        loop = asyncio.get_running_loop()
        old_track, new_track = loop.create_future(), loop.create_future()
        old_track.cancel()
        Music.finish_playback(old_track, RuntimeError("late callback"))
        self.assertFalse(new_track.done())
        Music.finish_playback(new_track, None)
        Music.finish_playback(new_track, RuntimeError("duplicate callback"))
        self.assertIsNone(await new_track)

    async def test_failed_voice_play_cleans_up_audio_source(self):
        cog = Music(SimpleNamespace(loop=asyncio.get_running_loop()))
        guild = SimpleNamespace(id=1)
        source = Mock()
        cog.make_source = Mock(return_value=source)
        cog.get_healthy_voice = AsyncMock(
            return_value=SimpleNamespace(
                play=Mock(side_effect=RuntimeError("disconnected"))
            )
        )
        cog.announce_now_playing = AsyncMock()
        cog.disconnect_if_idle = AsyncMock()
        cog.get_state(1).queue.put_nowait(SimpleNamespace(webpage_url="test"))
        with (
            patch("cogs.music.IDLE_DISCONNECT_SECONDS", 0.01),
            self.assertLogs("cogs.music"),
        ):
            await asyncio.wait_for(cog.player_loop(guild), timeout=1)
        source.cleanup.assert_called_once()

    async def test_tracking_prunes_inactive_members_without_losing_live_windows(self):
        cog = Sentinel(None)
        now = discord.utils.utcnow()
        cog.message_windows[(1, 1)] = deque(
            [{"created_at": now - timedelta(minutes=5)}]
        )
        cog.message_windows[(1, 2)] = deque([{"created_at": now}])
        cog.alert_cooldowns[(1, 1)] = now - timedelta(seconds=1)
        cog.alert_cooldowns[(1, 2)] = now + timedelta(minutes=2)
        cog.prune_tracking()
        self.assertNotIn((1, 1), cog.message_windows)
        self.assertNotIn((1, 1), cog.alert_cooldowns)
        self.assertIn((1, 2), cog.message_windows)
        self.assertIn((1, 2), cog.alert_cooldowns)
        self.assertEqual(cog.recent_messages(1, 99, 60), [])
        self.assertNotIn((1, 99), cog.message_windows)


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reminder = {
            "id": 1,
            "guild_id": 2,
            "channel_id": 3,
            "user_id": 4,
            "message": "test",
        }
        self.channel = SimpleNamespace(send=AsyncMock())
        self.user = SimpleNamespace(mention="member", send=AsyncMock())
        self.guild = SimpleNamespace(get_channel_or_thread=lambda _: self.channel)
        self.cog = object.__new__(Reminders)
        self.cog.bot = SimpleNamespace(
            get_guild=lambda _: self.guild, get_user=lambda _: self.user
        )

    async def run_pass(self):
        with (
            patch(
                "cogs.reminders.get_due_reminders",
                AsyncMock(return_value=[self.reminder]),
            ),
            patch("cogs.reminders.delete_reminder", AsyncMock()) as delete,
            patch("cogs.reminders.make_embed", AsyncMock(return_value=discord.Embed())),
        ):
            await Reminders.reminder_loop.coro(self.cog)
            return delete

    async def test_failed_channel_and_dm_keeps_reminder(self):
        error = discord.HTTPException(
            SimpleNamespace(status=503, reason="Unavailable"), "retry"
        )
        self.channel.send.side_effect = error
        self.user.send.side_effect = error
        delete = await self.run_pass()
        delete.assert_not_awaited()

    async def test_successful_delivery_deletes_reminder(self):
        delete = await self.run_pass()
        delete.assert_awaited_once_with(2, 1)
        self.user.send.assert_not_awaited()

    async def test_successful_dm_fallback_deletes_reminder(self):
        self.channel.send.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "no access"
        )
        delete = await self.run_pass()
        self.user.send.assert_awaited_once()
        delete.assert_awaited_once_with(2, 1)

    async def test_failed_first_page_does_not_starve_later_reminders(self):
        first = [
            dict(self.reminder, id=i, due_at="2026-01-01T00:00:00+00:00")
            for i in range(1, 26)
        ]
        last = dict(self.reminder, id=26, due_at="2026-01-02T00:00:00+00:00")
        self.cog.deliver_reminder = AsyncMock(side_effect=[False] * 25 + [True])
        with (
            patch(
                "cogs.reminders.get_due_reminders",
                AsyncMock(side_effect=[first, [last]]),
            ) as query,
            patch("cogs.reminders.delete_reminder", AsyncMock()) as delete,
        ):
            await Reminders.reminder_loop.coro(self.cog)
        self.assertEqual(self.cog.deliver_reminder.await_count, 26)
        delete.assert_awaited_once_with(2, 26)
        self.assertEqual(query.await_args.kwargs["after"], (first[-1]["due_at"], 25))
