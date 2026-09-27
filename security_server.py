import time
import threading

from database import db_connect
from fastapi.responses import JSONResponse

SECURITY_V3_SERVER_ENABLED = False
SECURITY_V3_SERVER_CACHE_TTL = 15
SECURITY_V3_SERVER_MAX_STREAMS_PER_USER = 2
_metric_callback = lambda name, amount=1: None

security_v3_server_state = {"lockdown": False, "lockdown_checked": 0.0}
security_v3_server_user_streams = {}
security_v3_server_lock = threading.Lock()


def configure(metric_callback, enabled, cache_ttl, max_streams_per_user):
    global _metric_callback, SECURITY_V3_SERVER_ENABLED
    global SECURITY_V3_SERVER_CACHE_TTL, SECURITY_V3_SERVER_MAX_STREAMS_PER_USER
    _metric_callback = metric_callback or (lambda name, amount=1: None)
    SECURITY_V3_SERVER_ENABLED = bool(enabled)
    SECURITY_V3_SERVER_CACHE_TTL = float(cache_ttl)
    SECURITY_V3_SERVER_MAX_STREAMS_PER_USER = int(max_streams_per_user)


def metric_inc(name, amount=1):
    _metric_callback(name, amount)


def security_v3_server_control_state():
    now = time.monotonic()
    if now - security_v3_server_state["lockdown_checked"] < SECURITY_V3_SERVER_CACHE_TTL:
        return security_v3_server_state["lockdown"]
    try:
        with db_connect() as db:
            with db.cursor() as cursor:
                cursor.execute("SELECT lockdown FROM security_v3_control WHERE id=1")
                row = cursor.fetchone()
        value = bool(row and row.get("lockdown"))
        security_v3_server_state["lockdown"] = value
        security_v3_server_state["lockdown_checked"] = now
        return value
    except Exception as error:
        print("[SECURITY V3] Control-state check failed:", error)
        return False


def security_v3_server_temp_blocked(user_id):
    try:
        with db_connect() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM security_v3_temp_blocks WHERE user_id=%s AND expires_at > NOW()",
                    (int(user_id),)
                )
                return cursor.fetchone() is not None
    except Exception as error:
        print("[SECURITY V3] Temp-block check failed:", error)
        return False


def security_v3_server_log_access(chat_id, ip, action, token=None, status_code=200):
    try:
        with db_connect() as db:
            with db.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS access_logs (
                        id BIGSERIAL PRIMARY KEY,
                        chat_id BIGINT,
                        ip TEXT,
                        action TEXT,
                        token TEXT,
                        status_code INTEGER,
                        accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cursor.execute("""
                    INSERT INTO access_logs(chat_id, ip, action, token, status_code, accessed_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (int(chat_id) if chat_id is not None else 0, str(ip or "unknown"), str(action), token, int(status_code)))
            db.commit()
    except Exception as error:
        print("[SECURITY V3] access log failed:", error)


def security_v3_server_user_id_from_token(token):
    try:
        with db_connect() as db:
            with db.cursor() as cursor:
                cursor.execute("SELECT chat_id FROM files WHERE token=%s", (token,))
                row = cursor.fetchone()
        return int(row["chat_id"]) if row and row.get("chat_id") is not None else 0
    except Exception:
        return 0


async def security_v3_server_middleware(request, call_next):
    if not SECURITY_V3_SERVER_ENABLED:
        return await call_next(request)
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"
    token = None
    action = "request"
    parts = path.strip("/").split("/")
    if parts and parts[0] and parts[0] not in {"health", "metrics", "share", "receive", "pair", "adolf-streamx-404.png"}:
        token = parts[0]
    user_id = security_v3_server_user_id_from_token(token) if token else 0
    if user_id and security_v3_server_temp_blocked(user_id):
        metric_inc("rate_limited")
        security_v3_server_log_access(user_id, client_ip, "blocked", token, 403)
        return JSONResponse({"ok": False, "error": "Access temporarily blocked"}, status_code=403)
    if path.startswith("/share/") or (token and path.count("/") >= 2):
        action = "stream"
        if security_v3_server_control_state():
            security_v3_server_log_access(user_id, client_ip, "lockdown", token, 503)
            return JSONResponse({"ok": False, "error": "Proxy is temporarily in security lockdown"}, status_code=503)
        if user_id:
            with security_v3_server_lock:
                active = security_v3_server_user_streams.get(user_id, 0)
                if active >= SECURITY_V3_SERVER_MAX_STREAMS_PER_USER:
                    security_v3_server_log_access(user_id, client_ip, "stream", token, 429)
                    return JSONResponse({"ok": False, "error": "Too many active streams", "retry_after": 15}, status_code=429)
                security_v3_server_user_streams[user_id] = active + 1
    try:
        response = await call_next(request)
        if user_id:
            security_v3_server_log_access(user_id, client_ip, action, token, response.status_code)
        return response
    finally:
        if user_id and action == "stream":
            with security_v3_server_lock:
                current = security_v3_server_user_streams.get(user_id, 1) - 1
                if current > 0:
                    security_v3_server_user_streams[user_id] = current
                else:
                    security_v3_server_user_streams.pop(user_id, None)
