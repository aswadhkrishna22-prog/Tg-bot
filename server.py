import asyncio
import html
import mimetypes
import os
import re
import psycopg2
import uuid
import secrets
import time
import shutil
import threading
import psutil
import qrcode
from psycopg2.extras import RealDictCursor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request as URLRequest, urlopen
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from telethon import TelegramClient, events, Button, errors
import uvicorn

# ============================================================
# CONFIG
# ============================================================

load_dotenv()

try:
    API_ID = int(os.getenv("TG_API_ID", "0"))
except ValueError:
    raise RuntimeError("TG_API_ID must be a number")

API_HASH = os.getenv("TG_API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SECURITY_BOT_TOKEN = os.getenv("SECURITY_BOT_TOKEN", "").strip()

# Deployment mode:
# true  = RamnayCloud: Telegram bot + web/streaming
# false = Render: web/streaming only, Telegram updates disabled
BOT_MODE = os.getenv("BOT_MODE", "false").strip().lower() in (
    "1", "true", "yes", "on"
)

try:
    SECURITY_OWNER_ID = int(os.getenv("SECURITY_OWNER_ID", "0"))
except ValueError:
    raise RuntimeError("SECURITY_OWNER_ID must be a number")

PUBLIC_URL = os.getenv(
    "PUBLIC_URL",
    "http://127.0.0.1:8000"
).strip().rstrip("/")

HOST = "0.0.0.0"
PORT = 8000
CHUNK_SIZE = 512 * 1024

# ============================================================
# SMART TEMPORARY RANGE CACHE
# ============================================================

CACHE_CHUNK_SIZE = 4 * 1024 * 1024       # 4 MB
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour
CACHE_MAX_SIZE = int(
    os.getenv("CACHE_MAX_SIZE", str(1024 * 1024 * 1024))
)  # 1 GB

CACHE_DIR = Path(
    os.getenv("CACHE_DIR", "/tmp/stady_proxy_cache")
)

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)

# Keep a safety margin so cache writes never consume the last free
# disk space. Per-token limits prevent one huge file from dominating
# the cache. Active chunks are protected from eviction while in use.
CACHE_PER_FILE_MAX_SIZE = int(
    os.getenv("CACHE_PER_FILE_MAX_SIZE", str(256 * 1024 * 1024))
)  # 256 MB per file

CACHE_MIN_FREE_SPACE = int(
    os.getenv("CACHE_MIN_FREE_SPACE", str(512 * 1024 * 1024))
)  # keep 512 MB free

CACHE_CLEANUP_INTERVAL = int(
    os.getenv("CACHE_CLEANUP_INTERVAL", "300")
)  # 5 minutes

cache_active_files = set()
cache_active_guard = threading.Lock()

# ============================================================
# STREAM CONCURRENCY PROTECTION
# ============================================================
# These limits protect the server from too many simultaneous
# viewers without changing the existing streaming behavior.
MAX_CONCURRENT_STREAMS = int(
    os.getenv("MAX_CONCURRENT_STREAMS", "20")
)

MAX_CONCURRENT_PER_FILE = int(
    os.getenv("MAX_CONCURRENT_PER_FILE", "5")
)

STREAM_ACQUIRE_TIMEOUT = int(
    os.getenv("STREAM_ACQUIRE_TIMEOUT", "15")
)

# ============================================================
# TELEGRAM API PROTECTION
# ============================================================
# Limit simultaneous Telegram media downloads and share FloodWait
# cooldown across all viewers. This prevents a burst of cache misses
# from creating a Telegram API request storm.
MAX_CONCURRENT_TELEGRAM_DOWNLOADS = int(
    os.getenv("MAX_CONCURRENT_TELEGRAM_DOWNLOADS", "3")
)
TELEGRAM_FLOODWAIT_CAP = int(
    os.getenv("TELEGRAM_FLOODWAIT_CAP", "60")
)

telegram_download_semaphore = asyncio.Semaphore(
    MAX_CONCURRENT_TELEGRAM_DOWNLOADS
)
telegram_cooldown_lock = asyncio.Lock()
telegram_cooldown_until = 0.0

global_stream_semaphore = asyncio.Semaphore(
    MAX_CONCURRENT_STREAMS
)

file_stream_semaphores = {}
file_stream_semaphores_guard = asyncio.Lock()


async def get_file_stream_semaphore(token):
    async with file_stream_semaphores_guard:
        semaphore = file_stream_semaphores.get(token)

        if semaphore is None:
            semaphore = asyncio.Semaphore(
                MAX_CONCURRENT_PER_FILE
            )
            file_stream_semaphores[token] = semaphore

        return semaphore


async def remove_file_stream_semaphore(token):
    async with file_stream_semaphores_guard:
        semaphore = file_stream_semaphores.get(token)

        if semaphore is not None:
            if semaphore._value == MAX_CONCURRENT_PER_FILE:
                file_stream_semaphores.pop(
                    token,
                    None
                )



cache_locks = {}
cache_locks_guard = asyncio.Lock()

# ============================================================
# FILE LIMITS / RATE LIMIT
# ============================================================

MAX_FILE_SIZE = 6 * 1024 * 1024 * 1024   # 6 GB

FILE_COOLDOWN = 10                        # 10 seconds

# Runtime safety / observability
STREAM_IDLE_TIMEOUT = float(os.getenv("STREAM_IDLE_TIMEOUT", "0"))  # 0 = disabled; browser streaming must not timeout mid-read
REQUEST_RATE_LIMIT = int(os.getenv("REQUEST_RATE_LIMIT", "300"))
REQUEST_RATE_WINDOW = int(os.getenv("REQUEST_RATE_WINDOW", "60"))
MAX_RATE_LIMIT_KEYS = int(os.getenv("MAX_RATE_LIMIT_KEYS", "10000"))
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
DB_KEEPALIVES_IDLE = int(os.getenv("DB_KEEPALIVES_IDLE", "30"))
DB_KEEPALIVES_INTERVAL = int(os.getenv("DB_KEEPALIVES_INTERVAL", "10"))
DB_KEEPALIVES_COUNT = int(os.getenv("DB_KEEPALIVES_COUNT", "3"))
request_rate_state = {}
request_rate_lock = threading.Lock()
server_metrics = {"requests": 0, "rate_limited": 0, "streams_started": 0, "streams_completed": 0, "streams_failed": 0, "stream_disconnects": 0, "telegram_retries": 0, "telegram_floodwaits": 0, "db_failures": 0}
metrics_lock = threading.Lock()

def metric_inc(name, amount=1):
    with metrics_lock:
        server_metrics[name] = server_metrics.get(name, 0) + amount

async def request_rate_middleware(request, call_next):
    path = request.url.path
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    if path not in ("/", "/health", "/metrics"):
        with request_rate_lock:
            state = request_rate_state.get(client)
            if state is None or now - state[0] >= REQUEST_RATE_WINDOW:
                request_rate_state[client] = [now, 1]
            else:
                state[1] += 1
                if state[1] > REQUEST_RATE_LIMIT:
                    metric_inc("rate_limited")
                    return JSONResponse({"ok": False, "error": "Too many requests", "retry_after": REQUEST_RATE_WINDOW}, status_code=429, headers={"Retry-After": str(REQUEST_RATE_WINDOW)})
            if len(request_rate_state) > MAX_RATE_LIMIT_KEYS:
                for key, _ in sorted(request_rate_state.items(), key=lambda item: item[1][0])[:max(1, len(request_rate_state)//10)]:
                    request_rate_state.pop(key, None)
    metric_inc("requests")
    return await call_next(request)

user_file_cooldowns = {}

BOT_USERNAME = ""

if API_ID <= 0:
    raise RuntimeError("TG_API_ID is missing or invalid")

if not API_HASH:
    raise RuntimeError("TG_API_HASH is missing")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing (required for Telegram streaming/authentication)"
    )

# ============================================================
# DATABASE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    ""
).strip()

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing"
    )


def db_connect():
    last_error = None
    for attempt in range(3):
        try:
            return psycopg2.connect(
                DATABASE_URL, sslmode="require", cursor_factory=RealDictCursor,
                connect_timeout=DB_CONNECT_TIMEOUT, keepalives=1,
                keepalives_idle=DB_KEEPALIVES_IDLE, keepalives_interval=DB_KEEPALIVES_INTERVAL,
                keepalives_count=DB_KEEPALIVES_COUNT
            )
        except Exception as error:
            last_error = error
            metric_inc("db_failures")
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
    raise last_error


def init_database():

    with db_connect() as db:

        with db.cursor() as cursor:

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    token TEXT PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    filename TEXT NOT NULL,
                    size BIGINT NOT NULL,
                    mime TEXT NOT NULL,
                    expires_at TIMESTAMPTZ
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT NOT NULL DEFAULT '',
                    last_name TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ
            """)

            cursor.execute("""
                UPDATE files
                SET expires_at = NOW() + INTERVAL '12 hours'
                WHERE expires_at IS NULL
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS bot_chat_id BIGINT
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS bot_message_id BIGINT
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS share_token TEXT
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_files_share_token
                ON files (share_token)
                WHERE share_token IS NOT NULL
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS pair_code TEXT
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_files_pair_code
                ON files (pair_code)
                WHERE pair_code IS NOT NULL
            """)

        db.commit()


def add_file(
    token,
    chat_id,
    message_id,
    filename,
    size,
    mime
):
    with db_connect() as db:

        with db.cursor() as cursor:

            cursor.execute("""
                INSERT INTO files
                (
                    token,
                    chat_id,
                    message_id,
                    filename,
                    size,
                    mime,
                    expires_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NOW() + INTERVAL '12 hours'
                )
            """, (
                token,
                chat_id,
                message_id,
                filename,
                size,
                mime
            ))

        db.commit()
        
def save_bot_message_id(
    token,
    bot_chat_id,
    bot_message_id
):
    with db_connect() as db:

        with db.cursor() as cursor:

            cursor.execute("""
                UPDATE files
                SET
                    bot_chat_id = %s,
                    bot_message_id = %s
                WHERE token = %s
            """, (
                int(bot_chat_id),
                int(bot_message_id),
                token
            ))

        db.commit()





def create_share_token(token):
    """Create a short token used only for device sharing."""
    for _ in range(10):
        share_token = uuid.uuid4().hex[:10]
        try:
            with db_connect() as db:
                with db.cursor() as cursor:
                    cursor.execute("""
                        UPDATE files
                        SET share_token = %s
                        WHERE token = %s
                    """, (share_token, token))
                db.commit()
            return share_token
        except psycopg2.errors.UniqueViolation:
            continue

    raise RuntimeError("Could not create a unique share token")


def get_file_by_share_token(share_token):
    with db_connect() as db:
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM files
                WHERE share_token = %s
                AND (
                    expires_at IS NULL
                    OR expires_at > NOW()
                )
            """, (share_token,))
            return cursor.fetchone()


