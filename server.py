import asyncio
import html
import os
import re
import uuid
import time
import shutil
import threading
import psutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request as URLRequest, urlopen
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from telethon import TelegramClient, events, Button, errors
import uvicorn

# ============================================================
# MODULAR CONFIG / PURE HELPERS
# ============================================================

from config import (
    API_ID, API_HASH, BOT_TOKEN, SECURITY_BOT_TOKEN, BOT_MODE,
    SECURITY_OWNER_ID, PUBLIC_URL, HOST, PORT, CHUNK_SIZE,
    CACHE_CHUNK_SIZE, CACHE_TTL, CACHE_MAX_SIZE, CACHE_DIR,
    CACHE_PER_FILE_MAX_SIZE, CACHE_MIN_FREE_SPACE, CACHE_CLEANUP_INTERVAL,
    MAX_CONCURRENT_STREAMS, MAX_CONCURRENT_PER_FILE, STREAM_ACQUIRE_TIMEOUT,
    MAX_CONCURRENT_TELEGRAM_DOWNLOADS, TELEGRAM_FLOODWAIT_CAP,
    MAX_FILE_SIZE, FILE_COOLDOWN, STREAM_IDLE_TIMEOUT, REQUEST_RATE_LIMIT,
    PREFETCH_ENABLED,
    PREFETCH_MAX_TASKS, DB_CONNECT_TIMEOUT, DB_KEEPALIVES_IDLE,
    DB_KEEPALIVES_INTERVAL, DB_KEEPALIVES_COUNT, BASE_DIR, DATABASE_URL,
    ERROR_PAGE, ERROR_IMAGE, RAIN_OVERLAY, RAIN_OVERLAY_WEBM,
    SECURITY_V3_SERVER_ENABLED, SECURITY_V3_SERVER_CACHE_TTL,
    SECURITY_V3_SERVER_MAX_STREAMS_PER_USER,
)

from utils import (
    clean_filename, get_mime, get_stream_mime, detect_media_profile,
    parse_range, format_uptime, usage_bar,
)

from database import (
    set_metric_callback,
    db_connect, init_database, add_file, save_bot_message_id,
    create_share_token, create_pair_code,
    record_file_access, record_bytes_served, get_file,
)

from telegram_service import (
    configure as configure_telegram_service,
    wait_for_telegram_cooldown, set_telegram_cooldown, telegram_stream,
)

from cache import (
    configure as configure_cache, cache_locks, cache_locks_guard,
    cache_active_files, cleanup_cache_sync, cached_telegram_stream,
    launch_prefetch, remove_cache_token,
)

from sharing import router as sharing_router, configure as configure_sharing
from pairing import router as pairing_router, configure as configure_pairing, cleanup_pair_attempts
from pages import render_error_page, render_home_page, render_watch_page

from cleanup import (
    configure as configure_cleanup,
    cleanup_cache_loop, cleanup_expired_files,
)

# Compatibility alias used by existing non-page error responses.
stady_error_page = render_error_page

# ============================================================
# STREAM CONCURRENCY PROTECTION
# ============================================================

