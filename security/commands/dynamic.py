"""Admin command management for dynamic Main Bot commands.

The multi-page draft is stored as a JSON envelope in the existing
``bot_commands.response`` field. The Main Bot dynamic fallback must decode
this envelope to provide user-facing Back/Next navigation.
"""

import html
import json

from telethon import Button, events

from security.auth import is_admin
from security.command_repository import (
    command_exists,
    create_command,
    disable_command,
    get_command,
    list_commands,
    normalize_command,
    update_command,
)
from security.state import clear_pending_action, get_pending_action, set_pending_action


# Response drafts are kept only while the admin is completing /cmdadd or /cmded.
# The final command is written to PostgreSQL only after the admin presses Next.
_command_drafts = {}


def _draft_key(user_id):
    return int(user_id)


def _next_button(command: str, page_no: int = 1):
    return Button.inline("Next ➡️", data=f"cmdnext:{command}:{page_no}".encode())


def _skip_button():
    return Button.inline("Skip buttons", data=b"cmdskip")


async def cmdadd_command(event):
    if not is_admin(event):
        return
    parts = (event.raw_text or "").split(None, 1)
    if len(parts) != 2:
        await event.reply("📝 Usage: <code>/cmdadd help</code>", parse_mode="html")
        return
    try:
        command = normalize_command(parts[1])
    except ValueError as error:
        await event.reply(f"❌ {html.escape(str(error))}", parse_mode="html")
        return
    if command_exists(command):
        await event.reply(
            "❌ That dynamic command already exists. Use <code>/cmded</code> to edit it.",
            parse_mode="html",
        )
        return

    _command_drafts.pop(_draft_key(event.sender_id), None)
    set_pending_action(event.sender_id, f"cmdadd:{command}")
    await event.reply(
        f"📝 <b>ADD /{html.escape(command)}</b>\n\n"
        "Send the response message now.\n"
        "Maximum: <code>4096</code> characters.\n\n"
        "Use /cancel to cancel.",
        parse_mode="html",
    )


async def cmded_command(event):
    if not is_admin(event):
        return
    parts = (event.raw_text or "").split(None, 1)
    if len(parts) != 2:
        await event.reply("📝 Usage: <code>/cmded help</code>", parse_mode="html")
        return
    try:
        command = normalize_command(parts[1])
    except ValueError as error:
        await event.reply(f"❌ {html.escape(str(error))}", parse_mode="html")
        return
    row = get_command(command, enabled_only=False)
    if not row:
        await event.reply("❌ Dynamic command not found.", parse_mode="html")
        return

    _command_drafts.pop(_draft_key(event.sender_id), None)
    set_pending_action(event.sender_id, f"cmded:{command}")
    await event.reply(
        f"✏️ <b>EDIT /{html.escape(command)}</b>\n\n"
        "Send the new response message.\n"
        "Maximum: <code>4096</code> characters.\n\n"
        "Use /cancel to cancel.",
        parse_mode="html",
    )


async def cmddel_command(event):
    if not is_admin(event):
        return
    parts = (event.raw_text or "").split(None, 1)
    if len(parts) != 2:
        await event.reply("🗑️ Usage: <code>/cmddel help</code>", parse_mode="html")
        return
    try:
        command = normalize_command(parts[1])
    except ValueError as error:
        await event.reply(f"❌ {html.escape(str(error))}", parse_mode="html")
        return
    if disable_command(command, event.sender_id):
        await event.reply(f"✅ <code>/{html.escape(command)}</code> disabled.", parse_mode="html")
    else:
        await event.reply("❌ Dynamic command not found or DB operation failed.", parse_mode="html")


async def cmdlist_command(event):
    if not is_admin(event):
        return
    rows = list_commands(100)
    if not rows:
        await event.reply("📭 No dynamic commands found (or database unavailable).", parse_mode="html")
        return
    lines = [
        "╭━━━━━━━━━━━━━━━━━━━━━━╮",
        "      🤖 DYNAMIC COMMANDS",
        "╰━━━━━━━━━━━━━━━━━━━━━━╯",
        "",
    ]
    for row in rows:
        status = "🟢 ON" if row["enabled"] else "🔴 OFF"
        lines.append(
            f"• <code>/{html.escape(row['command'])}</code> — {status} — "
            f"{html.escape(str(row['parse_mode']))}"
        )
    await event.reply("\n".join(lines), parse_mode="html")


