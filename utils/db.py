"""
Database helpers for the bot.

SQLite is a good fit for this project because it keeps setup simple while still
handling the bot's moderation, ticket, and analytics data cleanly.
"""

import os

import aiosqlite

from config import DB_PATH


async def ensure_column(db: aiosqlite.Connection, table_name: str, column_name: str, definition: str):
    """Add a missing column to an existing table without breaking older installs."""
    async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
        rows = await cursor.fetchall()

    existing_columns = {row[1] for row in rows}
    if column_name not in existing_columns:
        await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


async def init_db():
    """Create all required tables and perform light schema upgrades."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                mod_id      INTEGER NOT NULL,
                action      TEXT NOT NULL,
                reason      TEXT,
                duration    TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                inviter_id  INTEGER,
                code        TEXT NOT NULL,
                uses        INTEGER DEFAULT 0,
                UNIQUE(guild_id, code)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS message_stats (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                day         TEXT NOT NULL,
                count       INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, day)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_stats (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                minutes     INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS member_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                event       TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS mutes (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                expires_at  TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_settings (
                guild_id         INTEGER PRIMARY KEY,
                category_id      INTEGER,
                log_channel_id   INTEGER,
                panel_channel_id INTEGER
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_roles (
                guild_id INTEGER NOT NULL,
                role_id  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_categories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                name        TEXT NOT NULL,
                emoji       TEXT,
                description TEXT,
                UNIQUE(guild_id, name)
            )
            """
        )

        await db.execute(
            """
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
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS escalation_rules (
                guild_id    INTEGER NOT NULL,
                warn_count  INTEGER NOT NULL,
                action      TEXT NOT NULL,
                duration    TEXT,
                PRIMARY KEY (guild_id, warn_count)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS temp_bans (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                mod_id      INTEGER NOT NULL,
                reason      TEXT,
                expires_at  TIMESTAMP NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS autorole_settings (
                guild_id INTEGER PRIMARY KEY,
                role_id  INTEGER NOT NULL
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sticky_messages (
                guild_id       INTEGER NOT NULL,
                channel_id     INTEGER PRIMARY KEY,
                content        TEXT NOT NULL,
                created_by_id  INTEGER NOT NULL,
                bot_message_id INTEGER
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id            INTEGER PRIMARY KEY,
                welcome_channel_id  INTEGER,
                leave_channel_id    INTEGER,
                welcome_message     TEXT,
                leave_message       TEXT,
                embed_color         INTEGER
            )
            """
        )

        await ensure_column(db, "guild_settings", "embed_image_url", "TEXT")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_roles (
                guild_id    INTEGER NOT NULL,
                role_id     INTEGER NOT NULL,
                label       TEXT NOT NULL,
                emoji       TEXT,
                PRIMARY KEY (guild_id, role_id)
            )
            """
        )

        await db.commit()


async def add_case(guild_id, user_id, mod_id, action, reason=None, duration=None) -> int:
    """Insert a new case and return its generated case ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO cases (guild_id, user_id, mod_id, action, reason, duration) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, mod_id, action, reason, duration),
        )
        await db.commit()
        return cursor.lastrowid


async def get_case(guild_id, case_id) -> dict | None:
    """Fetch a single case by its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cases WHERE guild_id=? AND id=?",
            (guild_id, case_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_cases(guild_id, user_id) -> list[dict]:
    """Return all logged cases for one member in reverse chronological order."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cases WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
            (guild_id, user_id),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_recent_cases(guild_id, limit=10) -> list[dict]:
    """Return the most recent moderation cases for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cases WHERE guild_id=? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_warn_count(guild_id, user_id) -> int:
    """Count the active warning cases for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM cases WHERE guild_id=? AND user_id=? AND action='warn'",
            (guild_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0


async def get_recent_warns(guild_id, user_id, limit=5) -> list[dict]:
    """Return the newest warning cases for a specific user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM cases
            WHERE guild_id=? AND user_id=? AND action='warn'
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (guild_id, user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def clear_recent_warns(guild_id, user_id, amount: int) -> list[int]:
    """Delete the newest warning cases for a user and return the removed case IDs."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT id FROM cases
            WHERE guild_id=? AND user_id=? AND action='warn'
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (guild_id, user_id, amount),
        ) as cursor:
            rows = await cursor.fetchall()

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
    """Create or update an escalation rule for a warning threshold."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO escalation_rules (guild_id, warn_count, action, duration)
            VALUES (?,?,?,?)
            ON CONFLICT(guild_id, warn_count) DO UPDATE SET
            action=excluded.action,
            duration=excluded.duration
            """,
            (guild_id, warn_count, action, duration),
        )
        await db.commit()


