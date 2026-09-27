from telethon import events
from security.auth import is_admin
from security.config import OWNER_ID
from security.actions import confirm_action
from security.state import set_pending_action

async def block_command(event):

    if not is_admin(event):
        return

    match = event.pattern_match

    # --------------------------------------------------------
    # /block → ask for USER_ID
    # --------------------------------------------------------

    if not match.group(1):

        set_pending_action(
            event.sender_id,
            "block"
        )

        await event.reply(
            "🚫 <b>BLOCK USER</b>\n\n"
            "Send the <b>User ID</b> you want to block.\n\n"
            "Example:\n"
            "<code>8540425480</code>\n\n"
            "Use /cancel to cancel.",
            parse_mode="html"
        )

        return

    user_id = int(
        match.group(1)
    )

    reason = (
        match.group(2)
        or "Blocked by administrator"
    ).strip()

    if user_id == OWNER_ID:

        await event.reply(
            "❌ You cannot block yourself."
        )

        return

    set_pending_action(
        event.sender_id,
        f"block:{user_id}:{reason}"
    )

    await confirm_action(
        event,
        "block",
        user_id
    )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern=r"^/block(?:\s+(\d+)(?:\s+(.+))?)?$"))(block_command)
