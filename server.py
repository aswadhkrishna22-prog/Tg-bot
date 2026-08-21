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
# 512 KiB is a safe Telethon request size.
CHUNK_SIZE = 512 * 1024


# ============================================================
# VALIDATE CONFIG
# ============================================================

if API_ID <= 0:
    raise RuntimeError(
        "TG_API_ID is missing or invalid"
    )

if not API_HASH:
    raise RuntimeError(
        "TG_API_HASH is missing"
    )

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing"
    )


# ============================================================
# DATABASE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "files.db"


def db_connect():
    connection = sqlite3.connect(
        DATABASE,
        timeout=30
    )

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


def add_file(
    token,
    chat_id,
    message_id,
    filename,
    size,
    mime
):

    with db_connect() as db:

        db.execute(
            """
            INSERT INTO files
            (
                token,
                chat_id,
                message_id,
                filename,
                size,
                mime
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                chat_id,
                message_id,
                filename,
                size,
                mime
            )
        )

        db.commit()


def get_file(token):

    with db_connect() as db:

        row = db.execute(
            """
            SELECT *
            FROM files
            WHERE token = ?
            """,
            (token,)
        ).fetchone()

    return row


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Telegram Study Proxy"
)


# ============================================================
# TELEGRAM CLIENT
# ============================================================

bot = TelegramClient(
    "proxybot",
    API_ID,
    API_HASH
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

    mime, _ = mimetypes.guess_type(
        filename
    )

    if mime:
        return mime

    return "application/octet-stream"


def parse_range(
    range_header,
    file_size
):

    if not range_header:
        return 0, file_size - 1

    if not range_header.startswith("bytes="):
        raise ValueError("Invalid range")

    value = range_header[6:]

    # We only serve one range.
    if "," in value:
        raise ValueError("Multiple ranges not supported")

    start_text, end_text = value.split(
        "-",
        1
    )

    # bytes=500-
    if start_text:

        start = int(start_text)

        if start >= file_size:
            raise ValueError("Range outside file")

        if end_text:
            end = int(end_text)
        else:
            end = file_size - 1

            # IMPORTANT:
        # We DO NOT download the Telegram file.
        add_file(
            token=token,
            chat_id=chat_id,
            message_id=message_id,
            filename=filename,
            size=size,
            mime=mime
        )

        encoded_filename = quote(
            filename,
            safe=""
        )

        # 👇 IVIDE AANU MAATTAM VARUTHIYATHU 👇
        stream_url = f"{PUBLIC_URL}/watch/{token}"

        download_url = (
            f"{PUBLIC_URL}/"
            f"{token}/"
            f"{encoded_filename}"
            f"?action=download"
        )
        # 👆 MAATTAM KAZHINJU 👆

        size_gb = (
            size / 1024 / 1024 / 1024
        )

        print()
        print("=" * 60)
        print("[+] Telegram file registered")


# ============================================================
# TELEGRAM DOWNLOAD GENERATOR
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

        # Browser stopped playback / changed seek position.
        return

    except Exception as error:

        print(
            "[!] Telegram streaming error:",
            error
        )

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

        filename = clean_filename(
            filename
        )

        size = int(
            event.file.size or 0
        )

        mime = (
            event.file.mime_type
            or get_mime(filename)
        )

        token = uuid.uuid4().hex

        chat_id = int(
            event.chat_id
        )

        message_id = int(
            event.id
        )

        # IMPORTANT:
        # We DO NOT download the Telegram file.
        add_file(
            token=token,
            chat_id=chat_id,
            message_id=message_id,
            filename=filename,
            size=size,
            mime=mime
        )

        encoded_filename = quote(
            filename,
            safe=""
        )

        stream_url = (
            f"{PUBLIC_URL}/"
            f"{token}/"
            f"{encoded_filename}"
            f"?action=stream"
        )

        download_url = (
            f"{PUBLIC_URL}/"
            f"{token}/"
            f"{encoded_filename}"
            f"?action=download"
        )

        size_gb = (
            size / 1024 / 1024 / 1024
        )

        print()
        print("=" * 60)
        print("[+] Telegram file registered")
        print("[+] Filename:", filename)
        print(
            "[+] Size:",
            f"{size_gb:.2f} GB"
        )
        print("[+] Token:", token)
        print("[+] NO local download")
        print("=" * 60)

        await event.reply(
            "✅ Study file ready!\n\n"
            f"🎬 {filename}\n"
            f"📦 Size: {size_gb:.2f} GB\n\n"
            f"▶️ Stream:\n"
            f"{stream_url}\n\n"
            f"⬇️ Download:\n"
            f"{download_url}"
        )

    except Exception as error:

        print(
            "[!] File registration error:",
            error
        )

        try:

            await event.reply(
                "❌ Could not create stream link.\n\n"
                f"{error}"
            )

        except Exception:
            pass


# ============================================================
# START COMMAND
# ============================================================

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_command(event):

    await event.reply(
        "👋 Study File Proxy\n\n"
        "Send me a video/file and I will "
        "create a browser streaming link."
    )


# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
async def home():

    return """
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Study Proxy</title>

<style>

body {
    background: #101010;
    color: white;
    font-family: Arial;
    text-align: center;
    padding: 40px 20px;
}

.box {
    max-width: 600px;
    margin: auto;
    background: #1b1b1b;
    padding: 30px;
    border-radius: 15px;
}

</style>

</head>

<body>

<div class="box">

<h1>📚 Study File Proxy</h1>

<p>
Files are streamed directly from Telegram.
</p>

<p>
No permanent video copy is stored on Termux.
</p>

</div>

</body>

</html>
"""


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

        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    filename = row["filename"]

    safe_name = html.escape(
        filename
    )

    encoded_filename = quote(
        filename,
        safe=""
    )

    stream_url = (
        f"/{token}/"
        f"{encoded_filename}"
        f"?action=stream"
    )

    download_url = (
        f"/{token}/"
        f"{encoded_filename}"
        f"?action=download"
    )

    mime = row["mime"]

    if mime.startswith("video/"):

        player = f"""
        <video
            controls
            playsinline
            preload="metadata"
        >

            <source
                src="{stream_url}"
                type="{html.escape(mime)}"
            >

            Your browser does not support
            this video format.

        </video>
        """

    elif mime.startswith("audio/"):

        player = f"""
        <audio
            controls
            preload="metadata"
        >

            <source
                src="{stream_url}"
                type="{html.escape(mime)}"
            >

            Your browser does not support
            this audio format.

        </audio>
        """

    else:

        player = """
        <p>
            This file cannot be played
            directly in the browser.
        </p>
        """

    return f"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>{safe_name}</title>

<style>

body {{
    background: #101010;
    color: white;
    font-family: Arial;
    padding: 15px;
}}

.container {{
    max-width: 1000px;
    margin: auto;
}}

.filename {{
    word-break: break-word;
}}

video {{
    width: 100%;
    max-height: 80vh;
    background: black;
    border-radius: 12px;
}}

audio {{
    width: 100%;
}}

a {{
    display: inline-block;
    margin-top: 18px;
    margin-right: 8px;
    padding: 12px 18px;
    border-radius: 9px;
    color: white;
    text-decoration: none;
    background: #2196f3;
}}

</style>

</head>

<body>

<div class="container">

<h2 class="filename">
{safe_name}
</h2>

{player}

<a href="{download_url}">
⬇️ Download
</a>

</div>

</body>

</html>
"""


# ============================================================
# DIRECT TELEGRAM PROXY
# ============================================================

@app.get(
    "/{token}/{filename:path}"
)
async def direct_proxy(
    token: str,
    filename: str,
    request: Request,
    action: str = "stream"
):

    row = get_file(token)

    if not row:

        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    real_filename = row["filename"]

    # --------------------------------------------------------
    # Filename validation
    # --------------------------------------------------------

    if filename != real_filename:

        raise HTTPException(
            status_code=404,
            detail="Filename mismatch"
        )

    # --------------------------------------------------------
    # Get original Telegram message
    # --------------------------------------------------------

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

        raise HTTPException(
            status_code=404,
            detail="Telegram file no longer exists"
        )

    file_size = int(
        row["size"]
    )

    mime = row["mime"]

    # --------------------------------------------------------
    # DOWNLOAD
    # --------------------------------------------------------

    if action.lower() == "download":

        async def download_generator():

            async for chunk in telegram_stream(
                message,
                offset=0,
                length=file_size
            ):

                yield chunk

        headers = {
            "Content-Length":
                str(file_size),

            "Content-Disposition":
                f'attachment; filename="{quote(real_filename)}"',

            "Accept-Ranges":
                "bytes"
        }

        return StreamingResponse(
            download_generator(),
            status_code=200,
            media_type=mime,
            headers=headers
        )

    # --------------------------------------------------------
    # STREAM
    # --------------------------------------------------------

    range_header = request.headers.get(
        "range"
    )

    try:

        start, end = parse_range(
            range_header,
            file_size
        )

    except Exception:

        return StreamingResponse(
            iter(()),
            status_code=416,
            headers={
                "Content-Range":
                    f"bytes */{file_size}"
            }
        )

    length = (
        end - start + 1
    )

    async def stream_generator():

        async for chunk in telegram_stream(
            message,
            offset=start,
            length=length
        ):

            yield chunk

    headers = {
        "Accept-Ranges":
            "bytes",

        "Content-Length":
            str(length),

        "Content-Range":
            f"bytes {start}-{end}/{file_size}",

        "Content-Disposition":
            f'inline; filename="{quote(real_filename)}"',

        "Cache-Control":
            "no-cache"
    }

    if range_header:

        status_code = 206

    else:

        status_code = 200

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
    print("          TELEGRAM DIRECT PROXY SERVER")
    print("=" * 65)

    print()
    print("[+] Connecting to Telegram...")

    await bot.start(
        bot_token=BOT_TOKEN
    )

    me = await bot.get_me()

    username = (
        f"@{me.username}"
        if me.username
        else str(me.id)
    )

    print()
    print("[+] Telegram connected")
    print("[+] Bot:", username)

    print()
    print("[+] Public URL:")
    print(PUBLIC_URL)

    print()
    print("[+] Local URL:")
    print(
        f"http://127.0.0.1:{PORT}"
    )

    print()
    print("[+] Storage mode:")
    print(
        "Telegram storage → proxy → browser"
    )

    print()
    print("[+] No permanent video downloads")
    print("[+] Server ready")
    print("=" * 65)
    print()

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        loop="asyncio",
        log_level="info"
    )

    server = uvicorn.Server(
        config
    )

    try:

        await server.serve()

    finally:

        print(
            "[+] Disconnecting Telegram..."
        )

        await bot.disconnect()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print("[+] Server stopped.")
