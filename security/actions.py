"""Security bot action orchestration helpers.

Step 5 extraction: interactive confirmation and remove preparation.
"""

from telethon import Button
import html

from security.config import OWNER_ID
from security.auth import is_admin
from security.state import (
    clear_pending_action,
    get_pending_action,
    set_pending_action,
)


async def cancel_pending_action(event):
    clear_pending_action(event.sender_id)

    await event.reply(
        "❌ <b>Action cancelled.</b>",
        parse_mode="html"
    )


async def confirm_action(event, action, value):

    if not is_admin(event):
        return

    buttons = [
        [
            Button.inline(
                "✅ Confirm",
                data=f"confirm:{action}:{value}".encode()
            ),
            Button.inline(
                "❌ Cancel",
                data=b"cancel_action"
            )
        ]
    ]

    await event.reply(
        "⚠️ <b>CONFIRM ACTION</b>\n\n"
        f"Action: <code>{html.escape(action)}</code>\n"
        f"Target: <code>{html.escape(str(value))}</code>\n\n"
        "Are you sure?",
        buttons=buttons,
        parse_mode="html"
    )


async def prepare_remove(event, value):

    # --------------------------------------------------------
    # USER ID
    # --------------------------------------------------------

    if value.isdigit():

        user_id = int(value)

        set_pending_action(
            event.sender_id,
            f"remove_user:{user_id}"
        )

        await confirm_action(
            event,
            "remove_user",
            user_id
        )

        return

    # --------------------------------------------------------
    # TOKEN
    # --------------------------------------------------------

    if (
        len(value) == 32
        and all(
            c in "0123456789abcdefABCDEF"
            for c in value
        )
    ):

        token = value

        set_pending_action(
            event.sender_id,
            f"remove_token:{token}"
        )

        await confirm_action(
            event,
            "remove_token",
            token
        )

        return

    await event.reply(
        "❌ <b>Invalid input.</b>\n\n"
        "Send either a numeric User ID or a valid 32-character token.",
        parse_mode="html"
    )


