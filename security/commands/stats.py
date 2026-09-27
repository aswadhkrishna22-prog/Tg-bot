import html
from telethon import events
from security.auth import is_admin
from security.config import OWNER_ID
from security.database import is_blocked
from security.proxy_database import purge_user_files
from security.security_engine import (_v2_now, v2_user_stats, temporary_block_user, SECURITY_RATE_WINDOW, SECURITY_MAX_REQUESTS, SECURITY_MAX_STREAMS, SECURITY_AUTO_BLOCK_THRESHOLD, SECURITY_TEMP_BLOCK_MINUTES)
from security.state import (security_v2_state, security_v2_ip_hits, security_v2_user_hits)

async def security_stats_command(event):
    if not is_admin(event):
        return
    now = _v2_now()
    await event.reply(
        "📊 <b>SECURITY V2 STATS</b>\n\n"
        f"👥 Tracked users: <code>{len(security_v2_user_hits)}</code>\n"
        f"🌐 Tracked IPs: <code>{len(security_v2_ip_hits)}</code>\n"
        f"📡 Requests scanned: <code>{security_v2_state['requests_scanned']}</code>\n"
        f"🚫 Auto-blocks: <code>{security_v2_state['auto_blocks']}</code>\n"
        f"🔐 Lockdown: <code>{'ON' if security_v2_state['lockdown'] else 'OFF'}</code>\n"
        f"⏱️ Window: <code>{SECURITY_RATE_WINDOW}s</code> / <code>{SECURITY_MAX_REQUESTS}</code> requests\n"
        f"🕐 Last scan: <code>{now - security_v2_state['last_scan']}s ago</code>",
        parse_mode="html"
    )

async def user_stats_command(event):
    if not is_admin(event):
        return
    match = event.pattern_match
    uid = int(match.group(1)) if match.group(1) else event.sender_id
    stats = v2_user_stats(uid)
    await event.reply(
        "👤 <b>USER SECURITY STATS</b>\n\n"
        f"🆔 <code>{uid}</code>\n"
        f"📡 Requests: <code>{stats['requests']}</code>\n"
        f"▶️ Streams: <code>{stats['streams']}</code>\n"
        f"📥 Downloads: <code>{stats['downloads']}</code>\n"
        f"⚠️ Strikes: <code>{stats['strikes']}</code>\n"
        f"🚫 Blocked: <code>{'YES' if is_blocked(uid) else 'NO'}</code>",
        parse_mode="html"
    )

async def top_users_command(event):
    if not is_admin(event):
        return
    ranked = sorted(security_v2_user_hits.items(), key=lambda x: x[1], reverse=True)[:20]
    if not ranked:
        await event.reply("📭 No recent request data.")
        return
    lines = ["📈 <b>TOP USERS</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
    for index, (uid, count) in enumerate(ranked, 1):
        lines.append(f"{index}. <code>{uid}</code> — <code>{count}</code> requests")
    await event.reply("\n".join(lines), parse_mode="html")

async def top_ips_command(event):
    if not is_admin(event):
        return
    ranked = sorted(security_v2_ip_hits.items(), key=lambda x: x[1], reverse=True)[:20]
    if not ranked:
        await event.reply("📭 No recent IP data.")
        return
    lines = ["🌐 <b>TOP IPS</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
    for index, (ip, count) in enumerate(ranked, 1):
        lines.append(f"{index}. <code>{html.escape(ip)}</code> — <code>{count}</code> requests")
    await event.reply("\n".join(lines), parse_mode="html")

async def lockdown_command(event):
    if not is_admin(event):
        return
    security_v2_state["lockdown"] = not security_v2_state["lockdown"]
    state = "ENABLED" if security_v2_state["lockdown"] else "DISABLED"
    await event.reply(f"🚨 <b>SECURITY LOCKDOWN {state}</b>", parse_mode="html")

async def tempblock_command(event):
    if not is_admin(event):
        return
    match = event.pattern_match
    uid = int(match.group(1))
    minutes = int(match.group(2) or SECURITY_TEMP_BLOCK_MINUTES)
    reason = (match.group(3) or "Temporary administrator block").strip()
    if uid == OWNER_ID:
        await event.reply("❌ You cannot block the owner.")
        return
    temporary_block_user(uid, reason, minutes=minutes)
    removed = purge_user_files(uid)
    await event.reply(
        "⏱️ <b>TEMPORARY BLOCK</b>\n\n"
        f"👤 User: <code>{uid}</code>\n"
        f"⏳ Duration: <code>{minutes} min</code>\n"
        f"🗑️ Links revoked: <code>{removed}</code>",
        parse_mode="html"
    )

async def v2_help_command(event):
    if not is_admin(event):
        return
    await event.reply(
        "🛡️ <b>SECURITY V2</b>\n\n"
        "<code>/stats</code> — global security stats\n"
        "<code>/userstats USER_ID</code> — user stats\n"
        "<code>/topusers</code> — busiest users\n"
        "<code>/topips</code> — busiest IPs\n"
        "<code>/tempblock USER_ID MINUTES reason</code> — temporary block\n"
        "<code>/lockdown</code> — toggle emergency monitoring lockdown\n\n"
        f"Limits: <code>{SECURITY_MAX_REQUESTS}</code> requests/{SECURITY_RATE_WINDOW}s, "
        f"<code>{SECURITY_MAX_STREAMS}</code> stream events/{SECURITY_RATE_WINDOW}s, "
        f"<code>{SECURITY_AUTO_BLOCK_THRESHOLD}</code> strikes → temp block.",
        parse_mode="html"
    )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern='^/stats$'))(security_stats_command)
    security_bot.on(events.NewMessage(pattern='^/userstats(?:\\s+(\\d+))?$'))(user_stats_command)
    security_bot.on(events.NewMessage(pattern='^/topusers$'))(top_users_command)
    security_bot.on(events.NewMessage(pattern='^/topips$'))(top_ips_command)
    security_bot.on(events.NewMessage(pattern='^/lockdown$'))(lockdown_command)
    security_bot.on(events.NewMessage(pattern='^/tempblock\\s+(\\d+)(?:\\s+(\\d+))?(?:\\s+(.+))?$'))(tempblock_command)
    security_bot.on(events.NewMessage(pattern='^/v2help$'))(v2_help_command)
