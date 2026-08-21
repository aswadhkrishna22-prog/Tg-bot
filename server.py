import asyncio
import html
import mimetypes
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
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

PUBLIC_URL = (
    os.getenv(
        "PUBLIC_URL",
        "http://127.0.0.1:8000"
    )
    .strip()
    .rstrip("/")
)

HOST = "0.0.0.0"
PORT = 8000

CHUNK_SIZE = 512 * 1024

# ============================================================
# LINK EXPIRY
# ============================================================

LINK_TTL_HOURS = 12

BOT_USERNAME = ""

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

        # ----------------------------------------------------
        # Create table if it does not exist
        # ----------------------------------------------------

        db.execute("""
        CREATE TABLE IF NOT EXISTS files (

            token TEXT PRIMARY KEY,

            chat_id INTEGER NOT NULL,

            message_id INTEGER NOT NULL,

            filename TEXT NOT NULL,

            size INTEGER NOT NULL,

            mime TEXT NOT NULL,

            expires_at TEXT,

            reply_chat_id INTEGER,

            reply_message_id INTEGER

        )
        """)

        # ----------------------------------------------------
        # Migration for an OLD files.db
        # ----------------------------------------------------

        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(files)"
            ).fetchall()
        }

        # expires_at
        if "expires_at" not in columns:

            db.execute(
                "ALTER TABLE files ADD COLUMN expires_at TEXT"
            )

            # Existing old records are given a 12-hour
            # expiry from the migration time.
            migration_expiry = (
                datetime.now(timezone.utc)
                + timedelta(hours=LINK_TTL_HOURS)
            ).isoformat()

            db.execute(
                """
                UPDATE files
                SET expires_at = ?
                WHERE expires_at IS NULL
                """,
                (migration_expiry,)
            )

        # reply_chat_id
        if "reply_chat_id" not in columns:

            db.execute(
                """
                ALTER TABLE files
                ADD COLUMN reply_chat_id INTEGER
                """
            )

        # reply_message_id
        if "reply_message_id" not in columns:

            db.execute(
                """
                ALTER TABLE files
                ADD COLUMN reply_message_id INTEGER
                """
            )

        db.commit()


def add_file(
    token,
    chat_id,
    message_id,
    filename,
    size,
    mime,
    expires_at
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
                mime,
                expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                chat_id,
                message_id,
                filename,
                size,
                mime,
                expires_at
            )
        )

        db.commit()


def set_reply_message(
    token,
    chat_id,
    message_id
):

    with db_connect() as db:

        db.execute(
            """
            UPDATE files

            SET
                reply_chat_id = ?,
                reply_message_id = ?

            WHERE token = ?
            """,
            (
                chat_id,
                message_id,
                token
            )
        )

        db.commit()


def get_file(token):

    with db_connect() as db:

        return db.execute(
            """
            SELECT *
            FROM files
            WHERE token = ?
            """,
            (token,)
        ).fetchone()


def delete_file_record(token):

    with db_connect() as db:

        db.execute(
            """
            DELETE FROM files
            WHERE token = ?
            """,
            (token,)
        )

        db.commit()


def get_expired_files():

    with db_connect() as db:

        return db.execute(
            """
            SELECT *
            FROM files
            WHERE expires_at IS NOT NULL
            """
        ).fetchall()


def parse_expiry(value):

    try:

        expiry = datetime.fromisoformat(value)

        if expiry.tzinfo is None:

            expiry = expiry.replace(
                tzinfo=timezone.utc
            )

        return expiry

    except Exception:

        return None


def is_expired(row):

    expiry = parse_expiry(
        row["expires_at"]
    )

    if expiry is None:

        return True

    return (
        datetime.now(timezone.utc)
        >= expiry
    )


# ============================================================
# FASTAPI / TELEGRAM
# ============================================================

app = FastAPI(
    title="STADY-PROXY"
)

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

    return (
        mime
        or "application/octet-stream"
    )