async def remove_escalation_rule(guild_id, warn_count: int):
    """Remove an escalation rule for a warning threshold."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM escalation_rules WHERE guild_id=? AND warn_count=?",
            (guild_id, warn_count),
        )
        await db.commit()


async def get_escalation_rules(guild_id) -> list[dict]:
    """Return all escalation rules for a guild in threshold order."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM escalation_rules WHERE guild_id=? ORDER BY warn_count ASC",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_matching_escalation_rule(guild_id, warn_count: int) -> dict | None:
    """Return the escalation rule that exactly matches a warning count."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM escalation_rules WHERE guild_id=? AND warn_count=?",
            (guild_id, warn_count),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def add_temp_ban(guild_id, user_id, mod_id, expires_at: str, reason: str | None = None):
    """Store or refresh a temporary ban entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO temp_bans (guild_id, user_id, mod_id, reason, expires_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
            mod_id=excluded.mod_id,
            reason=excluded.reason,
            expires_at=excluded.expires_at
            """,
            (guild_id, user_id, mod_id, reason, expires_at),
        )
        await db.commit()


async def remove_temp_ban(guild_id, user_id):
    """Remove a temporary ban tracking entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM temp_bans WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.commit()


async def get_expired_temp_bans(now_iso: str) -> list[dict]:
    """Return temporary bans that should now be lifted."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM temp_bans WHERE expires_at<=? ORDER BY expires_at ASC",
            (now_iso,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_temp_bans_for_guild(guild_id) -> list[dict]:
    """List active temporary bans for one guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM temp_bans WHERE guild_id=? ORDER BY expires_at ASC",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def upsert_invite(guild_id, code, inviter_id, uses):
    """Store the latest usage count for an invite code."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO invites (guild_id, code, inviter_id, uses)
            VALUES (?,?,?,?)
            ON CONFLICT(guild_id, code) DO UPDATE SET
            uses=excluded.uses,
            inviter_id=excluded.inviter_id
            """,
            (guild_id, code, inviter_id, uses),
        )
        await db.commit()


async def get_invites(guild_id) -> list[dict]:
    """Return all stored invite snapshots for one guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM invites WHERE guild_id=?", (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def increment_message_stat(guild_id, user_id, day: str):
    """Increase one member's chat count for a specific date."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO message_stats (guild_id, user_id, day, count) VALUES (?,?,?,1)
            ON CONFLICT(guild_id, user_id, day) DO UPDATE SET count = count + 1
            """,
            (guild_id, user_id, day),
        )
        await db.commit()


async def get_top_chatters(guild_id, limit=10) -> list[dict]:
    """Return the top chatters across all recorded days."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT user_id, SUM(count) as total
            FROM message_stats
            WHERE guild_id=?
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT ?
            """,
            (guild_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def add_voice_time(guild_id, user_id, minutes: int):
    """Accumulate recorded voice minutes for a member."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO voice_stats (guild_id, user_id, minutes) VALUES (?,?,?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET minutes = minutes + ?
            """,
            (guild_id, user_id, minutes, minutes),
        )
        await db.commit()


async def get_top_voice(guild_id, limit=10) -> list[dict]:
    """Return the most active voice users for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, minutes FROM voice_stats WHERE guild_id=? ORDER BY minutes DESC LIMIT ?",
            (guild_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def log_member_event(guild_id, user_id, event: str):
    """Store a simple join or leave event."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO member_log (guild_id, user_id, event) VALUES (?,?,?)",
            (guild_id, user_id, event),
        )
        await db.commit()


async def set_autorole(guild_id, role_id):
    """Save the role that new members should receive automatically."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO autorole_settings (guild_id, role_id)
            VALUES (?,?)
            ON CONFLICT(guild_id) DO UPDATE SET role_id=excluded.role_id
            """,
            (guild_id, role_id),
        )
        await db.commit()


async def clear_autorole(guild_id):
    """Disable automatic role assignment for new members."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM autorole_settings WHERE guild_id=?", (guild_id,))
        await db.commit()


