import asyncio
import os
import sqlite3
import psycopg
import html
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, events, Button

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
                        u.user_id,
                        u.first_name,
                        u.last_name,
                        u.first_seen,
                        COUNT(f.token) AS file_count
                    FROM users u
                    LEFT JOIN files f
                        ON f.chat_id = u.user_id
                    GROUP BY
                        u.user_id,
                        u.first_name,
                        u.last_name,
                        u.first_seen
                    ORDER BY u.first_seen DESC
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

# ============================================================
# REMOVE FUNCTIONS
# ============================================================

def remove_user_data(user_id):

    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                # Get tokens first
                cursor.execute(
                    """
                    SELECT token
                    FROM files
                    WHERE chat_id = %s
                    """,
                    (int(user_id),)
                )

                rows = cursor.fetchall()

                tokens = [
                    str(row["token"])
                    for row in rows
                ]

                # Remove access history for this user
                cursor.execute(
                    """
                    DELETE FROM access_logs
                    WHERE chat_id = %s
                    """,
                    (int(user_id),)
                )

                # Remove all generated file/link records
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
            "[SECURITY] Remove user error:",
            error
        )

        raise


def remove_token_data(token):

    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT
                        token,
                        chat_id,
                        filename
                    FROM files
                    WHERE token = %s
                    """,
                    (token,)
                )

                row = cursor.fetchone()

                if not row:

                    return None

                cursor.execute(
                    """
                    DELETE FROM access_logs
                    WHERE token = %s
                    """,
                    (token,)
                )

                cursor.execute(
                    """
                    DELETE FROM files
                    WHERE token = %s
                    """,
                    (token,)
                )

                removed = cursor.rowcount

            db.commit()

            return {
                "removed": removed,
                "chat_id": row["chat_id"],
                "filename": row["filename"],
                "token": row["token"]
            }

    except Exception as error:

        print(
            "[SECURITY] Remove token error:",
            error
        )

        raise

def remove_user_files(user_id):

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
            "[SECURITY] Remove user error:",
            error
        )

        return -1


def remove_file_by_token(token):
    try:

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute(
                    """
                    DELETE FROM files
                    WHERE token = %s
                    """,
                    (token,)
                )

                removed = cursor.rowcount

            db.commit()

            return removed

    except Exception as error:

        print(
            "[SECURITY] Remove token error:",
            error
        )

        return -1

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
# INTERACTIVE ADMIN ACTIONS
# ============================================================

pending_actions = {}


def set_pending_action(user_id, action):
    pending_actions[int(user_id)] = action


def get_pending_action(user_id):
    return pending_actions.get(int(user_id))


def clear_pending_action(user_id):
    pending_actions.pop(int(user_id), None)


async def cancel_pending_action(event):
    clear_pending_action(event.sender_id)

    await event.reply(
        "❌ <b>Action cancelled.</b>",
        parse_mode="html"
    )


async def confirm_action(event, action, value):

    if not is_admin(event):
        return

    buttons = [
        [
            Button.inline(
                "✅ Confirm",
                data=f"confirm:{action}:{value}".encode()
            ),
            Button.inline(
                "❌ Cancel",
                data=b"cancel_action"
            )
        ]
    ]

    await event.reply(
        "⚠️ <b>CONFIRM ACTION</b>\n\n"
        f"Action: <code>{html.escape(action)}</code>\n"
        f"Target: <code>{html.escape(str(value))}</code>\n\n"
        "Are you sure?",
        buttons=buttons,
        parse_mode="html"
    )

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
        "🗑️ <code>/remove USER_ID</code>\n"
       "Remove all generated links for a user.\n\n"
         "🗑️ <code>/remove TOKEN</code>\n"
         "Remove one generated link.\n\n"

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

    print(
        "[DEBUG /users] sender_id:",
        event.sender_id,
        "owner_id:",
        OWNER_ID
    )

    if not is_admin(event):
        return

    users = get_proxy_users()

    if not users:

        await event.reply(
            "📭 No users/files found."
        )

        return

    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━━━╮",
        "       👥 STADY USERS",
        "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        ""
    ]

    for row in users[:100]:

        user_id = int(row["user_id"])

        first_name = row["first_name"] or ""
        last_name = row["last_name"] or ""

        name = (
            f"{first_name} {last_name}".strip()
            or "Unknown"
        )

        first_seen = row["first_seen"]

        if first_seen:
            started = first_seen.strftime(
                "%d %b %Y, %I:%M %p"
            )
        else:
            started = "Unknown"

        count = int(row["file_count"])

        status = (
            "🚫 BLOCKED"
            if is_blocked(user_id)
            else "✅ ACTIVE"
        )

        lines.extend([
            f"👤 <b>{html.escape(name)}</b>",
            f"🆔 <code>{user_id}</code>",
            f"📅 Started: <code>{started}</code>",
            f"📁 Files: <code>{count}</code>",
            status,
            ""
        ])

    await event.reply(
        "\n".join(lines),
        parse_mode="html"
    )

# ============================================================
# /INSPECT
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/inspect(?:\s+(\d+))?$"
    )
)
async def inspect_command(event):

    if not is_admin(event):
        return

    match = event.pattern_match

    # --------------------------------------------------------
    # /inspect without USER_ID → ask
    # --------------------------------------------------------

    if not match.group(1):

        set_pending_action(
            event.sender_id,
            "inspect"
        )

        await event.reply(
            "🔎 <b>USER INSPECTION</b>\n\n"
            "Send the <b>Telegram User ID</b> you want to inspect.\n\n"
            "Example:\n"
            "<code>8540425480</code>\n\n"
            "Use /cancel to cancel.",
            parse_mode="html"
        )

        return

    user_id = int(
        match.group(1)
    )

    await perform_inspect(
        event,
        user_id
    )


async def perform_inspect(event, user_id):

    try:

        files = get_user_files(
            user_id
        )

        status = (
            "🚫 BLOCKED"
            if is_blocked(user_id)
            else "✅ ACTIVE"
        )

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT
                        token,
                        filename,
                        action,
                        ip,
                        user_agent,
                        accessed_at
                    FROM access_logs
                    WHERE chat_id = %s
                    ORDER BY accessed_at DESC
                    LIMIT 100
                    """,
                    (int(user_id),)
                )

                history = cursor.fetchall()

        if not files and not history:

            await event.reply(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "       🔎 USER INSPECTION\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"Status: {status}\n\n"
                "📭 No files or access history found.",
                parse_mode="html"
            )

            return

        # ----------------------------------------------------
        # IMPORTANT:
        # Telegram messages have a size limit.
        # Send files/history separately.
        # ----------------------------------------------------

        await event.reply(
            "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
            "       🔎 USER INSPECTION\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"Status: {status}\n"
            f"📦 Files: <code>{len(files)}</code>\n"
            f"📊 Logged requests: <code>{len(history)}</code>",
            parse_mode="html"
        )

        # ----------------------------------------------------
        # FILES
        # ----------------------------------------------------

        if files:

            file_lines = [
                "📦 <b>ACTIVE FILES</b>",
                "━━━━━━━━━━━━━━━━━━━━━━"
            ]

            for index, row in enumerate(
                files,
                start=1
            ):

                filename = html.escape(
                    str(row["filename"] or "Unknown")
                )

                token = html.escape(
                    str(row["token"] or "")
                )

                size = int(
                    row["size"] or 0
                )

                if size >= 1024 ** 3:

                    size_text = (
                        f"{size / 1024 ** 3:.2f} GB"
                    )

                elif size >= 1024 ** 2:

                    size_text = (
                        f"{size / 1024 ** 2:.2f} MB"
                    )

                elif size >= 1024:

                    size_text = (
                        f"{size / 1024:.2f} KB"
                    )

                else:

                    size_text = f"{size} B"

                block = (
                    f"\n<b>{index}. {filename}</b>\n"
                    f"📦 Size: <code>{size_text}</code>\n"
                    f"🔑 Token: <code>{token}</code>\n"
                )

                # Prevent Telegram message overflow.
                if (
                    len("\n".join(file_lines))
                    + len(block)
                    > 3500
                ):

                    await event.reply(
                        "\n".join(file_lines),
                        parse_mode="html"
                    )

                    file_lines = []

                file_lines.append(
                    block
                )

            if file_lines:

                await event.reply(
                    "\n".join(file_lines),
                    parse_mode="html"
                )

        # ----------------------------------------------------
        # ACCESS HISTORY
        # ----------------------------------------------------

        if history:

            history_lines = [
                "📊 <b>ACCESS HISTORY</b>",
                "━━━━━━━━━━━━━━━━━━━━━━"
            ]

            for row in history:

                filename = html.escape(
                    str(row["filename"] or "Unknown")
                )

                action = (
                    str(row["action"] or "unknown")
                    .lower()
                )

                ip = html.escape(
                    str(row["ip"] or "Unknown")
                )

                accessed_at = html.escape(
                    str(row["accessed_at"] or "Unknown")
                )

                if action == "watch":

                    icon = "👁️"
                    action_name = "WATCH PAGE"

                elif action == "stream":

                    icon = "▶️"
                    action_name = "STREAM"

                elif action == "download":

                    icon = "📥"
                    action_name = "DOWNLOAD"

                else:

                    icon = "❔"
                    action_name = action.upper()

                block = (
                    f"\n{icon} <b>{action_name}</b>\n"
                    f"🎬 {filename}\n"
                    f"🌐 IP: <code>{ip}</code>\n"
                    f"🕐 <code>{accessed_at}</code>\n"
                )

                if (
                    len("\n".join(history_lines))
                    + len(block)
                    > 3500
                ):

                    await event.reply(
                        "\n".join(history_lines),
                        parse_mode="html"
                    )

                    history_lines = []

                history_lines.append(
                    block
                )

            if history_lines:

                await event.reply(
                    "\n".join(history_lines),
                    parse_mode="html"
                )
    except Exception as error:

        print(
            "[SECURITY] Inspect error:",
            error
        )

        await event.reply(
            "❌ <b>Inspect failed</b>\n\n"
            f"<code>{html.escape(str(error))}</code>",
            parse_mode="html"
        )

