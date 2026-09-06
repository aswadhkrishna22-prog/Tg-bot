import html
from io import BytesIO
from urllib.parse import quote

import qrcode
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

from config import PUBLIC_URL
from database import create_share_token, get_file_by_share_token

router = APIRouter()

STADY_CSS = ""

def stady_error_page():
    return ""

@router.get("/share/{share_token}", response_class=HTMLResponse)
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
<title>Adolf-StreamX | Share</title>
<style>{STADY_CSS}
.sharebox{{text-align:center;padding:18px 8px 10px}}
.qr{{width:min(310px,80vw);height:auto;background:#fff;padding:12px;border-radius:12px;margin:14px auto;display:block}}
.small{{color:#a9bfd0;font-size:14px;line-height:1.6}}
</style>
</head>
<body>
<main class="page">
<div class="brand">Adolf-StreamX</div>
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
    Enter this 6-digit code on the Adolf-StreamX home page on your TV.<br>
    The QR code above can still be scanned directly.
</p>
<p class="small">The QR opens a receiver page with player options.</p>
</div>
</section>
<div class="status">Adolf-StreamX • READY</div>
</main>
</body>
</html>"""
    )

@router.get("/share-qr/{share_token}.png")
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

@router.get("/receive/{share_token}", response_class=HTMLResponse)
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
<title>Adolf-StreamX | Receiver</title>
<style>{STADY_CSS}
.receiver{{text-align:center;padding:18px 8px}}
.file{{font-size:18px;word-break:break-word}}
</style>
</head>
<body>
<main class="page">
<div class="brand">Adolf-StreamX</div>
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
<div class="status" id="status">Adolf-StreamX • RECEIVER READY</div>
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
        setStatus("Adolf-StreamX • OPENING PLAYER");
        location.href = intent;
    }} else {{
        playBrowser();
    }}
}}
</script>
</body>
</html>"""
    )

def configure(css, error_page):
    global STADY_CSS, stady_error_page
    STADY_CSS = css
    stady_error_page = error_page

