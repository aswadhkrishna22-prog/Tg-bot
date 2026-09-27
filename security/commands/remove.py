import html
from telethon import events
from security.auth import is_admin
from security.config import OWNER_ID
from security.database import block_user
from security.proxy_database import purge_user_files, remove_token_data, remove_user_data
from security.state import (pending_actions, set_pending_action, get_pending_action, clear_pending_action)
from security.actions import confirm_action, prepare_remove
from security.commands.inspect import perform_inspect

async def remove_command(event):

    if not is_admin(event):
        return

    match = event.pattern_match

    # --------------------------------------------------------
    # /remove → ask
    # --------------------------------------------------------

    if not match.group(1):

        set_pending_action(
            event.sender_id,
            "remove"
        )

        await event.reply(
            "🗑️ <b>REMOVE DATA</b>\n\n"
            "Send either:\n\n"
            "👤 <b>User ID</b> — remove ALL generated "
            "links/files for that user.\n\n"
            "🔑 <b>Token</b> — remove ONLY that generated "
            "file/link.\n\n"
            "Example User ID:\n"
            "<code>8540425480</code>\n\n"
            "Example Token:\n"
            "<code>fd47579b090041028a6073c8ee6835cd</code>\n\n"
            "Use /cancel to cancel.",
            parse_mode="html"
        )

        return

    value = match.group(1).strip()

    await prepare_remove(
        event,
        value
    )

async def confirm_callback(event):

    if not is_admin(event):
        await event.answer(
            "⛔ Access denied.",
            alert=True
        )
        return

    try:

        data = event.data.decode(
            "utf-8"
        )

        parts = data.split(
            ":",
            2
        )

        if len(parts) != 3:

            await event.answer(
                "Invalid action.",
                alert=True
            )

            return

        _, action, value = parts

        # ----------------------------------------------------
        # BLOCK
        # ----------------------------------------------------

        if action == "block":

            user_id = int(value)

            if user_id == OWNER_ID:

                await event.answer(
                    "You cannot block yourself.",
                    alert=True
                )

                return

            pending = get_pending_action(
                event.sender_id
            )

            reason = "Blocked by administrator"

            if pending and pending.startswith(
                "block:"
            ):

                pending_parts = pending.split(
                    ":",
                    2
                )

                if len(pending_parts) == 3:

                    reason = (
                        pending_parts[2]
                        or reason
                    )

            block_user(
                user_id,
                reason
            )

            removed = purge_user_files(
                user_id
            )

            clear_pending_action(
                event.sender_id
            )

            await event.edit(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "        🚫 USER BLOCKED\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"📝 Reason: {html.escape(reason)}\n"
                f"🗑️ Links revoked: <code>{removed}</code>",
                parse_mode="html"
            )

            return

        # ----------------------------------------------------
        # REMOVE USER
        # ----------------------------------------------------

        if action == "remove_user":

            user_id = int(value)

            removed = remove_user_data(
                user_id
            )

            clear_pending_action(
                event.sender_id
            )

            await event.edit(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "        🗑️ USER DATA REMOVED\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"📦 Records removed: <code>{removed}</code>\n\n"
                "✅ Generated links and related access history removed.",
                parse_mode="html"
            )

            return

        # ----------------------------------------------------
        # REMOVE TOKEN
        # ----------------------------------------------------

        if action == "remove_token":

            token = value

            result = remove_token_data(
                token
            )

            clear_pending_action(
                event.sender_id
            )

            if not result:

                await event.edit(
                    "❌ <b>Token not found.</b>\n\n"
                    f"🔑 <code>{html.escape(token)}</code>",
                    parse_mode="html"
                )

                return

            filename = html.escape(
                str(
                    result["filename"]
                    or "Unknown"
                )
            )

            await event.edit(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "        🗑️ FILE REMOVED\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"📄 <b>{filename}</b>\n"
                f"👤 User ID: <code>{result['chat_id']}</code>\n"
                f"🔑 Token: <code>{html.escape(token)}</code>\n\n"
                "✅ Generated link and related access history removed.",
                parse_mode="html"
            )

            return

        await event.answer(
            "Unknown action.",
            alert=True
        )

    except Exception as error:

        print(
            "[SECURITY] Confirmation error:",
            error
        )

        await event.answer(
            "Operation failed.",
            alert=True
        )

        try:

            await event.edit(
                "❌ <b>Operation failed</b>\n\n"
                f"<code>{html.escape(str(error))}</code>",
                parse_mode="html"
            )

        except Exception:
            pass

async def cancel_action_callback(event):

    if not is_admin(event):
        await event.answer(
            "⛔ Access denied.",
            alert=True
        )
        return

    clear_pending_action(
        event.sender_id
    )

    await event.edit(
        "❌ <b>Action cancelled.</b>",
        parse_mode="html"
    )

async def cancel_command(event):

    if not is_admin(event):
        return

    clear_pending_action(
        event.sender_id
    )

    await event.reply(
        "❌ <b>Action cancelled.</b>",
        parse_mode="html"
    )

async def interactive_input_handler(event):

    if not is_admin(event):
        return

    pending = get_pending_action(
        event.sender_id
    )

    if not pending:
        return

    value = (
        event.raw_text or ""
    ).strip()

    # --------------------------------------------------------
    # INSPECT
    # --------------------------------------------------------

    if pending == "inspect":

        if not value.isdigit():

            await event.reply(
                "❌ Please send a numeric User ID.",
                parse_mode="html"
            )

            return

        clear_pending_action(
            event.sender_id
        )

        await perform_inspect(
            event,
            int(value)
        )

        return

    # --------------------------------------------------------
    # BLOCK
    # --------------------------------------------------------

    if pending == "block":

        if not value.isdigit():

            await event.reply(
                "❌ Please send a numeric User ID.",
                parse_mode="html"
            )

            return

        user_id = int(value)

        if user_id == OWNER_ID:

            clear_pending_action(
                event.sender_id
            )

            await event.reply(
                "❌ You cannot block yourself."
            )

            return

        set_pending_action(
            event.sender_id,
            f"block:{user_id}:Blocked by administrator"
        )

        await confirm_action(
            event,
            "block",
            user_id
        )

        return

    # --------------------------------------------------------
    # REMOVE
    # --------------------------------------------------------

    if pending == "remove":

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

        if (
            len(value) == 32
            and all(
                c in "0123456789abcdefABCDEF"
                for c in value
            )
        ):

            set_pending_action(
                event.sender_id,
                f"remove_token:{value}"
            )

            await confirm_action(
                event,
                "remove_token",
                value
            )

            return

        await event.reply(
            "❌ Invalid input.\n\n"
            "Send a User ID or 32-character token.",
            parse_mode="html"
        )

        return

def register(security_bot):
    security_bot.on(events.NewMessage(pattern=r"^/remove(?:\s+(.+))?$"))(remove_command)
    security_bot.on(events.CallbackQuery(pattern=rb"^confirm:"))(confirm_callback)
    security_bot.on(events.CallbackQuery(pattern=rb"^cancel_action$"))(cancel_action_callback)
    security_bot.on(events.NewMessage(pattern=r"^/cancel$"))(cancel_command)
    security_bot.on(events.NewMessage(pattern=r"^(?!/).+"))(interactive_input_handler)