# ============================================================
# /REMOVE
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/remove(?:\s+(.+))?$"
    )
)
async def remove_command(event):

    if not is_admin(event):
        return

    match = event.pattern_match

    # --------------------------------------------------------
    # /remove → ask
    # --------------------------------------------------------

    if not match.group(1):

        set_pending_action(
            event.sender_id,
            "remove"
        )

        await event.reply(
            "🗑️ <b>REMOVE DATA</b>\n\n"
            "Send either:\n\n"
            "👤 <b>User ID</b> — remove ALL generated "
            "links/files for that user.\n\n"
            "🔑 <b>Token</b> — remove ONLY that generated "
            "file/link.\n\n"
            "Example User ID:\n"
            "<code>8540425480</code>\n\n"
            "Example Token:\n"
            "<code>fd47579b090041028a6073c8ee6835cd</code>\n\n"
            "Use /cancel to cancel.",
            parse_mode="html"
        )

        return

    value = match.group(1).strip()

    await prepare_remove(
        event,
        value
    )


async def prepare_remove(event, value):

    # --------------------------------------------------------
    # USER ID
    # --------------------------------------------------------

    if value.isdigit():

        user_id = int(value)

        set_pending_action(
            event.sender_id,
            f"remove_user:{user_id}"
        )

        await confirm_action(
            event,
            "remove_user",
            user_id
        )

        return

    # --------------------------------------------------------
    # TOKEN
    # --------------------------------------------------------

    if (
        len(value) == 32
        and all(
            c in "0123456789abcdefABCDEF"
            for c in value
        )
    ):

        token = value

        set_pending_action(
            event.sender_id,
            f"remove_token:{token}"
        )

        await confirm_action(
            event,
            "remove_token",
            token
        )

        return

    await event.reply(
        "❌ <b>Invalid input.</b>\n\n"
        "Send either a numeric User ID or a valid 32-character token.",
        parse_mode="html"
    )
