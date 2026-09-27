from telethon import events
from security.auth import is_admin
from security.proxy_database import purge_all_blocked_users

async def purge_command(event):

    if not is_admin(event):
        return

    removed = purge_all_blocked_users()

    await event.reply(
        "🧹 <b>PURGE COMPLETE</b>\n\n"
        f"Revoked links: <code>{removed}</code>",
        parse_mode="html"
    )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern='^/purge$'))(purge_command)
