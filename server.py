import asyncio
import html
import mimetypes
import os
import re
import sqlite3
import uuid
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

PUBLIC_URL = os.getenv(
    "PUBLIC_URL",
    "http://127.0.0.1:8000"
).strip().rstrip("/")

HOST = "0.0.0.0"
PORT = 8000

CHUNK_SIZE = 512 * 1024

BOT_USERNAME = ""

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

        add_file(token=token, chat_id=chat_id, message_id=message_id, filename=filename, size=size, mime=mime)
        encoded_filename = quote(filename, safe="")
        stream_url = f"{PUBLIC_URL}/watch/{token}"
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

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_command(event):
    await event.reply(
        "👋 STADY-PROXY\n\n"
        "Send me a video/file and I will create a premium browser streaming link!"
    )

# ============================================================
# STADY-PROXY HTML THEME
# ============================================================

STADY_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&family=Poppins:wght@400;500;600&display=swap');

*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;font-family:Poppins,Arial,sans-serif;background:#030914;color:#eaf7ff}}
body{{
  overflow-x:hidden;
  background:
    radial-gradient(circle at 15% 20%,rgba(0,238,255,.16),transparent 28%),
    radial-gradient(circle at 85% 65%,rgba(255,0,213,.16),transparent 30%),
    linear-gradient(180deg,#020812,#061629 55%,#020812);
}}
body:before{{
  content:"";position:fixed;inset:0;pointer-events:none;opacity:.32;
  background-image:linear-gradient(rgba(0,255,255,.08) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(0,255,255,.05) 1px,transparent 1px);
  background-size:34px 34px;
  mask-image:linear-gradient(to bottom,transparent,#000 12%,#000 85%,transparent);
}}
.page{{width:min(720px,100%);margin:auto;padding:22px 14px 45px}}
.brand{{
  text-align:center;font-family:Orbitron,sans-serif;font-size:clamp(28px,7vw,46px);
  font-weight:800;letter-spacing:2px;margin:8px 0 20px;
  color:#69f7ff;text-shadow:0 0 8px #00eaff,0 0 22px #7c28ff,0 0 40px #ff18d5;
}}
.frame{{
  position:relative;padding:12px;border:2px solid #42eaff;border-radius:15px;
  background:linear-gradient(145deg,rgba(12,43,72,.9),rgba(4,13,28,.94));
  box-shadow:0 0 10px #00eaff, inset 0 0 20px rgba(0,234,255,.15),0 0 30px rgba(255,0,213,.2);
}}
.frame:before,.frame:after{{
  content:"";position:absolute;height:5px;width:90px;top:-5px;
  background:linear-gradient(90deg,#00eaff,#bdfcff,#ff24d7);
  box-shadow:0 0 12px #00eaff;border-radius:4px
}}
.frame:before{{left:35px}}.frame:after{{right:35px}}
.poster{{
  position:relative;overflow:hidden;border:2px solid #36f3ff;border-radius:8px;
  aspect-ratio:16/9;background:#0a2039;
  box-shadow:inset 0 0 22px rgba(0,255,255,.35),0 0 14px rgba(0,234,255,.45);
}}
.poster img{{width:100%;height:100%;display:block;object-fit:cover}}
.play{{
  position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
  width:118px;height:82px;border:2px solid #9afcff;border-radius:16px;
  background:rgba(75,90,112,.58);backdrop-filter:blur(5px);
  color:#dffcff;font-size:44px;line-height:78px;text-align:center;
  text-shadow:0 0 10px #00eaff;box-shadow:0 0 18px rgba(0,238,255,.35);
  cursor:pointer;
}}
.actions{{display:grid;gap:14px;margin:18px 0}}
.btn{{
  appearance:none;border:2px solid #38f5ff;border-radius:10px;padding:15px 12px;
  width:100%;font:500 clamp(17px,4.6vw,25px) Poppins,sans-serif;color:#eaffff;
  cursor:pointer;background:linear-gradient(180deg,rgba(17,72,103,.95),rgba(10,33,62,.98));
  box-shadow:0 0 9px rgba(0,238,255,.75),inset 0 0 16px rgba(0,238,255,.12),0 5px 0 rgba(255,0,204,.35);
  transition:.18s transform,.18s filter;
}}
.btn:hover{{filter:brightness(1.25);transform:translateY(-2px)}}
.btn:active{{transform:translateY(1px)}}
.icon{{margin:0 7px}}
.players{{
  display:none;border-radius:0 0 18px 18px;background:#101b28;
  margin-top:-14px;padding:22px 12px 18px;text-align:center;
  box-shadow:0 8px 18px rgba(0,0,0,.35);font-size:18px
}}
.players button{{
  display:block;width:100%;border:0;background:none;color:#f0f5ff;
  font:inherit;padding:8px;cursor:pointer
}}
.players button:hover{{color:#56efff}}
.info{{
  margin-top:14px;padding:16px 4px 8px;font-size:16px;line-height:2;
  color:#e7f4ff
}}
.info div{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.info b{{font-weight:500}}
.status{{font-size:13px;color:#8edfff;text-align:center;margin-top:8px;opacity:.8}}
@media(max-width:480px){{
  .page{{padding-left:9px;padding-right:9px}}
  .frame{{padding:9px}}
  .play{{width:95px;height:68px;line-height:64px;font-size:34px}}
  .info{{font-size:14px}}
}}
</style>
"""

# ============================================================
# WEB ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
        <title>STADY-PROXY</title>
        {STADY_CSS}
    </head>
    <body>
        <main class="page">
            <div class="brand">STADY-PROXY</div>
            <div class="status" style="font-size: 20px; margin-top: 50px;">SERVER ONLINE 🚀</div>
        </main>
    </body>
    </html>
    """

@app.get("/watch/{token}", response_class=HTMLResponse)
async def watch(token):
    row = get_file(token)
    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    filename = row["filename"]
    safe_name = html.escape(filename)
    encoded_filename = quote(filename, safe="")

    # Generates exact URLs based on DB
    full_stream_url = f"{PUBLIC_URL}/{token}/{encoded_filename}?action=stream"
    full_download_url = f"{PUBLIC_URL}/{token}/{encoded_filename}?action=download"

    # Convert size format matching your UI
    file_size = int(row["size"])
    if file_size >= 1024 * 1024 * 1024:
        size_str = f"{file_size / (1024 * 1024 * 1024):.2f} GB"
    elif file_size >= 1024 * 1024:
        size_str = f"{file_size / (1024 * 1024):.2f} MB"
    else:
        size_str = f"{file_size / 1024:.2f} KB"

    # Current Live Date mapping
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Android Intents config
    stream_no_scheme = full_stream_url.replace("https://", "").replace("http://", "")
    scheme = "https" if "https://" in full_stream_url else "http"

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>STADY-PROXY | {safe_name}</title>
{STADY_CSS}
</head>
<body>
<main class="page">
  <div class="brand">STADY-PROXY</div>

  <section class="frame">
    <div class="poster">
      <img id="poster" src="https://images.unsplash.com/photo-1511497584788-876760111969?auto=format&fit=crop&w=1200&q=85" alt="Video thumbnail">
      <button class="play" aria-label="Play" onclick="stream()">▶</button>
    </div>

    <div class="actions">
      <button class="btn" onclick="downloadFile()">☁️ Download ☁️</button>
      <button class="btn" onclick="togglePlayers()">⏵ Stream ⏵</button>

      <div class="players" id="players">
        <button onclick="openPlayer('mx')">MX Player</button>
        <button onclick="openPlayer('vlc')">VLC Mobile</button>
        <button onclick="openPlayer('playit')">PlayIt</button>
        <button onclick="openPlayer('splayer')">SPlayer</button>
        <button onclick="openPlayer('jplayer')">JPlayer</button>
        <button onclick="openPlayer('kmplayer')">KMPlayer</button>
        <button onclick="openPlayer('hdplayer')">HDPlayer</button>
        <button onclick="openPlayer('nplayer')">nPlayer</button>
      </div>

      <button class="btn" onclick="telegramDownload()">✈️ Telegram Download ✈️</button>
    </div>

    <div class="info">
      <div>📄 <b>File Name:</b> <span id="fileName">{safe_name}</span></div>
      <div>☰ <b>File Size:</b> <span id="fileSize">{size_str}</span></div>
      <div>👤 <b>File Owner:</b> <span id="owner">Admin</span></div>
      <div>◷ <b>Created Time:</b> <span id="created">{current_time}</span></div>
    </div>
  </section>

  <div class="status" id="status">STADY-PROXY • READY</div>
</main>

<script>
const CONFIG = {{
  downloadUrl: "{full_download_url}",
  streamUrl: "{full_stream_url}",
  telegramUrl: "https://t.me/{BOT_USERNAME}" 
}};

function setStatus(text){{document.getElementById('status').textContent=text}}

function downloadFile(){{
  if(!CONFIG.downloadUrl){{setStatus("Download URL not configured");return}}
  location.href=CONFIG.downloadUrl
}}
function telegramDownload(){{
  if(!CONFIG.telegramUrl){{setStatus("Telegram URL not configured");return}}
  location.href=CONFIG.telegramUrl
}}
function stream(){{
  if(!CONFIG.streamUrl){{setStatus("Stream URL not configured");togglePlayers();return}}
  location.href=CONFIG.streamUrl
}}
function togglePlayers(){{
  const p=document.getElementById('players')
  p.style.display=p.style.display==="block"?"none":"block"
}}
function openPlayer(player){{
  if(!CONFIG.streamUrl){{setStatus(player.toUpperCase()+" selected • Stream URL not configured");return}}
  
  const streamNoScheme = "{stream_no_scheme}";
  const scheme = "{scheme}";
  let intentUrl = CONFIG.streamUrl;
  
  if(player === 'mx') intentUrl = "intent://" + streamNoScheme + "#Intent;scheme=" + scheme + ";package=com.mxtech.videoplayer.ad;type=video/*;end;";
  else if(player === 'vlc') intentUrl = "intent://" + streamNoScheme + "#Intent;scheme=" + scheme + ";package=org.videolan.vlc;type=video/*;end;";
  else if(player === 'playit') intentUrl = "intent://" + streamNoScheme + "#Intent;scheme=" + scheme + ";package=com.playit.videoplayer;type=video/*;end;";
  else if(player === 'splayer') intentUrl = "intent://" + streamNoScheme + "#Intent;scheme=" + scheme + ";package=com.kmplayer;type=video/*;end;";
  else if(player === 'kmplayer') intentUrl = "intent://" + streamNoScheme + "#Intent;scheme=" + scheme + ";package=com.kmplayer;type=video/*;end;";
  else if(player === 'nplayer') intentUrl = "intent://" + streamNoScheme + "#Intent;scheme=" + scheme + ";package=com.newin.nplayer.pro;type=video/*;end;";
  
  location.href = intentUrl;
}}
</script>
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
    global BOT_USERNAME
    init_database()
    print()
    print("=" * 65)
    print("          TELEGRAM DIRECT PROXY SERVER (STADY-PROXY THEME)")
    print("=" * 65)

    print("\n[+] Connecting to Telegram...")
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    BOT_USERNAME = me.username if me.username else str(me.id)

    print(f"[+] Telegram connected\n[+] Bot: @{BOT_USERNAME}")
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