# ============================================================
# CONFIRMATION CALLBACKS
# ============================================================

@security_bot.on(
    events.CallbackQuery(
        pattern=rb"^confirm:"
    )
)
async def confirm_callback(event):

    if not is_admin(event):
        await event.answer(
            "⛔ Access denied.",
            alert=True
        )
        return

    try:

        data = event.data.decode(
            "utf-8"
        )

        parts = data.split(
            ":",
            2
        )

        if len(parts) != 3:

            await event.answer(
                "Invalid action.",
                alert=True
            )

            return

        _, action, value = parts

        # ----------------------------------------------------
        # BLOCK
        # ----------------------------------------------------

        if action == "block":

            user_id = int(value)

            if user_id == OWNER_ID:

                await event.answer(
                    "You cannot block yourself.",
                    alert=True
                )

                return

            pending = get_pending_action(
                event.sender_id
            )

            reason = "Blocked by administrator"

            if pending and pending.startswith(
                "block:"
            ):

                pending_parts = pending.split(
                    ":",
                    2
                )

                if len(pending_parts) == 3:

                    reason = (
                        pending_parts[2]
                        or reason
                    )

            block_user(
                user_id,
                reason
            )

            removed = purge_user_files(
                user_id
            )

            clear_pending_action(
                event.sender_id
            )

            await event.edit(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "        🚫 USER BLOCKED\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"📝 Reason: {html.escape(reason)}\n"
                f"🗑️ Links revoked: <code>{removed}</code>",
                parse_mode="html"
            )

            return

        # ----------------------------------------------------
        # REMOVE USER
        # ----------------------------------------------------

        if action == "remove_user":

            user_id = int(value)

            removed = remove_user_data(
                user_id
            )

            clear_pending_action(
                event.sender_id
            )

            await event.edit(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "        🗑️ USER DATA REMOVED\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"📦 Records removed: <code>{removed}</code>\n\n"
                "✅ Generated links and related access history removed.",
                parse_mode="html"
            )

            return

        # ----------------------------------------------------
        # REMOVE TOKEN
        # ----------------------------------------------------

        if action == "remove_token":

            token = value

            result = remove_token_data(
                token
            )

            clear_pending_action(
                event.sender_id
            )

            if not result:

                await event.edit(
                    "❌ <b>Token not found.</b>\n\n"
                    f"🔑 <code>{html.escape(token)}</code>",
                    parse_mode="html"
                )

                return

            filename = html.escape(
                str(
                    result["filename"]
                    or "Unknown"
                )
            )

            await event.edit(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "        🗑️ FILE REMOVED\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"📄 <b>{filename}</b>\n"
                f"👤 User ID: <code>{result['chat_id']}</code>\n"
                f"🔑 Token: <code>{html.escape(token)}</code>\n\n"
                "✅ Generated link and related access history removed.",
                parse_mode="html"
            )

            return

        await event.answer(
            "Unknown action.",
            alert=True
        )

    except Exception as error:

        print(
            "[SECURITY] Confirmation error:",
            error
        )

        await event.answer(
            "Operation failed.",
            alert=True
        )

        try:

            await event.edit(
                "❌ <b>Operation failed</b>\n\n"
                f"<code>{html.escape(str(error))}</code>",
                parse_mode="html"
            )

        except Exception:
            pass