def parse_range(
    range_header,
    file_size
):

    if not range_header:

        return (
            0,
            file_size - 1
        )

    if not range_header.startswith(
        "bytes="
    ):

        raise ValueError(
            "Invalid range"
        )

    value = range_header[6:]

    if "," in value:

        raise ValueError(
            "Multiple ranges not supported"
        )

    start_text, end_text = value.split(
        "-",
        1
    )

    # --------------------------------------------------------
    # bytes=START-END
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # bytes=-SUFFIX
    # --------------------------------------------------------

    end = int(end_text)

    if end <= 0:

        raise ValueError(
            "Invalid suffix range"
        )

    start = max(
        file_size - end,
        0
    )

    return (
        start,
        file_size - 1
    )


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
# DELETE EXPIRED FILE
# ============================================================

async def expire_file_later(
    token,
    expires_at
):

    delay = (
        expires_at
        - datetime.now(timezone.utc)
    ).total_seconds()

    if delay > 0:

        await asyncio.sleep(delay)

    row = get_file(token)

    if not row:
        return

    # --------------------------------------------------------
    # Double check expiry
    # --------------------------------------------------------

    if not is_expired(row):
        return

    # --------------------------------------------------------
    # DELETE ONLY BOT GENERATED REPLY
    # --------------------------------------------------------

    try:

        reply_chat_id = row[
            "reply_chat_id"
        ]

        reply_message_id = row[
            "reply_message_id"
        ]

        if (
            reply_chat_id
            and
            reply_message_id
        ):

            await bot.delete_messages(

                reply_chat_id,

                reply_message_id

            )

            print(
                "[+] Bot reply deleted:",
                token
            )

    except Exception as error:

        print(
            "[!] Could not delete bot reply:",
            error
        )

    # --------------------------------------------------------
    # DELETE DATABASE RECORD
    # --------------------------------------------------------

    delete_file_record(token)

    print(
        "[+] 12-hour link expired:",
        token
    )


# ============================================================
# CLEANUP EXPIRED FILES AFTER RESTART
# ============================================================

async def cleanup_expired_files():

    print(
        "[+] Checking expired files..."
    )

    rows = get_expired_files()

    now = datetime.now(
        timezone.utc
    )

    for row in rows:

        expiry = parse_expiry(
            row["expires_at"]
        )

        if not expiry:
            continue

        if now < expiry:
            continue

        token = row["token"]

        # ----------------------------------------------------
        # Delete bot reply
        # ----------------------------------------------------

        try:

            if (
                row["reply_chat_id"]
                and
                row["reply_message_id"]
            ):

                await bot.delete_messages(

                    row["reply_chat_id"],

                    row["reply_message_id"]

                )

                print(
                    "[+] Deleted old bot reply:",
                    token
                )

        except Exception as error:

            print(
                "[!] Old message deletion failed:",
                error
            )

        # ----------------------------------------------------
        # Remove database record
        # ----------------------------------------------------

        delete_file_record(
            token
        )

        print(
            "[+] Removed expired record:",
            token
        )


async def expiry_cleanup_loop():

    while True:

        try:

            await cleanup_expired_files()

        except Exception as error:

            print(
                "[!] Cleanup error:",
                error
            )

        # Check every 5 minutes

        await asyncio.sleep(
            300
        )


# ============================================================
# TELEGRAM BOT HANDLER
# ============================================================