def create_pair_code(token):
    """Create a unique 6-digit code used for TV pairing."""
    for _ in range(20):
        pair_code = f"{secrets.randbelow(1000000):06d}"

        try:
            with db_connect() as db:
                with db.cursor() as cursor:
                    cursor.execute("""
                        UPDATE files
                        SET pair_code = %s
                        WHERE token = %s
                    """, (pair_code, token))
                db.commit()

            return pair_code

        except psycopg2.errors.UniqueViolation:
            continue

    raise RuntimeError("Could not create a unique TV pairing code")


def get_file_by_pair_code(pair_code):
    with db_connect() as db:
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM files
                WHERE pair_code = %s
                AND (
                    expires_at IS NULL
                    OR expires_at > NOW()
                )
            """, (pair_code,))
            return cursor.fetchone()



# ============================================================
# FASTAPI / TELEGRAM
# ============================================================

app = FastAPI(title="STADY-PROXY")
app.middleware("http")(request_rate_middleware)

@app.get("/health")
async def health():
    telegram_ok = False
    try: telegram_ok = bool(bot.is_connected())
    except Exception: pass
    db_ok = False
    try:
        with db_connect() as db:
            with db.cursor() as cursor:
                cursor.execute("SELECT 1"); cursor.fetchone()
        db_ok = True
    except Exception: pass
    ok = telegram_ok and db_ok
    return JSONResponse({"ok": ok, "telegram": telegram_ok, "database": db_ok}, status_code=200 if ok else 503)


bot = TelegramClient(
    "proxybot",
    API_ID,
    API_HASH,
    receive_updates=BOT_MODE
)

BOT_START_TIME = time.time()
LAST_ERROR = "None"
# ============================================================
# CUSTOM STADY-PROXY ERROR PAGE
# ============================================================

ERROR_PAGE = BASE_DIR / "stady_proxy_404.html"
ERROR_IMAGE = BASE_DIR / "stady-proxy-404.png"


@app.get("/stady-proxy-404.png")
async def stady_proxy_404_image():
    return FileResponse(
        ERROR_IMAGE,
        media_type="image/png"
    )



def stady_error_page():
    try:
        return ERROR_PAGE.read_text(
            encoding="utf-8"
        )

    except Exception as error:
        print(
            "[!] Could not load custom 404 page:",
            error
        )

        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>STADY-PROXY — 404 ERROR</title>
        </head>
        <body style="
            background:#020812;
            color:#69f7ff;
            text-align:center;
            font-family:Arial;
            padding-top:100px;
        ">
            <h1>STADY-PROXY</h1>
            <h2>404 — FILE NOT AVAILABLE</h2>
            <a href="/" style="color:#ff24d7;">
                Return Home
            </a>
        </body>
        </html>
        """
def get_file(token):

    with db_connect() as db:

        with db.cursor() as cursor:

            cursor.execute("""
                SELECT *
                FROM files
                WHERE token = %s
                AND (
                    expires_at IS NULL
                    OR expires_at > NOW()
                )
            """, (
                token,
            ))

            return cursor.fetchone()

# ============================================================
# SERVER STATS
# ============================================================

def format_uptime(seconds):
    seconds = int(seconds)

    days = seconds // 86400
    seconds %= 86400

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60
    seconds %= 60

    return f"{days}d {hours}h {minutes}m {seconds}s"


def usage_bar(percent, total=10):
    filled = round(percent / 100 * total)
    filled = max(0, min(total, filled))

    return "●" * filled + "○" * (total - filled)


@bot.on(events.NewMessage(pattern=r"^/stats$"))
async def stats_command(event):

    if not BOT_MODE:
        return

    try:
        cpu = psutil.cpu_percent(interval=0.5)

        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        bot_uptime = format_uptime(
            time.time() - BOT_START_TIME
        )

        system_uptime = format_uptime(
            time.time() - psutil.boot_time()
        )

        db_status = "✅ ONLINE"

        try:
            with db_connect() as db:
                with db.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()

        except Exception as error:
            db_status = (
                f"❌ ERROR: "
                f"{html.escape(str(error))}"
            )

        try:
            telegram_status = (
                "✅ CONNECTED"
                if bot.is_connected()
                else "❌ DISCONNECTED"
            )

        except Exception:
            telegram_status = "❌ UNKNOWN"

        
        total_files = 0

        try:
            with db_connect() as db:
                with db.cursor() as cursor:

                    cursor.execute(
                        "SELECT COUNT(*) AS total FROM files"
                    )

                    result = cursor.fetchone()

                    total_files = int(
                        result["total"]
                        if result is not None
                        else 0
                    )

        except Exception:
            total_files = 0

        message = (
            "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
            "        ⚡ STADY-PROXY\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"

            "📊 <b>SERVER STATISTICS</b>\n\n"

            f"🤖 BOT STATUS: {telegram_status}\n"
            f"🌐 SERVER: ✅ ONLINE\n"
            f"🗄️ DATABASE: {db_status}\n\n"

            f"⏱️ BOT UPTIME: "
            f"<code>{bot_uptime}</code>\n"

            f"🖥️ SYS UPTIME: "
            f"<code>{system_uptime}</code>\n\n"

            f"⚙️ CPU: {usage_bar(cpu)} "
            f"<code>{cpu:.1f}%</code>\n\n"

            f"🧠 RAM: {usage_bar(ram.percent)} "
            f"<code>{ram.percent:.1f}%</code>\n"

            f"RAM In Use: "
            f"<code>{ram.used / 1024**3:.2f} GB</code>\n"

            f"RAM Total: "
            f"<code>{ram.total / 1024**3:.2f} GB</code>\n"

            f"RAM Free: "
            f"<code>{ram.available / 1024**3:.2f} GB</code>\n\n"

            f"💾 DISK: {usage_bar(disk.percent)} "
            f"<code>{disk.percent:.1f}%</code>\n"

            f"Drive In Use: "
            f"<code>{disk.used / 1024**3:.2f} GB</code>\n"

            f"Drive Total: "
            f"<code>{disk.total / 1024**3:.2f} GB</code>\n"

            f"Drive Free: "
            f"<code>{disk.free / 1024**3:.2f} GB</code>\n\n"

            f"📦 REGISTERED FILES: "
            f"<code>{total_files}</code>\n\n"

            "🛠️ LAST ERROR:\n"
            f"<code>{html.escape(str(LAST_ERROR))}</code>\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"
            'Made with ♥ by'
            '<a href="https://www.instagram.com/2aswadhh_._kr">'
            'aswadh_kr'
            '</a>'
        )

        await event.reply(
            message,
            parse_mode="html"
        )

    except Exception as error:

        print(
            "[!] Stats command error:",
            error
        )

        await event.reply(
            "❌ <b>STATS ERROR</b>\n\n"
            f"<code>{html.escape(str(error))}</code>",
            parse_mode="html"
        )


# ============================================================
# HELPERS
# ============================================================

def clean_filename(name):

    if not name:
        return "file"

    name = os.path.basename(name)

    name = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        name
    )

    return name[:180] or "file"


def get_mime(filename):

    # Telegram can occasionally store a generic/incorrect MIME type
    # (for example application/zip) for a real media file.  Prefer the
    # filename extension for common media containers so browsers receive
    # the correct Content-Type.
    ext = Path(filename or "").suffix.lower()
    media_mimes = {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".webm": "video/webm",
        ".ogv": "video/ogg",
        ".ogg": "audio/ogg",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".ts": "video/mp2t",
        ".m2ts": "video/mp2t",
        ".mts": "video/mp2t",
        ".flv": "video/x-flv",
        ".wmv": "video/x-ms-wmv",
    }
    if ext in media_mimes:
        return media_mimes[ext]

    mime, _ = mimetypes.guess_type(filename)

    return mime or "application/octet-stream"


def resolve_media_mime(filename, stored_mime=None):
    # For known media extensions, always use the canonical media MIME.
    # This prevents a stale Telegram/DB value such as application/zip from
    # breaking browser playback or the HTML5 media type detection.
    ext = Path(filename or "").suffix.lower()
    canonical = get_mime(filename)
    if ext in {
        ".mp4", ".m4v", ".webm", ".ogv", ".ogg", ".mkv",
        ".mov", ".avi", ".ts", ".m2ts", ".mts", ".flv", ".wmv"
    }:
        return canonical
    return (stored_mime or canonical or "application/octet-stream").lower()


def detect_media_profile(filename, mime=None):
    """Conservatively classify files for browser-vs-external playback.

    This is intentionally filename based: Render does not need FFmpeg just to
    inspect every Telegram file. Files explicitly marked as HEVC/H.265/10-bit
    or using MKV are treated as external-player media because browser support
    is inconsistent. MP4/M4V/WebM/Ogg files without those markers are offered
    to the browser. This does not transcode or modify the original file.
    """
    name = (filename or "").lower()
    ext = Path(name).suffix
    mime = (mime or get_mime(filename)).lower()

    codec_markers = (
        "hevc", "h.265", "h265", "x265", "10bit", "10-bit",
        "hdr10", "dolbyvision", "dvhe"
    )
    has_incompatible_marker = any(marker in name for marker in codec_markers)

    browser_containers = {".mp4", ".m4v", ".webm", ".ogv", ".ogg"}
    external_containers = {".mkv", ".avi", ".mov", ".ts", ".m2ts", ".mts", ".flv", ".wmv"}

    # MKV is handled by the client-side browser player below.  The container
    # itself is not handed to the native <video> element; Mediabunny reads the
    # Matroska stream over HTTP Range requests and decodes supported codecs via
    # WebCodecs.  Codec support is still device/browser dependent.
    if ext == ".mkv":
        return {
            "browser_ok": True,
            "reason": "MKV Browser Player (client-side demux/decode)",
            "label": "Browser MKV Player",
            "mime": mime,
            "extension": ext,
        }

    if has_incompatible_marker or ext in external_containers:
        return {
            "browser_ok": False,
            "reason": "HEVC/10-bit or another browser-inconsistent format detected",
            "label": "External Player Recommended",
            "mime": mime,
            "extension": ext or "unknown",
        }

    if ext in browser_containers and mime.startswith(("video/", "audio/")):
        return {
            "browser_ok": True,
            "reason": "Browser-friendly container detected; codec is not guaranteed by filename",
            "label": "Browser Playback",
            "mime": mime,
            "extension": ext or "unknown",
        }

    return {
        "browser_ok": False,
        "reason": "Unknown or browser-inconsistent media format",
        "label": "External Player Recommended",
        "mime": mime,
        "extension": ext or "unknown",
    }


