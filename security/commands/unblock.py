from telethon import events
from security.auth import is_admin
from security.database import unblock_user

async def unblock_command(event):

    if not is_admin(event):
        return

    user_id = int(
        event.pattern_match.group(1)
    )

    changed = unblock_user(
        user_id
    )

    if changed:

        text = (
            "✅ <b>USER UNBLOCKED</b>\n\n"
            f"User ID: <code>{user_id}</code>"
        )

    else:

        text = (
            "ℹ️ User is not currently blocked.\n\n"
            f"User ID: <code>{user_id}</code>"
        )

    await event.reply(
        text,
        parse_mode="html"
    )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern=r"^/unblock\s+(\d+)$"))(unblock_command)