async def get_autorole(guild_id) -> int | None:
    """Return the saved autorole ID, if one exists."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role_id FROM autorole_settings WHERE guild_id=?",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def set_sticky_message(guild_id, channel_id, content: str, created_by_id: int):
    """Create or replace a sticky message definition for a channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        current_message_id = await get_sticky_message_id(channel_id)
        await db.execute(
            """
            INSERT INTO sticky_messages (
                guild_id, channel_id, content, created_by_id, bot_message_id
            ) VALUES (?,?,?,?,?)
            ON CONFLICT(channel_id) DO UPDATE SET
            guild_id=excluded.guild_id,
            content=excluded.content,
            created_by_id=excluded.created_by_id,
            bot_message_id=excluded.bot_message_id
            """,
            (guild_id, channel_id, content, created_by_id, current_message_id),
        )
        await db.commit()


async def clear_sticky_message(channel_id):
    """Remove a sticky message definition from a channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sticky_messages WHERE channel_id=?", (channel_id,))
        await db.commit()


async def get_sticky_message(channel_id) -> dict | None:
    """Return the sticky message settings for one channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sticky_messages WHERE channel_id=?",
            (channel_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_all_sticky_messages(guild_id) -> list[dict]:
    """Return all sticky message definitions for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sticky_messages WHERE guild_id=? ORDER BY channel_id ASC",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_sticky_message_id(channel_id) -> int | None:
    """Return the last sticky message ID posted by the bot in a channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT bot_message_id FROM sticky_messages WHERE channel_id=?",
            (channel_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else None


async def update_sticky_message_id(channel_id, message_id: int | None):
    """Update the bot message ID linked to a sticky definition."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE sticky_messages SET bot_message_id=? WHERE channel_id=?",
            (message_id, channel_id),
        )
        await db.commit()


async def get_guild_settings(guild_id) -> dict | None:
    """Return the stored server-wide appearance and message settings."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guild_settings WHERE guild_id=?",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def upsert_guild_settings(
    guild_id,
    *,
    welcome_channel_id=None,
    leave_channel_id=None,
    welcome_message=None,
    leave_message=None,
    embed_color=None,
    embed_image_url=None,
):
    """Create or update the stored guild settings without losing untouched fields."""
    current = await get_guild_settings(guild_id) or {}
    values = {
        "welcome_channel_id": (
            welcome_channel_id if welcome_channel_id is not None else current.get("welcome_channel_id")
        ),
        "leave_channel_id": (
            leave_channel_id if leave_channel_id is not None else current.get("leave_channel_id")
        ),
        "welcome_message": (
            welcome_message if welcome_message is not None else current.get("welcome_message")
        ),
        "leave_message": (
            leave_message if leave_message is not None else current.get("leave_message")
        ),
        "embed_color": (
            embed_color if embed_color is not None else current.get("embed_color")
        ),
        "embed_image_url": (
            embed_image_url if embed_image_url is not None else current.get("embed_image_url")
        ),
    }

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO guild_settings (
                guild_id, welcome_channel_id, leave_channel_id,
                welcome_message, leave_message, embed_color, embed_image_url
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET
            welcome_channel_id=excluded.welcome_channel_id,
            leave_channel_id=excluded.leave_channel_id,
            welcome_message=excluded.welcome_message,
            leave_message=excluded.leave_message,
            embed_color=excluded.embed_color,
            embed_image_url=excluded.embed_image_url
            """,
            (
                guild_id,
                values["welcome_channel_id"],
                values["leave_channel_id"],
                values["welcome_message"],
                values["leave_message"],
                values["embed_color"],
                values["embed_image_url"],
            ),
        )
        await db.commit()


async def remove_embed_image(guild_id):
    """Clear the shared image or GIF used on branded embeds."""
    current = await get_guild_settings(guild_id) or {}
    await upsert_guild_settings(
        guild_id,
        welcome_channel_id=current.get("welcome_channel_id"),
        leave_channel_id=current.get("leave_channel_id"),
        welcome_message=current.get("welcome_message"),
        leave_message=current.get("leave_message"),
        embed_color=current.get("embed_color"),
        embed_image_url="",
    )


async def get_ticket_settings(guild_id) -> dict | None:
    """Return the saved ticket settings for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ticket_settings WHERE guild_id=?",
            (guild_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def upsert_ticket_settings(guild_id, category_id=None, log_channel_id=None, panel_channel_id=None):
    """Create or update ticket settings without resetting untouched values."""
    current = await get_ticket_settings(guild_id) or {}
    values = {
        "category_id": category_id if category_id is not None else current.get("category_id"),
        "log_channel_id": log_channel_id if log_channel_id is not None else current.get("log_channel_id"),
        "panel_channel_id": panel_channel_id if panel_channel_id is not None else current.get("panel_channel_id"),
    }

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO ticket_settings (guild_id, category_id, log_channel_id, panel_channel_id)
            VALUES (?,?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET
            category_id=excluded.category_id,
            log_channel_id=excluded.log_channel_id,
            panel_channel_id=excluded.panel_channel_id
            """,
            (
                guild_id,
                values["category_id"],
                values["log_channel_id"],
                values["panel_channel_id"],
            ),
        )
        await db.commit()


async def add_ticket_role(guild_id, role_id):
    """Allow a role to access ticket channels by default."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO ticket_roles (guild_id, role_id) VALUES (?,?)",
            (guild_id, role_id),
        )
        await db.commit()


async def remove_ticket_role(guild_id, role_id):
    """Remove a role from default ticket access."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM ticket_roles WHERE guild_id=? AND role_id=?",
            (guild_id, role_id),
        )
        await db.commit()


async def get_ticket_roles(guild_id) -> list[int]:
    """Return all role IDs that have default ticket access."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role_id FROM ticket_roles WHERE guild_id=? ORDER BY role_id",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def add_ticket_category(guild_id, name: str, emoji: str | None = None, description: str | None = None):
    """Create a selectable ticket category entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO ticket_categories (guild_id, name, emoji, description) VALUES (?,?,?,?)",
            (guild_id, name, emoji, description),
        )
        await db.commit()
        return cursor.lastrowid


async def remove_ticket_category(guild_id, category_id: int):
    """Delete a ticket category entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM ticket_categories WHERE guild_id=? AND id=?",
            (guild_id, category_id),
        )
        await db.commit()


async def get_ticket_categories(guild_id) -> list[dict]:
    """Return all ticket category entries for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ticket_categories WHERE guild_id=? ORDER BY id ASC",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def create_ticket(guild_id, channel_id, user_id, category_name: str) -> int:
    """Insert a new ticket record and return its ticket ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, category_name) VALUES (?,?,?,?)",
            (guild_id, channel_id, user_id, category_name),
        )
        await db.commit()
        return cursor.lastrowid


async def get_ticket_by_channel(channel_id) -> dict | None:
    """Return the ticket record linked to a channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tickets WHERE channel_id=?",
            (channel_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_open_ticket_for_user(guild_id, user_id) -> dict | None:
    """Return the newest open ticket for a member, if they have one."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM tickets
            WHERE guild_id=? AND user_id=? AND status='open'
            ORDER BY id DESC
            LIMIT 1
            """,
            (guild_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def close_ticket(channel_id, closed_by_id):
    """Mark an open ticket as closed."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE tickets
            SET status='closed', closed_at=CURRENT_TIMESTAMP, closed_by_id=?
            WHERE channel_id=? AND status='open'
            """,
            (closed_by_id, channel_id),
        )
        await db.commit()


async def get_open_tickets(guild_id) -> list[dict]:
    """Return all open tickets for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id=? AND status='open' ORDER BY id ASC",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def add_reaction_role(guild_id, role_id, label: str, emoji: str | None = None):
    """Store or update one self-assignable role option."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO reaction_roles (guild_id, role_id, label, emoji)
            VALUES (?,?,?,?)
            ON CONFLICT(guild_id, role_id) DO UPDATE SET
            label=excluded.label,
            emoji=excluded.emoji
            """,
            (guild_id, role_id, label, emoji),
        )
        await db.commit()


async def remove_reaction_role(guild_id, role_id):
    """Delete a self-assignable role option."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM reaction_roles WHERE guild_id=? AND role_id=?",
            (guild_id, role_id),
        )
        await db.commit()


async def get_reaction_roles(guild_id) -> list[dict]:
    """Return all configured self-assignable role options for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reaction_roles WHERE guild_id=? ORDER BY label COLLATE NOCASE ASC",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
