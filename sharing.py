import html
from io import BytesIO
from urllib.parse import quote

import qrcode
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse

from config import PUBLIC_URL
from database import create_share_token, get_file_by_share_token
from utils import get_stream_mime
from owner import get_owner_display
from pages import render_receive_page
from remote_control import remote_manager, message_size_ok, validate_command
from remote_ui import render_remote_page

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
        return HTMLResponse(content=stady_error_page(), status_code=404)
    try:
        session_id = await remote_manager.create_session()
    except Exception:
        session_id = None
    owner_display = None
    try:
        owner_display = await get_owner_display(row)
    except Exception:
        owner_display = None
    return HTMLResponse(content=render_receive_page(
        share_token=share_token,
        row=row,
        public_url=PUBLIC_URL,
        stady_css=STADY_CSS,
        get_stream_mime_func=get_stream_mime,
        owner_display=owner_display,
        remote_session_id=session_id,
    ))


@router.get("/remote/{session_id}", response_class=HTMLResponse)
async def remote_page(session_id: str):
    if await remote_manager.get_session(session_id) is None:
        return HTMLResponse(content=stady_error_page(), status_code=404)
    return HTMLResponse(content=render_remote_page(PUBLIC_URL, session_id))


@router.websocket("/ws/tv/{session_id}")
async def tv_socket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if not await remote_manager.attach_tv(session_id, websocket):
        await websocket.close(code=1008)
        return
    try:
        while True:
            message = await websocket.receive_text()
            if not message_size_ok(message):
                await websocket.close(code=1009)
                return
            # TV sends playback/status events; forward them to the paired phone.
            try:
                import json
                payload = json.loads(message)
            except Exception:
                continue
            if isinstance(payload, dict):
                await remote_manager.send_to_phone(session_id, payload)
    except WebSocketDisconnect:
        pass
    finally:
        session = await remote_manager.get_session(session_id)
        if session and session.tv_socket is websocket:
            session.tv_socket = None


@router.websocket("/ws/remote/{session_id}")
async def remote_socket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if not await remote_manager.attach_phone(session_id, websocket):
        await websocket.close(code=1008)
        return
    try:
        while True:
            message = await websocket.receive_text()
            if not message_size_ok(message):
                await websocket.close(code=1009)
                return
            try:
                import json
                payload = json.loads(message)
            except Exception:
                continue
            if not validate_command(payload):
                await websocket.send_json({"ok": False, "error": "Invalid command"})
                continue
            await remote_manager.send_to_tv(session_id, payload)
    except WebSocketDisconnect:
        pass
    finally:
        session = await remote_manager.get_session(session_id)
        if session and session.phone_socket is websocket:
            session.phone_socket = None

def configure(css, error_page):
    global STADY_CSS, stady_error_page
    STADY_CSS = css
    stady_error_page = error_page

