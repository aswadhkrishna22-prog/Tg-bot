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
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from telethon import TelegramClient, events, Button
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

cache_locks = {}
cache_locks_guard = asyncio.Lock()

# ============================================================
# FILE LIMITS / RATE LIMIT
# ============================================================

MAX_FILE_SIZE = 6 * 1024 * 1024 * 1024   # 6 GB

FILE_COOLDOWN = 10                        # 10 seconds

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

    connection = psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor
    )

    return connection


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

    mime, _ = mimetypes.guess_type(filename)

    return mime or "application/octet-stream"


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

async def telegram_stream(
    message,
    offset,
    length
):

    sent = 0

    try:

        async for chunk in bot.iter_download(
            message.media,
            offset=offset,
            limit=length,
            request_size=CHUNK_SIZE
        ):

            if not chunk:
                continue

            sent += len(chunk)

            yield chunk

            if sent >= length:
                break

    except asyncio.CancelledError:

        return

    except Exception as error:

        print(
            "[!] Telegram streaming error:",
            error
        )


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


def remove_cache_token(token):
    token_dir = CACHE_DIR / token

    if not token_dir.exists():
        return

    try:
        shutil.rmtree(
            token_dir,
            ignore_errors=True
        )
    except Exception as error:
        print(
            "[CACHE] Token cache cleanup failed:",
            error
        )


def cleanup_cache_sync():
    now = time.time()
    total_size = 0
    cache_files = []

    try:
        for path in CACHE_DIR.rglob("*"):
            if not path.is_file():
                continue

            try:
                stat = path.stat()
            except OSError:
                continue

            age = now - stat.st_mtime

            if age > CACHE_TTL:
                try:
                    path.unlink()
                except OSError:
                    pass
                continue

            if path.name.endswith(".cache"):
                total_size += stat.st_size
                cache_files.append(
                    (stat.st_mtime, stat.st_size, path)
                )

        if total_size > CACHE_MAX_SIZE:
            cache_files.sort(
                key=lambda item: item[0]
            )

            for _, size, path in cache_files:
                if total_size <= CACHE_MAX_SIZE:
                    break

                try:
                    path.unlink()
                    total_size -= size
                except OSError:
                    pass

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
        print(
            "[CACHE] Cleanup error:",
            error
        )


async def cleanup_cache_loop():
    while True:
        try:
            await asyncio.to_thread(
                cleanup_cache_sync
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(
                "[CACHE] Background cleanup error:",
                error
            )

        await asyncio.sleep(300)


async def download_cache_chunk(
    message,
    cache_file,
    chunk_start,
    chunk_length
):
    part_file = cache_file.with_suffix(
        ".cache.part"
    )

    sent = 0

    try:
        if part_file.exists():
            try:
                part_file.unlink()
            except OSError:
                pass

        with part_file.open(
            "wb"
        ) as output:

            async for chunk in telegram_stream(
                message,
                offset=chunk_start,
                length=chunk_length
            ):
                if not chunk:
                    continue

                remaining = (
                    chunk_length - sent
                )

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
                f"Cache chunk incomplete: "
                f"expected {chunk_length} bytes, "
                f"got {sent} bytes"
            )

        os.replace(
            part_file,
            cache_file
        )

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


async def ensure_cache_chunk(
    token,
    message,
    chunk_index,
    chunk_start,
    chunk_length
):
    cache_file = cache_path(
        token,
        chunk_index
    )

    try:
        stat = cache_file.stat()

        if (
            stat.st_size == chunk_length
            and time.time() - stat.st_mtime <= CACHE_TTL
        ):
            os.utime(
                cache_file,
                None
            )
            return cache_file

    except OSError:
        pass

    cache_key = (
        f"{token}:{chunk_index}"
    )

    lock = await get_cache_lock(
        cache_key
    )

    async with lock:
        try:
            stat = cache_file.stat()

            if (
                stat.st_size == chunk_length
                and time.time() - stat.st_mtime <= CACHE_TTL
            ):
                os.utime(
                    cache_file,
                    None
                )
                return cache_file

        except OSError:
            pass

        await download_cache_chunk(
            message,
            cache_file,
            chunk_start,
            chunk_length
        )

        await asyncio.to_thread(
            cleanup_cache_sync
        )

        return cache_file


