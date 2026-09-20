"""
Adolf-StreamX — Phone Remote UI
Step 13E

Standalone renderer for the phone-side remote-control page.
No FastAPI routes are registered here and no existing page/route is replaced.
The caller can mount the returned HTML at a later integration step.
"""

from __future__ import annotations

import html


REMOTE_COMMANDS = {
    "play": "▶",
    "pause": "⏸",
    "toggle": "▶ / ⏸",
    "seek_backward": "⏪ 10s",
    "seek_forward": "10s ⏩",
    "volume_down": "🔉",
    "volume_up": "🔊",
    "mute": "🔇",
    "fullscreen": "⛶",
    "stop": "⏹",
}


def render_remote_page(public_url: str, session_id: str, title: str = "Adolf-StreamX Remote") -> str:
    """Render the phone-side remote UI for an existing remote session."""
    safe_title = html.escape(str(title))
    safe_session = html.escape(str(session_id), quote=True)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05070d">
<title>{safe_title}</title>
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;background:#03060b;color:#edf3ff;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
body{{padding:18px;background:radial-gradient(circle at 50% -10%,rgba(83,72,170,.28),transparent 42%),#03060b}}
.remote-page{{width:min(520px,100%);margin:0 auto;padding:8px 0 28px}}
.header{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}}
.brand{{font-size:20px;font-weight:900;letter-spacing:-.4px}}
.brand span{{background:linear-gradient(90deg,#9b5cff,#4cc9ff);-webkit-background-clip:text;background-clip:text;color:transparent}}
.status{{display:flex;align-items:center;gap:7px;padding:8px 10px;border:1px solid rgba(130,150,190,.18);border-radius:999px;background:rgba(10,15,25,.8);font-size:11px;font-weight:800;color:#aebbd0}}
.dot{{width:7px;height:7px;border-radius:50%;background:#f0b35a;box-shadow:0 0 10px rgba(240,179,90,.45)}}
.dot.ok{{background:#5ee7a5;box-shadow:0 0 10px rgba(94,231,165,.65)}}
.card{{border:1px solid rgba(130,150,190,.16);border-radius:24px;background:linear-gradient(180deg,rgba(11,17,29,.94),rgba(5,9,16,.96));box-shadow:0 24px 70px rgba(0,0,0,.45);padding:18px}}
.tv{{border:1px solid rgba(130,150,190,.13);border-radius:18px;padding:16px;background:rgba(5,10,18,.8);text-align:center;margin-bottom:16px}}
.tv-label{{font-size:11px;text-transform:uppercase;letter-spacing:1.1px;color:#748197;font-weight:900}}
.tv-name{{margin-top:7px;font-size:17px;font-weight:850}}
.controls{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
button{{min-height:58px;border:1px solid rgba(130,150,190,.16);border-radius:17px;background:linear-gradient(180deg,#101827,#0a111d);color:#eef4ff;font-size:18px;font-weight:850;cursor:pointer;touch-action:manipulation;box-shadow:0 7px 20px rgba(0,0,0,.2)}}
button:active{{transform:scale(.97)}}
button.primary{{background:linear-gradient(135deg,#7139d8,#2e74d8);border-color:rgba(155,120,255,.48)}}
.wide{{grid-column:span 3}}
.seek,.volume{{margin-top:16px;padding:15px;border:1px solid rgba(130,150,190,.12);border-radius:18px;background:rgba(7,12,21,.72)}}
.section-title{{font-size:11px;color:#77849a;text-transform:uppercase;letter-spacing:1px;font-weight:900;margin-bottom:10px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
input[type=range]{{width:100%;accent-color:#8b5cf6}}
.vol-value{{text-align:center;margin-top:6px;color:#b9c5d8;font-size:12px;font-weight:800}}
.message{{margin-top:16px;padding:13px 14px;border:1px solid rgba(130,150,190,.12);border-radius:15px;background:rgba(8,13,22,.72);color:#aebbd0;text-align:center;font-size:12px;line-height:1.5}}
.code{{margin-top:12px;color:#647188;text-align:center;font-size:10px;overflow-wrap:anywhere}}
@media(max-width:380px){{body{{padding:12px}}.card{{padding:13px;border-radius:20px}}button{{min-height:54px}}}}
</style>
</head>
<body>
<main class="remote-page">
<header class="header">
  <div class="brand">Adolf-<span>StreamX</span></div>
  <div class="status"><i class="dot" id="dot"></i><span id="connection">CONNECTING</span></div>
</header>
<section class="card">
  <div class="tv">
    <div class="tv-label">TV Remote</div>
    <div class="tv-name">📺 Connected Player</div>
  </div>

  <div class="controls">
    <button class="primary wide" onclick="send('toggle')">▶ / ⏸</button>
    <button onclick="send('seek_backward')">⏪ 10s</button>
    <button onclick="send('seek_forward')">10s ⏩</button>
    <button onclick="send('stop')">⏹</button>
    <button onclick="send('mute')">🔇</button>
    <button onclick="send('fullscreen')">⛶</button>
  </div>

  <div class="seek">
    <div class="section-title">Seek</div>
    <div class="row">
      <button onclick="send('seek_backward')">−10 sec</button>
      <button onclick="send('seek_forward')">+10 sec</button>
    </div>
  </div>

  <div class="volume">
    <div class="section-title">Volume</div>
    <input id="volume" type="range" min="0" max="100" value="100" oninput="setVolume(this.value)">
    <div class="vol-value" id="volumeValue">100%</div>
  </div>

  <div class="message" id="message">Connecting to the TV…</div>
  <div class="code">Session: {safe_session}</div>
</section>
</main>

<script>
const SESSION_ID = {safe_session!r};
const socketScheme = location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = socketScheme + "//" + location.host + "/ws/remote/" + encodeURIComponent(SESSION_ID);
let socket = null;
let reconnectTimer = null;

const connection = document.getElementById("connection");
const dot = document.getElementById("dot");
const message = document.getElementById("message");
const volume = document.getElementById("volume");
const volumeValue = document.getElementById("volumeValue");

function setState(text, ok=false) {{
  connection.textContent = text;
  dot.classList.toggle("ok", ok);
}}

function connect() {{
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  setState("CONNECTING", false);
  try {{
    socket = new WebSocket(WS_URL);
    socket.onopen = () => {{
      setState("CONNECTED", true);
      message.textContent = "📺 TV remote connected. Controls are ready.";
    }};
    socket.onclose = () => {{
      setState("OFFLINE", false);
      message.textContent = "TV remote disconnected. Reconnecting…";
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 1800);
    }};
    socket.onerror = () => {{
      setState("ERROR", false);
      message.textContent = "Could not connect to the TV remote.";
    }};
    socket.onmessage = event => {{
      try {{
        const data = JSON.parse(event.data);
        if (data.event === "tv_connected") message.textContent = "📺 TV connected.";
        else if (data.event === "tv_disconnected") message.textContent = "⚠️ TV disconnected.";
        else if (data.event === "ack") message.textContent = "✓ Command sent to TV.";
        else if (data.event === "error") message.textContent = data.message || "Remote error.";
      }} catch (_) {{}}
    }};
  }} catch (_) {{
    setState("ERROR", false);
  }}
}}

function send(command, extra={{}}) {{
  if (!socket || socket.readyState !== WebSocket.OPEN) {{
    message.textContent = "⚠️ TV remote is not connected.";
    return;
  }}
  socket.send(JSON.stringify({{command, ...extra}}));
  message.textContent = "✓ " + command.replaceAll("_", " ") + " sent";
}}

function setVolume(value) {{
  volumeValue.textContent = value + "%";
  send("set_volume", {{value: Number(value)}});
}}

window.addEventListener("load", connect);
</script>
</body>
</html>'''
