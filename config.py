"""
Central project settings.

This file keeps the environment-driven configuration easy to scan so the bot is
simple to run locally. Per-server customization still lives in the database and
is managed through bot commands.
"""

import os

from dotenv import load_dotenv


load_dotenv()

# Core startup settings.
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PREFIX = os.getenv("PREFIX", ",")
OWNER_IDS = [
    int(value) for value in os.getenv("OWNER_IDS", "").split(",") if value.strip().isdigit()
]

# Database path.
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

# Optional logging channels kept for backwards compatibility with older configs.
INVITE_LOG_CHANNEL_ID = int(os.getenv("INVITE_LOG_CHANNEL_ID", 0))
JOIN_LOG_CHANNEL_ID = int(os.getenv("JOIN_LOG_CHANNEL_ID", 0))

# Default color palette used when a guild has not set its own theme.
COLOR_SUCCESS = 0x57F287
COLOR_ERROR = 0xED4245
COLOR_WARN = 0xFEE75C
COLOR_INFO = 0x5865F2
COLOR_MOD = 0x9B59B6