def parse_range(range_header, file_size):

    if not range_header:
        return 0, file_size - 1

    if not range_header.startswith("bytes="):
        raise ValueError("Invalid range")

    value = range_header[6:]

    if "," in value:
        raise ValueError(
            "Multiple ranges not supported"
        )

    start_text, end_text = value.split("-", 1)

    if start_text:

        start = int(start_text)

        if start >= file_size:
            raise ValueError(
                "Range outside file"
            )

        if end_text:
            end = min(
                int(end_text),
                file_size - 1
            )
        else:
            end = file_size - 1

        if start > end:
            raise ValueError(
                "Invalid range"
            )

        return start, end

    end = int(end_text)

    if end <= 0:
        raise ValueError(
            "Invalid suffix range"
        )

    start = max(
        file_size - end,
        0
    )

    return start, file_size - 1


# ============================================================
# TELEGRAM STREAM
# ============================================================

async def wait_for_telegram_cooldown():
    """Wait for the shared FloodWait cooldown, if one is active."""
    while True:
        async with telegram_cooldown_lock:
            remaining = telegram_cooldown_until - time.monotonic()

        if remaining <= 0:
            return

        await asyncio.sleep(min(remaining, 2.0))


async def set_telegram_cooldown(seconds):
    """Extend the shared Telegram cooldown without shortening an existing one."""
    global telegram_cooldown_until

    seconds = max(0.0, min(float(seconds), float(TELEGRAM_FLOODWAIT_CAP)))

    async with telegram_cooldown_lock:
        telegram_cooldown_until = max(
            telegram_cooldown_until,
            time.monotonic() + seconds
        )


async def telegram_stream(
    message,
    offset,
    length
):
    """Stream a Telegram byte range with bounded reconnect/retry support.

    If Telegram fails after some bytes were delivered, the next attempt
    resumes exactly at the undelivered byte instead of restarting the range.
    """
    sent = 0
    retries = 0

    max_retries = max(
        0,
        int(os.getenv("TELEGRAM_STREAM_MAX_RETRIES", "3"))
    )
    base_delay = max(
        0.25,
        float(os.getenv("TELEGRAM_STREAM_RETRY_DELAY", "0.5"))
    )
    max_delay = max(
        base_delay,
        float(os.getenv("TELEGRAM_STREAM_MAX_RETRY_DELAY", "8"))
    )

    while sent < length:
        current_offset = offset + sent
        remaining = length - sent

        try:
            # All Telegram media downloads pass through the same small gate.
            # This is deliberately separate from the viewer semaphore.
            await wait_for_telegram_cooldown()

            async with telegram_download_semaphore:
                await wait_for_telegram_cooldown()

                iterator = bot.iter_download(
                    message.media, offset=current_offset, limit=remaining, request_size=CHUNK_SIZE
                ).__aiter__()
                while True:
                    try:
                        if STREAM_IDLE_TIMEOUT > 0:
                            chunk = await asyncio.wait_for(
                                iterator.__anext__(),
                                timeout=STREAM_IDLE_TIMEOUT
                            )
                        else:
                            chunk = await iterator.__anext__()
                    except StopAsyncIteration:
                        break
                    if not chunk:
                        continue
                    remaining_now = length - sent
                    if len(chunk) > remaining_now:
                        chunk = chunk[:remaining_now]
                    sent += len(chunk)
                    yield chunk
                    if sent >= length:
                        return

            # Telegram ended the iterator before the requested range was
            # completely delivered. Treat that as a recoverable failure.
            if sent < length:
                raise IOError(
                    f"Telegram stream ended early: {sent}/{length} bytes"
                )

            return

        except asyncio.CancelledError:
            raise

        except Exception as error:
            if retries >= max_retries:
                print(
                    f"[!] Telegram stream failed after {retries} retries: {error}"
                )
                raise

            retries += 1

            # Telethon exposes FloodWaitError.seconds. Respect it, but cap
            # the delay so a browser/TV connection is not held forever.
            flood_wait = getattr(error, "seconds", None)
            if isinstance(error, errors.FloodWaitError) and flood_wait is not None:
                metric_inc("telegram_floodwaits")
                delay = min(
                    float(flood_wait),
                    float(TELEGRAM_FLOODWAIT_CAP)
                )
                await set_telegram_cooldown(delay)
            else:
                delay = min(
                    base_delay * (2 ** (retries - 1)),
                    max_delay
                )

            print(
                f"[!] Telegram stream interrupted at {sent}/{length} bytes; "
                f"retry {retries}/{max_retries} in {delay:.1f}s: {error}"
            )

            await asyncio.sleep(delay)


# ============================================================
# SMART TEMPORARY RANGE CACHE HELPERS
# ============================================================

def cache_path(token, chunk_index):
    token_dir = CACHE_DIR / token
    token_dir.mkdir(
        parents=True,
        exist_ok=True
    )
    return token_dir / f"{chunk_index}.cache"


async def get_cache_lock(cache_key):
    async with cache_locks_guard:
        lock = cache_locks.get(cache_key)

        if lock is None:
            lock = asyncio.Lock()
            cache_locks[cache_key] = lock

        return lock


def _cache_file_is_active(path):
    try:
        with cache_active_guard:
            return str(path) in cache_active_files
    except Exception:
        return False


def _mark_cache_active(path):
    with cache_active_guard:
        cache_active_files.add(str(path))


def _unmark_cache_active(path):
    with cache_active_guard:
        cache_active_files.discard(str(path))


def remove_cache_token(token):
    token_dir = CACHE_DIR / token

    if not token_dir.exists():
        return

    # Never delete a token directory while one of its chunks is being
    # read or written. The next cleanup pass will remove it safely.
    try:
        with cache_active_guard:
            active = any(
                item == str(token_dir)
                or item.startswith(str(token_dir) + os.sep)
                for item in cache_active_files
            )
        if active:
            print("[CACHE] Token cache is active; delaying removal:", token)
            return

        shutil.rmtree(token_dir, ignore_errors=True)
    except Exception as error:
        print("[CACHE] Token cache cleanup failed:", error)


def _cache_usage_snapshot():
    now = time.time()
    total_size = 0
    cache_files = []

    try:
        for path in CACHE_DIR.rglob("*.cache"):
            try:
                stat = path.stat()
            except OSError:
                continue

            age = now - stat.st_mtime
            if age > CACHE_TTL and not _cache_file_is_active(path):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue

            total_size += stat.st_size
            cache_files.append((stat.st_mtime, stat.st_size, path))
    except OSError:
        pass

    return total_size, cache_files


def cleanup_cache_sync(required_bytes=0):
    """Enforce TTL, global/per-file quotas and a minimum free-space reserve."""
    try:
        total_size, cache_files = _cache_usage_snapshot()

        # First enforce the per-file quota. Oldest chunks from the same
        # token are evicted first, but active chunks are never touched.
        by_token = {}
        for mtime, size, path in cache_files:
            token = path.parent.name
            by_token.setdefault(token, []).append((mtime, size, path))

        for token, items in by_token.items():
            file_total = sum(size for _, size, _ in items)
            if file_total <= CACHE_PER_FILE_MAX_SIZE:
                continue

            items.sort(key=lambda item: item[0])
            for _, size, path in items:
                if file_total <= CACHE_PER_FILE_MAX_SIZE:
                    break
                if _cache_file_is_active(path):
                    continue
                try:
                    path.unlink()
                    file_total -= size
                    total_size -= size
                except OSError:
                    pass

        # Determine how much must be removed to satisfy both the global
        # cache cap and the disk free-space reserve.
        try:
            free_space = shutil.disk_usage(CACHE_DIR).free
        except OSError:
            free_space = CACHE_MIN_FREE_SPACE

        target_total = min(
            CACHE_MAX_SIZE,
            max(0, total_size - max(0, CACHE_MIN_FREE_SPACE - free_space))
        )
        required_total = min(
            total_size,
            max(0, target_total - max(0, required_bytes))
        )

        if total_size > required_total:
            # Refresh mtimes after the per-file pass so eviction remains
            # true LRU-ish (recently served chunks naturally move forward).
            _, refreshed = _cache_usage_snapshot()
            refreshed.sort(key=lambda item: item[0])

            for _, size, path in refreshed:
                if total_size <= required_total:
                    break
                if _cache_file_is_active(path):
                    continue
                try:
                    path.unlink()
                    total_size -= size
                except OSError:
                    pass

        # Remove empty token directories.
        for directory in sorted(
            CACHE_DIR.rglob("*"),
            key=lambda item: len(item.parts),
            reverse=True
        ):
            if not directory.is_dir():
                continue
            try:
                directory.rmdir()
            except OSError:
                pass

    except Exception as error:
        print("[CACHE] Cleanup error:", error)


async def cleanup_cache_loop():
    while True:
        try:
            await asyncio.to_thread(cleanup_cache_sync)

            # Keep in-memory coordination maps bounded during long uptime.
            async with cache_locks_guard:
                if len(cache_locks) > 5000:
                    for key, lock in list(cache_locks.items()):
                        if not lock.locked():
                            cache_locks.pop(key, None)
                            if len(cache_locks) <= 3500:
                                break

            async with file_stream_semaphores_guard:
                if len(file_stream_semaphores) > 5000:
                    for token, semaphore in list(file_stream_semaphores.items()):
                        if semaphore._value == MAX_CONCURRENT_PER_FILE:
                            file_stream_semaphores.pop(token, None)
                            if len(file_stream_semaphores) <= 3500:
                                break

            with request_rate_lock:
                cutoff = time.monotonic() - REQUEST_RATE_WINDOW
                for client, state in list(request_rate_state.items()):
                    if state[0] < cutoff:
                        request_rate_state.pop(client, None)

        except asyncio.CancelledError:
            raise
        except Exception as error:
            print("[CACHE] Background cleanup error:", error)

        await asyncio.sleep(CACHE_CLEANUP_INTERVAL)


async def download_cache_chunk(
    message,
    cache_file,
    chunk_start,
    chunk_length
):
    part_file = cache_file.with_suffix(".cache.part")
    sent = 0

    _mark_cache_active(cache_file)
    try:
        # Make room before writing. A cache miss should not be allowed to
        # fill a nearly-full disk.
        await asyncio.to_thread(cleanup_cache_sync, chunk_length)

        try:
            free_space = shutil.disk_usage(CACHE_DIR).free
        except OSError:
            free_space = CACHE_MIN_FREE_SPACE

        if free_space < CACHE_MIN_FREE_SPACE + chunk_length:
            raise OSError(
                "Not enough free disk space for temporary cache"
            )

        if part_file.exists():
            try:
                part_file.unlink()
            except OSError:
                pass

        with part_file.open("wb") as output:
            async for chunk in telegram_stream(
                message,
                offset=chunk_start,
                length=chunk_length
            ):
                if not chunk:
                    continue

                remaining = chunk_length - sent
                if remaining <= 0:
                    break

                if len(chunk) > remaining:
                    chunk = chunk[:remaining]

                output.write(chunk)
                sent += len(chunk)

                if sent >= chunk_length:
                    break

        if sent != chunk_length:
            raise IOError(
                f"Cache chunk incomplete: expected {chunk_length} bytes, got {sent} bytes"
            )

        os.replace(part_file, cache_file)
        os.utime(cache_file, None)

    except asyncio.CancelledError:
        try:
            if part_file.exists():
                part_file.unlink()
        except OSError:
            pass
        raise

    except Exception:
        try:
            if part_file.exists():
                part_file.unlink()
        except OSError:
            pass
        raise

    finally:
        _unmark_cache_active(cache_file)