# ============================================================
# CANCEL CALLBACK
# ============================================================

@security_bot.on(
    events.CallbackQuery(
        pattern=rb"^cancel_action$"
    )
)
async def cancel_action_callback(event):

    if not is_admin(event):
        await event.answer(
            "⛔ Access denied.",
            alert=True
        )
        return

    clear_pending_action(
        event.sender_id
    )

    await event.edit(
        "❌ <b>Action cancelled.</b>",
        parse_mode="html"
    )
# ============================================================
# /CANCEL
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/cancel$"
    )
)
async def cancel_command(event):

    if not is_admin(event):
        return

    clear_pending_action(
        event.sender_id
    )

    await event.reply(
        "❌ <b>Action cancelled.</b>",
        parse_mode="html"
    )
# ============================================================
# INTERACTIVE INPUT HANDLER
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^(?!/).+"
    )
)
async def interactive_input_handler(event):

    if not is_admin(event):
        return

    pending = get_pending_action(
        event.sender_id
    )

    if not pending:
        return

    value = (
        event.raw_text or ""
    ).strip()

    # --------------------------------------------------------
    # INSPECT
    # --------------------------------------------------------

    if pending == "inspect":

        if not value.isdigit():

            await event.reply(
                "❌ Please send a numeric User ID.",
                parse_mode="html"
            )

            return

        clear_pending_action(
            event.sender_id
        )

        await perform_inspect(
            event,
            int(value)
        )

        return

    # --------------------------------------------------------
    # BLOCK
    # --------------------------------------------------------

    if pending == "block":

        if not value.isdigit():

            await event.reply(
                "❌ Please send a numeric User ID.",
                parse_mode="html"
            )

            return

        user_id = int(value)

        if user_id == OWNER_ID:

            clear_pending_action(
                event.sender_id
            )

            await event.reply(
                "❌ You cannot block yourself."
            )

            return

        set_pending_action(
            event.sender_id,
            f"block:{user_id}:Blocked by administrator"
        )

        await confirm_action(
            event,
            "block",
            user_id
        )

        return

    # --------------------------------------------------------
    # REMOVE
    # --------------------------------------------------------

    if pending == "remove":

        if value.isdigit():

            user_id = int(value)

            set_pending_action(
                event.sender_id,
                f"remove_user:{user_id}"
            )

            await confirm_action(
                event,
                "remove_user",
                user_id
            )

            return

        if (
            len(value) == 32
            and all(
                c in "0123456789abcdefABCDEF"
                for c in value
            )
        ):

            set_pending_action(
                event.sender_id,
                f"remove_token:{value}"
            )

            await confirm_action(
                event,
                "remove_token",
                value
            )

            return

        await event.reply(
            "❌ Invalid input.\n\n"
            "Send a User ID or 32-character token.",
            parse_mode="html"
        )

        return

# ============================================================
# /BLOCK
# ============================================================

@security_bot.on(
    events.NewMessage(
        pattern=r"^/block(?:\s+(\d+)(?:\s+(.+))?)?$"
    )
)
async def block_command(event):

    if not is_admin(event):
        return

    match = event.pattern_match

    # --------------------------------------------------------
    # /block → ask for USER_ID
    # --------------------------------------------------------

    if not match.group(1):

        set_pending_action(
            event.sender_id,
            "block"
        )

        await event.reply(
            "🚫 <b>BLOCK USER</b>\n\n"
            "Send the <b>User ID</b> you want to block.\n\n"
            "Example:\n"
            "<code>8540425480</code>\n\n"
            "Use /cancel to cancel.",
            parse_mode="html"
        )

        return

    user_id = int(
        match.group(1)
    )

    reason = (
        match.group(2)
        or "Blocked by administrator"
    ).strip()

    if user_id == OWNER_ID:

        await event.reply(
            "❌ You cannot block yourself."
        )

        return

    set_pending_action(
        event.sender_id,
        f"block:{user_id}:{reason}"
    )

    await confirm_action(
        event,
        "block",
        user_id
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
        "[+] STADY files DB: Neon PostgreSQL"
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
