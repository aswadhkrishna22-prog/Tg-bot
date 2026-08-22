import asyncio
import os
import sqlite3
import psycopg
import html
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ============================================================
# CONFIG
# ============================================================

load_dotenv()

try:
    API_ID = int(os.getenv("TG_API_ID", "0"))
except ValueError:
    raise RuntimeError("TG_API_ID must be a number")

API_HASH = os.getenv("TG_API_HASH", "").strip()
SECURITY_BOT_TOKEN = os.getenv("SECURITY_BOT_TOKEN", "").strip()

try:
    OWNER_ID = int(os.getenv("SECURITY_OWNER_ID", "0"))
except ValueError:
    raise RuntimeError("SECURITY_OWNER_ID must be a number")

if API_ID <= 0:
    raise RuntimeError("TG_API_ID is missing or invalid")

if not API_HASH:
    raise RuntimeError("TG_API_HASH is missing")

if not SECURITY_BOT_TOKEN:
    raise RuntimeError("SECURITY_BOT_TOKEN is missing")

if OWNER_ID <= 0:
    raise RuntimeError("SECURITY_OWNER_ID is missing or invalid")


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

SECURITY_DATABASE = BASE_DIR / "security.db"

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    ""
).strip()

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing"
    )
# ============================================================
# STADY-PROXY POSTGRESQL
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    ""
).strip()

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing"
    )


def files_pg_db():

    return psycopg.connect(
        DATABASE_URL,
        row_factory=psycopg.rows.dict_row
    )

# ============================================================
# TELEGRAM
# ============================================================

security_bot = TelegramClient(
    "security_bot",
    API_ID,
    API_HASH
)


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


# ============================================================
# STADY-PROXY FILE DATABASE — NEON POSTGRESQL
# ============================================================

def get_proxy_users():

    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute("""
                    SELECT
                        chat_id,
                        COUNT(*) AS file_count
                    FROM files
                    GROUP BY chat_id
                    ORDER BY file_count DESC
                """)

                return cursor.fetchall()

    except Exception as error:

        print(
            "[SECURITY] PostgreSQL users error:",
            error
        )

        return []
def get_user_files(user_id):

    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute("""
                    SELECT
                        token,
                        filename,
                        size,
                        mime
                    FROM files
                    WHERE chat_id = %s
                    ORDER BY token DESC
                """, (
                    int(user_id),
                ))

                return cursor.fetchall()

    except Exception as error:

        print(
            "[SECURITY] PostgreSQL files error:",
            error
        )

        return []

def purge_user_files(user_id):

    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute(
                    """
                    DELETE FROM files
                    WHERE chat_id = %s
                    """,
                    (int(user_id),)
                )

                removed = cursor.rowcount

            db.commit()

            return removed

    except Exception as error:

        print(
            "[SECURITY] PostgreSQL purge error:",
            error
        )

        return 0

def purge_all_blocked_users():

    blocked = get_blocked_users()

    total_removed = 0

    for row in blocked:

        user_id = int(
            row["user_id"]
        )

        removed = purge_user_files(
            user_id
        )

        total_removed += removed

    return total_removed
# ============================================================
# STADY-PROXY FILE DATABASE — NEON POSTGRESQL
# ============================================================