async def ensure_cache_chunk(
    token,
    message,
    chunk_index,
    chunk_start,
    chunk_length
):
    cache_file = cache_path(token, chunk_index)

    def valid_cache_file():
        try:
            stat = cache_file.stat()
            return (
                stat.st_size == chunk_length
                and time.time() - stat.st_mtime <= CACHE_TTL
            )
        except OSError:
            return False

    if valid_cache_file():
        # mtime doubles as the lightweight last-access timestamp.
        os.utime(cache_file, None)
        return cache_file

    # Per-chunk lock is request deduplication: if 10 viewers miss the
    # same chunk simultaneously, only the first one talks to Telegram.
    # The remaining requests wait and then reuse the completed cache file.
    cache_key = f"{token}:{chunk_index}"
    lock = await get_cache_lock(cache_key)

    async with lock:
        if valid_cache_file():
            os.utime(cache_file, None)
            return cache_file

        await download_cache_chunk(
            message,
            cache_file,
            chunk_start,
            chunk_length
        )

        # Re-check quotas immediately after a successful write.
        await asyncio.to_thread(cleanup_cache_sync)

        if not valid_cache_file():
            raise IOError("Temporary cache chunk was evicted or invalidated")

        os.utime(cache_file, None)
        return cache_file


async def cached_telegram_stream(
    token,
    message,
    file_size,
    offset,
    length
):
    end_position = offset + length

    first_chunk = offset // CACHE_CHUNK_SIZE
    last_chunk = (end_position - 1) // CACHE_CHUNK_SIZE

    for chunk_index in range(first_chunk, last_chunk + 1):
        chunk_start = chunk_index * CACHE_CHUNK_SIZE
        chunk_end = min(chunk_start + CACHE_CHUNK_SIZE, file_size)
        chunk_length = chunk_end - chunk_start

        cache_file = await ensure_cache_chunk(
            token, message, chunk_index, chunk_start, chunk_length
        )

        requested_start = max(offset, chunk_start)
        requested_end = min(end_position, chunk_end)
        read_start = requested_start - chunk_start
        read_length = requested_end - requested_start

        if read_length <= 0:
            continue

        _mark_cache_active(cache_file)
        try:
            os.utime(cache_file, None)

            with cache_file.open("rb") as cached_file:
                cached_file.seek(read_start)
                remaining = read_length

                while remaining > 0:
                    piece = await asyncio.to_thread(
                        cached_file.read, min(CHUNK_SIZE, remaining)
                    )

                    if not piece:
                        raise IOError(
                            "Temporary cache file ended unexpectedly"
                        )

                    remaining -= len(piece)
                    yield piece

            os.utime(cache_file, None)
        finally:
            _unmark_cache_active(cache_file)


@bot.on(events.NewMessage)
async def receive_file(event):

    if not BOT_MODE:
        return

    print(
        "[DEBUG] MESSAGE RECEIVED:",
        event.id,
        "FILE:",
        bool(event.file),
        "CHAT:",
        event.chat_id
    )

    if not event.file:
        return

    try:

        chat_id = int(event.chat_id)

        # ====================================================
        # FILE SIZE CHECK
        # ====================================================

        size = int(event.file.size or 0)

        if size > MAX_FILE_SIZE:

            size_gb = size / 1024 / 1024 / 1024

            await event.reply(
                "❌ <b>FILE TOO LARGE</b>\n\n"
                f"📦 Your file: "
                f"<code>{size_gb:.2f} GB</code>\n"
                f"📏 Maximum allowed: "
                f"<code>6 GB</code>",
                parse_mode="html"
            )

            print(
                f"[LIMIT] Rejected oversized file "
                f"from {chat_id}: {size_gb:.2f} GB"
            )

            return

        # ====================================================
        # 10 SECOND PER-USER COOLDOWN
        # ====================================================

        now = time.monotonic()

        last_upload = user_file_cooldowns.get(chat_id)

        if last_upload is not None:

            elapsed = now - last_upload

            if elapsed < FILE_COOLDOWN:

                remaining = FILE_COOLDOWN - elapsed

                await event.reply(
                    "⏳ <b>Please wait.</b>\n\n"
                    f"You can send another file in "
                    f"<code>{remaining:.1f} seconds</code>.",
                    parse_mode="html"
                )

                print(
                    f"[RATE LIMIT] User {chat_id} "
                    f"must wait {remaining:.1f}s"
                )

                return

        # Start cooldown only after passing checks
        user_file_cooldowns[chat_id] = now

        # ====================================================
        # FILENAME
        # ====================================================

        filename = event.file.name

        if not filename:

            mime = (
                event.file.mime_type
                or "application/octet-stream"
            )

            if mime.startswith("video/"):
                filename = "video.mp4"

            elif mime.startswith("audio/"):
                filename = "audio.mp3"

            else:
                filename = "telegram_file"

        filename = clean_filename(filename)

        # ====================================================
        # MIME
        # ====================================================

        mime = (
            event.file.mime_type
            or get_mime(filename)
        )

        # ====================================================
        # TOKEN
        # ====================================================

        token = uuid.uuid4().hex

        message_id = int(event.id)

        # ====================================================
        # REGISTER FILE
        # ====================================================

        add_file(
            token,
            chat_id,
            message_id,
            filename,
            size,
            mime
        )

        stream_url = (
            f"{PUBLIC_URL}/watch/{token}"
        )

        share_token = create_share_token(token)
        share_url = f"{PUBLIC_URL}/share/{share_token}"

        pair_code = create_pair_code(token)

        size_gb = (
            size / 1024 / 1024 / 1024
        )

        print(
            "\n" + "=" * 60
        )

        print(
            "[+] Telegram file registered"
        )

        print(
            "[+] Filename:",
            filename
        )

        print(
            f"[+] Size: {size_gb:.2f} GB"
        )

        print(
            "[+] Token:",
            token
        )

        print(
            "=" * 60
        )

        # ====================================================
        # WATCH BUTTON
        # ====================================================

        buttons = [
            [
                Button.url(
                    "▶️ WATCH / STREAM",
                    stream_url
                )
            ],
            [
                Button.url(
                    "📺 SHARE WITH ANOTHER DEVICE",
                    share_url
                )
            ]
        ]

        sent_message = await event.reply(
            "✅ <b>STADY-PROXY FILE READY!</b>\n\n"
            f"🎬 <b>{html.escape(filename)}</b>\n"
            f"📦 Size: "
            f"<code>{size_gb:.2f} GB</code>\n\n"
            f"📺 <b>TV PAIRING CODE:</b> <code>{pair_code}</code>\n\n"
            "On your TV, open STADY-PROXY and enter this 6-digit code.\n\n"
            "Click the button below to stream:",
            buttons=buttons,
            parse_mode="html"
        )

        save_bot_message_id(
            token,
            chat_id,
            int(sent_message.id)
        )

    except Exception as error:

        print(
            "[!] File registration error:",
            error
        )

        try:

            await event.reply(
                "❌ <b>Could not create file link.</b>\n\n"
                f"<code>{html.escape(str(error))}</code>",
                parse_mode="html"
            )

        except Exception:
            pass

async def notify_new_user(user):
    if not SECURITY_BOT_TOKEN or SECURITY_OWNER_ID <= 0:
        return

    first_name = user.first_name or ""
    last_name = user.last_name or ""
    username = user.username or "None"
    user_id = int(user.id)

    text = (
        "🆕 <b>NEW USER</b>\n\n"
        f"👤 <b>Name:</b> {html.escape(first_name + (' ' + last_name if last_name else ''))}\n"
        f"🔗 <b>Username:</b> @{html.escape(username) if username != 'None' else 'None'}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>"
    )

    try:
        data = urlencode({
            "chat_id": SECURITY_OWNER_ID,
            "text": text,
            "parse_mode": "HTML"
        }).encode()

        request = URLRequest(
            f"https://api.telegram.org/bot{SECURITY_BOT_TOKEN}/sendMessage",
            data=data,
            method="POST"
        )

        await asyncio.to_thread(urlopen, request, timeout=10)

    except Exception as error:
        print(f"Security notification failed: {error}")


