import asyncio
import html
import mimetypes
import os
import re
import sqlite3
import uuid
import time
import psutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from telethon import TelegramClient, events
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

PUBLIC_URL = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").strip().rstrip("/")
HOST = "0.0.0.0"
PORT = 8000
CHUNK_SIZE = 512 * 1024

BOT_USERNAME = ""

if API_ID <= 0:
    raise RuntimeError("TG_API_ID is missing or invalid")
if not API_HASH:
    raise RuntimeError("TG_API_HASH is missing")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

# ============================================================
# DATABASE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "files.db"

def db_connect():
    connection = sqlite3.connect(DATABASE, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection

def init_database():
    with db_connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                token TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                size INTEGER NOT NULL,
                mime TEXT NOT NULL
            )
        """)
        db.commit()

def add_file(token, chat_id, message_id, filename, size, mime):
    with db_connect() as db:
        db.execute("""
            INSERT INTO files
            (token, chat_id, message_id, filename, size, mime)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (token, chat_id, message_id, filename, size, mime))
        db.commit()

def get_file(token):
    with db_connect() as db:
        return db.execute(
            "SELECT * FROM files WHERE token = ?", (token,)
        ).fetchone()

# ============================================================
# FASTAPI / TELEGRAM
# ============================================================

app = FastAPI(title="STADY-PROXY")
bot = TelegramClient("proxybot", API_ID, API_HASH)

BOT_START_TIME = time.time()
LAST_ERROR = "None"

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
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        storage_items = []

        try:
            for item in BASE_DIR.iterdir():
                try:
                    if item.is_file():
                        item_size = item.stat().st_size
                    elif item.is_dir():
                        item_size = 0
                        for f in item.rglob("*"):
                            try:
                                if f.is_file():
                                    item_size += f.stat().st_size
                            except (PermissionError, OSError):
                                continue
                    else:
                        continue

                    storage_items.append((item_size, item.name))

                except (PermissionError, OSError):
                    continue

            storage_items.sort(key=lambda x: x[0], reverse=True)
            storage_items = storage_items[:8]

        except Exception:
            storage_items = []

        if storage_items:
            storage_text = "\n".join(
                f"📁 {html.escape(name)}: "
                f"<code>{size / 1024**3:.2f} GB</code>"
                for size, name in storage_items
            )
        else:
            storage_text = "Unable to read storage breakdown."

        bot_uptime = format_uptime(
            time.time() - BOT_START_TIME
        )

        system_uptime = format_uptime(
            time.time() - psutil.boot_time()
        )

        db_status = "✅ ONLINE"

        try:
            with db_connect() as db:
                db.execute("SELECT 1").fetchone()
        except Exception as error:
            db_status = f"❌ ERROR: {html.escape(str(error))}"

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
                result = db.execute(
                    "SELECT COUNT(*) AS total FROM files"
                ).fetchone()
                total_files = int(result["total"])
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

            f"⏱️ BOT UPTIME: <code>{bot_uptime}</code>\n"
            f"🖥️ SYS UPTIME: <code>{system_uptime}</code>\n\n"

            f"⚙️ CPU: {usage_bar(cpu)} "
            f"<code>{cpu:.1f}%</code>\n\n"

            f"🧠 RAM: {usage_bar(ram.percent)} "
            f"<code>{ram.percent:.1f}%</code>\n"
            f"RAM In Use: <code>{ram.used / 1024**3:.2f} GB</code>\n"
            f"RAM Total: <code>{ram.total / 1024**3:.2f} GB</code>\n"
            f"RAM Free: <code>{ram.available / 1024**3:.2f} GB</code>\n\n"

            f"💾 DISK: {usage_bar(disk.percent)} "
            f"<code>{disk.percent:.1f}%</code>\n"
            f"Drive In Use: <code>{disk.used / 1024**3:.2f} GB</code>\n"
            f"Drive Total: <code>{disk.total / 1024**3:.2f} GB</code>\n"
            f"Drive Free: <code>{disk.free / 1024**3:.2f} GB</code>\n\n"

            "📂 <b>STORAGE BREAKDOWN</b>\n"
            f"{storage_text}\n\n"

            f"📦 REGISTERED FILES: <code>{total_files}</code>\n\n"

            "🛠️ LAST ERROR:\n"
            f"<code>{html.escape(str(LAST_ERROR))}</code>\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━\n"
            '❤️ Made with '
            '<a href="https://www.instagram.com/2aswadhh_._kr">'
            'aswadh_kr'
            "</a>"
        )

        await event.reply(
            message,
            parse_mode="html"
        )

    except Exception as error:
        print("[] Stats command error:", error)

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
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
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
        raise ValueError("Multiple ranges not supported")

    start_text, end_text = value.split("-", 1)

    if start_text:
        start = int(start_text)
        if start >= file_size:
            raise ValueError("Range outside file")

        if end_text:
            end = min(int(end_text), file_size - 1)
        else:
            end = file_size - 1

        if start > end:
            raise ValueError("Invalid range")

        return start, end

    end = int(end_text)
    if end <= 0:
        raise ValueError("Invalid suffix range")

    start = max(file_size - end, 0)
    return start, file_size - 1

# ============================================================
# TELEGRAM STREAM
# ============================================================

async def telegram_stream(message, offset, length):
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
        print("[!] Telegram streaming error:", error)

# ============================================================
# TELEGRAM BOT HANDLERS
# ============================================================

@bot.on(events.NewMessage)
async def receive_file(event):
    if not event.file:
        return

    try:
        filename = event.file.name

        if not filename:
            mime = event.file.mime_type or "application/octet-stream"

            if mime.startswith("video/"):
                filename = "video.mp4"
            elif mime.startswith("audio/"):
                filename = "audio.mp3"
            else:
                filename = "telegram_file"

        filename = clean_filename(filename)
        size = int(event.file.size or 0)
        mime = event.file.mime_type or get_mime(filename)

        token = uuid.uuid4().hex
        chat_id = int(event.chat_id)
        message_id = int(event.id)

        add_file(
            token,
            chat_id,
            message_id,
            filename,
            size,
            mime
        )

        stream_url = f"{PUBLIC_URL}/watch/{token}"

        size_gb = size / 1024 / 1024 / 1024

        print("\n" + "=" * 60)
        print("[+] Telegram file registered")
        print("[+] Filename:", filename)
        print(f"[+] Size: {size_gb:.2f} GB")
        print("[+] Token:", token)
        print("=" * 60)

        from telethon import Button

        buttons = [
            [
                Button.url(
                    "▶️ WATCH / STREAM",
                    stream_url
                )
            ]
        ]

        await event.reply(
            "✅ <b>STADY-PROXY FILE READY!</b>\n\n"
            f"🎬 <b>{html.escape(filename)}</b>\n"
            f"📦 Size: <code>{size_gb:.2f} GB</code>\n\n"
            "Choose an option below:",
            buttons=buttons,
            parse_mode="html"
        )

    except Exception as error:
        print("[!] File registration error:", error)

        try:
            await event.reply(
                "❌ <b>Could not create file link.</b>\n\n"
                f"<code>{html.escape(str(error))}</code>",
                parse_mode="html"
            )
        except Exception:
            pass

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_command(event):
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

        '❤️ Made with <a href="https://www.instagram.com/2aswadhh_._kr">aswadh_kr</a>',
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
}"""

# (file continues unchanged)
