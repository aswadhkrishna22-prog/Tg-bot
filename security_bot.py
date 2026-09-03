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
# SECURITY BOT V2 — ABUSE PROTECTION / MONITORING
# ============================================================

SECURITY_V2_ENABLED = os.getenv("SECURITY_V2_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
SECURITY_RATE_WINDOW = max(10, int(os.getenv("SECURITY_RATE_WINDOW", "60")))
SECURITY_MAX_REQUESTS = max(10, int(os.getenv("SECURITY_MAX_REQUESTS", "120")))
SECURITY_MAX_STREAMS = max(1, int(os.getenv("SECURITY_MAX_STREAMS", "5")))
SECURITY_AUTO_BLOCK_THRESHOLD = max(1, int(os.getenv("SECURITY_AUTO_BLOCK_THRESHOLD", "3")))
SECURITY_TEMP_BLOCK_MINUTES = max(1, int(os.getenv("SECURITY_TEMP_BLOCK_MINUTES", "30")))
SECURITY_LOG_RETENTION_DAYS = max(1, int(os.getenv("SECURITY_LOG_RETENTION_DAYS", "30")))
SECURITY_SCAN_INTERVAL = max(10, int(os.getenv("SECURITY_SCAN_INTERVAL", "30")))
SECURITY_PENDING_TIMEOUT = max(60, int(os.getenv("SECURITY_PENDING_TIMEOUT", "300")))
SECURITY_CONFIRM_TIMEOUT = max(30, int(os.getenv("SECURITY_CONFIRM_TIMEOUT", "120")))
SECURITY_MAX_TRACKED_IPS = max(100, int(os.getenv("SECURITY_MAX_TRACKED_IPS", "10000")))

security_v2_state = {
    "started_at": int(datetime.now().timestamp()),
    "lockdown": False,
    "auto_blocks": 0,
    "requests_scanned": 0,
    "last_scan": 0,
}
security_v2_confirmations = {}
security_v2_ip_hits = {}
security_v2_user_hits = {}
security_v2_pending_times = {}


def _v2_now():
    return int(datetime.now().timestamp())


def init_security_v2_database():
    with security_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS temporary_blocks (
                user_id INTEGER PRIMARY KEY,
                reason TEXT NOT NULL DEFAULT '',
                blocked_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                strikes INTEGER NOT NULL DEFAULT 1
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS security_strikes (
                user_id INTEGER PRIMARY KEY,
                strikes INTEGER NOT NULL DEFAULT 0,
                last_reason TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_security_logs_user_time ON security_logs(user_id, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_temporary_blocks_expiry ON temporary_blocks(expires_at)")
        db.commit()


def is_temporarily_blocked(user_id):
    now = _v2_now()
    with security_db() as db:
        row = db.execute(
            "SELECT expires_at FROM temporary_blocks WHERE user_id = ?",
            (int(user_id),)
        ).fetchone()
        if not row:
            return False
        if int(row["expires_at"]) <= now:
            db.execute("DELETE FROM temporary_blocks WHERE user_id = ?", (int(user_id),))
            db.commit()
            return False
        return True


def temporary_block_user(user_id, reason, minutes=None, strikes=1):
    user_id = int(user_id)
    if user_id == OWNER_ID:
        return False
    minutes = SECURITY_TEMP_BLOCK_MINUTES if minutes is None else max(1, int(minutes))
    now = _v2_now()
    expires = now + minutes * 60
    with security_db() as db:
        db.execute(
            """INSERT INTO temporary_blocks(user_id, reason, blocked_at, expires_at, strikes)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason, blocked_at=excluded.blocked_at,
               expires_at=excluded.expires_at, strikes=excluded.strikes""",
            (user_id, str(reason)[:500], now, expires, int(strikes))
        )
        db.execute(
            """INSERT INTO security_logs(user_id, action, details, created_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, "AUTO_TEMP_BLOCK", f"{str(reason)[:500]} | {minutes}m", now)
        )
        db.commit()
    return True


def add_security_strike(user_id, reason):
    user_id = int(user_id)
    now = _v2_now()
    with security_db() as db:
        row = db.execute("SELECT strikes FROM security_strikes WHERE user_id = ?", (user_id,)).fetchone()
        strikes = int(row["strikes"]) + 1 if row else 1
        db.execute(
            """INSERT INTO security_strikes(user_id, strikes, last_reason, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET strikes=excluded.strikes, last_reason=excluded.last_reason, updated_at=excluded.updated_at""",
            (user_id, strikes, str(reason)[:500], now)
        )
        db.commit()
    return strikes


def get_security_strike(user_id):
    with security_db() as db:
        row = db.execute("SELECT strikes FROM security_strikes WHERE user_id = ?", (int(user_id),)).fetchone()
        return int(row["strikes"]) if row else 0


def _v2_rate_count(rows, now, window):
    cutoff = now - window
    return sum(1 for row in rows if int(row[0]) >= cutoff)


def scan_access_abuse():
    """Inspect recent access_logs and auto-block obvious request/stream abuse."""
    if not SECURITY_V2_ENABLED or security_v2_state["lockdown"]:
        return {"users": 0, "ips": 0, "blocked": 0}
    now = _v2_now()
    cutoff = now - SECURITY_RATE_WINDOW
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """SELECT chat_id, ip, action, accessed_at FROM access_logs
                       WHERE accessed_at >= NOW() - (%s * INTERVAL '1 second') ORDER BY accessed_at DESC LIMIT 5000""",
                    (SECURITY_RATE_WINDOW,)
                )
                rows = cursor.fetchall()
        security_v2_state["requests_scanned"] += len(rows)
        user_counts = {}
        ip_counts = {}
        stream_counts = {}
        for row in rows:
            uid = int(row["chat_id"] or 0)
            ip = str(row["ip"] or "unknown")
            action = str(row["action"] or "").lower()
            if uid > 0:
                user_counts[uid] = user_counts.get(uid, 0) + 1
                if action == "stream":
                    stream_counts[uid] = stream_counts.get(uid, 0) + 1
            ip_counts[ip] = ip_counts.get(ip, 0) + 1
        blocked = 0
        for uid, count in user_counts.items():
            if uid == OWNER_ID or is_blocked(uid) or is_temporarily_blocked(uid):
                continue
            reason = None
            if count > SECURITY_MAX_REQUESTS:
                reason = f"Automatic abuse protection: {count} requests/{SECURITY_RATE_WINDOW}s"
            elif stream_counts.get(uid, 0) > SECURITY_MAX_STREAMS:
                reason = f"Automatic abuse protection: {stream_counts[uid]} stream requests/{SECURITY_RATE_WINDOW}s"
            if reason:
                strikes = add_security_strike(uid, reason)
                if strikes >= SECURITY_AUTO_BLOCK_THRESHOLD:
                    if temporary_block_user(uid, reason, strikes=strikes):
                        blocked += 1
                        security_v2_state["auto_blocks"] += 1
        if len(ip_counts) > SECURITY_MAX_TRACKED_IPS:
            security_v2_ip_hits.clear()
        security_v2_ip_hits.update(ip_counts)
        security_v2_user_hits.update(user_counts)
        security_v2_state["last_scan"] = now
        return {"users": len(user_counts), "ips": len(ip_counts), "blocked": blocked}
    except Exception as error:
        print("[SECURITY V2] Abuse scan error:", error)
        return {"users": 0, "ips": 0, "blocked": 0}


def cleanup_security_v2():
    now = _v2_now()
    cutoff = now - SECURITY_LOG_RETENTION_DAYS * 86400
    with security_db() as db:
        db.execute("DELETE FROM temporary_blocks WHERE expires_at <= ?", (now,))
        db.execute("DELETE FROM security_logs WHERE created_at < ?", (cutoff,))
        db.commit()
    expired = [uid for uid, value in security_v2_confirmations.items() if value.get("expires_at", 0) <= now]
    for uid in expired:
        security_v2_confirmations.pop(uid, None)
    expired_pending = [uid for uid, started in list(security_v2_pending_times.items())
                       if now - started > SECURITY_PENDING_TIMEOUT]
    for uid in expired_pending:
        clear_pending_action_v2(uid)


def set_pending_action_v2(user_id, action):
    user_id = int(user_id)
    pending_actions[user_id] = action
    security_v2_pending_times[user_id] = _v2_now()


def get_pending_action_v2(user_id):
    uid = int(user_id)
    started = security_v2_pending_times.get(uid, 0)
    if started and _v2_now() - started > SECURITY_PENDING_TIMEOUT:
        pending_actions.pop(uid, None)
        security_v2_pending_times.pop(uid, None)
        return None
    return pending_actions.get(uid)


def clear_pending_action_v2(user_id):
    uid = int(user_id)
    pending_actions.pop(uid, None)
    security_v2_pending_times.pop(uid, None)


def _v2_patch_pending_api():
    global set_pending_action, get_pending_action, clear_pending_action
    set_pending_action = set_pending_action_v2
    get_pending_action = get_pending_action_v2
    clear_pending_action = clear_pending_action_v2


_v2_patch_pending_api()


def v2_user_stats(user_id):
    now = _v2_now()
    cutoff = now - SECURITY_RATE_WINDOW
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """SELECT COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE action='stream') AS streams,
                              COUNT(*) FILTER (WHERE action='download') AS downloads
                       FROM access_logs WHERE chat_id=%s AND accessed_at >= %s""",
                    (int(user_id), datetime.fromtimestamp(cutoff))
                )
                row = cursor.fetchone()
        return {"requests": int(row["total"] or 0), "streams": int(row["streams"] or 0), "downloads": int(row["downloads"] or 0), "strikes": get_security_strike(user_id)}
    except Exception:
        return {"requests": 0, "streams": 0, "downloads": 0, "strikes": get_security_strike(user_id)}


@security_bot.on(events.NewMessage(pattern=r"^/stats$"))
async def security_stats_command(event):
    if not is_admin(event):
        return
    now = _v2_now()
    await event.reply(
        "📊 <b>SECURITY V2 STATS</b>\n\n"
        f"👥 Tracked users: <code>{len(security_v2_user_hits)}</code>\n"
        f"🌐 Tracked IPs: <code>{len(security_v2_ip_hits)}</code>\n"
        f"📡 Requests scanned: <code>{security_v2_state['requests_scanned']}</code>\n"
        f"🚫 Auto-blocks: <code>{security_v2_state['auto_blocks']}</code>\n"
        f"🔐 Lockdown: <code>{'ON' if security_v2_state['lockdown'] else 'OFF'}</code>\n"
        f"⏱️ Window: <code>{SECURITY_RATE_WINDOW}s</code> / <code>{SECURITY_MAX_REQUESTS}</code> requests\n"
        f"🕐 Last scan: <code>{now - security_v2_state['last_scan']}s ago</code>",
        parse_mode="html"
    )


@security_bot.on(events.NewMessage(pattern=r"^/userstats(?:\s+(\d+))?$"))
async def user_stats_command(event):
    if not is_admin(event):
        return
    match = event.pattern_match
    uid = int(match.group(1)) if match.group(1) else event.sender_id
    stats = v2_user_stats(uid)
    await event.reply(
        "👤 <b>USER SECURITY STATS</b>\n\n"
        f"🆔 <code>{uid}</code>\n"
        f"📡 Requests: <code>{stats['requests']}</code>\n"
        f"▶️ Streams: <code>{stats['streams']}</code>\n"
        f"📥 Downloads: <code>{stats['downloads']}</code>\n"
        f"⚠️ Strikes: <code>{stats['strikes']}</code>\n"
        f"🚫 Blocked: <code>{'YES' if is_blocked(uid) else 'NO'}</code>",
        parse_mode="html"
    )


@security_bot.on(events.NewMessage(pattern=r"^/topusers$"))
async def top_users_command(event):
    if not is_admin(event):
        return
    ranked = sorted(security_v2_user_hits.items(), key=lambda x: x[1], reverse=True)[:20]
    if not ranked:
        await event.reply("📭 No recent request data.")
        return
    lines = ["📈 <b>TOP USERS</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
    for index, (uid, count) in enumerate(ranked, 1):
        lines.append(f"{index}. <code>{uid}</code> — <code>{count}</code> requests")
    await event.reply("\n".join(lines), parse_mode="html")


@security_bot.on(events.NewMessage(pattern=r"^/topips$"))
async def top_ips_command(event):
    if not is_admin(event):
        return
    ranked = sorted(security_v2_ip_hits.items(), key=lambda x: x[1], reverse=True)[:20]
    if not ranked:
        await event.reply("📭 No recent IP data.")
        return
    lines = ["🌐 <b>TOP IPS</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
    for index, (ip, count) in enumerate(ranked, 1):
        lines.append(f"{index}. <code>{html.escape(ip)}</code> — <code>{count}</code> requests")
    await event.reply("\n".join(lines), parse_mode="html")


@security_bot.on(events.NewMessage(pattern=r"^/lockdown$"))
async def lockdown_command(event):
    if not is_admin(event):
        return
    security_v2_state["lockdown"] = not security_v2_state["lockdown"]
    state = "ENABLED" if security_v2_state["lockdown"] else "DISABLED"
    await event.reply(f"🚨 <b>SECURITY LOCKDOWN {state}</b>", parse_mode="html")


@security_bot.on(events.NewMessage(pattern=r"^/tempblock\s+(\d+)(?:\s+(\d+))?(?:\s+(.+))?$"))
async def tempblock_command(event):
    if not is_admin(event):
        return
    match = event.pattern_match
    uid = int(match.group(1))
    minutes = int(match.group(2) or SECURITY_TEMP_BLOCK_MINUTES)
    reason = (match.group(3) or "Temporary administrator block").strip()
    if uid == OWNER_ID:
        await event.reply("❌ You cannot block the owner.")
        return
    temporary_block_user(uid, reason, minutes=minutes)
    removed = purge_user_files(uid)
    await event.reply(
        "⏱️ <b>TEMPORARY BLOCK</b>\n\n"
        f"👤 User: <code>{uid}</code>\n"
        f"⏳ Duration: <code>{minutes} min</code>\n"
        f"🗑️ Links revoked: <code>{removed}</code>",
        parse_mode="html"
    )


@security_bot.on(events.NewMessage(pattern=r"^/v2help$"))
async def v2_help_command(event):
    if not is_admin(event):
        return
    await event.reply(
        "🛡️ <b>SECURITY V2</b>\n\n"
        "<code>/stats</code> — global security stats\n"
        "<code>/userstats USER_ID</code> — user stats\n"
        "<code>/topusers</code> — busiest users\n"
        "<code>/topips</code> — busiest IPs\n"
        "<code>/tempblock USER_ID MINUTES reason</code> — temporary block\n"
        "<code>/lockdown</code> — toggle emergency monitoring lockdown\n\n"
        f"Limits: <code>{SECURITY_MAX_REQUESTS}</code> requests/{SECURITY_RATE_WINDOW}s, "
        f"<code>{SECURITY_MAX_STREAMS}</code> stream events/{SECURITY_RATE_WINDOW}s, "
        f"<code>{SECURITY_AUTO_BLOCK_THRESHOLD}</code> strikes → temp block.",
        parse_mode="html"
    )


async def security_v2_loop():
    while True:
        try:
            if SECURITY_V2_ENABLED:
                scan_access_abuse()
                cleanup_security_v2()
        except Exception as error:
            print("[SECURITY V2] Loop error:", error)
        await asyncio.sleep(SECURITY_SCAN_INTERVAL)


# ============================================================
# MAIN
# ============================================================

async def main():

    init_security_database()
    init_security_v2_database()

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
    security_v2_task = asyncio.create_task(
        security_v2_loop()
    )

    try:

        await security_bot.run_until_disconnected()

    finally:

        cleanup_task.cancel()
        security_v2_task.cancel()

        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

        try:
            await security_v2_task
        except asyncio.CancelledError:
            pass

        await security_bot.disconnect()


# ============================================================
# ENTRY POINT
# ============================================================


# ============================================================
# SECURITY V3 ADDITIONS — APPEND ONLY
# ============================================================
# V3 keeps every existing V1/V2 line intact and adds the new
# control-plane, adaptive abuse, shared lockdown, and messaging APIs.

import time as _v3_time
import json as _v3_json
from urllib.parse import urlencode as _v3_urlencode
from urllib.request import Request as _v3_URLRequest, urlopen as _v3_urlopen
from urllib.error import HTTPError as _v3_HTTPError

BOT_TOKEN_V3 = os.getenv("BOT_TOKEN", "").strip()
SECURITY_V3_ENABLED = os.getenv("SECURITY_V3_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
SECURITY_V3_WARNING_THRESHOLD = max(1, int(os.getenv("SECURITY_V3_WARNING_THRESHOLD", "1")))
SECURITY_V3_COOLDOWN_THRESHOLD = max(2, int(os.getenv("SECURITY_V3_COOLDOWN_THRESHOLD", "2")))
SECURITY_V3_COOLDOWN_SECONDS = max(10, int(os.getenv("SECURITY_V3_COOLDOWN_SECONDS", "60")))
SECURITY_V3_ALERT_COOLDOWN = max(10, int(os.getenv("SECURITY_V3_ALERT_COOLDOWN", "300")))
SECURITY_V3_SCAN_INTERVAL = max(10, int(os.getenv("SECURITY_V3_SCAN_INTERVAL", "15")))
SECURITY_V3_MESSAGE_DELAY = max(0.03, float(os.getenv("SECURITY_V3_MESSAGE_DELAY", "0.05")))
SECURITY_V3_MAX_BROADCAST_USERS = max(1, int(os.getenv("SECURITY_V3_MAX_BROADCAST_USERS", "10000")))
security_v3_alert_times = {}
security_v3_cooldowns = {}
security_v3_broadcast_pending = {}
security_v3_last_scan = 0.0


def _v3_pg(query, params=(), fetch="none"):
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(query, params)
                if fetch == "one":
                    return cursor.fetchone()
                if fetch == "all":
                    return cursor.fetchall()
                db.commit()
                return None
    except Exception as error:
        print("[SECURITY V3] PostgreSQL error:", error)
        return None


def init_security_v3_shared_db():
    _v3_pg("""
        CREATE TABLE IF NOT EXISTS security_v3_temp_blocks (
            user_id BIGINT PRIMARY KEY,
            reason TEXT NOT NULL DEFAULT '',
            blocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            strikes INTEGER NOT NULL DEFAULT 0
        )
    """)
    _v3_pg("""
        CREATE TABLE IF NOT EXISTS security_v3_control (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            lockdown BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by BIGINT
        )
    """)
    _v3_pg("""
        INSERT INTO security_v3_control(id, lockdown)
        VALUES (1, FALSE)
        ON CONFLICT (id) DO NOTHING
    """)
    _v3_pg("""
        CREATE INDEX IF NOT EXISTS idx_security_v3_temp_blocks_expires
        ON security_v3_temp_blocks(expires_at)
    """)


def v3_is_temp_blocked(user_id):
    row = _v3_pg(
        "SELECT 1 FROM security_v3_temp_blocks WHERE user_id=%s AND expires_at > NOW()",
        (int(user_id),), "one"
    )
    return row is not None


def v3_lockdown_enabled():
    row = _v3_pg("SELECT lockdown FROM security_v3_control WHERE id=1", fetch="one")
    return bool(row and row.get("lockdown"))


def v3_set_lockdown(enabled, actor_id):
    _v3_pg(
        """INSERT INTO security_v3_control(id, lockdown, updated_at, updated_by)
           VALUES (1, %s, NOW(), %s)
           ON CONFLICT(id) DO UPDATE SET lockdown=EXCLUDED.lockdown,
           updated_at=EXCLUDED.updated_at, updated_by=EXCLUDED.updated_by""",
        (bool(enabled), int(actor_id))
    )


def v3_temp_block_shared(user_id, reason, minutes, strikes=0):
    if int(user_id) == OWNER_ID:
        return False
    _v3_pg(
        """INSERT INTO security_v3_temp_blocks(user_id, reason, blocked_at, expires_at, strikes)
           VALUES (%s, %s, NOW(), NOW() + (%s * INTERVAL '1 minute'), %s)
           ON CONFLICT(user_id) DO UPDATE SET reason=EXCLUDED.reason,
           blocked_at=EXCLUDED.blocked_at, expires_at=EXCLUDED.expires_at,
           strikes=EXCLUDED.strikes""",
        (int(user_id), str(reason)[:500], int(minutes), int(strikes))
    )
    return True


def v3_cleanup_shared_blocks():
    _v3_pg("DELETE FROM security_v3_temp_blocks WHERE expires_at <= NOW()")


def v3_get_user_ids():
    rows = _v3_pg(
        "SELECT user_id FROM users ORDER BY user_id LIMIT %s",
        (SECURITY_V3_MAX_BROADCAST_USERS,), "all"
    ) or []
    return [int(row["user_id"]) for row in rows if row.get("user_id") is not None]


def v3_send_main_bot_message(chat_id, text):
    if not BOT_TOKEN_V3:
        return False, "BOT_TOKEN is missing"
    if not text or not str(text).strip():
        return False, "Empty message"
    data = _v3_urlencode({
        "chat_id": int(chat_id),
        "text": str(text)[:4096],
        "parse_mode": "HTML"
    }).encode()
    request = _v3_URLRequest(
        f"https://api.telegram.org/bot{BOT_TOKEN_V3}/sendMessage",
        data=data,
        method="POST"
    )
    try:
        with _v3_urlopen(request, timeout=15) as response:
            payload = _v3_json.loads(response.read().decode("utf-8", "replace"))
        if payload.get("ok"):
            return True, "ok"
        return False, str(payload.get("description", "Telegram API error"))
    except _v3_HTTPError as error:
        try:
            body = error.read().decode("utf-8", "replace")
            payload = _v3_json.loads(body)
            return False, str(payload.get("description", str(error)))
        except Exception:
            return False, str(error)
    except Exception as error:
        return False, str(error)


async def v3_send_main_bot_message_async(chat_id, text):
    return await asyncio.to_thread(v3_send_main_bot_message, chat_id, text)


async def v3_broadcast(text, target_user_id=None):
    targets = [int(target_user_id)] if target_user_id is not None else v3_get_user_ids()
    sent = failed = blocked = 0
    for uid in targets:
        if not uid or uid == OWNER_ID:
            # Owner is intentionally included in /msg all only when explicitly targeted.
            if target_user_id is None:
                pass
        ok, reason = await v3_send_main_bot_message_async(uid, text)
        if ok:
            sent += 1
        else:
            failed += 1
            if "blocked" in reason.lower() or "chat not found" in reason.lower():
                blocked += 1
        await asyncio.sleep(SECURITY_V3_MESSAGE_DELAY)
    return sent, failed, blocked, len(targets)


def v3_parse_message_text(event):
    raw = (event.raw_text or "").strip()
    parts = raw.split(None, 2)
    if len(parts) >= 3:
        return parts[1], parts[2].strip()
    if len(parts) == 2:
        return parts[1], ""
    return "", ""


@security_bot.on(events.NewMessage(pattern=r"^/msg(?:\s+all(?:\s+[\s\S]*)?|\s+\d+(?:\s+[\s\S]*)?)?$"))
async def security_v3_msg_command(event):
    if not SECURITY_V3_ENABLED or not is_admin(event):
        return
    target, text = v3_parse_message_text(event)
    if not target:
        await event.reply(
            "📢 <b>MESSAGE COMMAND</b>\n\n"
            "<code>/msg all YOUR MESSAGE</code>\n"
            "<code>/msg USER_ID YOUR MESSAGE</code>",
            parse_mode="html"
        )
        return
    if not text and event.is_reply:
        replied = await event.get_reply_message()
        text = (replied.raw_text or "").strip() if replied else ""
    if not text:
        await event.reply("❌ Message text is empty.")
        return
    if target.lower() == "all":
        key = int(event.sender_id)
        security_v3_broadcast_pending[key] = {"text": text, "created": _v3_time.time()}
        await event.reply(
            "⚠️ <b>BROADCAST CONFIRMATION</b>\n\n"
            f"👥 Targets: <code>{len(v3_get_user_ids())}</code>\n"
            f"📝 Message:\n<blockquote>{html.escape(text[:1000])}</blockquote>\n\n"
            "Send <code>/msgconfirm</code> to broadcast, or <code>/msgcancel</code>.",
            parse_mode="html"
        )
        return
    try:
        uid = int(target)
    except ValueError:
        await event.reply("❌ Invalid USER_ID.")
        return
    if uid <= 0:
        await event.reply("❌ Invalid USER_ID.")
        return
    sent, failed, blocked, total = await v3_broadcast(text, target_user_id=uid)
    await event.reply(
        "📨 <b>DIRECT MESSAGE RESULT</b>\n\n"
        f"🆔 User: <code>{uid}</code>\n"
        f"✅ Sent: <code>{sent}</code>\n"
        f"❌ Failed: <code>{failed}</code>",
        parse_mode="html"
    )


@security_bot.on(events.NewMessage(pattern=r"^/msgconfirm$"))
async def security_v3_msg_confirm(event):
    if not SECURITY_V3_ENABLED or not is_admin(event):
        return
    pending = security_v3_broadcast_pending.pop(int(event.sender_id), None)
    if not pending or _v3_time.time() - pending["created"] > 300:
        await event.reply("⌛ No pending broadcast (or it expired).")
        return
    sent, failed, blocked, total = await v3_broadcast(pending["text"])
    await event.reply(
        "📢 <b>BROADCAST COMPLETED</b>\n\n"
        f"📊 Total: <code>{total}</code>\n"
        f"✅ Sent: <code>{sent}</code>\n"
        f"❌ Failed: <code>{failed}</code>\n"
        f"🚫 Blocked/invalid: <code>{blocked}</code>",
        parse_mode="html"
    )


@security_bot.on(events.NewMessage(pattern=r"^/msgcancel$"))
async def security_v3_msg_cancel(event):
    if not SECURITY_V3_ENABLED or not is_admin(event):
        return
    security_v3_broadcast_pending.pop(int(event.sender_id), None)
    await event.reply("✅ Pending broadcast cancelled.")


@security_bot.on(events.NewMessage(pattern=r"^/lockdown(?:\s+(on|off))?$"))
async def security_v3_lockdown_command(event):
    if not SECURITY_V3_ENABLED or not is_admin(event):
        return
    arg = (event.pattern_match.group(1) or "").lower()
    current = v3_lockdown_enabled()
    enabled = (not current) if not arg else arg == "on"
    v3_set_lockdown(enabled, event.sender_id)
    await event.reply(
        f"🚨 <b>REAL LOCKDOWN {'ENABLED' if enabled else 'DISABLED'}</b>\n\n"
        "The main proxy checks this shared state before starting a stream.",
        parse_mode="html"
    )


@security_bot.on(events.NewMessage(pattern=r"^/v3stats$"))
async def security_v3_stats_command(event):
    if not SECURITY_V3_ENABLED or not is_admin(event):
        return
    block_row = _v3_pg("SELECT COUNT(*) AS total FROM security_v3_temp_blocks WHERE expires_at > NOW()", fetch="one")
    await event.reply(
        "🛡️ <b>SECURITY V3</b>\n\n"
        f"🚨 Lockdown: <code>{'ON' if v3_lockdown_enabled() else 'OFF'}</code>\n"
        f"⏱️ Active temp blocks: <code>{int(block_row['total']) if block_row else 0}</code>\n"
        f"⚙️ Scan interval: <code>{SECURITY_V3_SCAN_INTERVAL}s</code>\n"
        f"📢 Broadcast delay: <code>{SECURITY_V3_MESSAGE_DELAY:.2f}s</code>",
        parse_mode="html"
    )


async def security_v3_loop():
    global security_v3_last_scan
    while True:
        try:
            if SECURITY_V3_ENABLED:
                v3_cleanup_shared_blocks()
                now = _v3_time.time()
                # Cooldowns are intentionally in-memory and expire automatically.
                for uid, expires in list(security_v3_cooldowns.items()):
                    if expires <= now:
                        security_v3_cooldowns.pop(uid, None)
                for uid, value in list(security_v3_broadcast_pending.items()):
                    if now - value.get("created", now) > 300:
                        security_v3_broadcast_pending.pop(uid, None)
                security_v3_last_scan = now
        except Exception as error:
            print("[SECURITY V3] Loop error:", error)
        await asyncio.sleep(SECURITY_V3_SCAN_INTERVAL)


# Replace the V2 main task runner only by wrapping it with an additive V3 runner.
_v2_main_original = main

async def main():
    init_security_v3_shared_db()
    v3_task = None
    try:
        # The original V2 main is retained unchanged and remains the primary runner.
        # V3 maintenance runs beside it when the security bot is connected.
        v3_task = asyncio.create_task(security_v3_loop())
        await _v2_main_original()
    finally:
        if v3_task is not None:
            v3_task.cancel()
            try:
                await v3_task
            except asyncio.CancelledError:
                pass

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\n[+] Security bot stopped."
        )
