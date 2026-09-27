"""SQLite database helpers for the security bot."""

import sqlite3
from datetime import datetime

from .config import SECURITY_DATABASE

# ============================================================
# SECURITY DATABASE
# ============================================================

def security_db():
    db = sqlite3.connect(
        SECURITY_DATABASE,
        timeout=30
    )

    db.row_factory = sqlite3.Row

    return db


def init_security_database():

    with security_db() as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id INTEGER PRIMARY KEY,
                reason TEXT NOT NULL DEFAULT '',
                blocked_at INTEGER NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS security_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL
            )
        """)

        db.commit()


# ============================================================
# BLOCKLIST FUNCTIONS
# ============================================================

def is_blocked(user_id):

    with security_db() as db:

        result = db.execute(
            """
            SELECT 1
            FROM blocked_users
            WHERE user_id = ?
            """,
            (int(user_id),)
        ).fetchone()

        return result is not None


def block_user(user_id, reason):

    now = int(datetime.now().timestamp())

    with security_db() as db:

        db.execute(
            """
            INSERT OR REPLACE INTO blocked_users
            (
                user_id,
                reason,
                blocked_at
            )
            VALUES (?, ?, ?)
            """,
            (
                int(user_id),
                reason[:500],
                now
            )
        )

        db.execute(
            """
            INSERT INTO security_logs
            (
                user_id,
                action,
                details,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(user_id),
                "BLOCK",
                reason[:500],
                now
            )
        )

        db.commit()


def unblock_user(user_id):

    now = int(datetime.now().timestamp())

    with security_db() as db:

        result = db.execute(
            """
            DELETE FROM blocked_users
            WHERE user_id = ?
            """,
            (int(user_id),)
        )

        db.execute(
            """
            INSERT INTO security_logs
            (
                user_id,
                action,
                details,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(user_id),
                "UNBLOCK",
                "",
                now
            )
        )

        db.commit()

        return result.rowcount > 0


def get_blocked_users():

    with security_db() as db:

        return db.execute(
            """
            SELECT user_id, reason, blocked_at
            FROM blocked_users
            ORDER BY blocked_at DESC
            """
        ).fetchall()


