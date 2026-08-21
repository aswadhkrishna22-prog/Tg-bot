import asyncio
import html
import mimetypes
import os
import re
import sqlite3
import uuid
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

PUBLIC_URL = os.getenv(
    "PUBLIC_URL",
    "http://127.0.0.1:8000"
).strip().rstrip("/")

HOST = "0.0.0.0"
PORT = 8000

# Telegram chunk size.
CHUNK_SIZE = 512 * 1024

# ============================================================
# VALIDATE CONFIG
# ============================================================

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
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                token TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                size INTEGER NOT NULL,
                mime TEXT NOT NULL
            )
            """
        )
        db.commit()

def add_file(token, chat_id, message_id, filename, size, mime):
    with db_connect() as db:
        db.execute(
            """
            INSERT INTO files (token, chat_id, message_id, filename, size, mime)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (token, chat_id, message_id, filename, size, mime)
        )
        db.commit()

def get_file(token):
    with db_connect() as db:
        row = db.execute("SELECT * FROM files WHERE token = ?", (token,)).fetchone()
    return row

# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(title="Study Proxy")

# ============================================================
# TELEGRAM CLIENT
# ============================================================

bot = TelegramClient("proxybot", API_ID, API_HASH)

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
    if mime:
        return mime
    return "application/octet-stream"

def parse_range(range_header, file_size):
    # FIXED: Cleaned up the corrupted parse_range function
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
            end = int(end_text)
        else:
            end = file_size - 1
        return start, end
    else:
        end = int(end_text)
        if end == 0:
            return 0, 0
        start = file_size - end
        if start < 0:
            start = 0
        return start, file_size - 1

# ============================================================
# TELEGRAM DOWNLOAD GENERATOR
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
        return

# ============================================================
# TELEGRAM BOT HANDLER
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

        # IMPORTANT: We DO NOT download the Telegram file.
        add_file(token=token, chat_id=chat_id, message_id=message_id, filename=filename, size=size, mime=mime)

        encoded_filename = quote(filename, safe="")

        # User clicks this link to see the premium webpage
        stream_url = f"{PUBLIC_URL}/watch/{token}"
        
        # Raw download link
        download_url = f"{PUBLIC_URL}/{token}/{encoded_filename}?action=download"

        size_gb = size / 1024 / 1024 / 1024

        print()
        print("=" * 60)
        print("[+] Telegram file registered")
        print("[+] Filename:", filename)
        print(f"[+] Size: {size_gb:.2f} GB")
        print("[+] Token:", token)
        print("=" * 60)

        await event.reply(
            "✅ Study file ready!\n\n"
            f"🎬 {filename}\n"
            f"📦 Size: {size_gb:.2f} GB\n\n"
            f"▶️ Watch/Stream:\n"
            f"{stream_url}"
        )

    except Exception as error:
        print("[!] File registration error:", error)
        try:
            await event.reply(f"❌ Could not create stream link.\n\n{error}")
        except Exception:
            pass

# ============================================================
# START COMMAND
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_command(event):
    await event.reply(
        "👋 Study File Proxy\n\n"
        "Send me a video/file and I will create a premium browser streaming link!"
    )

# ============================================================
# HTML THEME (CYBERPUNK NEON)
# ============================================================

