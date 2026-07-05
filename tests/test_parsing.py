# ============================================================
#   Made by Kieranmcm07 on GitHub
#   GitHub: https://github.com/Kieranmcm07
# ============================================================
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import discord

from cogs.invite_logger import invite_uses
from cogs.moderation import build_chatlog_text, parse_duration
from cogs.music import parse_spotify_reference, spotify_track_from_payload
from cogs.music import spotify_playlist_total_from_html, spotify_track_ids_from_html
from cogs.music import parse_youtube_playlist_reference, youtube_playlist_entry_url
from cogs.reminders import parse_duration_prefix
from utils.embeds import decorate_embed
from utils.time import parse_db_timestamp, unix_timestamp


class FakeUser:
    def __init__(self, name: str, user_id: int):
        self.name = name
        self.id = user_id

    def __str__(self):
        return self.name


class FakeAvatar:
    url = "https://example.com/bot.png"


class FakeBotUser:
    name = "Test Bot"
    display_avatar = FakeAvatar()


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
        self.assertIn(
            "[2026-05-02 12:30:00 UTC] Member#0001 (111): hello there", transcript
        )


class HelperRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_decorate_embed_preserves_existing_thumbnail(self):
        bot = SimpleNamespace(user=FakeBotUser())
        embed = discord.Embed(description="keeps custom thumbnail")
        embed.set_thumbnail(url="https://example.com/custom.png")

        decorated = await decorate_embed(bot, None, embed)

        self.assertEqual(decorated.thumbnail.url, "https://example.com/custom.png")

    def test_invite_uses_treats_missing_count_as_zero(self):
        self.assertEqual(invite_uses(SimpleNamespace(uses=None)), 0)
        self.assertEqual(invite_uses(SimpleNamespace(uses=3)), 3)


class SpotifyParsingTests(unittest.TestCase):
    def test_parse_spotify_track_url(self):
        reference = parse_spotify_reference(
            "https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl?si=test"
        )

        self.assertIsNotNone(reference)
        self.assertEqual(reference.kind, "track")
        self.assertEqual(reference.item_id, "11dFghVXANMlKmJXsNCbNl")

    def test_parse_spotify_uri(self):
        reference = parse_spotify_reference(
            "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
        )

        self.assertIsNotNone(reference)
        self.assertEqual(reference.kind, "playlist")
        self.assertEqual(reference.item_id, "37i9dQZF1DXcBWIGoYBM5M")

    def test_parse_spotify_international_url(self):
        reference = parse_spotify_reference(
            "https://open.spotify.com/intl-gb/album/6JWc4iAiJ9FjyK0B59ABb4"
        )

        self.assertIsNotNone(reference)
        self.assertEqual(reference.kind, "album")
        self.assertEqual(reference.item_id, "6JWc4iAiJ9FjyK0B59ABb4")

    def test_reject_non_spotify_host(self):
        self.assertIsNone(
            parse_spotify_reference(
                "https://notspotify.com/track/11dFghVXANMlKmJXsNCbNl"
            )
        )

    def test_spotify_track_payload_becomes_searchable_metadata(self):
        track = spotify_track_from_payload(
            {
                "type": "track",
                "name": "Test Song",
                "artists": [{"name": "Test Artist"}],
                "duration_ms": 123456,
                "external_urls": {
                    "spotify": "https://open.spotify.com/track/example"
                },
                "album": {
                    "images": [
                        {"url": "https://example.com/cover.png"},
                    ],
                },
            }
        )

        self.assertIsNotNone(track)
        self.assertEqual(track.display_title, "Test Artist - Test Song")
        self.assertEqual(track.duration, 123)
        self.assertEqual(track.thumbnail_url, "https://example.com/cover.png")
        self.assertIn("official audio", track.search_query)

    def test_spotify_track_ids_from_public_html(self):
        html = """
        <meta name="music:song" content="https://open.spotify.com/track/abc123"/>
        <a href="/track/def456">Song</a>
        <a href="/track/abc123">Duplicate</a>
        <div>spotify:track:ghi789</div>
        """

        self.assertEqual(
            spotify_track_ids_from_html(html, 10),
            ["abc123", "def456", "ghi789"],
        )

    def test_spotify_playlist_total_from_public_html(self):
        html = '<meta name="description" content="Playlist &middot; General &middot; 154 items"/>'

        self.assertEqual(spotify_playlist_total_from_html(html), 154)


class YouTubePlaylistParsingTests(unittest.TestCase):
    def test_parse_youtube_playlist_url(self):
        reference = parse_youtube_playlist_reference(
            "https://www.youtube.com/playlist?list=PL123abc"
        )

        self.assertIsNotNone(reference)
        self.assertEqual(reference.playlist_id, "PL123abc")

    def test_parse_youtube_watch_url_with_playlist(self):
        reference = parse_youtube_playlist_reference(
            "https://www.youtube.com/watch?v=abc123&list=PL456def"
        )

        self.assertIsNotNone(reference)
        self.assertEqual(reference.playlist_id, "PL456def")

    def test_reject_single_youtube_video_without_playlist(self):
        self.assertIsNone(
            parse_youtube_playlist_reference(
                "https://www.youtube.com/watch?v=abc123"
            )
        )

    def test_flat_youtube_entry_becomes_watch_url(self):
        self.assertEqual(
            youtube_playlist_entry_url({"id": "abc123", "url": "abc123"}),
            "https://www.youtube.com/watch?v=abc123",
        )


if __name__ == "__main__":
    unittest.main()
