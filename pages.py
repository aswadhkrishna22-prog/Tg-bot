"""Adolf-StreamX presentation layer.

Contains HTML renderers only; route registration and runtime state remain in
server.py and are passed into the renderers explicitly.
"""

import html
from datetime import datetime
from urllib.parse import quote

def render_error_page():
    """Compact glass 404 overlay over the normal Adolf-StreamX watch UI."""
    # Keep this URL fixed so the page never exposes an unresolved template placeholder.
    bot_link = "https://t.me/AdolfFTLbot?start=unavailable"
    forest_image = (
        "https://images.unsplash.com/photo-1448375240586-882707db888b"
        "?auto=format&fit=crop&w=1600&q=90"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<meta name="theme-color" content="#05070d">
<title>Adolf-StreamX | 404</title>
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#05070d;color:#eef2ff}}
body{{overflow:hidden;background:radial-gradient(circle at 8% 8%,rgba(124,58,237,.13),transparent 30%),radial-gradient(circle at 92% 42%,rgba(6,182,212,.09),transparent 28%),linear-gradient(180deg,#05070d 0%,#070a12 52%,#04060b 100%)}}
.watch-page{{width:min(1120px,calc(100% - 28px));margin:0 auto;padding:28px 0 48px}}
.watch-header{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:22px}}
.watch-brand{{font-size:22px;font-weight:900;letter-spacing:-.4px}}
.watch-brand span{{background:linear-gradient(90deg,#9b5cff,#4cc9ff);-webkit-background-clip:text;background-clip:text;color:transparent}}
.watch-status{{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid rgba(110,140,190,.18);border-radius:999px;background:rgba(12,17,30,.72);color:#aeb9cc;font-size:12px;font-weight:700}}
.watch-status i{{width:7px;height:7px;border-radius:50%;background:#5ee7a5;box-shadow:0 0 12px rgba(94,231,165,.7)}}
.media-card{{overflow:hidden;border-radius:24px;border:1px solid rgba(125,145,190,.18);background:#050913;box-shadow:0 24px 80px rgba(0,0,0,.42)}}
.poster{{position:relative;aspect-ratio:16/9;min-height:240px;overflow:hidden;background:#07100b}}
.poster::before{{content:"";position:absolute;inset:0;background-image:url("{forest_image}");background-size:cover;background-position:center;transform:scale(1.015)}}
.poster::after{{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(2,5,10,.10),rgba(2,5,10,.48))}}
.poster-play{{position:absolute;z-index:2;left:50%;top:50%;transform:translate(-50%,-50%);width:78px;height:78px;border:1px solid rgba(255,255,255,.30);border-radius:50%;background:rgba(5,10,20,.72);color:white;display:grid;place-items:center;font-size:30px;padding-left:4px;box-shadow:0 12px 42px rgba(0,0,0,.45);backdrop-filter:blur(12px)}}
.file-title-card{{padding:20px 22px;border-top:1px solid rgba(125,145,190,.12)}}
.skeleton-title{{height:20px;width:72%;border-radius:8px;background:rgba(148,163,184,.13)}}
.skeleton-sub{{margin-top:10px;height:13px;width:34%;border-radius:7px;background:rgba(148,163,184,.09)}}
.action-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}}
.action-btn{{min-height:58px;border-radius:16px;border:1px solid rgba(125,145,190,.16);background:linear-gradient(180deg,#0d1423,#090f1b);color:#edf2fb;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:800}}
.info-card{{margin-top:18px;overflow:hidden;border:1px solid rgba(125,145,190,.14);border-radius:20px;background:rgba(8,12,21,.78)}}
.info-head{{padding:18px 20px;border-bottom:1px solid rgba(125,145,190,.12);font-size:13px;font-weight:900;letter-spacing:.8px;text-transform:uppercase;color:#c6d0e2}}
.info-row{{display:grid;grid-template-columns:150px 1fr;gap:16px;padding:15px 20px;border-bottom:1px solid rgba(125,145,190,.08)}}
.info-row:last-child{{border-bottom:0}}
.info-label{{color:#727f95;font-size:13px}}
.info-value{{height:14px;width:55%;border-radius:7px;background:rgba(148,163,184,.08)}}
.fake-status{{margin-top:18px;height:40px;border-radius:12px;background:rgba(8,12,21,.70);border:1px solid rgba(125,145,190,.12)}}
.error-overlay{{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px;overflow:hidden;background:rgba(0,0,0,.40);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}}
.rain{{position:absolute;inset:-10%;pointer-events:none;opacity:.55;background:repeating-linear-gradient(104deg,transparent 0 45px,rgba(190,225,255,.18) 46px,transparent 48px 90px);animation:rain 1.6s linear infinite}}
@keyframes rain{{from{{transform:translateY(-55px)}}to{{transform:translateY(55px)}}}}
.error-modal{{position:relative;z-index:2;width:min(350px,calc(100vw - 30px));border:1px solid rgba(255,255,255,.20);border-radius:20px;background:linear-gradient(145deg,rgba(36,42,54,.40),rgba(10,14,23,.58));box-shadow:0 28px 90px rgba(0,0,0,.66),0 0 65px rgba(255,45,75,.12),inset 0 1px 0 rgba(255,255,255,.10);backdrop-filter:blur(18px) saturate(140%);-webkit-backdrop-filter:blur(18px) saturate(140%);padding:22px 18px 18px;text-align:center;overflow:hidden}}
.error-modal::before{{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(125deg,rgba(255,255,255,.12),transparent 24%,transparent 72%,rgba(255,255,255,.035));border-radius:inherit}}
.error-icon{{position:relative;width:48px;height:48px;margin:0 auto;color:#ff5265;font-size:42px;line-height:48px;text-shadow:0 0 18px rgba(255,55,75,.72)}}
.error-code{{position:relative;margin:0;font-size:60px;line-height:1;font-weight:850;letter-spacing:3px;background:linear-gradient(180deg,#fff,#ff7080 40%,#ff3048);-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent}}
.error-title{{position:relative;margin:9px 0 0;color:#f5f7fc;font-size:14px;letter-spacing:3px;font-weight:600}}
.error-message{{position:relative;margin:13px auto 0;color:#bfc5d0;font-size:13px;line-height:1.6;max-width:300px}}
.buttons{{position:relative;display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:18px}}
.action-btn-404{{min-height:46px;border:1px solid rgba(255,255,255,.18);border-radius:11px;background:rgba(12,17,28,.78);color:#eef2f7;text-decoration:none;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;cursor:pointer}}
.action-btn-404:hover{{border-color:rgba(255,255,255,.35);transform:translateY(-1px)}}
@media(max-width:430px){{.watch-page{{width:calc(100% - 18px);padding-top:16px}}.watch-brand{{font-size:19px}}.watch-status{{font-size:10px;padding:7px 9px}}.media-card{{border-radius:18px}}.poster{{min-height:205px}}.poster-play{{width:70px;height:70px;font-size:27px}}.action-grid{{grid-template-columns:1fr}}.info-row{{grid-template-columns:1fr;gap:6px;padding:13px 16px}}.error-modal{{width:min(340px,calc(100vw - 24px));padding:20px 15px 16px}}.error-code{{font-size:54px}}.buttons{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<main class="watch-page" aria-hidden="true">
<header class="watch-header">
<div class="watch-brand">Adolf-<span>StreamX</span></div>
<div class="watch-status"><i></i> ONLINE</div>
</header>
<section class="media-card">
<div class="poster"><div class="poster-play">▶</div></div>
<div class="file-title-card"><div class="skeleton-title"></div><div class="skeleton-sub"></div></div>
</section>
<div class="action-grid"><div class="action-btn">⇩ Download File</div><div class="action-btn">⛓ Copy Share Link</div></div>
<div class="action-grid"><div class="action-btn">🎬 External Players</div></div>
<section class="info-card">
<div class="info-head">▣ File Information</div>
<div class="info-row"><div class="info-label">File Name</div><div class="info-value"></div></div>
<div class="info-row"><div class="info-label">File Size</div><div class="info-value"></div></div>
<div class="info-row"><div class="info-label">File Owner</div><div class="info-value"></div></div>
</section>
<div class="fake-status"></div>
</main>
<div class="error-overlay" role="dialog" aria-modal="true" aria-labelledby="errorTitle">
<div class="rain"></div>
<section class="error-modal">
<div class="error-icon">⚠</div>
<h1 class="error-code">404</h1>
<div id="errorTitle" class="error-title">FILE NOT AVAILABLE</div>
<p class="error-message">⚠️ Sorry! This file is currently unavailable.</p>
<div class="buttons">
<button class="action-btn-404" onclick="location.reload()">↻ RELOAD BROWSER</button>
<a class="action-btn-404" href="{bot_link}">⌂ RETURN HOME</a>
</div>
</section>
</div>
</body>
</html>"""


def render_home_page(stady_css):

    return f"""<!DOCTYPE html>
<html lang="en">
<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Adolf-StreamX</title>

<style>{stady_css}</style>

</head>

<body>

<main class="page">

    <div class="brand">
        Adolf-StreamX
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
            <div id="pairError" style="grid-column:1/-1;color:#ff7b8c;text-align:center;font-weight:700;font-size:13px;min-height:20px"></div>
        </div>

        <p style="text-align:center;line-height:1.7;color:#a9bfd0;font-size:14px;">
            <b>📖 TV PAIRING — HOW TO USE</b><br><br>
            1️⃣ Send a video/file to the Adolf-StreamX Telegram bot.<br>
            2️⃣ Open the generated SHARE page on your phone.<br>
            3️⃣ Find the 6-digit TV pairing code shown there (it is also sent in Telegram).<br>
            4️⃣ On your TV, open this Adolf-StreamX home page.<br>
            5️⃣ Enter the 6-digit code above and tap <b>PAIR TV</b>.<br>
            6️⃣ Your TV will open the receiver page with VLC, MX Player and Browser Player options.<br><br>
            ⏳ Pairing codes follow the same 12-hour file expiry.
        </p>

    </section>

<script>
async function pairDevice() {{
    const input = document.getElementById("pairCode");
    const code = input.value.trim();
    const error = document.getElementById("pairError");
    if (!/^[0-9]{{6}}$/.test(code)) {{
        error.textContent = "Code must be 6 digits";
        input.focus();
        return;
    }}
    error.textContent = "";
    try {{
        const response = await fetch("/pair/" + code, {{headers: {{"X-Pair-AJAX": "1"}}}});
        const redirect = response.headers.get("X-Pair-Redirect");
        if (redirect) {{ location.href = redirect; return; }}
        const data = await response.json().catch(() => null);
        error.textContent = (data && data.error) || "Code is not valid";
    }} catch (_) {{
        error.textContent = "Unable to verify code. Try again.";
    }}
}}
</script>

</main>

</body>
</html>"""


async def render_watch_page(token, row, public_url, stady_css, get_owner_display_func, create_share_token_func, get_stream_mime_func, error_page_func):
    filename = row["filename"]
    safe_name = html.escape(filename)
    encoded_filename = quote(filename, safe="")

    stream_url = (
        f"{public_url}/{token}/"
        f"{encoded_filename}?action=stream"
    )

    file_size = int(row["size"])
    mime = get_stream_mime_func(filename, row["mime"])

    if file_size >= 1024**3:
        size_str = f"{file_size / 1024**3:.2f} GB"
    elif file_size >= 1024**2:
        size_str = f"{file_size / 1024**2:.2f} MB"
    else:
        size_str = f"{file_size / 1024:.2f} KB"

    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    owner_display = html.escape(await get_owner_display_func(row))

    try:
        share_token = row.get("share_token") if hasattr(row, "get") else None
        if not share_token:
            share_token = create_share_token_func(token)
        share_url = f"{public_url}/share/{share_token}"
    except Exception:
        share_url = stream_url

    # The poster is intentionally clean: forest image + play button only.
    # The real <video> element is created after the user taps play, so native
    # browser controls provide reliable pause, seek, volume and fullscreen.
    forest_image = (
        "https://images.unsplash.com/photo-1448375240586-882707db888b"
        "?auto=format&fit=crop&w=1600&q=90"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#05070d">
<title>Adolf-StreamX | {safe_name}</title>
<style>
{stady_css}

/* ==========================================================
   PREMIUM WATCH PLAYER — clean poster, native video controls
   ========================================================== */
.watch-page {{
    width: min(1120px, calc(100% - 28px));
    margin: 0 auto;
    padding: 28px 0 48px;
}}

.watch-header {{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:16px;
    margin-bottom:22px;
}}

.watch-brand {{
    font-size:22px;
    font-weight:900;
    letter-spacing:-.4px;
}}
.watch-brand span {{
    background:linear-gradient(90deg,#9b5cff,#4cc9ff);
    -webkit-background-clip:text;
    background-clip:text;
    color:transparent;
}}
.watch-status {{
    display:inline-flex;
    align-items:center;
    gap:8px;
    padding:8px 12px;
    border:1px solid rgba(110,140,190,.18);
    border-radius:999px;
    background:rgba(12,17,30,.72);
    color:#aeb9cc;
    font-size:12px;
    font-weight:700;
}}
.watch-status i {{
    width:7px;
    height:7px;
    border-radius:50%;
    background:#5ee7a5;
    box-shadow:0 0 12px rgba(94,231,165,.7);
}}

.media-card {{
    overflow:hidden;
    border-radius:24px;
    border:1px solid rgba(125,145,190,.18);
    background:#050913;
    box-shadow:0 24px 80px rgba(0,0,0,.42);
}}

.poster {{
    position:relative;
    aspect-ratio:16/9;
    min-height:240px;
    overflow:hidden;
    background:#07100b;
}}
.poster::before {{
    content:"";
    position:absolute;
    inset:0;
    background-image:url("{forest_image}");
    background-size:cover;
    background-position:center;
    transform:scale(1.015);
}}
.poster::after {{
    content:"";
    position:absolute;
    inset:0;
    background:linear-gradient(180deg,rgba(2,5,10,.06),rgba(2,5,10,.38));
}}

.poster.playing::before,
.poster.playing::after {{
    display:none;
}}


.poster-play {{
    position:absolute;
    z-index:2;
    left:50%;
    top:50%;
    transform:translate(-50%,-50%);
    width:92px;
    height:92px;
    border:1px solid rgba(255,255,255,.45);
    border-radius:50%;
    background:rgba(5,10,20,.82);
    color:white;
    display:grid;
    place-items:center;
    font-size:34px;
    padding:0 0 0 5px;
    cursor:pointer;
    box-shadow:0 12px 42px rgba(0,0,0,.45), 0 0 0 7px rgba(120,95,255,.10);
    backdrop-filter:blur(14px);
    transition:transform .18s ease, box-shadow .18s ease, background .18s ease;
}}
.poster-play:hover {{
    transform:translate(-50%,-50%) scale(1.06);
    background:rgba(10,16,30,.92);
    box-shadow:0 16px 48px rgba(0,0,0,.5), 0 0 0 9px rgba(120,95,255,.13);
}}
.poster-play:active {{
    transform:translate(-50%,-50%) scale(.97);
}}

.video-shell {{
    position:relative;
    width:100%;
    aspect-ratio:16/9;
    background:#000;
}}
.video-shell video {{
    display:block;
    width:100%;
    height:100%;
    object-fit:contain;
    background:#000;
}}

.video-error {{
    display:none;
    position:absolute;
    left:16px;
    right:16px;
    bottom:70px;
    z-index:3;
    padding:12px 14px;
    border:1px solid rgba(255,120,120,.25);
    border-radius:12px;
    background:rgba(20,5,8,.86);
    color:#ffd4d4;
    text-align:center;
    font-size:13px;
    backdrop-filter:blur(12px);
}}

.file-title-card {{
    padding:20px 22px;
    border-top:1px solid rgba(125,145,190,.12);
}}
.file-title {{
    margin:0;
    color:#f4f7ff;
    font-size:18px;
    font-weight:800;
    line-height:1.4;
    overflow-wrap:anywhere;
}}
.file-sub {{
    margin-top:6px;
    color:#8995aa;
    font-size:13px;
}}

.action-grid {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12px;
    margin-top:16px;
}}
.action-btn {{
    min-height:58px;
    border-radius:16px;
    border:1px solid rgba(125,145,190,.16);
    background:linear-gradient(180deg,#0d1423,#090f1b);
    color:#edf2fb;
    text-decoration:none;
    display:flex;
    align-items:center;
    justify-content:center;
    gap:9px;
    font-size:15px;
    font-weight:800;
    cursor:pointer;
    transition:transform .16s ease,border-color .16s ease,background .16s ease;
}}
.action-btn:hover {{
    transform:translateY(-2px);
    border-color:rgba(126,95,255,.55);
    background:linear-gradient(180deg,#11192b,#0b1220);
}}
.action-btn.primary {{
    background:linear-gradient(135deg,#7139d8,#2e74d8);
    border-color:rgba(155,120,255,.48);
}}
.footer {{
    margin-top: 28px;
    padding: 18px 0 8px;
    text-align: center;
    font-size: 13px;
    color: rgba(255, 255, 255, 0.45);
}}

.footer .heart {{
    color: #ff4d6d;
    font-size: 15px;
    margin: 0 3px;
}}

.instagram-link {{
    margin-left: 4px;
    text-decoration: none;
    font-weight: 600;

    background: linear-gradient(
        45deg,
        #feda75,
        #fa7e1e,
        #d62976,
        #962fbf,
        #4f5bd5
    );

    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;

    transition: opacity 0.2s ease;
}}

.instagram-link:hover {{
    opacity: 0.8;
}}

.instagram-icon {{
    font-size: 16px;
    margin-right: 3px;
    -webkit-text-fill-color: #d62976;
}}
.info-card {{
    margin-top:18px;
    overflow:hidden;
    border:1px solid rgba(125,145,190,.14);
    border-radius:20px;
    background:rgba(8,12,21,.78);
}}
.info-head {{
    padding:18px 20px;
    border-bottom:1px solid rgba(125,145,190,.12);
    font-size:13px;
    font-weight:900;
    letter-spacing:.8px;
    text-transform:uppercase;
    color:#c6d0e2;
}}
.info-row {{
    display:grid;
    grid-template-columns:150px 1fr;
    gap:16px;
    padding:15px 20px;
    border-bottom:1px solid rgba(125,145,190,.08);
}}
.info-row:last-child {{ border-bottom:0; }}
.info-label {{ color:#727f95; font-size:13px; }}
.info-value {{ color:#dce4f1; font-size:14px; overflow-wrap:anywhere; }}

@media (max-width:650px) {{
    .watch-page {{ width:calc(100% - 20px); padding-top:16px; }}
    .watch-header {{ margin-bottom:14px; }}
    .watch-brand {{ font-size:19px; }}
    .watch-status {{ font-size:10px; padding:7px 9px; }}
    .media-card {{ border-radius:18px; }}
    .poster {{ min-height:205px; }}
    .poster-play {{ width:72px; height:72px; font-size:27px; }}
    .file-title-card {{ padding:16px; }}
    .action-grid {{ grid-template-columns:1fr; }}
    .info-row {{ grid-template-columns:1fr; gap:5px; padding:13px 16px; }}
}}
</style>
</head>
<body>
<main class="watch-page">

<header class="watch-header">
    <div class="watch-brand">Adolf-<span>StreamX</span></div>
    <div class="watch-status"><i></i> ONLINE</div>
</header>

<section class="media-card">
    <div class="poster" id="playerArea" aria-label="Video preview">
        <button class="poster-play" type="button" onclick="startVideo()" aria-label="Play video">▶</button>
    </div>
    <div class="file-title-card">
        <p class="file-title">{safe_name}</p>
        <div class="file-sub">{size_str} · {html.escape(mime)}</div>
    </div>
</section>

<div class="action-grid">
    <a class="action-btn primary" href="{stream_url}&action=download" download>⇩ Download File</a>
    <button class="action-btn" type="button" onclick="copyShareLink()">⛓ Copy Share Link</button>
</div>

<div class="action-grid" style="margin-top:12px;">
    <button class="action-btn" type="button" onclick="togglePlayers()">🎬 External Players</button>
</div>

<div class="players" id="players" style="display:none;">
    <button type="button" onclick="openPlayer('mx')">MX Player</button>
    <button type="button" onclick="openPlayer('vlc')">VLC Mobile</button>
    <button type="button" onclick="openPlayer('playit')">PlayIt</button>
    <button type="button" onclick="openPlayer('kmplayer')">KMPlayer</button>
    <button type="button" onclick="openPlayer('nplayer')">nPlayer</button>
</div>

<section class="info-card">
    <div class="info-head">▣ File Information</div>
    <div class="info-row"><div class="info-label">File Name</div><div class="info-value">{safe_name}</div></div>
    <div class="info-row"><div class="info-label">File Size</div><div class="info-value">{size_str}</div></div>
    <div class="info-row"><div class="info-label">File Owner</div><div class="info-value">{owner_display}</div></div>
    <div class="info-row"><div class="info-label">Created Time</div><div class="info-value">{created}</div></div>
</section>

<div class="status" id="status" style="margin-top:18px;">Adolf-StreamX • READY</div>

<footer class="footer">
    Made with
    <span class="heart">♥</span>
    by
    <a href="https://www.instagram.com/2aswadhh_._kr"
       target="_blank"
       rel="noopener noreferrer"
       class="instagram-link">
        <span class="instagram-icon">◎</span>
        @aswadh_kr
    </a>
</footer>

</main>

<script>
const STREAM_URL = {stream_url!r};
const SHARE_URL = {share_url!r};

function setStatus(text) {{
    const el = document.getElementById("status");
    if (el) el.textContent = text;
}}

async function copyShareLink() {{
    try {{
        await navigator.clipboard.writeText(SHARE_URL);
        setStatus("Adolf-StreamX • SHARE LINK COPIED ✓");
    }} catch (_) {{
        window.prompt("Copy this share link:", SHARE_URL);
    }}
}}

function startVideo() {{
    const area = document.getElementById("playerArea");
    if (!area || area.querySelector("video")) return;

    area.classList.add("playing");
    area.innerHTML = `
        <div class="video-shell">
            <video id="mainVideo" controls playsinline preload="metadata" autoplay src="${{STREAM_URL}}"></video>
            <div id="videoError" class="video-error">
                Browser could not decode this video's codec/container.
            </div>
        </div>`;

    const video = document.getElementById("mainVideo");
    const errorBox = document.getElementById("videoError");

    video.addEventListener("loadstart", () => setStatus("Adolf-StreamX • LOADING…"));
    video.addEventListener("waiting", () => setStatus("Adolf-StreamX • BUFFERING…"));
    video.addEventListener("canplay", () => setStatus("Adolf-StreamX • READY ▶"));
    video.addEventListener("play", () => setStatus("Adolf-StreamX • PLAYING ▶"));
    video.addEventListener("pause", () => setStatus("Adolf-StreamX • PAUSED"));
    video.addEventListener("ended", () => setStatus("Adolf-StreamX • ENDED"));
    video.addEventListener("error", () => {{
        errorBox.style.display = "block";
        setStatus("Adolf-StreamX • BROWSER CODEC ERROR");
    }});

    // This call is made from the user's button click, so mobile browsers are
    // allowed to start playback with audio in normal circumstances.
    video.play().catch(() => {{
        setStatus("Adolf-StreamX • TAP PLAY TO START");
    }});
}}

function togglePlayers() {{
    const players = document.getElementById("players");
    if (!players) return;
    players.style.display = players.style.display === "grid" ? "none" : "grid";
}}

function openPlayer(player) {{
    const noScheme = STREAM_URL.replace("https://", "").replace("http://", "");
    const scheme = STREAM_URL.startsWith("https://") ? "https" : "http";
    let intent = "";

    if (player === "mx") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";package=com.mxtech.videoplayer.ad;type=video/*;end;";
    else if (player === "vlc") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";package=org.videolan.vlc;type=video/*;end;";
    else if (player === "playit") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";package=com.playit.videoplayer;type=video/*;end;";
    else if (player === "kmplayer") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";package=com.kmplayer;type=video/*;end;";
    else if (player === "nplayer") intent = "intent://" + noScheme + "#Intent;scheme=" + scheme + ";type=video/*;end;";

    if (intent) location.href = intent;
}}
</script>
</body>
</html>"""

