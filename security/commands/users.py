import html
from telethon import events
from security.auth import is_admin
from security.config import OWNER_ID
from security.database import is_blocked
from security.proxy_database import get_proxy_users

async def users_command(event):

    print(
        "[DEBUG /users] sender_id:",
        event.sender_id,
        "owner_id:",
        OWNER_ID
    )

    if not is_admin(event):
        return

    users = get_proxy_users()

    if not users:

        await event.reply(
            "📭 No users/files found."
        )

        return

    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━━━╮",
        "       👥 STADY USERS",
        "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        ""
    ]

    for row in users[:100]:

        user_id = int(row["user_id"])

        first_name = row["first_name"] or ""
        last_name = row["last_name"] or ""

        name = (
            f"{first_name} {last_name}".strip()
            or "Unknown"
        )

        first_seen = row["first_seen"]

        if first_seen:
            started = first_seen.strftime(
                "%d %b %Y, %I:%M %p"
            )
        else:
            started = "Unknown"

        count = int(row["file_count"])

        status = (
            "🚫 BLOCKED"
            if is_blocked(user_id)
            else "✅ ACTIVE"
        )

        lines.extend([
            f"👤 <b>{html.escape(name)}</b>",
            f"🆔 <code>{user_id}</code>",
            f"📅 Started: <code>{started}</code>",
            f"📁 Files: <code>{count}</code>",
            status,
            ""
        ])

    await event.reply(
        "\n".join(lines),
        parse_mode="html"
    )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern='^/users$'))(users_command)
