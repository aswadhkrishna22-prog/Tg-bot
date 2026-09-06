import html
import re
import threading
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from config import PAIR_MAX_ATTEMPTS, PAIR_ATTEMPT_WINDOW, PAIR_LOCKOUT_SECONDS
from database import create_share_token, get_file_by_pair_code

router = APIRouter()
STADY_CSS = ""
def stady_error_page():
    return ""

def metric_inc(name, amount=1):
    pass

pair_attempt_state = {}
pair_attempt_lock = threading.Lock()

def pair_page(error_message=""):
    """Standalone TV pairing page used for direct /pair and invalid-code fallbacks."""
    error_html = (
        f'<div id="pairError" style="color:#ff7b8c;text-align:center;'
        f'font-weight:700;font-size:13px;min-height:20px;margin-top:10px">'
        f'{html.escape(error_message)}</div>'
        if error_message else
        '<div id="pairError" style="color:#ff7b8c;text-align:center;'
        'font-weight:700;font-size:13px;min-height:20px;margin-top:10px"></div>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Adolf-StreamX | TV Pairing</title>
<style>{STADY_CSS}</style>
</head>
<body>
<main class="page">
<div class="brand">Adolf-StreamX</div>
<section class="frame" style="padding:24px">
<div style="text-align:center">
<h2>📺 TV PAIRING</h2>
<p style="color:#94a3b8;line-height:1.6">Enter the 6-digit code shown in Telegram.</p>
<div class="actions" style="margin-top:18px">
<input id="pairCode" class="btn" type="text" inputmode="numeric" pattern="[0-9]{{6}}" maxlength="6" placeholder="ENTER 6-DIGIT TV CODE" style="text-align:center">
<button class="btn" onclick="pairDevice()">📺 PAIR TV</button>
</div>
{error_html}
</div>
</section>
<script>
async function pairDevice() {{
    const input = document.getElementById("pairCode");
    const error = document.getElementById("pairError");
    const code = input.value.trim();
    if (!/^[0-9]{{6}}$/.test(code)) {{
        error.textContent = "Code must be 6 digits";
        input.focus();
        return;
    }}
    error.textContent = "";
    try {{
        const response = await fetch("/pair/" + code, {{headers: {{"X-Pair-AJAX": "1"}}}});
        const data = await response.json().catch(() => null);
        if (data && data.ok && data.redirect) {{
            location.href = data.redirect;
            return;
        }}
        error.textContent = (data && data.error) || "Code is not valid";
    }} catch (_) {{
        error.textContent = "Unable to verify code. Try again.";
    }}
}}
</script>
</main>
</body>
</html>"""

def pair_is_locked(client_ip):
    """Return (locked, retry_after_seconds) for this client IP."""
    now = time.monotonic()
    with pair_attempt_lock:
        state = pair_attempt_state.get(client_ip)
        if state:
            if now < state[2]:
                return True, int(state[2] - now)
    return False, 0

def register_pair_failure(client_ip):
    """Record a failed pairing attempt and apply the configured lockout."""
    now = time.monotonic()
    with pair_attempt_lock:
        state = pair_attempt_state.get(client_ip)
        # state = [first_attempt_time, attempt_count, lockout_until_time]
        if (
            not state
            or (state[2] > 0 and now >= state[2])
            or now - state[0] > PAIR_ATTEMPT_WINDOW
        ):
            state = [now, 0, 0]

        state[1] += 1
        if state[1] >= PAIR_MAX_ATTEMPTS:
            state[2] = now + PAIR_LOCKOUT_SECONDS

        pair_attempt_state[client_ip] = state
        retry_after = int(state[2] - now) if state[2] > now else 0
        return state[1], retry_after

@router.get("/pair", response_class=HTMLResponse)
async def pair_home():
    return HTMLResponse(pair_page())

@router.get("/pair/{code}")
async def pair_device(code: str, request: Request):
    code = code.strip()
    client_ip = request.client.host if request.client else "unknown"
    locked, retry_after = pair_is_locked(client_ip)
    if locked:
        metric_inc("pair_locked")
        if request.headers.get("X-Pair-AJAX") == "1":
            return JSONResponse({"ok": False, "error": f"Too many attempts. Try again in {retry_after}s."}, status_code=429, headers={"Retry-After": str(retry_after)})
        return HTMLResponse(pair_page(f"Too many attempts. Try again in {retry_after}s."), status_code=429)

    if not re.fullmatch(r"\d{6}", code):
        attempts, _ = register_pair_failure(client_ip)
        metric_inc("pair_invalid")
        if request.headers.get("X-Pair-AJAX") == "1":
            return JSONResponse({"ok": False, "error": "Code is not valid"}, status_code=422)
        return HTMLResponse(pair_page("Code is not valid"), status_code=422)

    row = get_file_by_pair_code(code)
    if not row:
        print(f"[PAIR] Invalid/unavailable code: {code!r}")
        attempts, retry_after = register_pair_failure(client_ip)
        metric_inc("pair_invalid")
        message = "Code is not valid" if retry_after <= 0 else f"Too many attempts. Try again in {retry_after}s."
        if request.headers.get("X-Pair-AJAX") == "1":
            return JSONResponse({"ok": False, "error": message}, status_code=429 if retry_after else 422, headers={"Retry-After": str(retry_after)} if retry_after else None)
        return HTMLResponse(pair_page(message), status_code=429 if retry_after else 422)

    share_token = row.get("share_token") if hasattr(row, "get") else None
    if not share_token:
        share_token = create_share_token(row["token"])
    receiver_url = f"/receive/{share_token}"

    # A successful pairing starts a fresh attempt window for this client.
    with pair_attempt_lock:
        pair_attempt_state.pop(client_ip, None)

    if request.headers.get("X-Pair-AJAX") == "1":
        return JSONResponse({"ok": True, "redirect": receiver_url}, headers={"X-Pair-Redirect": receiver_url})
    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta http-equiv="refresh" content="0;url={receiver_url}"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Adolf-StreamX | TV Paired</title></head><body style="background:#030914;color:#eaf7ff;font-family:Arial;text-align:center;padding-top:80px"><h2>📺 TV PAIRED</h2><p>Opening receiver…</p></body></html>""")

def cleanup_pair_attempts():
    now = time.monotonic()
    cutoff = now - PAIR_ATTEMPT_WINDOW
    with pair_attempt_lock:
        for client, state in list(pair_attempt_state.items()):
            if state[0] < cutoff and state[2] <= now:
                pair_attempt_state.pop(client, None)


def configure(css, error_page, metric_callback):
    global STADY_CSS, stady_error_page, metric_inc
    STADY_CSS = css
    stady_error_page = error_page
    metric_inc = metric_callback

