"""
config.py — all my settings in one place.
Copy this to .env or just fill the values in directly if it's private.
Never commit your actual token to git — add config.py to .gitignore
or use the .env approach with python-dotenv.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # loads values from a .env file if one exists

# --- Core ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
PREFIX = os.getenv("PREFIX", ",")  # default prefix is comma, like in the screenshot
OWNER_IDS = [
    int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip().isdigit()
]

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "data/bot.db")  # SQLite file location

# --- Logging channels (set these in your server and paste the IDs) ---
# These are optional — the bot works fine without them, those features just stay quiet
MOD_LOG_CHANNEL_ID = int(os.getenv("MOD_LOG_CHANNEL_ID", 0))
INVITE_LOG_CHANNEL_ID = int(os.getenv("INVITE_LOG_CHANNEL_ID", 0))
JOIN_LOG_CHANNEL_ID = int(os.getenv("JOIN_LOG_CHANNEL_ID", 0))

# --- Colours for embeds ---
# keeping these in one place so I can change the whole theme without hunting through files
COLOR_SUCCESS = 0x57F287  # green
COLOR_ERROR = 0xED4245  # red
COLOR_WARN = 0xFEE75C  # yellow
COLOR_INFO = 0x5865F2  # blurple
COLOR_MOD = 0x9B59B6  # purple — for moderation embeds