def get_proxy_users():

    try:

        with psycopg2.connect(
            DATABASE_URL,
            sslmode="require",
            cursor_factory=RealDictCursor
        ) as db:

            with db.cursor() as cursor:

                cursor.execute("""
                    SELECT
                        chat_id,
                        COUNT(*) AS file_count
                    FROM files
                    GROUP BY chat_id
                    ORDER BY file_count DESC
                """)

                return cursor.fetchall()

    except Exception as error:

        print(
   # ============================================================
# STADY-PROXY FILE DATABASE — NEON POSTGRESQL
# ============================================================

def get_proxy_users():

    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute("""
                    SELECT
                        chat_id,
                        COUNT(*) AS file_count
                    FROM files
                    GROUP BY chat_id
                    ORDER BY file_count DESC
                """)

                return cursor.fetchall()

    except Exception as error:

        print(
            "[SECURITY] PostgreSQL users error:",
            error
        )

        return []


def get_user_files(user_id):

    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute("""
                    SELECT
                        token,
                        filename,
                        size,
                        mime
                    FROM files
                    WHERE chat_id = %s
                    ORDER BY token DESC
                """, (
                    int(user_id),
                ))

                return cursor.fetchall()

    except Exception as error:

        print(
            "[SECURITY] PostgreSQL files error:",
            error
        )

        return []


def purge_user_files(user_id):

    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute("""
                    DELETE FROM files
                    WHERE chat_id = %s
                """, (
                    int(user_id),
                ))

                removed = cursor.rowcount

            db.commit()

            return removed

    except Exception as error:

        print(
            "[SECURITY] PostgreSQL purge error:",
            error
        )

        return 0


def purge_all_blocked_users():

    blocked = get_blocked_users()

    total_removed = 0

    for row in blocked:

        user_id = int(
            row["user_id"]
        )

        removed = purge_user_files(
            user_id
        )

        total_removed += removed

    return total_removed
# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(event):

    try:

        return int(event.sender_id or 0) == OWNER_ID

    except Exception:

        return False


# ============================================================
# /START
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/start$"
    )
)
async def start_command(event):

    if not is_admin(event):

        await event.reply(
            "⛔ Access denied."
        )

        return

    await event.reply(
        "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
        "      🛡️ STADY SECURITY\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"

        "👥 <code>/users</code>\n"
        "View users currently using STADY-PROXY.\n\n"

        "🔎 <code>/inspect USER_ID</code>\n"
        "View a user's active files.\n\n"

        "🚫 <code>/block USER_ID reason</code>\n"
        "Block a user and revoke their links.\n\n"

        "✅ <code>/unblock USER_ID</code>\n"
        "Unblock a user.\n\n"

        "🚷 <code>/blocked</code>\n"
        "View blocked users.\n\n"

        "🧹 <code>/purge</code>\n"
        "Remove links belonging to blocked users.",
        parse_mode="html"
    )


# ============================================================
# /USERS
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/users$"
    )
)
async def users_command(event):

    if not is_admin(event):
        return

    users = get_proxy_users()

    if not users:

        await event.reply(
            "📭 No users/files found in files.db."
        )

        return

    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━━━╮",
        "       👥 STADY USERS",
        "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        ""
    ]

    for row in users[:100]:

        user_id = int(row["chat_id"])

        count = int(
            row["file_count"]
        )

        status = (
            "🚫 BLOCKED"
            if is_blocked(user_id)
            else "✅ ACTIVE"
        )

        lines.append(
            f"• <code>{user_id}</code> "
            f"— {count} file(s) "
            f"— {status}"
        )

    await event.reply(
        "\n".join(lines),
        parse_mode="html"
    )


# ============================================================
# /INSPECT
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/inspect\s+(\d+)$"
    )
)
async def inspect_command(event):

    if not is_admin(event):
        return

    user_id = int(
        event.pattern_match.group(1)
    )

    files = get_user_files(
        user_id
    )

    status = (
        "🚫 BLOCKED"
        if is_blocked(user_id)
        else "✅ ACTIVE"
    )

    if not files:

        await event.reply(
            "🔎 <b>USER INSPECTION</b>\n\n"
            f"User ID: <code>{user_id}</code>\n"
            f"Status: {status}\n\n"
            "📭 No active files.",
            parse_mode="html"
        )

        return

    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━━━╮",
        "       🔎 USER INSPECTION",
        "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        "",
        f"👤 User ID: <code>{user_id}</code>",
        f"Status: {status}",
        f"📦 Files: <code>{len(files)}</code>",
        ""
    ]

    for row in files[:30]:

        filename = html.escape(
            str(row["filename"])
        )

        size = int(
            row["size"] or 0
        )

        size_mb = (
            size / 1024 / 1024
        )

        token = str(
            row["token"]
        )

        lines.append(
            f"📄 <b>{filename}</b>\n"
            f"   Size: <code>{size_mb:.2f} MB</code>\n"
            f"   Token: <code>{token}</code>\n"
        )

    await event.reply(
        "\n".join(lines),
        parse_mode="html"
    )


