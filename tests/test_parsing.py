import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from cogs.moderation import build_chatlog_text, parse_duration
from cogs.reminders import parse_duration_prefix
from utils.time import parse_db_timestamp, unix_timestamp


class FakeUser:
    def __init__(self, name: str, user_id: int):
        self.name = name
        self.id = user_id

    def __str__(self):
        return self.name


class TimeHelperTests(unittest.TestCase):
    def test_parse_sqlite_timestamp_as_utc(self):
        self.assertEqual(
            parse_db_timestamp("2026-05-02 12:00:00"),
            datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        )

    def test_parse_offset_timestamp_to_utc(self):
        self.assertEqual(
            parse_db_timestamp("2026-05-02T13:00:00+01:00"),
            datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        )

    def test_unix_timestamp_handles_epoch(self):
        self.assertEqual(unix_timestamp("1970-01-01 00:00:00"), 0)


class DurationParsingTests(unittest.TestCase):
    def test_moderation_duration_compact(self):
        self.assertEqual(parse_duration("1h30m"), 5400)

    def test_moderation_duration_rejects_trailing_text(self):
        self.assertIsNone(parse_duration("10m later"))

    def test_reminder_prefix_reads_duration_and_message(self):
        self.assertEqual(
            parse_duration_prefix("2 weeks review the appeal"),
            (1209600, "review the appeal"),
        )


class ChatlogFormattingTests(unittest.TestCase):
    def test_chatlog_includes_header_and_message(self):
        guild = SimpleNamespace(name="Test Guild", id=123)
        channel = SimpleNamespace(name="general", id=456)
        requester = FakeUser("Moderator#0001", 789)
        message = SimpleNamespace(
            created_at=datetime(2026, 5, 2, 12, 30, tzinfo=timezone.utc),
            author=FakeUser("Member#0001", 111),
            clean_content="hello there",
            edited_at=None,
            reference=None,
            attachments=[],
            stickers=[],
            embeds=[],
        )

        transcript = build_chatlog_text(guild, channel, requester, [message], 1)

        self.assertIn("Guild: Test Guild (123)", transcript)
        self.assertIn("Channel: #general (456)", transcript)
        self.assertIn("[2026-05-02 12:30:00 UTC] Member#0001 (111): hello there", transcript)


if __name__ == "__main__":
    unittest.main()