@bot.on(events.NewMessage(pattern=r"^/start(?:\s+(.+))?$"))
async def start_command(event):

    if not BOT_MODE:
        return

    # Deep-link from the STADY-PROXY 404 page.
    # Telegram sends: /start unavailable
    start_match = event.pattern_match
    start_param = (
        start_match.group(1).strip().lower()
        if start_match and start_match.group(1)
        else ""
    )

    if start_param == "unavailable":
        await event.reply(
            "⚠️ <b>Sorry! This file is currently unavailable.</b>\n\n"
            "🔒 The file may have been removed, expired, "
            "or access may have been restricted by the administrator.\n\n"
            "🛠️ <b>Found a problem?</b>\n"
            "Please contact the administrator:\n"
            "👉 <a href=\"https://t.me/aswadhcr7\">@aswadhcr7</a>",
            parse_mode="html"
        )
        return

    user = await event.get_sender()
    is_new_user = False

    try:
        with db_connect() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users
                    (user_id, first_name, last_name, username)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO NOTHING
                    RETURNING user_id
                    """,
                    (
                        int(user.id),
                        user.first_name or "",
                        user.last_name or "",
                        user.username or ""
                    )
                )

                is_new_user = cursor.fetchone() is not None

    except Exception as error:
        print(f"User tracking failed: {error}")

    if is_new_user:
        await notify_new_user(user)

    await event.reply(

        "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
        "        ⚡ STADY-PROXY\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"

        "🎬 FILE → STREAM → DOWNLOAD\n\n"

        "Send me any video or file and\n"
        "I'll instantly create a browser\n"
        "streaming & download link for you.\n\n"

        "✨ FEATURES\n\n"

        "▶️ Fast Browser Streaming\n"
        "☁️ Direct Download\n"
        "📱 Mobile Friendly\n"
        "🔗 Easy Link Sharing\n"
        "📦 Supports MP4, MKV, MP3, APK,\n"
        "   ZIP, PDF & many more formats\n\n"

        "⏳ 12-HOUR LINK\n"
        "Your generated link stays active\n"
        "for 12 hours only.\n\n"

        "🗑️ AUTO CLEANUP\n"
        "Generated bot messages are\n"
        "automatically deleted after 12 hours.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "📤 Send your file to get started.\n\n"

        'Made with ❤️ by'
        '<a href="https://www.instagram.com/2aswadhh_._kr">'
        'aswadh_kr'
        '</a>',

        parse_mode="html"
    )


# ============================================================
# STADY-PROXY THEME
# IMPORTANT:
# CSS uses SINGLE braces because this string is not an f-string.
# ============================================================

STADY_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&family=Poppins:wght@400;500;600&display=swap');

*{box-sizing:border-box}

html,body{
    margin:0;
    min-height:100%;
    font-family:Poppins,Arial,sans-serif;
    background:#030914;
    color:#eaf7ff;
}

body{
    overflow-x:hidden;
    background:
        radial-gradient(circle at 15% 20%,rgba(0,238,255,.16),transparent 28%),
        radial-gradient(circle at 85% 65%,rgba(255,0,213,.16),transparent 30%),
        linear-gradient(180deg,#020812,#061629 55%,#020812);
}

body:before{
    content:"";
    position:fixed;
    inset:0;
    pointer-events:none;
    opacity:.32;
    background-image:
        linear-gradient(rgba(0,255,255,.08) 1px,transparent 1px),
        linear-gradient(90deg,rgba(0,255,255,.05) 1px,transparent 1px);
    background-size:34px 34px;
    mask-image:linear-gradient(
        to bottom,
        transparent,
        #000 12%,
        #000 85%,
        transparent
    );
}

.page{
    width:min(720px,100%);
    margin:auto;
    padding:22px 14px 45px;
}

.brand{
    text-align:center;
    font-family:Orbitron,sans-serif;
    font-size:clamp(28px,7vw,46px);
    font-weight:800;
    letter-spacing:2px;
    margin:8px 0 20px;
    color:#69f7ff;
    text-shadow:
        0 0 8px #00eaff,
        0 0 22px #7c28ff,
        0 0 40px #ff18d5;
}

.frame{
    position:relative;
    padding:12px;
    border:2px solid #42eaff;
    border-radius:15px;
    background:
        linear-gradient(
            145deg,
            rgba(12,43,72,.9),
            rgba(4,13,28,.94)
        );
    box-shadow:
        0 0 10px #00eaff,
        inset 0 0 20px rgba(0,234,255,.15),
        0 0 30px rgba(255,0,213,.2);
}

.frame:before,
.frame:after{
    content:"";
    position:absolute;
    height:5px;
    width:90px;
    top:-5px;
    background:linear-gradient(
        90deg,
        #00eaff,
        #bdfcff,
        #ff24d7
    );
    box-shadow:0 0 12px #00eaff;
    border-radius:4px;
}

.frame:before{left:35px}
.frame:after{right:35px}

.poster{
    position:relative;
    overflow:hidden;
    border:2px solid #36f3ff;
    border-radius:8px;
    aspect-ratio:16/9;
    background:#0a2039;
    box-shadow:
        inset 0 0 22px rgba(0,255,255,.35),
        0 0 14px rgba(0,234,255,.45);
}

.poster img{
    width:100%;
    height:100%;
    display:block;
    object-fit:cover;
}

.play{
    position:absolute;
    left:50%;
    top:50%;
    transform:translate(-50%,-50%);
    width:118px;
    height:82px;
    border:2px solid #9afcff;
    border-radius:16px;
    background:rgba(75,90,112,.58);
    backdrop-filter:blur(5px);
    color:#dffcff;
    font-size:44px;
    line-height:78px;
    text-align:center;
    text-shadow:0 0 10px #00eaff;
    box-shadow:0 0 18px rgba(0,238,255,.35);
    cursor:pointer;
}

.actions{
    display:grid;
    gap:14px;
    margin:18px 0;
}

.btn{
    appearance:none;
    border:2px solid #38f5ff;
    border-radius:10px;
    padding:15px 12px;
    width:100%;
    font:500 clamp(17px,4.6vw,25px) Poppins,sans-serif;
    color:#eaffff;
    cursor:pointer;
    background:
        linear-gradient(
            180deg,
            rgba(17,72,103,.95),
            rgba(10,33,62,.98)
        );
    box-shadow:
        0 0 9px rgba(0,238,255,.75),
        inset 0 0 16px rgba(0,238,255,.12),
        0 5px 0 rgba(255,0,204,.35);
    transition:.18s transform,.18s filter;
}

.btn:hover{
    filter:brightness(1.25);
    transform:translateY(-2px);
}

.btn:active{
    transform:translateY(1px);
}

.players{
    display:none;
    border-radius:0 0 18px 18px;
    background:#101b28;
    margin-top:-14px;
    padding:22px 12px 18px;
    text-align:center;
    box-shadow:0 8px 18px rgba(0,0,0,.35);
    font-size:18px;
}

.players button{
    display:block;
    width:100%;
    border:0;
    background:none;
    color:#f0f5ff;
    font:inherit;
    padding:8px;
    cursor:pointer;
}

.players button:hover{
    color:#56efff;
}

.info{
    margin-top:14px;
    padding:16px 4px 8px;
    font-size:16px;
    line-height:2;
    color:#e7f4ff;
}

.info div{
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}

.info b{
    font-weight:500;
}

.status{
    font-size:13px;
    color:#8edfff;
    text-align:center;
    margin-top:8px;
    opacity:.8;
}

@media(max-width:480px){

    .page{
        padding-left:9px;
        padding-right:9px;
    }

    .frame{
        padding:9px;
    }

    .play{
        width:95px;
        height:68px;
        line-height:64px;
        font-size:34px;
    }

    .info{
        font-size:14px;
    }
}
"""


# ============================================================
# HOME
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home():

    return f"""<!DOCTYPE html>
<html lang="en">
<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>STADY-PROXY</title>

<style>{STADY_CSS}</style>

</head>

<body>

<main class="page">

    <div class="brand">
        STADY-PROXY
    </div>

    <section class="frame">

        <div class="poster">

            <img
                src="https://images.unsplash.com/photo-1511497584788-876760111969?auto=format&fit=crop&w=1200&q=85"
            >

        </div>

        <div
            class="status"
            style="font-size:20px;margin:25px 0;"
        >
            SERVER ONLINE 🚀
        </div>

        <div class="actions">
            <input
                id="pairCode"
                class="btn"
                type="text"
                inputmode="numeric"
                pattern="[0-9]{6}"
                maxlength="6"
                placeholder="ENTER 6-DIGIT TV CODE"
                style="text-align:center;"
            >
            <button
                class="btn"
                onclick="pairDevice()"
            >
                📺 PAIR TV
            </button>
        </div>

        <p style="text-align:center;line-height:1.7;color:#a9bfd0;font-size:14px;">
            <b>📖 TV PAIRING — HOW TO USE</b><br><br>
            1️⃣ Send a video/file to the STADY-PROXY Telegram bot.<br>
            2️⃣ Open the generated SHARE page on your phone.<br>
            3️⃣ Find the 6-digit TV pairing code shown there (it is also sent in Telegram).<br>
            4️⃣ On your TV, open this STADY-PROXY home page.<br>
            5️⃣ Enter the 6-digit code above and tap <b>PAIR TV</b>.<br>
            6️⃣ Your TV will open the receiver page with VLC, MX Player and Browser Player options.<br><br>
            ⏳ Pairing codes follow the same 12-hour file expiry.
        </p>

    </section>

<script>
function pairDevice() {{
    const input = document.getElementById("pairCode");
    const code = input.value.trim();

    if (!/^[0-9]{{6}}$/.test(code)) {{
        input.focus();
        return;
    }}

    location.href = "/pair/" + code;
}}
</script>

</main>

</body>
</html>"""


# ============================================================
# WATCH PAGE
# ============================================================