async def dynamic_interactive_input(event):
    """Collect page text for /cmdadd or /cmded."""
    if not is_admin(event):
        return
    pending = get_pending_action(event.sender_id)
    draft = _command_drafts.get(_draft_key(event.sender_id))
    if not isinstance(pending, str) or not pending.startswith(("cmdadd:", "cmded:")):
        return
    if draft and draft.get("stage") in ("buttons", "finish"):
        return

    value = (event.raw_text or "").strip()
    if not value:
        await event.reply("❌ Response cannot be empty.", parse_mode="html")
        return
    if len(value) > 4096:
        await event.reply("❌ Response is too long. Maximum is 4096 characters.", parse_mode="html")
        return

    command = pending.split(":", 1)[1]

    if not draft:
        draft = {
            "action": pending.split(":", 1)[0],
            "command": command,
            "pages": [value],
            "stage": "page",
        }
        _command_drafts[_draft_key(event.sender_id)] = draft
    else:
        if draft.get("stage") != "page":
            return
        if len(draft.get("pages", [])) >= 20:
            draft["stage"] = "buttons"
            await _ask_for_buttons(event, draft)
            return
        draft["pages"].append(value)

    page_no = len(draft["pages"])
    nav = []
    if page_no > 1:
        nav.append(_back_button(command, page_no))
    nav.append(_next_button(command, page_no))
    nav.append(_finish_button(command, page_no))

    await event.reply(
        f"📄 <b>Page {page_no} received.</b>\n\n"
        "Use <b>Next ➡️</b> to add another page, "
        "<b>Back</b> to replace the current page, or "
        "<b>Finish ➡️</b> to continue to optional buttons.",
        buttons=[nav],
        parse_mode="html",
    )


def _back_button(command: str, page_no: int):
    if page_no <= 1:
        return None
    return Button.inline("⬅️ Back", data=f"cmdback:{command}:{page_no}".encode())


def _finish_button(command: str, page_no: int):
    return Button.inline("Finish ➡️", data=f"cmdfinish:{command}:{page_no}".encode())


