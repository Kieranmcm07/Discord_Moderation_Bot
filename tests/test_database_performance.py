"""Check cached reads and concurrent updates against an isolated SQLite file."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import db
from utils.cache import AsyncTTLCache


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_expiry_mutability_and_bound(self):
        cache = AsyncTTLCache(ttl=30, maxsize=2)
        calls = []

        @cache.cached
        async def read(key):
            calls.append(key)
            return {"value": key}

        with patch("utils.cache.monotonic", return_value=0):
            first = await read(1)
            first["value"] = 99
            self.assertEqual(await read(key=1), {"value": 1})
            await read(2)
            await read(3)
            self.assertEqual(len(cache._entries), 2)
            await read(1)
        with patch("utils.cache.monotonic", return_value=31):
            await read(1)
        self.assertEqual(calls, [1, 2, 3, 1, 1])

    async def test_invalidation_during_read_does_not_cache_stale_result(self):
        cache = AsyncTTLCache()
        entered, release = asyncio.Event(), asyncio.Event()
        state = {"value": 1}

        @cache.cached
        async def read(key):
            value = state["value"]
            entered.set()
            await release.wait()
            return value

        task = asyncio.create_task(read(1))
        await entered.wait()
        state["value"] = 2
        cache.clear()
        release.set()
        self.assertEqual(await task, 1)
        self.assertEqual(await read(1), 2)


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = str(Path(temporary.name) / "test.db")
        patcher = patch.object(db, "DB_PATH", self.database)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(db._settings_cache.clear)
        await db.init_db()

    async def test_repeated_message_settings_reads_open_only_three_connections(self):
        with patch.object(db, "connect_db", wraps=db.connect_db) as connect:
            for _ in range(100):
                await db.get_automod_settings(1)
                await db.get_sentinel_settings(1)
                await db.get_sticky_message(10)
            self.assertEqual(connect.call_count, 3)

    async def test_settings_changes_visible_immediately(self):
        await db.get_guild_settings(1)
        await db.get_automod_settings(1)
        await db.get_sentinel_settings(1)
        await db.get_ticket_settings(1)
        await db.upsert_guild_settings(1, mod_log_channel_id=10, embed_color=123)
        await db.upsert_automod_settings(1, enabled=0)
        await db.upsert_sentinel_settings(1, alert_threshold=90)
        await db.upsert_ticket_settings(1, category_id=12)
        self.assertEqual((await db.get_guild_settings(1))["embed_color"], 123)
        self.assertEqual((await db.get_automod_settings(1))["enabled"], 0)
        self.assertEqual((await db.get_sentinel_settings(1))["alert_threshold"], 90)
        self.assertEqual((await db.get_ticket_settings(1))["category_id"], 12)
        await db.clear_mod_log_channel(1)
        settings = await db.get_guild_settings(1)
        self.assertEqual(settings["mod_log_channel_id"], 0)
        self.assertEqual(settings["embed_color"], 123)

    async def test_concurrent_settings_updates_preserve_both_fields(self):
        cases = (
            (
                db.upsert_guild_settings,
                db.get_guild_settings,
                {"embed_color": 123},
                {"mod_log_channel_id": 10},
            ),
            (
                db.upsert_ticket_settings,
                db.get_ticket_settings,
                {"category_id": 12},
                {"log_channel_id": 10},
            ),
            (
                db.upsert_sentinel_settings,
                db.get_sentinel_settings,
                {"enabled": 0},
                {"alert_threshold": 90},
            ),
            (
                db.upsert_automod_settings,
                db.get_automod_settings,
                {"enabled": 0},
                {"delete_links": 1},
            ),
        )
        for setter, getter, first, second in cases:
            with self.subTest(setter=setter.__name__):
                await asyncio.gather(setter(1, **first), setter(1, **second))
                settings = await getter(1)
                for key, value in (first | second).items():
                    self.assertEqual(settings[key], value)

    async def test_defaults_and_empty_updates(self):
        before = await db.get_automod_settings(1)
        await db.upsert_automod_settings(1)
        self.assertEqual(await db.get_automod_settings(1), before)
        await db.upsert_guild_settings(1, embed_color=123)
        await db.upsert_guild_settings(1)
        self.assertEqual((await db.get_guild_settings(1))["embed_color"], 123)

    async def test_sticky_creation_edit_and_removal_invalidate_cache(self):
        self.assertIsNone(await db.get_sticky_message(10))
        await db.set_sticky_message(1, 10, "first", 5)
        self.assertEqual((await db.get_sticky_message(10))["content"], "first")
        await db.update_sticky_message_id(10, 99)
        self.assertEqual((await db.get_sticky_message(10))["bot_message_id"], 99)
        await db.set_sticky_message(1, 10, "second", 5)
        sticky = await db.get_sticky_message(10)
        self.assertEqual(sticky["content"], "second")
        self.assertEqual(sticky["bot_message_id"], 99)
        await db.clear_sticky_message(10)
        self.assertIsNone(await db.get_sticky_message(10))

    async def test_reminder_pages_skip_retained_rows_without_skipping_pending_rows(
        self,
    ):
        due = "2026-01-01T00:00:00+00:00"
        ids = [await db.add_reminder(1, 10, 20, "test", due) for _ in range(27)]
        first = await db.get_due_reminders(due)
        self.assertEqual([row["id"] for row in first], ids[:25])
        # Successful rows disappear, but failed rows in the first page remain.
        await db.delete_reminder(1, ids[0])
        second = await db.get_due_reminders(due, after=(due, first[-1]["id"]))
        self.assertEqual([row["id"] for row in second], ids[25:])
        self.assertEqual(len(await db.get_due_reminders(due)), 25)