from stream_control import (
    global_stream_semaphore,
    file_stream_semaphores,
    file_stream_semaphores_guard,
    get_file_stream_semaphore,
    remove_file_stream_semaphore,
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


# ============================================================
# FILE LIMITS / RATE LIMIT
# ============================================================

MAX_FILE_SIZE = 6 * 1024 * 1024 * 1024   # 6 GB

FILE_COOLDOWN = 10                        # 10 seconds

# Per-user upload cooldown state. Kept at module scope because receive_file()
# uses it to prevent rapid repeated uploads from the same Telegram user.
user_file_cooldowns = {}

# Runtime bot username, populated after Telegram connection in main().
BOT_USERNAME = ""

# Runtime observability and request-rate limiting are provided by observability.py.

from observability import (
    metric_inc,
    get_metrics_snapshot,
    request_rate_middleware,
    request_rate_state,
    request_rate_lock,
    cleanup_request_rate_state,
)

app = FastAPI(title="Adolf-StreamX")
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

configure_telegram_service(
    bot=bot,
    telegram_download_semaphore=telegram_download_semaphore,
    telegram_cooldown_lock=telegram_cooldown_lock,
    chunk_size=CHUNK_SIZE,
    telegram_floodwait_cap=TELEGRAM_FLOODWAIT_CAP,
    stream_idle_timeout=STREAM_IDLE_TIMEOUT,
    metric_inc=metric_inc,
)

BOT_START_TIME = time.time()
LAST_ERROR = "None"
# ============================================================
# CUSTOM Adolf-StreamX ERROR PAGE
# ============================================================

@app.get("/stady-proxy-rain-overlay-v2.webm")
async def stady_proxy_rain_overlay_webm():
    if not RAIN_OVERLAY_WEBM.is_file():
        raise HTTPException(status_code=404, detail="Rain overlay WebM asset not found")
    return FileResponse(RAIN_OVERLAY_WEBM, media_type="video/webm", headers={"Cache-Control":"public, max-age=31536000, immutable", "Accept-Ranges":"bytes"})


@app.get("/stady-proxy-rain-overlay-v2.mp4")
async def stady_proxy_rain_overlay():
    if not RAIN_OVERLAY.is_file():
        raise HTTPException(status_code=404, detail="Rain overlay asset not found")
    return FileResponse(RAIN_OVERLAY, media_type="video/mp4", headers={"Cache-Control":"public, max-age=31536000, immutable", "Accept-Ranges":"bytes"})


@app.get("/adolf-streamx-404.png")
async def stady_proxy_404_image():
    return FileResponse(
        ERROR_IMAGE,
        media_type="image/png"
    )





from owner import configure as configure_owner, get_owner_display

configure_owner(bot=bot, db_connect=db_connect)

# ============================================================
# SERVER STATS
# ============================================================

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
            "        ⚡ Adolf-StreamX\n"
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
# PURE HELPERS
# ============================================================
# Implemented in utils.py; imported above to preserve the existing API.

# ============================================================
# TELEGRAM STREAM
# ============================================================







# ============================================================
# BACKGROUND CLEANUP
# ============================================================
# Implemented in cleanup.py; imported above to preserve the existing API.


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
        sender = await event.get_sender()
        owner_name = " ".join(part for part in [getattr(sender, "first_name", "") or "", getattr(sender, "last_name", "") or ""] if part).strip()
        owner_username = getattr(sender, "username", "") or ""
        if not owner_name:
            owner_name = f"@{owner_username}" if owner_username else "Telegram User"

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
            mime,
            owner_name,
            owner_username
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
            "✅ <b>Adolf-StreamX FILE READY!</b>\n\n"
            f"🎬 <b>{html.escape(filename)}</b>\n"
            f"📦 Size: "
            f"<code>{size_gb:.2f} GB</code>\n\n"
            f"📺 <b>TV PAIRING CODE:</b> <code>{pair_code}</code>\n\n"
            "On your TV, open Adolf-StreamX and enter this 6-digit code.\n\n"
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

    # Deep-link from the Adolf-StreamX 404 page.
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
                    ON CONFLICT (user_id) DO UPDATE SET
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        username = EXCLUDED.username
                    RETURNING user_id, (xmax = 0) AS inserted
                    """,
                    (
                        int(user.id),
                        user.first_name or "",
                        user.last_name or "",
                        user.username or ""
                    )
                )

                user_row = cursor.fetchone()
                is_new_user = bool(user_row and user_row.get("inserted"))

    except Exception as error:
        print(f"User tracking failed: {error}")

    if is_new_user:
        await notify_new_user(user)

    await event.reply(

        "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
        "        ⚡ Adolf-StreamX\n"
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
# Adolf-StreamX THEME
# IMPORTANT:
# CSS uses SINGLE braces because this string is not an f-string.
# ============================================================

STADY_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

*{box-sizing:border-box}
html,body{margin:0;min-height:100%;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#05070d;color:#eef2ff}
body{overflow-x:hidden;background:
 radial-gradient(circle at 8% 8%,rgba(124,58,237,.13),transparent 30%),
 radial-gradient(circle at 92% 42%,rgba(6,182,212,.09),transparent 28%),
 linear-gradient(180deg,#05070d 0%,#070a12 52%,#04060b 100%)}
body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.16;background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(to bottom,black,transparent 78%)}
.page{width:min(1120px,calc(100% - 32px));margin:0 auto;padding:24px 0 44px;position:relative;z-index:1}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:8px 2px 22px;border-bottom:1px solid rgba(148,163,184,.10)}
.brand-wrap{display:flex;align-items:center;gap:12px;min-width:0}
.logo-mark{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(135deg,#7c3aed,#2563eb);box-shadow:0 10px 35px rgba(99,102,241,.24);font-size:21px;font-weight:800;color:#fff}
.brand-name{font-size:21px;font-weight:800;letter-spacing:.4px;white-space:nowrap}.brand-name span{color:#22d3ee}.brand-sub{margin-top:3px;color:#7f8ba3;font-size:12px}
.top-actions{display:flex;align-items:center;gap:9px}.online{display:inline-flex;align-items:center;gap:8px;padding:10px 14px;border:1px solid rgba(34,197,94,.13);border-radius:999px;background:rgba(15,23,42,.58);color:#a7f3d0;font-size:12px;font-weight:700}.online i{width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 12px rgba(34,197,94,.75)}
.top-btn,.menu-btn{border:1px solid rgba(124,58,237,.62);background:rgba(10,14,25,.78);color:#f5f7ff;border-radius:11px;padding:10px 14px;font:600 13px Inter;cursor:pointer;text-decoration:none;transition:.18s}.top-btn:hover,.menu-btn:hover{transform:translateY(-1px);border-color:#8b5cf6;background:rgba(20,16,39,.95)}.menu-btn{width:40px;padding:10px 0;border-color:rgba(148,163,184,.18);font-size:18px}
.hero{text-align:center;padding:44px 12px 30px}.hero h1{margin:0;font-size:clamp(32px,5vw,52px);line-height:1.08;letter-spacing:-1.8px;font-weight:800;background:linear-gradient(90deg,#a855f7 0%,#60a5fa 48%,#22d3ee 100%);-webkit-background-clip:text;background-clip:text;color:transparent}.hero p{margin:12px auto 0;color:#94a3b8;font-size:16px;max-width:620px}
.frame{border:1px solid rgba(99,102,241,.18);background:linear-gradient(180deg,rgba(10,14,25,.86),rgba(7,10,18,.94));border-radius:22px;overflow:hidden;box-shadow:0 22px 70px rgba(0,0,0,.34)}
.player-wrap{padding:12px}.poster{position:relative;width:100%;aspect-ratio:16/9;min-height:260px;overflow:hidden;border-radius:16px;background:#03050a center/cover no-repeat url('https://images.unsplash.com/photo-1500534623283-312aade485b7?auto=format&fit=crop&w=1600&q=85');border:1px solid rgba(148,163,184,.12)}.poster:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(2,5,12,.12),rgba(2,5,12,.54))}.poster-content{position:absolute;inset:0;z-index:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px}.poster-icon{width:82px;height:82px;border-radius:50%;display:grid;place-items:center;background:rgba(3,7,18,.78);border:2px solid transparent;background-image:linear-gradient(#07101c,#07101c),linear-gradient(135deg,#a855f7,#22d3ee);background-origin:border-box;background-clip:padding-box,border-box;box-shadow:0 0 45px rgba(34,211,238,.16),0 0 35px rgba(168,85,247,.16);font-size:31px;color:#fff}.poster-title{margin-top:16px;font-size:18px;font-weight:700}.poster-sub{margin-top:7px;color:#c0cadb;font-size:13px;max-width:430px;line-height:1.5}.poster-codec,.profile-badge{display:inline-flex;align-items:center;gap:7px;margin-top:12px;padding:7px 11px;border:1px solid rgba(148,163,184,.18);border-radius:999px;background:rgba(2,6,16,.58);color:#cbd5e1;font-size:12px}.profile-row{text-align:center;padding:0 12px 10px}.profile-badge{color:#a5f3fc;border-color:rgba(34,211,238,.18)}
.video-shell{position:relative;width:100%;height:100%;background:#000;border-radius:16px;overflow:hidden}.video-shell video{width:100%;height:100%;display:block;object-fit:contain;background:#000;border:0;outline:0}.video-controls{position:absolute;left:10px;right:10px;bottom:10px;z-index:10;padding:8px 10px 7px;border-radius:13px;background:linear-gradient(180deg,transparent,rgba(0,0,0,.9) 34%);opacity:1;transition:opacity .2s}.video-controls.hide{opacity:0;pointer-events:none}.video-seek{width:100%;height:5px;margin:0 0 6px;accent-color:#8b5cf6;cursor:pointer}.control-row{display:flex;align-items:center;gap:8px;color:#fff}.control-row button{border:0;background:transparent;color:#fff;font-size:20px;padding:3px 7px;cursor:pointer}.video-time{font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}.control-spacer{flex:1}.video-error{display:none;position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(88%,420px);padding:16px;border-radius:14px;background:rgba(0,0,0,.9);color:#fff;text-align:center;font-size:14px;line-height:1.5;z-index:12}
.action-panel{padding:4px 20px 20px}.primary-actions{display:grid;grid-template-columns:1fr 1fr;gap:14px}.btn{border:1px solid rgba(148,163,184,.15);border-radius:15px;min-height:74px;padding:13px 16px;background:rgba(15,23,42,.72);color:#f8fafc;text-decoration:none;font:600 17px Inter;cursor:pointer;transition:.18s;box-shadow:inset 0 1px rgba(255,255,255,.025)}.btn small{display:block;margin-top:5px;color:#94a3b8;font-size:12px;font-weight:500}.btn.stream-btn{border-color:rgba(168,85,247,.7);background:linear-gradient(135deg,rgba(76,29,149,.22),rgba(15,23,42,.72))}.btn.download-btn{border-color:rgba(34,211,238,.72);background:linear-gradient(135deg,rgba(8,145,178,.13),rgba(15,23,42,.72))}.btn:hover{transform:translateY(-2px);box-shadow:0 14px 30px rgba(0,0,0,.24)}.secondary-actions{display:flex;gap:10px;margin-top:10px}.secondary-actions .btn{min-height:46px;font-size:13px;padding:10px 14px;flex:1}.disabled{opacity:.45;cursor:not-allowed}
.players{display:none;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:10px;padding:10px;border:1px solid rgba(148,163,184,.10);border-radius:14px;background:rgba(2,6,16,.55)}.players button{border:1px solid rgba(148,163,184,.14);background:#0b1120;color:#dbe5f5;border-radius:10px;padding:10px 7px;font:600 12px Inter;cursor:pointer}.players button:hover{border-color:#7c3aed;background:#11162a}
.info{margin:0 20px 20px;border:1px solid rgba(148,163,184,.12);border-radius:16px;overflow:hidden;background:rgba(8,12,22,.64)}.info-head{display:flex;align-items:center;gap:10px;padding:17px 20px;border-bottom:1px solid rgba(148,163,184,.10);color:#b9c5da;font-size:13px;font-weight:700;letter-spacing:.4px;text-transform:uppercase}.info-head .ico{color:#a855f7;font-size:18px}.info-row{display:grid;grid-template-columns:190px 1fr;gap:20px;padding:16px 20px;border-bottom:1px solid rgba(148,163,184,.07);font-size:14px}.info-row:last-child{border-bottom:0}.info-label{color:#8290a8}.info-value{color:#cbd5e1;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.verified{color:#c4b5fd;font-weight:700}
.features{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:18px}.feature{padding:17px;border:1px solid rgba(148,163,184,.11);border-radius:14px;background:rgba(8,12,22,.64)}.feature-icon{font-size:22px;margin-bottom:12px}.feature strong{display:block;font-size:13px}.feature span{display:block;margin-top:5px;color:#77849b;font-size:11px;line-height:1.4}
.status{text-align:center;color:#7c8ba3;font-size:12px;margin:18px 0}.footer{text-align:center;color:#68758c;font-size:12px;padding-top:10px}.footer .brand-footer{color:#a78bfa;font-weight:700}.footer a{color:#ec4899;text-decoration:none;font-weight:700}
@media(max-width:760px){.page{width:min(100% - 18px,1120px);padding-top:12px}.topbar{padding-bottom:16px}.brand-name{font-size:18px}.brand-sub{font-size:11px}.online{display:none}.hero{padding:28px 8px 22px}.hero h1{font-size:34px;letter-spacing:-1.2px}.hero p{font-size:14px}.frame{border-radius:18px}.player-wrap{padding:9px}.poster{min-height:210px;border-radius:13px}.action-panel{padding:3px 12px 14px}.primary-actions{gap:9px}.btn{min-height:67px;font-size:15px;padding:11px}.secondary-actions{gap:8px}.players{grid-template-columns:repeat(2,1fr)}.info{margin:0 12px 14px}.info-row{grid-template-columns:110px 1fr;padding:14px 14px;font-size:13px}.features{grid-template-columns:repeat(2,1fr);gap:8px;margin:12px}.feature{padding:13px}.feature-icon{margin-bottom:8px}.feature strong{font-size:12px}.feature span{font-size:10px}}
@media(max-width:430px){.top-btn{display:none}.logo-mark{width:38px;height:38px}.brand-name{font-size:17px}.hero h1{font-size:30px}.poster-icon{width:68px;height:68px;font-size:26px}.primary-actions{grid-template-columns:1fr}.secondary-actions{display:grid;grid-template-columns:1fr 1fr}.info-row{grid-template-columns:1fr;gap:5px}.info-value{text-align:left;white-space:normal;word-break:break-word}.features{grid-template-columns:1fr 1fr}}
"""

# ============================================================
# HOME
# ============================================================



# ============================================================
# WATCH PAGE
# ============================================================

# ============================================================
# DEVICE SHARING / TV PAIRING ROUTES
# ============================================================

configure_sharing(STADY_CSS, stady_error_page)
configure_pairing(STADY_CSS, stady_error_page, metric_inc)

configure_cleanup(
    cleanup_cache_sync=cleanup_cache_sync,
    cache_locks=cache_locks,
    cache_locks_guard=cache_locks_guard,
    file_stream_semaphores=file_stream_semaphores,
    file_stream_semaphores_guard=file_stream_semaphores_guard,
    max_concurrent_per_file=MAX_CONCURRENT_PER_FILE,
    cache_cleanup_interval=CACHE_CLEANUP_INTERVAL,
    cleanup_request_rate_state=cleanup_request_rate_state,
    cleanup_pair_attempts=cleanup_pair_attempts,
    db_connect=db_connect,
    remove_cache_token=remove_cache_token,
    bot=bot,
)
@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=render_home_page(STADY_CSS))