CYBERPUNK_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Rajdhani:wght@500;600;700&display=swap');
    
    * { box-sizing: border-box; }
    
    body {
        background-color: #05050a;
        background-image: 
            linear-gradient(rgba(0, 243, 255, 0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(0, 243, 255, 0.03) 1px, transparent 1px);
        background-size: 30px 30px;
        color: #00f3ff;
        font-family: 'Rajdhani', sans-serif;
        margin: 0;
        padding: 20px;
        display: flex;
        flex-direction: column;
        align-items: center;
        min-height: 100vh;
    }
    
    h1.logo {
        font-family: 'Orbitron', sans-serif;
        font-size: 32px;
        color: #00f3ff;
        text-shadow: 0 0 10px rgba(0, 243, 255, 0.6), 0 0 20px rgba(0, 243, 255, 0.4);
        margin: 20px 0 30px 0;
        text-transform: uppercase;
        letter-spacing: 3px;
        text-align: center;
    }
    
    .main-container {
        width: 100%;
        max-width: 450px;
        border: 2px solid #1a2b3c;
        border-radius: 15px;
        padding: 25px 20px;
        background: rgba(5, 10, 20, 0.85);
        box-shadow: 0 0 15px rgba(0, 243, 255, 0.1), inset 0 0 20px rgba(0, 243, 255, 0.05);
        position: relative;
    }
    
    /* Tech Corner Borders */
    .main-container::before, .main-container::after {
        content: '';
        position: absolute;
        width: 25px; height: 25px;
        border: 2px solid #00f3ff;
        box-shadow: 0 0 10px rgba(0,243,255,0.5);
    }
    .main-container::before { top: -2px; left: -2px; border-right: none; border-bottom: none; border-radius: 15px 0 0 0; }
    .main-container::after { bottom: -2px; right: -2px; border-left: none; border-top: none; border-radius: 0 0 15px 0; }

    .player-box {
        width: 100%;
        border: 2px solid #ff00ff;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 0 15px rgba(255, 0, 255, 0.3);
        margin-bottom: 25px;
        background: #000;
        position: relative;
    }
    
    video, audio {
        width: 100%;
        display: block;
        max-height: 250px;
        outline: none;
    }
    
    .btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        padding: 14px;
        margin-bottom: 15px;
        border-radius: 8px;
        text-decoration: none;
        font-family: 'Orbitron', sans-serif;
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
        transition: all 0.3s ease;
        cursor: pointer;
        background: rgba(0, 243, 255, 0.02);
    }
    
    .btn-magenta {
        border: 2px solid #ff00ff;
        color: #ff00ff;
        box-shadow: 0 0 10px rgba(255, 0, 255, 0.2), inset 0 0 10px rgba(255, 0, 255, 0.1);
    }
    .btn-magenta:hover { 
        background: rgba(255, 0, 255, 0.15); 
        box-shadow: 0 0 20px rgba(255, 0, 255, 0.6), inset 0 0 15px rgba(255, 0, 255, 0.4); 
    }

    .btn-cyan {
        border: 2px solid #00f3ff;
        color: #00f3ff;
        box-shadow: 0 0 10px rgba(0, 243, 255, 0.2), inset 0 0 10px rgba(0, 243, 255, 0.1);
    }
    .btn-cyan:hover { 
        background: rgba(0, 243, 255, 0.15); 
        box-shadow: 0 0 20px rgba(0, 243, 255, 0.6), inset 0 0 15px rgba(0, 243, 255, 0.4); 
    }

    .info-box {
        margin-top: 25px;
        padding: 18px;
        border: 1px solid rgba(0, 243, 255, 0.3);
        border-radius: 10px;
        background: rgba(0, 0, 0, 0.6);
        text-align: left;
        font-size: 16px;
        line-height: 1.8;
    }
    
    .info-row {
        display: flex;
        align-items: center;
        margin-bottom: 10px;
    }
    
    .info-icon { margin-right: 12px; font-size: 18px; width: 20px; text-align: center; }
    .info-label { color: #8899aa; margin-right: 8px; font-weight: 600; }
    .info-value { color: #ffffff; font-weight: 700; word-break: break-all; }
    
    .eq-bars {
        display: inline-flex;
        align-items: flex-end;
        height: 14px;
        margin-left: 10px;
        gap: 3px;
    }
    .eq-bar {
        width: 3px;
        background-color: #00f3ff;
        border-radius: 1px;
        animation: eq 1s ease-in-out infinite alternate;
        box-shadow: 0 0 5px #00f3ff;
    }
    @keyframes eq {
        0% { height: 4px; }
        100% { height: 14px; }
    }
</style>
"""

# ============================================================
# HOME
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home():
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>STUDY PROXY</title>
        {CYBERPUNK_CSS}
    </head>
    <body>
        <h1 class="logo">STUDY-PROXY</h1>
        <div class="main-container" style="text-align:center;">
            <h2 style="color:#ff00ff; font-family:'Orbitron', sans-serif;">🚀 SERVER ONLINE</h2>
            <p style="font-size: 18px; color: #fff;">Send files to the Telegram Bot to generate streaming links.</p>
            <div class="player-box" style="padding: 20px; font-weight: bold; background: rgba(0,243,255,0.05); border-color:#00f3ff; color: #00f3ff; font-family: 'Orbitron', sans-serif;">
                HIGH SPEED • SECURE • NO LOGS
            </div>
        </div>
    </body>
    </html>
    """

# ============================================================
# WATCH PAGE
# ============================================================

@app.get("/watch/{token}", response_class=HTMLResponse)
async def watch(token):
    row = get_file(token)
    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    filename = row["filename"]
    safe_name = html.escape(filename)
    encoded_filename = quote(filename, safe="")

    # Core URLS
    full_stream_url = f"{PUBLIC_URL}/{token}/{encoded_filename}?action=stream"
    full_download_url = f"{PUBLIC_URL}/{token}/{encoded_filename}?action=download"

    # Convert sizes
    file_size = int(row["size"])
    if file_size >= 1024 * 1024 * 1024:
        size_str = f"{file_size / (1024 * 1024 * 1024):.2f} GB"
    elif file_size >= 1024 * 1024:
        size_str = f"{file_size / (1024 * 1024):.2f} MB"
    else:
        size_str = f"{file_size / 1024:.2f} KB"

    mime = row["mime"]

    # Player HTML
    if mime.startswith("video/"):
        player = f"""
        <video controls playsinline preload="metadata">
            <source src="{full_stream_url}" type="{html.escape(mime)}">
            Your browser does not support this video format.
        </video>"""
    elif mime.startswith("audio/"):
        player = f"""
        <audio controls preload="metadata" style="margin-top: 10px; margin-bottom: 10px;">
            <source src="{full_stream_url}" type="{html.escape(mime)}">
            Your browser does not support this audio format.
        </audio>"""
    else:
        player = f"""
        <div style="padding: 30px; text-align: center; color: #ff00ff; font-family: 'Orbitron', sans-serif;">
            ⚠️ FILE CANNOT BE STREAMED<br><br><span style="font-size:14px; color:#fff;">Please use the download button below.</span>
        </div>"""

    # Android Intents for External Players
    # Removing http/https for scheme processing
    stream_no_scheme = full_stream_url.replace("https://", "").replace("http://", "")
    scheme = "https" if "https://" in full_stream_url else "http"

    mx_intent = f"intent://{stream_no_scheme}#Intent;scheme={scheme};package=com.mxtech.videoplayer.ad;type=video/*;end;"
    vlc_intent = f"intent://{stream_no_scheme}#Intent;scheme={scheme};package=org.videolan.vlc;type=video/*;end;"
    playit_intent = f"intent://{stream_no_scheme}#Intent;scheme={scheme};package=com.playit.videoplayer;type=video/*;end;"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{safe_name}</title>
        {CYBERPUNK_CSS}
    </head>
    <body>

        <h1 class="logo">STUDY-PROXY</h1>

        <div class="main-container">

            <!-- Video Player Box -->
            <div class="player-box">
                {player}
            </div>

            <!-- Download Button -->
            <a href="{full_download_url}" class="btn btn-cyan">
                <span style="margin-right:10px; font-size:18px;">☁️</span> DOWNLOAD FILE
            </a>

            <!-- MX Player Button -->
            <a href="{mx_intent}" class="btn btn-magenta">
                <span style="margin-right:10px; font-size:18px;">▶️</span> PLAY IN MX PLAYER
            </a>

            <!-- VLC Button -->
            <a href="{vlc_intent}" class="btn btn-magenta">
                <span style="margin-right:10px; font-size:18px;">▶️</span> PLAY IN VLC
            </a>

            <!-- PLAYit Button -->
            <a href="{playit_intent}" class="btn btn-magenta">
                <span style="margin-right:10px; font-size:18px;">▶️</span> PLAY IN PLAYit
            </a>

            <!-- File Info Box -->
            <div class="info-box">
                <div class="info-row">
                    <span class="info-icon">📄</span>
                    <span class="info-label">File Name:</span>
                    <span class="info-value">{safe_name}</span>
                </div>
                <div class="info-row">
                    <span class="info-icon">🗜️</span>
                    <span class="info-label">File Size:</span>
                    <span class="info-value">{size_gb}</span>
                    <div class="eq-bars">
                        <div class="eq-bar" style="animation-delay: 0.1s;"></div>
                        <div class="eq-bar" style="animation-delay: 0.3s;"></div>
                        <div class="eq-bar" style="animation-delay: 0.0s;"></div>
                        <div class="eq-bar" style="animation-delay: 0.4s;"></div>
                        <div class="eq-bar" style="animation-delay: 0.2s;"></div>
                    </div>
                </div>
                <div class="info-row">
                    <span class="info-icon">👤</span>
                    <span class="info-label">File Owner:</span>
                    <span class="info-value">Admin</span>
                </div>
            </div>

        </div>

    </body>
    </html>
    """

# ============================================================
# DIRECT TELEGRAM PROXY (DO NOT EDIT)
# ============================================================

@app.get("/{token}/{filename:path}")
async def direct_proxy(token: str, filename: str, request: Request, action: str = "stream"):
    row = get_file(token)
    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    real_filename = row["filename"]
    if filename != real_filename:
        raise HTTPException(status_code=404, detail="Filename mismatch")

    try:
        message = await bot.get_messages(row["chat_id"], ids=row["message_id"])
    except Exception as error:
        print("[!] Telegram message lookup failed:", error)
        raise HTTPException(status_code=500, detail="Could not access Telegram file")

    if not message or not message.media:
        raise HTTPException(status_code=404, detail="Telegram file no longer exists")

    file_size = int(row["size"])
    mime = row["mime"]

    if action.lower() == "download":
        async def download_generator():
            async for chunk in telegram_stream(message, offset=0, length=file_size):
                yield chunk

        headers = {
            "Content-Length": str(file_size),
            "Content-Disposition": f'attachment; filename="{quote(real_filename)}"',
            "Accept-Ranges": "bytes"
        }
        return StreamingResponse(download_generator(), status_code=200, media_type=mime, headers=headers)

    range_header = request.headers.get("range")
    try:
        start, end = parse_range(range_header, file_size)
    except Exception:
        return StreamingResponse(
            iter(()),
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"}
        )

    length = (end - start + 1)

    async def stream_generator():
        async for chunk in telegram_stream(message, offset=start, length=length):
            yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Disposition": f'inline; filename="{quote(real_filename)}"',
        "Cache-Control": "no-cache"
    }

    status_code = 206 if range_header else 200

    return StreamingResponse(
        stream_generator(),
        status_code=status_code,
        media_type=mime,
        headers=headers
    )

# ============================================================
# MAIN
# ============================================================

async def main():
    init_database()
    print()
    print("=" * 65)
    print("          TELEGRAM DIRECT PROXY SERVER (CYBERPUNK THEME)")
    print("=" * 65)

    print("\n[+] Connecting to Telegram...")
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    username = f"@{me.username}" if me.username else str(me.id)

    print(f"[+] Telegram connected\n[+] Bot: {username}")
    print(f"\n[+] Public URL:\n{PUBLIC_URL}")
    print(f"\n[+] Local URL:\nhttp://127.0.0.1:{PORT}")
    print("\n[+] Server ready")
    print("=" * 65)

    config = uvicorn.Config(app, host=HOST, port=PORT, loop="asyncio", log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        print("[+] Disconnecting Telegram...")
        await bot.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[+] Server stopped.")

