# ============================================================
#   Made by Kieranmcm07 on GitHub
#   GitHub: https://github.com/Kieranmcm07
# ============================================================
"""
Central project settings.

This file keeps the environment-driven configuration easy to scan so the bot is
simple to run locally. Per-server customization still lives in the database and
is managed through bot commands.
"""

# Most values come from .env so I do not have to hard-code private stuff.
import os

from dotenv import load_dotenv

load_dotenv()


def parse_int_env(name: str, default: int = 0) -> int:
    """Read an integer environment value without crashing on blank input."""
    value = os.getenv(name, "").strip()
    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def resolve_mod_log_channel_id(settings: dict | None = None) -> int:
    """Return a guild mod-log override, falling back to the environment default."""
    if settings and settings.get("mod_log_channel_id") is not None:
        return int(settings.get("mod_log_channel_id") or 0)
    return MOD_LOG_CHANNEL_ID


# Core startup settings.
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PREFIX = os.getenv("PREFIX", ",")
BOT_VERSION = os.getenv("BOT_VERSION", "v1.2.0").strip() or "v1.2.0"
PRESENCE_ROTATION_SECONDS = max(30, parse_int_env("PRESENCE_ROTATION_SECONDS", 45))
OWNER_IDS = [
    int(value)
    for value in os.getenv("OWNER_IDS", "").split(",")
    if value.strip().isdigit()
]

# Public project links shown by bot info and credits commands.
PROJECT_CREATOR = "Kieranmcm07"
GITHUB_PROFILE_URL = "https://github.com/Kieranmcm07"
PROJECT_REPO_URL = "https://github.com/Kieranmcm07/Discord_Moderation_Bot"

# Database path.
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

# Optional Spotify Web API support for music commands. Spotify is used for
# metadata only; playback still resolves through the existing yt-dlp flow.
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_MAX_TRACKS = parse_int_env("SPOTIFY_MAX_TRACKS", 50)
SPOTIFY_MARKET = os.getenv("SPOTIFY_MARKET", "US").strip().upper()

# Optional logging channels kept for backwards compatibility with older configs.
MOD_LOG_CHANNEL_ID = parse_int_env("MOD_LOG_CHANNEL_ID")
INVITE_LOG_CHANNEL_ID = parse_int_env("INVITE_LOG_CHANNEL_ID")
JOIN_LOG_CHANNEL_ID = parse_int_env("JOIN_LOG_CHANNEL_ID")

# Default color palette used when a guild has not set its own theme.
COLOR_SUCCESS = 0x57F287
COLOR_ERROR = 0xED4245
COLOR_WARN = 0xFEE75C
COLOR_INFO = 0x5865F2
COLOR_MOD = 0x9B59B6