async def cached_telegram_stream(
    token,
    message,
    file_size,
    offset,
    length
):
    end_position = offset + length

    first_chunk = (
        offset // CACHE_CHUNK_SIZE
    )

    last_chunk = (
        (end_position - 1)
        // CACHE_CHUNK_SIZE
    )

    for chunk_index in range(
        first_chunk,
        last_chunk + 1
    ):
        chunk_start = (
            chunk_index
            * CACHE_CHUNK_SIZE
        )

        chunk_end = min(
            chunk_start
            + CACHE_CHUNK_SIZE,
            file_size
        )

        chunk_length = (
            chunk_end - chunk_start
        )

        cache_file = await ensure_cache_chunk(
            token,
            message,
            chunk_index,
            chunk_start,
            chunk_length
        )

        requested_start = max(
            offset,
            chunk_start
        )

        requested_end = min(
            end_position,
            chunk_end
        )

        read_start = (
            requested_start - chunk_start
        )

        read_length = (
            requested_end - requested_start
        )

        if read_length <= 0:
            continue

        with cache_file.open(
            "rb"
        ) as cached_file:

            cached_file.seek(
                read_start
            )

            remaining = read_length

            while remaining > 0:
                piece = await asyncio.to_thread(
                    cached_file.read,
                    min(CHUNK_SIZE, remaining)
                )

                if not piece:
                    raise IOError(
                        "Temporary cache file ended unexpectedly"
                    )

                remaining -= len(piece)
                yield piece


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

    encoded_filename = quote(
        filename,
        safe=""
    )

    stream_url = (
        f"{PUBLIC_URL}/{token}/"
        f"{encoded_filename}?action=stream"
    )

    file_size = int(row["size"])

    if file_size >= 1024**3:

        size_str = (
            f"{file_size / 1024**3:.2f} GB"
        )

    elif file_size >= 1024**2:

        size_str = (
            f"{file_size / 1024**2:.2f} MB"
        )

    else:

        size_str = (
            f"{file_size / 1024:.2f} KB"
        )

    created = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    stream_no_scheme = (
        stream_url
        .replace("https://", "")
        .replace("http://", "")
    )

    scheme = (
        "https"
        if stream_url.startswith("https://")
        else "http"
    )

    return f"""<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0, maximum-scale=1.0"
>

<title>
STADY-PROXY | {safe_name}
</title>

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
alt="Video thumbnail"
>

<button
    class="play"
    aria-label="Play"
    onclick="stream()"
>
▶
</button>

</div>

<div class="actions">

<button
    class="btn"
    onclick="togglePlayers()"
>
⏵ Stream ⏵
</button>
<a
    class="btn"
    href="{stream_url}&action=download"
    download
    style="text-decoration:none;text-align:center;display:block;"
>
⬇ Download
</a>
<div
    class="players"
    id="players"
>
<button onclick="openPlayer('mx')">
MX Player
</button>

<button onclick="openPlayer('vlc')">
VLC Mobile
</button>

<button onclick="openPlayer('playit')">
PlayIt
</button>

<button onclick="openPlayer('splayer')">
SPlayer
</button>

<button onclick="openPlayer('jplayer')">
JPlayer
</button>

<button onclick="openPlayer('kmplayer')">
KMPlayer
</button>

<button onclick="openPlayer('hdplayer')">
HDPlayer
</button>

<button onclick="openPlayer('nplayer')">
nPlayer
</button>

</div>

</div>

<div class="info">

<div>
📄 <b>File Name:</b>
<span>{safe_name}</span>
</div>

<div>
☰ <b>File Size:</b>
<span>{size_str}</span>
</div>

<div>
👤 <b>File Owner:</b>
<span>STADY-PROXY</span>
</div>

<div>
◷ <b>Created Time:</b>
<span>{created}</span>
</div>

</div>

</section>

<div
    class="status"
    id="status"
>
STADY-PROXY • READY
</div>

<div style="
    text-align:center;
    margin-top:22px;
    padding-bottom:8px;
    font-size:14px;
    color:#888;
">
     Made with ♥ by
    <a
        href="https://www.instagram.com/2aswadhh_._kr"
        target="_blank"
        rel="noopener noreferrer"
        style="
            display:inline-flex;
            align-items:center;
            gap:6px;
            margin-left:4px;
            color:#ff2bd6;
            text-decoration:none;
            font-weight:700;
            text-shadow:
                0 0 5px rgba(255,43,214,.8),
                0 0 12px rgba(255,43,214,.55);
        "
    >
        <svg
            width="17"
            height="17"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            <rect
                x="3"
                y="3"
                width="18"
                height="18"
                rx="5"
                stroke="currentColor"
                stroke-width="2"
            />
            <circle
                cx="12"
                cy="12"
                r="4"
                stroke="currentColor"
                stroke-width="2"
            />
            <circle
                cx="17.5"
                cy="6.5"
                r="1"
                fill="currentColor"
            />
        </svg>
        aswadh_kr
    </a>
</div>

</main>

<script>

const STREAM_URL = {stream_url!r};

function setStatus(text) {{
    document.getElementById("status").textContent = text;
}}

function stream() {{

    const poster = document.querySelector(".poster");
    if (!poster) return;

    poster.innerHTML = `
        <video
            id="mainVideo"
            controls
            autoplay
            playsinline
            preload="metadata"
            style="
                width:100%;
                height:100%;
                display:block;
                object-fit:contain;
                background:#000;
                border-radius:18px;
            "
        >
            <source src="${{STREAM_URL}}" type="video/mp4">
            Your browser does not support video playback.
        </video>
    `;

    const video = document.getElementById("mainVideo");

    video.play().catch(() => {{
        video.controls = true;
    }});

    setStatus("STADY-PROXY • PLAYING ▶");
}}

function togglePlayers() {{

    const players =
        document.getElementById("players");

    players.style.display =
        players.style.display === "block"
        ? "none"
        : "block";
}}

function openPlayer(player) {{

    let intent = "";

    if (player === "mx") {{

        intent =
        "intent://" +
        "{stream_no_scheme}" +
        "#Intent;scheme={scheme};" +
        "package=com.mxtech.videoplayer.ad;" +
        "type=video/*;end;";
    }}

    else if (player === "vlc") {{

        intent =
        "intent://" +
        "{stream_no_scheme}" +
        "#Intent;scheme={scheme};" +
        "package=org.videolan.vlc;" +
        "type=video/*;end;";
    }}

    else if (player === "playit") {{

        intent =
        "intent://" +
        "{stream_no_scheme}" +
        "#Intent;scheme={scheme};" +
        "package=com.playit.videoplayer;" +
        "type=video/*;end;";
    }}

    else if (player === "kmplayer") {{

        intent =
        "intent://" +
        "{stream_no_scheme}" +
        "#Intent;scheme={scheme};" +
        "package=com.kmplayer;" +
        "type=video/*;end;";
    }}

    if (intent) {{
        location.href = intent;
    }}

    else {{
        location.href = STREAM_URL;
    }}
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

    mime = row["mime"]

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

        async for chunk in cached_telegram_stream(
            token=token,
            message=message,
            file_size=file_size,
            offset=start,
            length=length
        ):

            yield chunk
    content_disposition = (
        f'attachment; filename="{quote(real_filename)}"'
        if action == "download"
        else f'inline; filename="{quote(real_filename)}"'
    )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Disposition": content_disposition,
        "Cache-Control": "no-cache"
    }
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
