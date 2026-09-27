"""Lightweight service health monitoring for the security bot.

The security bot can monitor the two external Adolf-StreamX web endpoints.
Its own process status is represented by the bot itself and is reported on
startup/shutdown. A process cannot reliably send a message after a hard kill,
so an external watchdog is required for unexpected security-bot crashes.
"""

import asyncio
import html
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from security.config import OWNER_ID

CHECK_INTERVAL = max(15, int(os.getenv("SERVICE_MONITOR_INTERVAL", "60")))
HTTP_TIMEOUT = max(3, int(os.getenv("SERVICE_MONITOR_TIMEOUT", "10")))

WEB_HOST_URL = os.getenv("MONITOR_JUSTRUNMY_WEB_URL", "https://adolf-streamx.n.onjrnm.vip/health").strip()
RAMNAYMCLOUD_URL = os.getenv("MONITOR_RAMNAYMCLOUD_URL", "https://1tv1i3p5jabf.ramnaymcloud.com/health").strip()

SERVICE_END_AT = {
    "JustRunMy - Security": os.getenv("MONITOR_JRM_SECURITY_END_AT", "").strip(),
    "JustRunMy - Web Hosting": os.getenv("MONITOR_JRM_WEB_END_AT", "").strip(),
    "RamnaymCloud - Server": os.getenv("MONITOR_RAMNAYMCLOUD_END_AT", "").strip(),
}

SERVICE_URLS = {
    "JustRunMy - Web Hosting": WEB_HOST_URL,
    "RamnaymCloud - Server": RAMNAYMCLOUD_URL,
}

# None means not checked yet. True/False are the last observed states.
_service_states = {
    "JustRunMy - Security": True,
    "JustRunMy - Web Hosting": None,
    "RamnaymCloud - Server": None,
}
_service_changed_at = {name: time.monotonic() for name in _service_states}
_monitor_lock = asyncio.Lock()


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    return f"{hours}h {minutes}m {seconds}s"


def _parse_end_at(value):
    if not value:
        return None
    try:
        raw = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _end_text(service_name):
    end_at = _parse_end_at(SERVICE_END_AT.get(service_name, ""))
    if end_at is None:
        return "End time: not configured"
    remaining = (end_at - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        return "Server end: expired"
    return f"Server end: {_format_duration(remaining)}"


def _http_check(url):
    if not url:
        return False, "URL not configured"
    try:
        request = Request(
            url,
            headers={"User-Agent": "Adolf-StreamX-Security-Monitor/1.0"},
            method="GET",
        )
        with urlopen(request, timeout=HTTP_TIMEOUT) as response:
            status = int(getattr(response, "status", 200))
            return 200 <= status < 400, f"HTTP {status}"
    except HTTPError as error:
        return False, f"HTTP {error.code}"
    except (URLError, TimeoutError, OSError) as error:
        return False, type(error).__name__
    except Exception as error:
        return False, type(error).__name__


async def check_external_services():
    results = {}
    for name, url in SERVICE_URLS.items():
        online, detail = await asyncio.to_thread(_http_check, url)
        results[name] = {"online": online, "detail": detail}
    return results


def set_security_bot_state(online):
    _service_states["JustRunMy - Security"] = bool(online)
    _service_changed_at["JustRunMy - Security"] = time.monotonic()


def snapshot_states():
    return dict(_service_states)


def render_check(results=None):
    states = snapshot_states()
    if results:
        for name, item in results.items():
            states[name] = bool(item["online"])

    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━━━╮",
        "       ⚡ SERVER CHECK",
        "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        "",
    ]

    for name in ("JustRunMy - Security", "JustRunMy - Web Hosting", "RamnaymCloud - Server"):
        state = states[name]
        if state is True:
            icon, text = "🟢", "ON"
        elif state is False:
            icon, text = "🔴", "OFF"
        else:
            icon, text = "⚪", "UNKNOWN"
        lines.append(f"{icon} <b>{html.escape(name)}</b>")
        lines.append(f"Status: <code>{text}</code>")
        lines.append(_end_text(name))
        if results and name in results:
            lines.append(f"Check: <code>{html.escape(results[name]['detail'])}</code>")
        lines.append("")

    online_count = sum(value is True for value in states.values())
    lines.append(f"📊 Online: <code>{online_count}/3</code>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def _transition_messages(results):
    messages = []
    now = time.monotonic()
    for name, item in results.items():
        new_state = bool(item["online"])
        old_state = _service_states[name]
        _service_states[name] = new_state
        _service_changed_at[name] = now
        if old_state is None or old_state == new_state:
            continue
        if new_state:
            messages.append(
                "🟢 <b>SERVICE ONLINE</b>\n\n"
                f"📍 {html.escape(name)}\n"
                "Status: <code>ON</code>\n"
                f"Check: <code>{html.escape(item['detail'])}</code>"
            )
        else:
            messages.append(
                "🔴 <b>SERVICE OFFLINE</b>\n\n"
                f"📍 {html.escape(name)}\n"
                "Status: <code>OFF</code>\n"
                f"Check: <code>{html.escape(item['detail'])}</code>\n\n"
                "⚠️ Please check the hosting service."
            )
    return messages


async def monitor_loop(send_message):
    while True:
        try:
            async with _monitor_lock:
                results = await check_external_services()
                for message in _transition_messages(results):
                    await send_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print("[MONITOR] Loop error:", error)
        await asyncio.sleep(CHECK_INTERVAL)


def is_owner(sender_id):
    try:
        return int(sender_id or 0) == OWNER_ID
    except Exception:
        return False