@bot.on(events.NewMessage)
async def receive_file(event):

    if not event.file:
        return

    try:

        # ----------------------------------------------------
        # Filename
        # ----------------------------------------------------

        filename = event.file.name

        if not filename:

            mime = (
                event.file.mime_type
                or "application/octet-stream"
            )

            if mime.startswith(
                "video/"
            ):

                filename = "video.mp4"

            elif mime.startswith(
                "audio/"
            ):

                filename = "audio.mp3"

            else:

                filename = "telegram_file"

        filename = clean_filename(
            filename
        )

        # ----------------------------------------------------
        # File information
        # ----------------------------------------------------

        size = int(
            event.file.size or 0
        )

        mime = (
            event.file.mime_type
            or get_mime(filename)
        )

        # ----------------------------------------------------
        # Telegram source
        # ----------------------------------------------------

        token = uuid.uuid4().hex

        chat_id = int(
            event.chat_id
        )

        message_id = int(
            event.id
        )

        # ----------------------------------------------------
        # EXACT 12 HOUR EXPIRY
        # ----------------------------------------------------

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(
                hours=LINK_TTL_HOURS
            )
        )

        # ----------------------------------------------------
        # Save database record
        # ----------------------------------------------------

        add_file(

            token,

            chat_id,

            message_id,

            filename,

            size,

            mime,

            expires_at.isoformat()

        )

        # ----------------------------------------------------
        # URLs
        # ----------------------------------------------------

        stream_url = (
            f"{PUBLIC_URL}/watch/{token}"
        )

        download_url = (
            f"{PUBLIC_URL}/"
            f"{token}/"
            f"{quote(filename, safe='')}"
            f"?action=download"
        )

        size_gb = (
            size
            / 1024
            / 1024
            / 1024
        )

        # ----------------------------------------------------
        # LOG
        # ----------------------------------------------------

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
            "[+] Expires:",
            expires_at.isoformat()
        )

        print(
            "[+] Stream URL:",
            stream_url
        )

        print(
            "[+] Download URL:",
            download_url
        )

        print(
            "=" * 60
        )

        # ----------------------------------------------------
        # BUTTONS
        # ----------------------------------------------------

        buttons = [

            [
                Button.url(
                    "⚡ FAST DOWNLOAD 💥",
                    download_url
                )
            ],

            [
                Button.url(
                    "▶️ WATCH / STREAM",
                    stream_url
                )
            ]

        ]

        # ----------------------------------------------------
        # BOT REPLY
        # ----------------------------------------------------

        reply = await event.reply(

            "✅ STADY-PROXY file ready!\n\n"

            f"🎬 {filename}\n"

            f"📦 Size: {size_gb:.2f} GB\n\n"

            "⏳ This file will be deleted "
            "in 12 hours.\n"

            "🔗 This link will expire "
            "in 12 hours.\n\n"

            "👇 Choose an option:",

            buttons=buttons

        )

        # ----------------------------------------------------
        # Save generated reply message ID
        # ----------------------------------------------------

        set_reply_message(

            token,

            int(reply.chat_id),

            int(reply.id)

        )

        # ----------------------------------------------------
        # Schedule deletion
        # ----------------------------------------------------

        asyncio.create_task(

            expire_file_later(

                token,

                expires_at

            )

        )

    except Exception as error:

        print(
            "[!] File registration error:",
            error
        )

        try:

            await event.reply(

                "❌ Could not create "
                "stream link.\n\n"
                f"{error}"

            )

        except Exception:

            pass


# ============================================================
# /start
# ============================================================

@bot.on(
    events.NewMessage(
        pattern=r"^/start$"
    )
)
async def start_command(event):

    await event.reply(

        "👋 STADY-PROXY\n\n"

        "Send me a video/file and "
        "I will create a browser "
        "streaming link."

    )


# ============================================================
# STADY-PROXY CSS
# ============================================================

