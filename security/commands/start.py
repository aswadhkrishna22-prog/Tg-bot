from telethon import events
from security.auth import is_admin

async def start_command(event):

    if not is_admin(event):

        await event.reply(
            "⛔ Access denied."
        )

        return

    await event.reply(
        "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
        "      🛡️ STADY SECURITY\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"

        "👥 <code>/users</code>\n"
        "View users currently using STADY-PROXY.\n\n"

        "🔎 <code>/inspect USER_ID</code>\n"
        "View a user's active files.\n\n"
        "🗑️ <code>/remove USER_ID</code>\n"
       "Remove all generated links for a user.\n\n"
         "🗑️ <code>/remove TOKEN</code>\n"
         "Remove one generated link.\n\n"

        "🚫 <code>/block USER_ID reason</code>\n"
        "Block a user and revoke their links.\n\n"

        "✅ <code>/unblock USER_ID</code>\n"
        "Unblock a user.\n\n"

        "🚷 <code>/blocked</code>\n"
        "View blocked users.\n\n"

        "🧹 <code>/purge</code>\n"
        "Remove links belonging to blocked users.",
        parse_mode="html"
    )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern='^/start$'))(start_command)
