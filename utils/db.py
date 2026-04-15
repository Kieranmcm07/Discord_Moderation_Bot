"""
utils/db.py — everything database related lives here.
I'm using SQLite because it needs zero setup and the data isn't massive.
If you ever need to scale, swapping to Postgres is straightforward from here.
"""

import aiosqlite
import os
from config import DB_PATH


async def init_db():
    """
    Create all the tables if they don't exist.
    I call this once at startup so the bot never crashes because a table is missing.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:

        # --- cases / infractions table ---
        # every warn, mute, kick, ban gets logged here with a case number
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                mod_id      INTEGER NOT NULL,
                action      TEXT NOT NULL,        -- warn / mute / kick / ban / unban / unmute
                reason      TEXT,
                duration    TEXT,                 -- NULL for permanent actions
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- invite tracking ---
        # I snapshot invite uses when the bot starts, then diff them on member join
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                inviter_id  INTEGER,
                code        TEXT NOT NULL,
                uses        INTEGER DEFAULT 0,
                UNIQUE(guild_id, code)
            )
        """)

        # --- message activity stats ---
        # counts messages per user per guild per day for the stats command
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_stats (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                day         TEXT NOT NULL,        -- stored as YYYY-MM-DD
                count       INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, day)
            )
        """)

        # --- voice activity stats ---
        # stores time spent in VC in minutes
        await db.execute("""
            CREATE TABLE IF NOT EXISTS voice_stats (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                minutes     INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # --- join/leave log ---
        # useful for tracking raid patterns or just seeing member history
        await db.execute("""
            CREATE TABLE IF NOT EXISTS member_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                event       TEXT NOT NULL,        -- 'join' or 'leave'
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- mutes table so I can track timed mutes and lift them ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mutes (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                expires_at  TIMESTAMP,            -- NULL = permanent
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # --- ticket system settings ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_settings (
                guild_id         INTEGER PRIMARY KEY,
                category_id      INTEGER,
                log_channel_id   INTEGER,
                panel_channel_id INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_roles (
                guild_id INTEGER NOT NULL,
                role_id  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_categories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                emoji       TEXT,
                description TEXT,
                UNIQUE(guild_id, name)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id        INTEGER NOT NULL,
                channel_id      INTEGER NOT NULL UNIQUE,
                user_id         INTEGER NOT NULL,
                category_name   TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'open',
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at       TIMESTAMP,
                closed_by_id    INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS escalation_rules (
                guild_id    INTEGER NOT NULL,
                warn_count  INTEGER NOT NULL,
                action      TEXT NOT NULL,
                duration    TEXT,
                PRIMARY KEY (guild_id, warn_count)
            )
        """)

        await db.commit()


# ─────────────────────────────────────────────
# Case helpers
# ─────────────────────────────────────────────

async def add_case(guild_id, user_id, mod_id, action, reason=None, duration=None) -> int:
    """Insert a new case and return its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO cases (guild_id, user_id, mod_id, action, reason, duration) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, mod_id, action, reason, duration)
        )
        await db.commit()
        return cur.lastrowid


async def get_case(guild_id, case_id) -> dict | None:
    """Fetch a single case by its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cases WHERE guild_id=? AND id=?", (guild_id, case_id)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_user_cases(guild_id, user_id) -> list[dict]:
    """Get all cases for a specific user in a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cases WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
            (guild_id, user_id)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_recent_cases(guild_id, limit=10) -> list[dict]:
    """Get the most recent N cases in a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cases WHERE guild_id=? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_warn_count(guild_id, user_id) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM cases WHERE guild_id=? AND user_id=? AND action='warn'",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def get_recent_warns(guild_id, user_id, limit=5) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM cases
               WHERE guild_id=? AND user_id=? AND action='warn'
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
            (guild_id, user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


async def clear_recent_warns(guild_id, user_id, amount: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id FROM cases
               WHERE guild_id=? AND user_id=? AND action='warn'
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
            (guild_id, user_id, amount),
        ) as cur:
            rows = await cur.fetchall()

        case_ids = [row[0] for row in rows]
        if not case_ids:
            return []

        placeholders = ",".join("?" for _ in case_ids)
        await db.execute(
            f"DELETE FROM cases WHERE guild_id=? AND id IN ({placeholders})",
            (guild_id, *case_ids),
        )
        await db.commit()
        return case_ids


async def upsert_escalation_rule(guild_id, warn_count: int, action: str, duration: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO escalation_rules (guild_id, warn_count, action, duration)
               VALUES (?,?,?,?)
               ON CONFLICT(guild_id, warn_count) DO UPDATE SET
               action=excluded.action,
               duration=excluded.duration""",
            (guild_id, warn_count, action, duration),
        )
        await db.commit()


async def remove_escalation_rule(guild_id, warn_count: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM escalation_rules WHERE guild_id=? AND warn_count=?",
            (guild_id, warn_count),
        )
        await db.commit()


async def get_escalation_rules(guild_id) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM escalation_rules WHERE guild_id=? ORDER BY warn_count ASC",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


async def get_matching_escalation_rule(guild_id, warn_count: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM escalation_rules WHERE guild_id=? AND warn_count=?",
            (guild_id, warn_count),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ─────────────────────────────────────────────
# Invite helpers
# ─────────────────────────────────────────────

async def upsert_invite(guild_id, code, inviter_id, uses):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO invites (guild_id, code, inviter_id, uses)
               VALUES (?,?,?,?)
               ON CONFLICT(guild_id, code) DO UPDATE SET uses=excluded.uses, inviter_id=excluded.inviter_id""",
            (guild_id, code, inviter_id, uses)
        )
        await db.commit()


async def get_invites(guild_id) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM invites WHERE guild_id=?", (guild_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ─────────────────────────────────────────────
# Stats helpers
# ─────────────────────────────────────────────

async def increment_message_stat(guild_id, user_id, day: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO message_stats (guild_id, user_id, day, count) VALUES (?,?,?,1)
               ON CONFLICT(guild_id, user_id, day) DO UPDATE SET count = count + 1""",
            (guild_id, user_id, day)
        )
        await db.commit()


async def get_top_chatters(guild_id, limit=10) -> list[dict]:
    """Top chatters across all time for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT user_id, SUM(count) as total FROM message_stats
               WHERE guild_id=? GROUP BY user_id ORDER BY total DESC LIMIT ?""",
            (guild_id, limit)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def add_voice_time(guild_id, user_id, minutes: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO voice_stats (guild_id, user_id, minutes) VALUES (?,?,?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET minutes = minutes + ?""",
            (guild_id, user_id, minutes, minutes)
        )
        await db.commit()


async def get_top_voice(guild_id, limit=10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, minutes FROM voice_stats WHERE guild_id=? ORDER BY minutes DESC LIMIT ?",
            (guild_id, limit)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def log_member_event(guild_id, user_id, event: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO member_log (guild_id, user_id, event) VALUES (?,?,?)",
            (guild_id, user_id, event)
        )
        await db.commit()


# Ticket helpers

async def get_ticket_settings(guild_id) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ticket_settings WHERE guild_id=?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def upsert_ticket_settings(
    guild_id,
    category_id=None,
    log_channel_id=None,
    panel_channel_id=None,
):
    current = await get_ticket_settings(guild_id) or {}
    values = {
        "category_id": category_id if category_id is not None else current.get("category_id"),
        "log_channel_id": log_channel_id if log_channel_id is not None else current.get("log_channel_id"),
        "panel_channel_id": panel_channel_id if panel_channel_id is not None else current.get("panel_channel_id"),
    }

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO ticket_settings (guild_id, category_id, log_channel_id, panel_channel_id)
               VALUES (?,?,?,?)
               ON CONFLICT(guild_id) DO UPDATE SET
               category_id=excluded.category_id,
               log_channel_id=excluded.log_channel_id,
               panel_channel_id=excluded.panel_channel_id""",
            (
                guild_id,
                values["category_id"],
                values["log_channel_id"],
                values["panel_channel_id"],
            ),
        )
        await db.commit()


async def add_ticket_role(guild_id, role_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO ticket_roles (guild_id, role_id) VALUES (?,?)",
            (guild_id, role_id),
        )
        await db.commit()


async def remove_ticket_role(guild_id, role_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM ticket_roles WHERE guild_id=? AND role_id=?",
            (guild_id, role_id),
        )
        await db.commit()


async def get_ticket_roles(guild_id) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role_id FROM ticket_roles WHERE guild_id=? ORDER BY role_id",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [row[0] for row in rows]


async def add_ticket_category(guild_id, name: str, emoji: str | None = None, description: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO ticket_categories (guild_id, name, emoji, description)
               VALUES (?,?,?,?)""",
            (guild_id, name, emoji, description),
        )
        await db.commit()
        return cur.lastrowid


async def remove_ticket_category(guild_id, category_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM ticket_categories WHERE guild_id=? AND id=?",
            (guild_id, category_id),
        )
        await db.commit()


async def get_ticket_categories(guild_id) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ticket_categories WHERE guild_id=? ORDER BY id ASC",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


async def create_ticket(guild_id, channel_id, user_id, category_name: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO tickets (guild_id, channel_id, user_id, category_name)
               VALUES (?,?,?,?)""",
            (guild_id, channel_id, user_id, category_name),
        )
        await db.commit()
        return cur.lastrowid


async def get_ticket_by_channel(channel_id) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tickets WHERE channel_id=?",
            (channel_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_open_ticket_for_user(guild_id, user_id) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id=? AND user_id=? AND status='open' ORDER BY id DESC LIMIT 1",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def close_ticket(channel_id, closed_by_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE tickets
               SET status='closed', closed_at=CURRENT_TIMESTAMP, closed_by_id=?
               WHERE channel_id=? AND status='open'""",
            (closed_by_id, channel_id),
        )
        await db.commit()


async def get_open_tickets(guild_id) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id=? AND status='open' ORDER BY id ASC",
            (guild_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]
