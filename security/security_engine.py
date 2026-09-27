import asyncio
import os
from datetime import datetime

from security.config import (
    OWNER_ID,
)
from security.database import security_db, is_blocked
from security.proxy_database import files_pg_db
from security.state import (
    pending_actions,
    security_v2_state,
    security_v2_confirmations,
    security_v2_ip_hits,
    security_v2_user_hits,
    security_v2_pending_times,
    clear_pending_action,
)

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
        clear_pending_action(uid)



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


