import asyncio

from telethon import TelegramClient

from security.config import API_ID, API_HASH, SECURITY_BOT_TOKEN, OWNER_ID
from security.database import init_security_database
from security.security_engine import SECURITY_V2_ENABLED, SECURITY_SCAN_INTERVAL, init_security_v2_database, scan_access_abuse, cleanup_security_v2
from security.proxy_database import purge_all_blocked_users
from security.commands import register_all
from security.v3 import setup as setup_v3, security_v3_loop, init_security_v3_shared_db
from security.service_monitor import monitor_loop, set_security_bot_state, check_external_services, render_check

security_bot = TelegramClient("security_bot", API_ID, API_HASH)
register_all(security_bot)
setup_v3(security_bot)

async def cleanup_loop():
    while True:
        try:
            removed = purge_all_blocked_users()
            if removed:
                print(f"[SECURITY] Revoked {removed} blocked-user link(s).")
        except Exception as error:
            print("[SECURITY] Cleanup error:", error)
        await asyncio.sleep(10)

async def security_v2_loop():
    while True:
        try:
            if SECURITY_V2_ENABLED:
                scan_access_abuse()
                cleanup_security_v2()
        except Exception as error:
            print("[SECURITY V2] Loop error:", error)
        await asyncio.sleep(SECURITY_SCAN_INTERVAL)

async def main():
    init_security_database()
    init_security_v2_database()
    init_security_v3_shared_db()

    print()
    print("=" * 60)
    print("       STADY-PROXY SECURITY BOT")
    print("=" * 60)
    print("[+] Connecting to Telegram...")

    await security_bot.start(bot_token=SECURITY_BOT_TOKEN)
    set_security_bot_state(True)
    me = await security_bot.get_me()
    username = me.username if me.username else str(me.id)
    print(f"[+] Security bot: @{username}")
    print(f"[+] Owner ID: {OWNER_ID}")

    async def send_monitor_message(message):
        try:
            await security_bot.send_message(OWNER_ID, message, parse_mode="html")
        except Exception as error:
            print("[MONITOR] Notification failed:", error)

    monitor_task = asyncio.create_task(monitor_loop(send_monitor_message))
    try:
        initial_results = await check_external_services()
        await send_monitor_message(render_check(initial_results))
    except Exception as error:
        print("[MONITOR] Initial check failed:", error)
    cleanup_task = asyncio.create_task(cleanup_loop())
    v2_task = asyncio.create_task(security_v2_loop())
    v3_task = asyncio.create_task(security_v3_loop())
    try:
        print("[+] Security bot is running.")
        await security_bot.run_until_disconnected()
    finally:
        set_security_bot_state(False)
        for task in (monitor_task, cleanup_task, v2_task, v3_task):
            task.cancel()
        await asyncio.gather(monitor_task, cleanup_task, v2_task, v3_task, return_exceptions=True)
        try:
            await security_bot.send_message(
                OWNER_ID,
                "🔴 <b>SECURITY BOT OFFLINE</b>\n\n"
                "📍 JustRunMy - Security\n"
                "Status: <code>OFF</code>\n\n"
                "⚠️ Manual restart may be required.",
                parse_mode="html",
            )
        except Exception as error:
            print("[STATUS] Offline notification failed:", error)
        await security_bot.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[+] Security bot stopped.")