@app.get(
    "/watch/{token}",
    response_class=HTMLResponse
)
async def watch(token):

    row = get_file(token)

    if not row:
        return HTMLResponse(
            content=stady_error_page(),
            status_code=404
        )

    filename = row["filename"]
    safe_name = html.escape(filename)
    encoded_filename = quote(filename, safe="")

    stream_url = (
        f"{PUBLIC_URL}/{token}/"
        f"{encoded_filename}?action=stream"
    )

    file_size = int(row["size"])
    mime = resolve_media_mime(filename, row["mime"])
    profile = detect_media_profile(filename, mime)
    browser_ok = profile["browser_ok"]
    profile_label = html.escape(profile["label"])
    profile_reason = html.escape(profile["reason"])
    detected_mime = html.escape(profile["mime"])
    detected_ext = html.escape(profile["extension"])

    if file_size >= 1024**3:
        size_str = f"{file_size / 1024**3:.2f} GB"
    elif file_size >= 1024**2:
        size_str = f"{file_size / 1024**2:.2f} MB"
    else:
        size_str = f"{file_size / 1024:.2f} KB"

    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stream_no_scheme = stream_url.replace("https://", "").replace("http://", "")
    scheme = "https" if stream_url.startswith("https://") else "http"

    browser_button = (
        '<button class="btn" id="browserBtn" onclick="stream()">▶ Browser Stream</button>'
        if browser_ok
        else '<button class="btn disabled" type="button" disabled>⚠ Browser Video Not Recommended</button>'
    )

    initial_media = (
        f"""<div class="poster-content">
            <div class="poster-icon">▶</div>
            <div class="poster-title">Browser-ready media</div>
            <div class="poster-sub">Tap Browser Stream to start</div>
        </div>"""
        if browser_ok else
        f"""<div class="poster-content">
            <div class="poster-icon">🎬</div>
            <div class="poster-title">External Player Recommended</div>
            <div class="poster-sub">{profile_reason}</div>
            <div class="poster-codec">{detected_ext} · {detected_mime}</div>
        </div>"""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, viewport-fit=cover">
<title>STADY-PROXY | {safe_name}</title>
<style>
{STADY_CSS}

/* Final clean player */
.poster {{
    position:relative;
    overflow:hidden;
    background:#02050a;
}}
.poster-content {{
    position:absolute;
    inset:0;
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    text-align:center;
    padding:24px;
    box-sizing:border-box;
    background:radial-gradient(circle at center, rgba(0,234,255,.10), transparent 58%);
}}
.poster-icon {{
    font-size:48px;
    margin-bottom:12px;
    filter:drop-shadow(0 0 12px rgba(0,234,255,.8));
}}
.poster-title {{font-size:19px;font-weight:800;color:#fff}}
.poster-sub {{margin-top:8px;font-size:13px;color:#a9bfd0;max-width:390px;line-height:1.5}}
.poster-codec {{
    margin-top:12px;
    padding:7px 11px;
    border:1px solid rgba(105,247,255,.35);
    border-radius:999px;
    font-size:12px;
    color:#69f7ff;
    background:rgba(0,0,0,.28);
}}
.profile-badge {{
    display:inline-flex;
    align-items:center;
    gap:7px;
    margin-top:12px;
    padding:7px 11px;
    border-radius:999px;
    font-size:12px;
    font-weight:700;
    color:#fff;
    background:rgba(0,0,0,.32);
    border:1px solid rgba(255,255,255,.16);
}}
.disabled {{opacity:.48;cursor:not-allowed}}
.video-shell {{position:relative;width:100%;height:100%;background:#000;border-radius:18px;overflow:hidden}}
.video-shell video {{width:100%;height:100%;display:block;object-fit:contain;background:#000;border:0;outline:0}}
.video-controls {{
    position:absolute;left:10px;right:10px;bottom:10px;z-index:10;
    padding:8px 10px 7px;border-radius:13px;
    background:linear-gradient(180deg,transparent,rgba(0,0,0,.88) 34%);
    box-sizing:border-box;
    opacity:1;transition:opacity .2s;
}}
.video-controls.hide {{opacity:0;pointer-events:none}}
.video-seek {{width:100%;height:5px;margin:0 0 6px;accent-color:#69f7ff;cursor:pointer}}
.control-row {{display:flex;align-items:center;gap:8px;color:#fff}}
.control-row button {{border:0;background:transparent;color:#fff;font-size:20px;padding:3px 7px;cursor:pointer}}
.video-time {{font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}}
.control-spacer {{flex:1}}
.video-error {{
    display:none;position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
    width:min(88%,420px);box-sizing:border-box;padding:16px;border-radius:14px;
    background:rgba(0,0,0,.9);color:#fff;text-align:center;font-size:14px;line-height:1.5;z-index:12;
}}
</style>
</head>
<body>
<main class="page">
<div class="brand">STADY-PROXY</div>
<section class="frame">

<div class="poster" id="playerArea">
    {initial_media}
</div>

<div style="text-align:center">
    <span class="profile-badge">● {profile_label}</span>
</div>

<div class="actions">
    {browser_button}
    <button class="btn" onclick="togglePlayers()">🎬 External Players</button>
    <a class="btn" href="{stream_url}&action=download" download style="text-decoration:none;text-align:center;display:block;">⬇ Download</a>

    <div class="players" id="players">
        <button onclick="openPlayer('mx')">MX Player</button>
        <button onclick="openPlayer('vlc')">VLC Mobile</button>
        <button onclick="openPlayer('playit')">PlayIt</button>
        <button onclick="openPlayer('kmplayer')">KMPlayer</button>
        <button onclick="openPlayer('nplayer')">nPlayer</button>
    </div>
</div>

<div class="info">
<div>📄 <b>File Name:</b> <span>{safe_name}</span></div>
<div>☰ <b>File Size:</b> <span>{size_str}</span></div>
<div>🎞 <b>Detected:</b> <span>{detected_ext} · {detected_mime}</span></div>
<div>👤 <b>File Owner:</b> <span>STADY-PROXY</span></div>
<div>◷ <b>Created Time:</b> <span>{created}</span></div>
</div>

</section>

<div class="status" id="status">STADY-PROXY • READY</div>

<div style="text-align:center;margin-top:22px;padding-bottom:8px;font-size:14px;color:#888;">
Made with ♥ by
<a href="https://www.instagram.com/2aswadhh_._kr" target="_blank" rel="noopener noreferrer" style="display:inline-flex;align-items:center;gap:6px;margin-left:4px;color:#ff2bd6;text-decoration:none;font-weight:700;text-shadow:0 0 5px rgba(255,43,214,.8),0 0 12px rgba(255,43,214,.55);">aswadh_kr</a>
</div>
</main>

<script>
const STREAM_URL = {stream_url!r};
const BROWSER_OK = {str(browser_ok).lower()};
const BROWSER_MKV = {str(detected_ext.lower() == ".mkv").lower()};

function setStatus(text) {{
    const el = document.getElementById("status");
    if (el) el.textContent = text;
}}

async function streamMkv() {{
    const area = document.getElementById("playerArea");
    if (!area) return;

    area.innerHTML = `
        <div class="video-shell" id="videoShell">
            <canvas id="mkvCanvas" style="width:100%;height:100%;display:block;background:#000"></canvas>
            <div id="videoError" class="video-error"></div>
            <div class="video-controls" id="videoControls">
                <input id="videoSeek" class="video-seek" type="range" min="0" max="1000" value="0" step="1" aria-label="Seek">
                <div class="control-row">
                    <button id="videoPlay" type="button" aria-label="Play or pause">▶</button>
                    <span id="videoTime" class="video-time">0:00 / 0:00</span>
                    <span class="control-spacer"></span>
                    <button id="videoMute" type="button" aria-label="Mute">🔊</button>
                    <button id="videoFullscreen" type="button" aria-label="Fullscreen">⛶</button>
                </div>
            </div>
        </div>`;

    const canvas = document.getElementById("mkvCanvas");
    const ctx = canvas.getContext("2d", {{ alpha: false }});
    const seek = document.getElementById("videoSeek");
    const playBtn = document.getElementById("videoPlay");
    const muteBtn = document.getElementById("videoMute");
    const fullscreenBtn = document.getElementById("videoFullscreen");
    const timeLabel = document.getElementById("videoTime");
    const controls = document.getElementById("videoControls");
    const shell = document.getElementById("videoShell");
    const errorBox = document.getElementById("videoError");
    let hideTimer = null;
    let running = false;
    let position = 0;
    let duration = 0;
    let raf = 0;
    let generation = 0;
    let audioContext = null;
    let audioGain = null;
    let audioNodes = [];
    let videoTask = null;
    let audioTask = null;
    let mediabunny = null;
    let input = null;
    let videoTrack = null;
    let audioTrack = null;
    let videoSink = null;
    let audioSink = null;

    function formatTime(s) {{
        if (!Number.isFinite(s) || s < 0) return "0:00";
        s = Math.floor(s);
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        return h ? `${{h}}:${{String(m).padStart(2,"0")}}:${{String(sec).padStart(2,"0")}}` : `${{m}}:${{String(sec).padStart(2,"0")}}`;
    }}

    function updateUI() {{
        seek.value = duration ? String(Math.max(0, Math.min(1000, position / duration * 1000))) : "0";
        timeLabel.textContent = `${{formatTime(position)}} / ${{formatTime(duration)}}`;
        playBtn.textContent = running ? "❚❚" : "▶";
        muteBtn.textContent = audioGain && audioGain.gain.value === 0 ? "🔇" : "🔊";
    }}

    function showControls() {{
        controls.classList.add("show");
        clearTimeout(hideTimer);
        if (running) hideTimer = setTimeout(() => controls.classList.remove("show"), 2500);
    }}

    function stopAudio() {{
        for (const node of audioNodes) {{
            try {{ node.stop(); }} catch (_) {{}}
            try {{ node.disconnect(); }} catch (_) {{}}
        }}
        audioNodes = [];
    }}

    async function stopPlayback() {{
        running = false;
        generation++;
        if (raf) cancelAnimationFrame(raf);
        stopAudio();
        if (videoTask) {{ try {{ await videoTask; }} catch (_) {{}} }}
        if (audioTask) {{ try {{ await audioTask; }} catch (_) {{}} }}
        videoTask = null;
        audioTask = null;
        updateUI();
    }}

    async function ensureInput() {{
        if (input) return;
        setStatus("STADY-PROXY • LOADING MKV PLAYER…");
        mediabunny = await import("https://cdn.jsdelivr.net/npm/mediabunny/+esm");
        input = new mediabunny.Input({{
            source: new mediabunny.UrlSource(STREAM_URL),
            formats: mediabunny.ALL_FORMATS
        }});
        if (!(await input.canRead())) throw new Error("This MKV could not be read by the browser player.");
        videoTrack = await input.getPrimaryVideoTrack();
        audioTrack = await input.getPrimaryAudioTrack();
        if (!videoTrack) throw new Error("No video track was found in this MKV.");
        duration = await input.computeDuration();
        videoSink = new mediabunny.CanvasSink(videoTrack, {{ poolSize: 2 }});
        if (audioTrack) audioSink = new mediabunny.AudioBufferSink(audioTrack);
        updateUI();
    }}

    async function renderVideo(myGeneration, startAt) {{
        let firstWall = performance.now();
        let firstTs = null;
        try {{
            for await (const frame of videoSink.canvases(startAt, Math.min(duration, startAt + 30))) {{
                if (!running || myGeneration !== generation) return;
                if (firstTs === null) {{ firstTs = frame.timestamp; firstWall = performance.now(); }}
                const target = firstWall + (frame.timestamp - firstTs) * 1000;
                const wait = target - performance.now();
                if (wait > 2) await new Promise(r => setTimeout(r, Math.min(wait, 100)));
                if (!running || myGeneration !== generation) return;
                const c = frame.canvas;
                if (canvas.width !== c.width || canvas.height !== c.height) {{ canvas.width = c.width; canvas.height = c.height; }}
                ctx.drawImage(c, 0, 0, canvas.width, canvas.height);
                position = frame.timestamp;
                updateUI();
                if (position >= duration - 0.05) {{ running = false; updateUI(); setStatus("STADY-PROXY • ENDED"); return; }}
            }}
        }} finally {{
            if (videoSink) {{}}
        }}
    }}

    async function renderAudio(myGeneration, startAt) {{
        if (!audioSink || !audioContext) return;
        const base = audioContext.currentTime + 0.08;
        try {{
            for await (const item of audioSink.buffers(startAt, Math.min(duration, startAt + 30))) {{
                if (!running || myGeneration !== generation) return;
                const node = audioContext.createBufferSource();
                node.buffer = item.buffer;
                node.connect(audioGain);
                const when = Math.max(audioContext.currentTime + 0.02, base + (item.timestamp - startAt));
                node.start(when);
                audioNodes.push(node);
            }}
        }} catch (e) {{
            console.warn("MKV audio playback error:", e);
        }}
    }}

    async function playMkv() {{
        try {{
            await ensureInput();
            if (!audioContext) {{
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                audioGain = audioContext.createGain();
                audioGain.connect(audioContext.destination);
            }}
            await audioContext.resume();
            if (running) return;
            running = true;
            generation++;
            const myGeneration = generation;
            setStatus("STADY-PROXY • MKV PLAYING ▶");
            showControls();
            videoTask = renderVideo(myGeneration, position);
            audioTask = renderAudio(myGeneration, position);
            await Promise.race([videoTask, audioTask]);
            if (running && myGeneration === generation && position < duration - 0.1) {{
                running = false;
                updateUI();
            }}
        }} catch (e) {{
            console.error(e);
            running = false;
            errorBox.innerHTML = "⚠️ <b>Browser MKV playback failed</b><br><span style=\"opacity:.8\">" + String(e.message || e).replace(/[<>&]/g, "") + "</span><br><br>Try VLC / MX Player if this device does not support the video's codec.";
            errorBox.style.display = "block";
            setStatus("STADY-PROXY • MKV PLAYER ERROR");
            updateUI();
        }}
    }}

    playBtn.onclick = () => running ? stopPlayback() : playMkv();
    muteBtn.onclick = () => {{
        if (!audioGain) return;
        audioGain.gain.value = audioGain.gain.value === 0 ? 1 : 0;
        updateUI();
    }};
    fullscreenBtn.onclick = () => {{
        if (shell.requestFullscreen) shell.requestFullscreen().catch(() => {{}});
    }};
    seek.oninput = async () => {{
        const target = duration ? Number(seek.value) / 1000 * duration : 0;
        position = Math.max(0, Math.min(duration || 0, target));
        updateUI();
        const wasRunning = running;
        await stopPlayback();
        if (wasRunning) await playMkv();
    }};
    shell.onclick = (e) => {{
        if (e.target.closest(".video-controls")) return;
        if (running) stopPlayback(); else playMkv();
        showControls();
    }};
    shell.addEventListener("mousemove", showControls);
    shell.addEventListener("touchstart", showControls, {{passive:true}});
    showControls();
    updateUI();
    setStatus("STADY-PROXY • MKV READY — TAP ▶");
}}

function stream() {{
    if (BROWSER_MKV) {{
        streamMkv();
        return;
    }}

    if (!BROWSER_OK) {{
        setStatus("STADY-PROXY • USE VLC / MX PLAYER");
        togglePlayers(true);
        return;
    }}

    const area = document.getElementById("playerArea");
    if (!area) return;

    area.innerHTML = `
        <div class="video-shell" id="videoShell">
            <video id="mainVideo" autoplay playsinline preload="metadata" src="${{STREAM_URL}}"></video>
            <div id="videoError" class="video-error">
                ⚠️ Browser cannot decode this video's video track.<br>
                <span style="opacity:.8">Use VLC / MX Player for this file.</span>
            </div>
            <div class="video-controls" id="videoControls">
                <input id="videoSeek" class="video-seek" type="range" min="0" max="1000" value="0" step="1" aria-label="Seek">
                <div class="control-row">
                    <button id="videoPlay" type="button" aria-label="Play or pause">▶</button>
                    <span id="videoTime" class="video-time">0:00 / 0:00</span>
                    <span class="control-spacer"></span>
                    <button id="videoMute" type="button" aria-label="Mute">🔊</button>
                    <button id="videoFullscreen" type="button" aria-label="Fullscreen">⛶</button>
                </div>
            </div>
        </div>`;

    const video = document.getElementById("mainVideo");
    const seek = document.getElementById("videoSeek");
    const playBtn = document.getElementById("videoPlay");
    const muteBtn = document.getElementById("videoMute");
    const fullscreenBtn = document.getElementById("videoFullscreen");
    const timeLabel = document.getElementById("videoTime");
    const errorBox = document.getElementById("videoError");
    const controls = document.getElementById("videoControls");
    let hideTimer = null;

    function formatTime(seconds) {{
        if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) return h + ":" + String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0");
        return m + ":" + String(s).padStart(2,"0");
    }}

    function updateUI() {{
        const duration = video.duration;
        const current = video.currentTime || 0;
        timeLabel.textContent = formatTime(current) + " / " + formatTime(duration);
        if (Number.isFinite(duration) && duration > 0) seek.value = String(Math.round((current / duration) * 1000));
        playBtn.textContent = video.paused ? "▶" : "Ⅱ";
        muteBtn.textContent = video.muted ? "🔇" : "🔊";
    }}

    function showControls() {{
        controls.classList.remove("hide");
        clearTimeout(hideTimer);
        if (!video.paused) hideTimer = setTimeout(() => controls.classList.add("hide"), 2500);
    }}

    playBtn.addEventListener("click", () => {{
        if (video.paused) video.play().catch(() => {{}}); else video.pause();
        showControls();
    }});
    muteBtn.addEventListener("click", () => {{ video.muted = !video.muted; updateUI(); showControls(); }});
    fullscreenBtn.addEventListener("click", async () => {{
        try {{
            const shell = document.getElementById("videoShell");
            if (shell.requestFullscreen) await shell.requestFullscreen();
            else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
        }} catch (_) {{}}
    }});
    seek.addEventListener("input", () => {{
        if (Number.isFinite(video.duration) && video.duration > 0) video.currentTime = (Number(seek.value) / 1000) * video.duration;
        showControls();
    }});
    video.addEventListener("loadedmetadata", () => {{
        updateUI();
        if (video.videoWidth === 0 || video.videoHeight === 0) {{
            errorBox.style.display = "block";
            setStatus("STADY-PROXY • VIDEO CODEC NOT SUPPORTED");
        }}
    }});
    video.addEventListener("timeupdate", updateUI);
    video.addEventListener("play", () => {{ updateUI(); showControls(); setStatus("STADY-PROXY • PLAYING ▶"); }});
    video.addEventListener("pause", () => {{ updateUI(); showControls(); }});
    video.addEventListener("volumechange", updateUI);
    video.addEventListener("waiting", () => setStatus("STADY-PROXY • BUFFERING…"));
    video.addEventListener("canplay", () => setStatus("STADY-PROXY • READY ▶"));
    video.addEventListener("error", () => {{
        if (video.error && (video.error.code === MediaError.MEDIA_ERR_DECODE || video.error.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED)) {{
            errorBox.style.display = "block";
            setStatus("STADY-PROXY • BROWSER VIDEO NOT SUPPORTED");
        }}
    }});
    video.addEventListener("click", () => {{ if (video.paused) video.play().catch(() => {{}}); else video.pause(); showControls(); }});
    document.getElementById("videoShell").addEventListener("mousemove", showControls);
    document.getElementById("videoShell").addEventListener("touchstart", showControls, {{passive:true}});

    video.play().catch(() => {{ updateUI(); }});
    setStatus("STADY-PROXY • LOADING ▶");
}}

function togglePlayers(forceOpen=false) {{
    const players = document.getElementById("players");
    if (!players) return;
    if (forceOpen) players.style.display = "block";
    else players.style.display = players.style.display === "block" ? "none" : "block";
}}

function openPlayer(player) {{
    let intent = "";
    if (player === "mx") intent = "intent://" + "{stream_no_scheme}" + "#Intent;scheme={scheme};package=com.mxtech.videoplayer.ad;type=video/*;end;";
    else if (player === "vlc") intent = "intent://" + "{stream_no_scheme}" + "#Intent;scheme={scheme};package=org.videolan.vlc;type=video/*;end;";
    else if (player === "playit") intent = "intent://" + "{stream_no_scheme}" + "#Intent;scheme={scheme};package=com.playit.videoplayer;type=video/*;end;";
    else if (player === "kmplayer") intent = "intent://" + "{stream_no_scheme}" + "#Intent;scheme={scheme};package=com.kmplayer;type=video/*;end;";
    else if (player === "nplayer") intent = "intent://" + "{stream_no_scheme}" + "#Intent;scheme={scheme};type=video/*;end;";
    if (intent) location.href = intent; else location.href = STREAM_URL;
}}
</script>
</body>
</html>"""


# ============================================================
# DEVICE SHARING
# ============================================================

@app.get("/share/{share_token}", response_class=HTMLResponse)
async def share_page(share_token: str):
    row = get_file_by_share_token(share_token)

    if not row:
        return HTMLResponse(
            content=stady_error_page(),
            status_code=404
        )

    filename = row["filename"]
    safe_name = html.escape(filename)
    pair_code = row["pair_code"] or "------"
    receiver_url = f"{PUBLIC_URL}/receive/{share_token}"

    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>STADY-PROXY | Share</title>
<style>{STADY_CSS}
.sharebox{{text-align:center;padding:18px 8px 10px}}
.qr{{width:min(310px,80vw);height:auto;background:#fff;padding:12px;border-radius:12px;margin:14px auto;display:block}}
.small{{color:#a9bfd0;font-size:14px;line-height:1.6}}
</style>
</head>
<body>
<main class="page">
<div class="brand">STADY-PROXY</div>
<section class="frame">
<div class="sharebox">
<h2>📺 SHARE WITH ANOTHER DEVICE</h2>
<p class="small">Scan this QR code on the other device.</p>
<img class="qr" src="/share-qr/{share_token}.png" alt="Share QR code">
<p><b>{safe_name}</b></p>
<p style="font-size:18px;margin:18px 0 8px;">
    📺 <b>TV PAIRING CODE</b>
</p>
<p style="
    font-family:monospace;
    font-size:34px;
    font-weight:800;
    letter-spacing:8px;
    margin:0 0 14px;
    color:#69f7ff;
    text-shadow:0 0 12px #00eaff;
">
    {pair_code}
</p>
<p class="small">
    Enter this 6-digit code on the STADY-PROXY home page on your TV.<br>
    The QR code above can still be scanned directly.
</p>
<p class="small">The QR opens a receiver page with player options.</p>
</div>
</section>
<div class="status">STADY-PROXY • READY</div>
</main>
</body>
</html>"""
    )


@app.get("/share-qr/{share_token}.png")
async def share_qr(share_token: str):
    from io import BytesIO

    row = get_file_by_share_token(share_token)

    if not row:
        return HTMLResponse(
            content=stady_error_page(),
            status_code=404
        )

    receiver_url = f"{PUBLIC_URL}/receive/{share_token}"

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(receiver_url)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="image/png",
        headers={"Cache-Control": "no-store"}
    )


@app.get("/receive/{share_token}", response_class=HTMLResponse)
async def receive_page(share_token: str):
    row = get_file_by_share_token(share_token)

    if not row:
        return HTMLResponse(
            content=stady_error_page(),
            status_code=404
        )

    filename = row["filename"]
    safe_name = html.escape(filename)
    encoded_filename = quote(filename, safe="")
    stream_url = (
        f"{PUBLIC_URL}/{row['token']}/"
        f"{encoded_filename}?action=stream"
    )

    stream_no_scheme = (
        stream_url.replace("https://", "").replace("http://", "")
    )
    scheme = "https" if stream_url.startswith("https://") else "http"

    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>STADY-PROXY | Receiver</title>
<style>{STADY_CSS}
.receiver{{text-align:center;padding:18px 8px}}
.file{{font-size:18px;word-break:break-word}}
</style>
</head>
<body>
<main class="page">
<div class="brand">STADY-PROXY</div>
<section class="frame">
<div class="receiver">
<h2>📺 READY TO STREAM</h2>
<p class="file"><b>{safe_name}</b></p>

<div class="actions">
<button class="btn" onclick="openPlayer('vlc')">▶ VLC</button>
<button class="btn" onclick="openPlayer('mx')">▶ MX PLAYER</button>
<button class="btn" onclick="playBrowser()">🌐 BROWSER PLAYER</button>
</div>

<p class="small">
⚠️ Can't open directly in VLC or MX Player?<br>
Copy the link below and paste it into your player.
</p>

<button class="btn" onclick="copyStreamLink()">
    📋 COPY STREAM LINK
</button>

<p id="copyLink" class="small" style="word-break:break-all;margin-top:12px;">
{stream_url}
</p>

<p class="small">If an external player does not open, use Browser Player.</p>
</div>
</section>
<div class="status" id="status">STADY-PROXY • RECEIVER READY</div>
</main>

<script>
const STREAM_URL = {stream_url!r};

function setStatus(text) {{
    document.getElementById("status").textContent = text;
}}

function playBrowser() {{
    location.href = STREAM_URL;
}}

function copyStreamLink() {{
    navigator.clipboard.writeText(STREAM_URL).then(() => {{
        setStatus("✅ STREAM LINK COPIED");
    }}).catch(() => {{
        const input = document.createElement("input");
        input.value = STREAM_URL;
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        input.remove();
        setStatus("✅ STREAM LINK COPIED");
    }});
}}

function openPlayer(player) {{
    let intent = "";

    if (player === "vlc") {{
        intent =
            "intent://" +
            "{stream_no_scheme}" +
            "#Intent;scheme={scheme};" +
            "package=org.videolan.vlc;" +
            "type=video/*;end;";
    }} else if (player === "mx") {{
        intent =
            "intent://" +
            "{stream_no_scheme}" +
            "#Intent;scheme={scheme};" +
            "package=com.mxtech.videoplayer.ad;" +
            "type=video/*;end;";
    }}

    if (intent) {{
        setStatus("STADY-PROXY • OPENING PLAYER");
        location.href = intent;
    }} else {{
        playBrowser();
    }}
}}
</script>
</body>
</html>"""
    )


# ============================================================
# TV PAIRING
# ============================================================

@app.get("/pair/{code}", response_class=HTMLResponse)
async def pair_device(code: str):
    code = code.strip()

    if not re.fullmatch(r"\d{6}", code):
        return HTMLResponse(
            content=stady_error_page(),
            status_code=404
        )

    row = get_file_by_pair_code(code)

    if not row:
        return HTMLResponse(
            content=stady_error_page(),
            status_code=404
        )

    share_token = row["share_token"]

    if not share_token:
        share_token = create_share_token(row["token"])

    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html>
<head>
<meta http-equiv="refresh" content="0; url=/receive/{share_token}">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>STADY-PROXY | TV Pairing</title>
</head>
<body style="
    background:#030914;
    color:#eaf7ff;
    font-family:Arial,sans-serif;
    text-align:center;
    padding-top:80px;
">
<h2>📺 TV PAIRED</h2>
<p>Opening the receiver page...</p>
<p><a href="/receive/{share_token}" style="color:#69f7ff;">Continue</a></p>
</body>
</html>"""
    )


# ============================================================
# DIRECT TELEGRAM PROXY
# ============================================================

@app.get("/{token}/{filename:path}")
async def direct_proxy(
    token: str,
    filename: str,
    request: Request,
    action: str = "stream"
):

    row = get_file(token)

    if not row:

        return HTMLResponse(
        content=stady_error_page(),
        status_code=404
        )

    real_filename = row["filename"]

    if filename != real_filename:

        return HTMLResponse(
        content=stady_error_page(),
        status_code=404

        )

    try:

        message = await bot.get_messages(
            row["chat_id"],
            ids=row["message_id"]
        )

    except Exception as error:

        print(
            "[!] Telegram message lookup failed:",
            error
        )

        raise HTTPException(
            status_code=500,
            detail="Could not access Telegram file"
        )

    if not message or not message.media:

        return HTMLResponse(
        content=stady_error_page(),
        status_code=404
        )

    file_size = int(row["size"])

    mime = resolve_media_mime(real_filename, row["mime"])

    range_header = request.headers.get(
        "range"
    )

    try:

        start, end = parse_range(
            range_header,
            file_size
        )

    except Exception:

        raise HTTPException(
            status_code=416,
            detail="Invalid range",
            headers={
                "Content-Range":
                    f"bytes */{file_size}"
            }
        )

    length = end - start + 1

    async def stream_generator():

        metric_inc("streams_started")
        file_semaphore = (
            await get_file_stream_semaphore(token)
        )

        global_acquired = False
        file_acquired = False

        try:
            try:
                await asyncio.wait_for(
                    global_stream_semaphore.acquire(),
                    timeout=STREAM_ACQUIRE_TIMEOUT
                )
                global_acquired = True

                await asyncio.wait_for(
                    file_semaphore.acquire(),
                    timeout=STREAM_ACQUIRE_TIMEOUT
                )
                file_acquired = True

            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Too many active streams. "
                        "Please try again shortly."
                    ),
                    headers={
                        "Retry-After": str(
                            STREAM_ACQUIRE_TIMEOUT
                        )
                    }
                )

            try:
                # IMPORTANT: stream directly from Telegram instead of waiting for a
                # complete 4 MB cache chunk. This lets browsers receive the first
                # bytes immediately and seek progressively with HTTP Range.
                async for chunk in telegram_stream(
                    message=message, offset=start, length=length
                ):
                    yield chunk
                metric_inc("streams_completed")
            except asyncio.CancelledError:
                metric_inc("stream_disconnects")
                raise
            except Exception:
                metric_inc("streams_failed")
                raise

        finally:
            if file_acquired:
                file_semaphore.release()

            if global_acquired:
                global_stream_semaphore.release()

            await remove_file_stream_semaphore(token)
    content_disposition = (
        f'attachment; filename="{quote(real_filename)}"'
        if action == "download"
        else f'inline; filename="{quote(real_filename)}"'
    )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": content_disposition,
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }

    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return StreamingResponse(
        stream_generator(),
        status_code=(
            206
            if range_header
            else 200
        ),
        media_type=mime,
        headers=headers
    )
    
@app.get("/metrics")
async def metrics():
    with metrics_lock:
        snapshot = dict(server_metrics)
    snapshot["active_stream_slots"] = MAX_CONCURRENT_STREAMS - global_stream_semaphore._value
    snapshot["active_telegram_downloads"] = MAX_CONCURRENT_TELEGRAM_DOWNLOADS - telegram_download_semaphore._value
    snapshot["cache_active_chunks"] = len(cache_active_files)
    snapshot["cache_locks"] = len(cache_locks)
    snapshot["rate_limit_keys"] = len(request_rate_state)
    return snapshot


# ============================================================
# 12-HOUR AUTO CLEANUP
# ============================================================

async def cleanup_expired_files():

    while True:

        try:

            expired_files = []

            with db_connect() as db:

                with db.cursor() as cursor:

                    cursor.execute("""
                        SELECT
                            token,
                            bot_chat_id,
                            bot_message_id
                        FROM files
                        WHERE expires_at IS NOT NULL
                        AND expires_at <= NOW()
                    """)

                    expired_files = cursor.fetchall()

            for row in expired_files:

                token = row["token"]
                bot_chat_id = row["bot_chat_id"]
                bot_message_id = row["bot_message_id"]

                if bot_chat_id and bot_message_id:

                    try:

                        await bot.delete_messages(
                            int(bot_chat_id),
                            int(bot_message_id)
                        )

                    except Exception as error:

                        print(
                            "[CLEANUP] "
                            "Telegram message delete failed:",
                            error
                        )

                with db_connect() as db:

                    with db.cursor() as cursor:

                        cursor.execute("""
                            DELETE FROM files
                            WHERE token = %s
                        """, (
                            token,
                        ))

                    db.commit()

                remove_cache_token(token)

                print(
                    "[CLEANUP] Expired file removed:",
                    token
                )

        except Exception as error:

            print(
                "[CLEANUP] Error:",
                error
            )

        await asyncio.sleep(60)


# ============================================================
# MAIN
# ============================================================

async def main():

    global BOT_USERNAME

    init_database()

    print()

    print("=" * 65)

    print(
        "       TELEGRAM DIRECT PROXY — STADY-PROXY"
    )

    print("=" * 65)

    print(
        "\n[+] Connecting to Telegram..."
    )

    await bot.start(
        bot_token=BOT_TOKEN
    )

    me = await bot.get_me()

    BOT_USERNAME = (
        me.username
        if me.username
        else str(me.id)
    )

    print(
        "[+] Telegram connected"
    )

    print(
        f"[+] Bot: @{BOT_USERNAME}"
    )

    print(
        "[+] BOT MODE: "
        + ("ENABLED (RAMNAYCLOUD)" if BOT_MODE
           else "DISABLED (RENDER WEB/STREAM ONLY)")
    )

    print(
        "[+] Telegram updates: "
        + ("ENABLED" if BOT_MODE else "DISABLED")
    )

    print(
        f"[+] Public URL: {PUBLIC_URL}"
    )

    print(
        f"[+] Local URL: http://127.0.0.1:{PORT}"
    )

    print(
        "[+] Server ready"
    )

    print("=" * 65)

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        loop="asyncio",
        log_level="info"
    )

    server = uvicorn.Server(config)

    cleanup_task = None

    if BOT_MODE:
        cleanup_task = asyncio.create_task(
            cleanup_expired_files()
        )

    cache_cleanup_task = asyncio.create_task(
        cleanup_cache_loop()
    )

    try:

        await server.serve()

    finally:

        if cleanup_task is not None:
            cleanup_task.cancel()

            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

        cache_cleanup_task.cancel()

        try:
            await cache_cleanup_task
        except asyncio.CancelledError:
            pass

        print(
            "[+] Disconnecting Telegram..."
        )

        await bot.disconnect()


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\n[+] Server stopped."
)


# ============================================================
# SERVER SECURITY V3 INTEGRATION — APPEND ONLY
# ============================================================
# Shared PostgreSQL state lets the security bot enforce blocks and
# lockdown even when the two services run as separate processes.

SECURITY_V3_SERVER_ENABLED = os.getenv("SECURITY_V3_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
SECURITY_V3_SERVER_CACHE_TTL = max(2, float(os.getenv("SECURITY_V3_SERVER_CACHE_TTL", "5")))
SECURITY_V3_SERVER_MAX_STREAMS_PER_USER = max(1, int(os.getenv("SECURITY_V3_SERVER_MAX_STREAMS_PER_USER", "5")))
security_v3_server_state = {"lockdown": False, "lockdown_checked": 0.0}
security_v3_server_user_streams = {}
security_v3_server_lock = threading.Lock()


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
        # Fail open on control-plane DB errors so an accidental security DB outage
        # does not take down normal playback. Existing rate limits still apply.
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
    if parts and parts[0] and parts[0] not in {"health", "metrics", "share", "receive", "pair", "stady-proxy-404.png"}:
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


# Register V3 middleware additively after the original middleware function definitions.
try:
    app.middleware("http")(security_v3_server_middleware)
except Exception as error:
    print("[SECURITY V3] Middleware registration failed:", error)