@app.get("/watch/{token}", response_class=HTMLResponse)
async def watch(token):
    row = get_file(token)
    if not row:
        return HTMLResponse(
            content=render_error_page(),
            status_code=404,
            headers={"Cache-Control": "no-store"}
        )
    return HTMLResponse(
        content=await render_watch_page(
            token, row, PUBLIC_URL, STADY_CSS,
            get_owner_display, create_share_token, get_stream_mime, render_error_page,
        )
    )


app.include_router(sharing_router)
app.include_router(pairing_router)










# ============================================================
# TV PAIRING
# ============================================================








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

    # Use the real filename extension for media responses. Telegram can store
    # an incorrect generic MIME (for example application/zip for an .mp4).
    mime = get_stream_mime(real_filename, row["mime"])

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
                # Stream the requested byte range directly from Telegram.
                # This avoids putting the playback path behind the temporary
                # chunk-cache layer, which can interfere with progressive
                # playback/seek behavior in browsers and external players.
                stream_action = "download" if action == "download" else "stream"
                await asyncio.to_thread(record_file_access, token, stream_action)
                sent_bytes = 0
                async for chunk in telegram_stream(
                    message=message, offset=start, length=length
                ):
                    sent_bytes += len(chunk)
                    yield chunk
                await asyncio.to_thread(record_bytes_served, token, sent_bytes)
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
    snapshot = get_metrics_snapshot()
    snapshot["active_stream_slots"] = MAX_CONCURRENT_STREAMS - global_stream_semaphore._value
    snapshot["active_telegram_downloads"] = MAX_CONCURRENT_TELEGRAM_DOWNLOADS - telegram_download_semaphore._value
    snapshot["cache_active_chunks"] = len(cache_active_files)
    snapshot["cache_locks"] = len(cache_locks)
    snapshot["rate_limit_keys"] = len(request_rate_state)
    snapshot["active_viewers"] = snapshot["active_stream_slots"]
    try:
        disk = shutil.disk_usage(CACHE_DIR)
        snapshot["disk_free_gb"] = round(disk.free / 1024**3, 2)
        snapshot["disk_used_gb"] = round(disk.used / 1024**3, 2)
    except OSError:
        pass
    return snapshot


# ============================================================
# 12-HOUR AUTO CLEANUP
# ============================================================
# Implemented in cleanup.py; imported above to preserve the existing API.


# ============================================================
# SERVER SECURITY V3 INTEGRATION
# ============================================================
from security import (
    configure as configure_security_v3,
    security_v3_server_middleware,
)

configure_security_v3(
    metric_inc,
    SECURITY_V3_SERVER_ENABLED,
    SECURITY_V3_SERVER_CACHE_TTL,
    SECURITY_V3_SERVER_MAX_STREAMS_PER_USER,
)

# Register V3 middleware additively after the original middleware function definitions.
try:
    app.middleware("http")(security_v3_server_middleware)
except Exception as error:
    print("[SECURITY V3] Middleware registration failed:", error)


# ============================================================
# MAIN
# ============================================================

async def main():

    global BOT_USERNAME

    init_database()

    print()

    print("=" * 65)

    print(
        "       TELEGRAM DIRECT PROXY — Adolf-StreamX"
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