def _serialize_pages(pages):
    return json.dumps(
        {"type": "paged_command", "pages": pages},
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def _finish_without_buttons(event, draft):
    user_id = _draft_key(event.sender_id)
    action = draft["action"]
    command = draft["command"]
    pages = draft.get("pages") or [draft.get("response", "")]

    # The existing repository has one response column. Store the page
    # collection in a JSON envelope. Main Bot must decode this envelope
    # for actual user-facing Back/Next navigation.
    response_payload = _serialize_pages(pages)

    clear_pending_action(user_id)
    _command_drafts.pop(user_id, None)

    ok = (
        create_command(command, response_payload, event.sender_id)
        if action == "cmdadd"
        else update_command(command, response_payload, event.sender_id)
    )
    if ok:
        verb = "created" if action == "cmdadd" else "updated"
        await event.respond(
            f"✅ <code>/{html.escape(command)}</code> {verb} successfully "
            f"with {len(pages)} page(s).",
            parse_mode="html",
        )
    else:
        await event.respond(
            "❌ Database operation failed. No bot crash occurred.",
            parse_mode="html",
        )


async def _ask_for_buttons(event, draft):
    await event.respond(
        "🔘 <b>Button setup</b>\n\n"
        "Send buttons as a JSON array, for example:\n\n"
        '<code>[[{"text":"📺 CONNECT TV","url":"https://adolfbot.s.gy"}]]</code>\n\n'
        "Or press <b>Skip buttons</b>.\n"
        "Use /cancel to cancel.",
        buttons=[[_skip_button()]],
        parse_mode="html",
    )


async def dynamic_next_callback(event):
    if not is_admin(event):
        await event.answer("Not authorized.", alert=True)
        return

    data = event.data.decode("utf-8", "ignore")
    if not data.startswith("cmdnext:"):
        return

    parts = data.split(":")
    if len(parts) != 3:
        await event.answer("Invalid setup state.", alert=True)
        return

    command = parts[1]
    try:
        page_no = int(parts[2])
    except ValueError:
        await event.answer("Invalid page.", alert=True)
        return

    draft = _command_drafts.get(_draft_key(event.sender_id))
    pending = get_pending_action(event.sender_id)
    if (
        not draft
        or draft.get("stage") != "page"
        or pending not in (f"cmdadd:{command}", f"cmded:{command}")
        or len(draft.get("pages", [])) != page_no
    ):
        await event.answer("This command setup expired.", alert=True)
        return

    if page_no >= 20:
        draft["stage"] = "buttons"
        await event.answer("Maximum 20 pages reached.", alert=True)
        await _ask_for_buttons(event, draft)
        return

    await event.answer("Send the next page")
    await event.respond(
        f"📄 <b>Page {page_no + 1}</b>\n\n"
        "Send the response text for this page.\n"
        "Maximum: <code>4096</code> characters.\n\n"
        "Use /cancel to cancel.",
        parse_mode="html",
    )


async def dynamic_back_callback(event):
    if not is_admin(event):
        await event.answer("Not authorized.", alert=True)
        return

    data = event.data.decode("utf-8", "ignore")
    if not data.startswith("cmdback:"):
        return

    parts = data.split(":")
    if len(parts) != 3:
        await event.answer("Invalid page.", alert=True)
        return

    command = parts[1]
    try:
        page_no = int(parts[2])
    except ValueError:
        await event.answer("Invalid page.", alert=True)
        return

    draft = _command_drafts.get(_draft_key(event.sender_id))
    pending = get_pending_action(event.sender_id)
    if (
        not draft
        or draft.get("stage") != "page"
        or pending not in (f"cmdadd:{command}", f"cmded:{command}")
        or page_no != len(draft.get("pages", []))
        or page_no <= 1
    ):
        await event.answer("This command setup expired.", alert=True)
        return

    draft["pages"].pop()
    await event.answer("Back")
    await event.respond(
        f"📄 <b>Page {len(draft['pages'])}</b>\n\n"
        "Send the replacement response for this page.",
        parse_mode="html",
    )


async def dynamic_finish_callback(event):
    if not is_admin(event):
        await event.answer("Not authorized.", alert=True)
        return

    data = event.data.decode("utf-8", "ignore")
    if not data.startswith("cmdfinish:"):
        return

    parts = data.split(":")
    if len(parts) != 3:
        await event.answer("Invalid setup state.", alert=True)
        return

    command = parts[1]
    try:
        page_no = int(parts[2])
    except ValueError:
        await event.answer("Invalid page.", alert=True)
        return

    draft = _command_drafts.get(_draft_key(event.sender_id))
    pending = get_pending_action(event.sender_id)
    if (
        not draft
        or draft.get("stage") != "page"
        or pending not in (f"cmdadd:{command}", f"cmded:{command}")
        or len(draft.get("pages", [])) != page_no
    ):
        await event.answer("This command setup expired.", alert=True)
        return

    draft["stage"] = "buttons"
    await event.answer("Buttons")
    await _ask_for_buttons(event, draft)


async def dynamic_skip_callback(event):
    if not is_admin(event):
        await event.answer("Not authorized.", alert=True)
        return
    if event.data != b"cmdskip":
        return

    draft = _command_drafts.get(_draft_key(event.sender_id))
    pending = get_pending_action(event.sender_id)
    if not draft or not isinstance(pending, str) or not pending.startswith(("cmdadd:", "cmded:")):
        await event.answer("This command setup expired.", alert=True)
        return

    await event.answer("Saving...")
    await _finish_without_buttons(event, draft)


async def dynamic_button_input(event):
    """Collect optional button JSON after the page flow is finished."""
    if not is_admin(event):
        return

    pending = get_pending_action(event.sender_id)
    draft = _command_drafts.get(_draft_key(event.sender_id))
    if (
        not draft
        or draft.get("stage") != "buttons"
        or pending not in (f"cmdadd:{draft['command']}", f"cmded:{draft['command']}")
    ):
        return

    value = (event.raw_text or "").strip()
    if not value or value.lower() == "/skip":
        await _finish_without_buttons(event, draft)
        return

    try:
        buttons = json.loads(value)
    except json.JSONDecodeError:
        await event.reply(
            "❌ Invalid JSON. Example:\n"
            '<code>[[{"text":"📺 CONNECT TV","url":"https://adolfbot.s.gy"}]]</code>',
            parse_mode="html",
        )
        return

    action = draft["action"]
    command = draft["command"]
    pages = draft.get("pages", [])
    response_payload = _serialize_pages(pages)

    try:
        ok = (
            create_command(command, response_payload, event.sender_id, buttons=buttons)
            if action == "cmdadd"
            else update_command(command, response_payload, event.sender_id, buttons=buttons)
        )
    except ValueError as error:
        await event.reply(f"❌ {html.escape(str(error))}", parse_mode="html")
        return

    clear_pending_action(event.sender_id)
    _command_drafts.pop(_draft_key(event.sender_id), None)

    if ok:
        verb = "created" if action == "cmdadd" else "updated"
        await event.reply(
            f"✅ <code>/{html.escape(command)}</code> {verb} successfully "
            f"with {len(pages)} page(s) and buttons.",
            parse_mode="html",
        )
    else:
        await event.reply(
            "❌ Database operation failed. No bot crash occurred.",
            parse_mode="html",
        )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern=r"^/cmdadd(?:\s+(.+))?$"))(cmdadd_command)
    security_bot.on(events.NewMessage(pattern=r"^/cmded(?:\s+(.+))?$"))(cmded_command)
    security_bot.on(events.NewMessage(pattern=r"^/cmddel(?:\s+(.+))?$"))(cmddel_command)
    security_bot.on(events.NewMessage(pattern=r"^/cmdlist$"))(cmdlist_command)
    security_bot.on(events.CallbackQuery(data=b"cmdskip"))(dynamic_skip_callback)
    security_bot.on(events.CallbackQuery(pattern=rb"^cmdnext:"))(dynamic_next_callback)
    security_bot.on(events.CallbackQuery(pattern=rb"^cmdback:"))(dynamic_back_callback)
    security_bot.on(events.CallbackQuery(pattern=rb"^cmdfinish:"))(dynamic_finish_callback)
    # Keep these after the existing command handlers. The button-input handler
    # only acts while a dynamic-command draft is active.
    security_bot.on(events.NewMessage(pattern=r"^(?!/).+"))(dynamic_interactive_input)
    security_bot.on(events.NewMessage(pattern=r"^(?!/).+"))(dynamic_button_input)
