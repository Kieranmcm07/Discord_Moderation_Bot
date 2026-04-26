"""
Central project settings.

This file keeps the environment-driven configuration easy to scan so the bot is
simple to run locally. Per-server customization still lives in the database and
is managed through bot commands.
"""

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
OWNER_IDS = [
    int(value)
    for value in os.getenv("OWNER_IDS", "").split(",")
    if value.strip().isdigit()
]

# Database path.
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

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
