import html
from telethon import events
from security.auth import is_admin
from security.database import get_blocked_users

async def blocked_command(event):

    if not is_admin(event):
        return

    rows = get_blocked_users()

    if not rows:

        await event.reply(
            "✅ Blocklist is empty."
        )

        return

    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━━━╮",
        "       🚫 BLOCKED USERS",
        "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        ""
    ]

    for row in rows[:100]:

        user_id = int(
            row["user_id"]
        )

        reason = html.escape(
            str(row["reason"] or "No reason")
        )

        lines.append(
            f"• <code>{user_id}</code>\n"
            f"  📝 {reason}\n"
        )

    await event.reply(
        "\n".join(lines),
        parse_mode="html"
    )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern='^/blocked$'))(blocked_command)