# ============================================================
# /BLOCK
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/block\s+(\d+)(?:\s+(.+))?$"
    )
)
async def block_command(event):

    if not is_admin(event):
        return

    user_id = int(
        event.pattern_match.group(1)
    )

    reason = (
        event.pattern_match.group(2)
        or "Blocked by administrator"
    ).strip()

    if user_id == OWNER_ID:

        await event.reply(
            "❌ You cannot block yourself."
        )

        return

    block_user(
        user_id,
        reason
    )

    removed = purge_user_files(
        user_id
    )

    await event.reply(
        "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
        "        🚫 USER BLOCKED\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"

        f"👤 User ID: <code>{user_id}</code>\n"
        f"📝 Reason: {html.escape(reason)}\n"
        f"🗑️ Links revoked: <code>{removed}</code>",
        parse_mode="html"
    )


# ============================================================
# /UNBLOCK
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/unblock\s+(\d+)$"
    )
)
async def unblock_command(event):

    if not is_admin(event):
        return

    user_id = int(
        event.pattern_match.group(1)
    )

    changed = unblock_user(
        user_id
    )

    if changed:

        text = (
            "✅ <b>USER UNBLOCKED</b>\n\n"
            f"User ID: <code>{user_id}</code>"
        )

    else:

        text = (
            "ℹ️ User is not currently blocked.\n\n"
            f"User ID: <code>{user_id}</code>"
        )

    await event.reply(
        text,
        parse_mode="html"
    )


# ============================================================
# /BLOCKED
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/blocked$"
    )
)
async def blocked_command(event):

    if not is_admin(event):
        return

    rows = get_blocked_users()

    if not rows:

        await event.reply(
            "✅ Blocklist is empty."
        )

        return

    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━━━╮",
        "       🚫 BLOCKED USERS",
        "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        ""
    ]

    for row in rows[:100]:

        user_id = int(
            row["user_id"]
        )

        reason = html.escape(
            str(row["reason"] or "No reason")
        )

        lines.append(
            f"• <code>{user_id}</code>\n"
            f"  📝 {reason}\n"
        )

    await event.reply(
        "\n".join(lines),
        parse_mode="html"
    )


# ============================================================
# /PURGE
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/purge$"
    )
)
async def purge_command(event):

    if not is_admin(event):
        return

    removed = purge_all_blocked_users()

    await event.reply(
        "🧹 <b>PURGE COMPLETE</b>\n\n"
        f"Revoked links: <code>{removed}</code>",
        parse_mode="html"
    )


# ============================================================
# AUTOMATIC CLEANUP
# ============================================================

async def cleanup_loop():

    while True:

        try:

            removed = (
                purge_all_blocked_users()
            )

            if removed:

                print(
                    "[SECURITY] Revoked "
                    f"{removed} blocked-user link(s)."
                )

        except Exception as error:

            print(
                "[SECURITY] Cleanup error:",
                error
            )

        await asyncio.sleep(10)


# ============================================================
# MAIN
# ============================================================

async def main():

    init_security_database()

    print()
    print("=" * 60)
    print("       STADY-PROXY SECURITY BOT")
    print("=" * 60)

    print(
        "[+] Connecting to Telegram..."
    )

    await security_bot.start(
        bot_token=SECURITY_BOT_TOKEN
    )

    me = await security_bot.get_me()

    username = (
        me.username
        if me.username
        else str(me.id)
    )

    print(
        f"[+] Security bot: @{username}"
    )

    print(
        f"[+] Owner ID: {OWNER_ID}"
    )

    print(
        f"[+] Security DB: {SECURITY_DATABASE}"
    )

    print(
        f"[+] STADY files DB: {FILES_DATABASE}"
    )

    print(
        "[+] Security system ready"
    )

    print("=" * 60)

    cleanup_task = asyncio.create_task(
        cleanup_loop()
    )

    try:

        await security_bot.run_until_disconnected()

    finally:

        cleanup_task.cancel()

        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

        await security_bot.disconnect()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\n[+] Security bot stopped."
        )
