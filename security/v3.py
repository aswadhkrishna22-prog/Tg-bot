import asyncio
import html
import os
import json as _v3_json
from security.ai_repair import capture_error
import time as _v3_time
from urllib.parse import urlencode as _v3_urlencode
from urllib.request import Request as _v3_URLRequest, urlopen as _v3_urlopen
from urllib.error import HTTPError as _v3_HTTPError

from telethon import events

from security.config import OWNER_ID
from security.auth import is_admin
from security.proxy_database import files_pg_db

security_bot = None

def setup(client):
    global security_bot
    security_bot = client
    _register_v3_handlers(client)
    return client


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


async def security_v3_msg_cancel(event):
    if not SECURITY_V3_ENABLED or not is_admin(event):
        return
    security_v3_broadcast_pending.pop(int(event.sender_id), None)
    await event.reply("✅ Pending broadcast cancelled.")


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




def _register_v3_handlers(client):
    client.add_event_handler(security_v3_msg_command, events.NewMessage(pattern=r"^/msg(?:\s+all(?:\s+[\s\S]*)?|\s+\d+(?:\s+[\s\S]*)?)?$"))
    client.add_event_handler(security_v3_msg_confirm, events.NewMessage(pattern=r"^/msgconfirm$"))
    client.add_event_handler(security_v3_msg_cancel, events.NewMessage(pattern=r"^/msgcancel$"))
    client.add_event_handler(security_v3_lockdown_command, events.NewMessage(pattern=r"^/lockdown(?:\s+(on|off))?$"))
    client.add_event_handler(security_v3_stats_command, events.NewMessage(pattern=r"^/v3stats$"))
