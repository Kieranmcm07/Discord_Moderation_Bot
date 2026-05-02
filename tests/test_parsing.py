import unittest
from datetime import datetime, timezone

from cogs.moderation import parse_duration
from cogs.reminders import parse_duration_prefix
from utils.time import parse_db_timestamp, unix_timestamp


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


if __name__ == "__main__":
    unittest.main()