STADY_CSS = """
@import url(
'https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&family=Poppins:wght@400;500;600&display=swap'
);

*{
    box-sizing:border-box;
}

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
        radial-gradient(
            circle at 15% 20%,
            rgba(0,238,255,.16),
            transparent 28%
        ),

        radial-gradient(
            circle at 85% 65%,
            rgba(255,0,213,.16),
            transparent 30%
        ),

        linear-gradient(
            180deg,
            #020812,
            #061629 55%,
            #020812
        );
}

body:before{
    content:"";
    position:fixed;
    inset:0;
    pointer-events:none;
    opacity:.32;

    background-image:
        linear-gradient(
            rgba(0,255,255,.08)
            1px,
            transparent 1px
        ),

        linear-gradient(
            90deg,
            rgba(0,255,255,.05)
            1px,
            transparent 1px
        );

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

    font-size:
        clamp(
            28px,
            7vw,
            46px
        );

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

    border:
        2px solid #42eaff;

    border-radius:15px;

    background:
        linear-gradient(
            145deg,
            rgba(12,43,72,.9),
            rgba(4,13,28,.94)
        );

    box-shadow:
        0 0 10px #00eaff,
        inset 0 0 20px
            rgba(0,234,255,.15),
        0 0 30px
            rgba(255,0,213,.2);
}

.frame:before,
.frame:after{
    content:"";

    position:absolute;

    height:5px;

    width:90px;

    top:-5px;

    background:
        linear-gradient(
            90deg,
            #00eaff,
            #bdfcff,
            #ff24d7
        );

    box-shadow:
        0 0 12px #00eaff;

    border-radius:4px;
}

.frame:before{
    left:35px;
}

.frame:after{
    right:35px;
}

.poster{
    position:relative;

    overflow:hidden;

    border:
        2px solid #36f3ff;

    border-radius:8px;

    aspect-ratio:16/9;

    background:#0a2039;

    box-shadow:
        inset 0 0 22px
            rgba(0,255,255,.35),

        0 0 14px
            rgba(0,234,255,.45);
}

.poster video{
    width:100%;
    height:100%;
    display:block;
    object-fit:cover;
    background:#000;
}

.poster img{
    width:100%;
    height:100%;
    object-fit:cover;
}

.play{
    position:absolute;

    left:50%;
    top:50%;

    transform:
        translate(-50%,-50%);

    width:118px;
    height:82px;

    border:
        2px solid #9afcff;

    border-radius:16px;

    background:
        rgba(75,90,112,.58);

    backdrop-filter:
        blur(5px);

    color:#dffcff;

    font-size:44px;

    line-height:78px;

    text-align:center;

    text-shadow:
        0 0 10px #00eaff;

    box-shadow:
        0 0 18px
        rgba(0,238,255,.35);

    cursor:pointer;

    z-index:5;
}

.play.hidden{
    display:none;
}

.video-error{
    display:none;

    position:absolute;

    left:50%;
    top:50%;

    transform:
        translate(-50%,-50%);

    width:90%;

    text-align:center;

    color:#ffffff;

    font-size:14px;

    line-height:1.6;

    z-index:4;
}

.actions{
    display:grid;

    gap:14px;

    margin:18px 0;
}

.btn{
    appearance:none;

    border:
        2px solid #38f5ff;

    border-radius:10px;

    padding:15px 12px;

    width:100%;

    font:
        500
        clamp(
            17px,
            4.6vw,
            25px
        )
        Poppins,sans-serif;

    color:#eaffff;

    cursor:pointer;

    background:
        linear-gradient(
            180deg,
            rgba(17,72,103,.95),
            rgba(10,33,62,.98)
        );

    box-shadow:
        0 0 9px
        rgba(0,238,255,.75),

        inset 0 0 16px
        rgba(0,238,255,.12),

        0 5px 0
        rgba(255,0,204,.35);

    transition:
        .18s transform,
        .18s filter;
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

    border-radius:
        0 0 18px 18px;

    background:#101b28;

    margin-top:-14px;

    padding:
        22px 12px 18px;

    text-align:center;

    box-shadow:
        0 8px 18px
        rgba(0,0,0,.35);

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

    padding:
        16px 4px 8px;

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

.credit{
    margin-top:25px;

    text-align:center;

    color:#bfeeff;

    font-size:14px;

    line-height:1.8;

    opacity:.9;
}

.credit a{
    color:#ff8fce;

    text-decoration:none;

    font-weight:600;
}

.credit a:hover{
    color:#ffffff;

    text-decoration:underline;
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

    .credit{
        font-size:13px;
    }

}
"""


# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
async def home():

    return f"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,
    initial-scale=1.0"
>

<title>STADY-PROXY</title>

<style>
{STADY_CSS}
</style>

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
    style="
        width:100%;
        height:100%;
        object-fit:cover;
    "
>

</div>

<div
    class="status"
    style="
        font-size:20px;
        margin:25px 0;
    "
>
    SERVER ONLINE 🚀
</div>

</section>

</main>

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

    # --------------------------------------------------------
    # Missing token
    # --------------------------------------------------------

    if not row:

        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    # --------------------------------------------------------
    # 12-HOUR EXPIRY CHECK
    # --------------------------------------------------------

    if is_expired(row):

        # Remove database record

        delete_file_record(
            token
        )

        raise HTTPException(
            status_code=404,
            detail=(
                "This file link has "
                "expired after 12 hours."
            )
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

    file_size = int(
        row["size"]
    )

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

    return f"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,
    initial-scale=1.0,
    maximum-scale=1.0"
>

<title>
STADY-PROXY | {safe_name}
</title>

<style>
{STADY_CSS}
</style>

</head>

<body>

<main class="page">

<div class="brand">
    STADY-PROXY
</div>

<section class="frame">

<div class="poster">

<video
    id="videoPlayer"
    preload="metadata"
    playsinline
    controls
    poster="https://images.unsplash.com/photo-1511497584788-876760111969?auto=format&fit=crop&w=1200&q=85"
>

<source
    src="{stream_url}"
    type="{html.escape(row['mime'])}"
>

Your browser does not support
HTML5 video.

</video>


<button
    class="play"
    id="playButton"
    aria-label="Play video"
    onclick="playVideo()"
>
▶
</button>


<div
    class="video-error"
    id="videoError"
>

⚠️ This video format cannot
be played by this browser.

<br>

Try Download or an external
video player.

</div>

</div>


<div class="actions">

<button
    class="btn"
    onclick="downloadFile()"
>
☁️ Download ☁️
</button>


<button
    class="btn"
    onclick="stream()"
>
⏵ Stream ⏵
</button>

</div>


<div class="info">

<div>
📄
<b>File Name:</b>
<span>{safe_name}</span>
</div>

<div>
☰
<b>File Size:</b>
<span>{size_str}</span>
</div>

<div>
👤
<b>File Owner:</b>
<span>STADY-PROXY</span>
</div>

<div>
◷
<b>Created Time:</b>
<span>{created}</span>
</div>

<div>
⏳
<b>Link:</b>
<span>Valid for 12 hours</span>
</div>

</div>

</section>


<div class="credit">

STADY-PROXY •
This file link expires in 12 hours

</div>


<div
    class="status"
    id="status"
>
STADY-PROXY • READY
</div>

</main>


<script>

const STREAM_URL =
    {stream_url!r};

const DOWNLOAD_URL =
    {download_url!r};


const videoPlayer =
    document.getElementById(
        "videoPlayer"
    );


const playButton =
    document.getElementById(
        "playButton"
    );


const videoError =
    document.getElementById(
        "videoError"
    );


function setStatus(text) {{

    document
        .getElementById("status")
        .textContent = text;

}}


async function playVideo() {{

    try {{

        videoError.style.display =
            "none";

        await videoPlayer.play();

        playButton.classList.add(
            "hidden"
        );

        setStatus(
            "STADY-PROXY • PLAYING"
        );

    }} catch(error) {{

        console.log(
            "Video playback error:",
            error
        );

        videoError.style.display =
            "block";

        setStatus(
            "Browser cannot play "
            + "this video format"
        );

    }}

}}


videoPlayer.addEventListener(
    "play",
    function() {{

        playButton.classList.add(
            "hidden"
        );

        setStatus(
            "STADY-PROXY • PLAYING"
        );

    }}
);


videoPlayer.addEventListener(
    "pause",
    function() {{

        if (!videoPlayer.ended) {{

            playButton.classList.remove(
                "hidden"
            );

            setStatus(
                "STADY-PROXY • PAUSED"
            );

        }}

    }}
);


videoPlayer.addEventListener(
    "ended",
    function() {{

        playButton.classList.remove(
            "hidden"
        );

        setStatus(
            "STADY-PROXY • FINISHED"
        );

    }}
);


videoPlayer.addEventListener(
    "error",
    function() {{

        videoError.style.display =
            "block";

        setStatus(
            "Browser cannot play "
            + "this video format"
        );

    }}
);


function downloadFile() {{

    location.href =
        DOWNLOAD_URL;

}}


function stream() {{

    videoPlayer.scrollIntoView({{
        behavior:"smooth",
        block:"center"
    }});

    playVideo();

}}

</script>

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

    # --------------------------------------------------------
    # Missing token
    # --------------------------------------------------------

    if not row:

        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    # --------------------------------------------------------
    # EXPIRY CHECK
    # --------------------------------------------------------

    if is_expired(row):

        delete_file_record(
            token
        )

        raise HTTPException(
            status_code=404,
            detail=(
                "This file link has "
                "expired after 12 hours."
            )
        )

    # --------------------------------------------------------
    # Filename validation
    # --------------------------------------------------------

    real_filename = row[
        "filename"
    ]

    if filename != real_filename:

        raise HTTPException(
            status_code=404,
            detail="Filename mismatch"
        )

    # --------------------------------------------------------
    # Telegram message
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
            detail=(
                "Could not access "
                "Telegram file"
            )
        )

    if (
        not message
        or
        not message.media
    ):

        raise HTTPException(
            status_code=404,
            detail=(
                "Telegram file "
                "no longer exists"
            )
        )

    file_size = int(
        row["size"]
    )

    mime = row["mime"]

    # ========================================================
    # DOWNLOAD
    # ========================================================

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
                (
                    'attachment; filename="'
                    + quote(
                        real_filename
                    )
                    + '"'
                ),

            "Accept-Ranges":
                "bytes"

        }

        return StreamingResponse(

            download_generator(),

            status_code=200,

            media_type=mime,

            headers=headers

        )

    # ========================================================
    # STREAM
    # ========================================================

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

    length = (
        end
        - start
        + 1
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
            (
                f"bytes "
                f"{start}-{end}/"
                f"{file_size}"
            ),

        "Content-Disposition":
            (
                'inline; filename="'
                + quote(
                    real_filename
                )
                + '"'
            ),

        "Cache-Control":
            "no-cache"

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
# MAIN
# ============================================================

async def main():

    global BOT_USERNAME

    # --------------------------------------------------------
    # Database
    # --------------------------------------------------------

    init_database()

    print()

    print(
        "=" * 65
    )

    print(
        "       TELEGRAM DIRECT PROXY — STADY-PROXY"
    )

    print(
        "=" * 65
    )

    print()

    print(
        "[+] Connecting to Telegram..."
    )

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

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
        f"[+] Public URL: {PUBLIC_URL}"
    )

    print(
        f"[+] Local URL: http://127.0.0.1:{PORT}"
    )

    print(
        "[+] Link lifetime: 12 hours"
    )

    print(
        "[+] Bot reply auto-delete: ENABLED"
    )

    print(
        "[+] Server ready"
    )

    print(
        "=" * 65
    )

    # --------------------------------------------------------
    # Clean already expired records
    # --------------------------------------------------------

    await cleanup_expired_files()

    # --------------------------------------------------------
    # Background cleanup
    # --------------------------------------------------------

    cleanup_task = asyncio.create_task(
        expiry_cleanup_loop()
    )

    # --------------------------------------------------------
    # Uvicorn
    # --------------------------------------------------------

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

        cleanup_task.cancel()

        try:

            await cleanup_task

        except asyncio.CancelledError:

            pass

        print(
            "[+] Disconnecting Telegram..."
        )

        await bot.disconnect()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\n[+] Server stopped."
        )
