import html
from telethon import events
from security.auth import is_admin
from security.database import is_blocked
from security.proxy_database import files_pg_db, get_user_files
from security.state import set_pending_action

async def inspect_command(event):

    if not is_admin(event):
        return

    match = event.pattern_match

    # --------------------------------------------------------
    # /inspect without USER_ID → ask
    # --------------------------------------------------------

    if not match.group(1):

        set_pending_action(
            event.sender_id,
            "inspect"
        )

        await event.reply(
            "🔎 <b>USER INSPECTION</b>\n\n"
            "Send the <b>Telegram User ID</b> you want to inspect.\n\n"
            "Example:\n"
            "<code>8540425480</code>\n\n"
            "Use /cancel to cancel.",
            parse_mode="html"
        )

        return

    user_id = int(
        match.group(1)
    )

    await perform_inspect(
        event,
        user_id
    )

async def perform_inspect(event, user_id):

    try:

        files = get_user_files(
            user_id
        )

        status = (
            "🚫 BLOCKED"
            if is_blocked(user_id)
            else "✅ ACTIVE"
        )

        with files_pg_db() as db:

            with db.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT
                        token,
                        filename,
                        action,
                        ip,
                        user_agent,
                        accessed_at
                    FROM access_logs
                    WHERE chat_id = %s
                    ORDER BY accessed_at DESC
                    LIMIT 100
                    """,
                    (int(user_id),)
                )

                history = cursor.fetchall()

        if not files and not history:

            await event.reply(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "       🔎 USER INSPECTION\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"Status: {status}\n\n"
                "📭 No files or access history found.",
                parse_mode="html"
            )

            return

        # ----------------------------------------------------
        # IMPORTANT:
        # Telegram messages have a size limit.
        # Send files/history separately.
        # ----------------------------------------------------

        await event.reply(
            "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
            "       🔎 USER INSPECTION\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"Status: {status}\n"
            f"📦 Files: <code>{len(files)}</code>\n"
            f"📊 Logged requests: <code>{len(history)}</code>",
            parse_mode="html"
        )

        # ----------------------------------------------------
        # FILES
        # ----------------------------------------------------

        if files:

            file_lines = [
                "📦 <b>ACTIVE FILES</b>",
                "━━━━━━━━━━━━━━━━━━━━━━"
            ]

            for index, row in enumerate(
                files,
                start=1
            ):

                filename = html.escape(
                    str(row["filename"] or "Unknown")
                )

                token = html.escape(
                    str(row["token"] or "")
                )

                size = int(
                    row["size"] or 0
                )

                if size >= 1024 ** 3:

                    size_text = (
                        f"{size / 1024 ** 3:.2f} GB"
                    )

                elif size >= 1024 ** 2:

                    size_text = (
                        f"{size / 1024 ** 2:.2f} MB"
                    )

                elif size >= 1024:

                    size_text = (
                        f"{size / 1024:.2f} KB"
                    )

                else:

                    size_text = f"{size} B"

                block = (
                    f"\n<b>{index}. {filename}</b>\n"
                    f"📦 Size: <code>{size_text}</code>\n"
                    f"🔑 Token: <code>{token}</code>\n"
                )

                # Prevent Telegram message overflow.
                if (
                    len("\n".join(file_lines))
                    + len(block)
                    > 3500
                ):

                    await event.reply(
                        "\n".join(file_lines),
                        parse_mode="html"
                    )

                    file_lines = []

                file_lines.append(
                    block
                )

            if file_lines:

                await event.reply(
                    "\n".join(file_lines),
                    parse_mode="html"
                )

        # ----------------------------------------------------
        # ACCESS HISTORY
        # ----------------------------------------------------

        if history:

            history_lines = [
                "📊 <b>ACCESS HISTORY</b>",
                "━━━━━━━━━━━━━━━━━━━━━━"
            ]

            for row in history:

                filename = html.escape(
                    str(row["filename"] or "Unknown")
                )

                action = (
                    str(row["action"] or "unknown")
                    .lower()
                )

                ip = html.escape(
                    str(row["ip"] or "Unknown")
                )

                accessed_at = html.escape(
                    str(row["accessed_at"] or "Unknown")
                )

                if action == "watch":

                    icon = "👁️"
                    action_name = "WATCH PAGE"

                elif action == "stream":

                    icon = "▶️"
                    action_name = "STREAM"

                elif action == "download":

                    icon = "📥"
                    action_name = "DOWNLOAD"

                else:

                    icon = "❔"
                    action_name = action.upper()

                block = (
                    f"\n{icon} <b>{action_name}</b>\n"
                    f"🎬 {filename}\n"
                    f"🌐 IP: <code>{ip}</code>\n"
                    f"🕐 <code>{accessed_at}</code>\n"
                )

                if (
                    len("\n".join(history_lines))
                    + len(block)
                    > 3500
                ):

                    await event.reply(
                        "\n".join(history_lines),
                        parse_mode="html"
                    )

                    history_lines = []

                history_lines.append(
                    block
                )

            if history_lines:

                await event.reply(
                    "\n".join(history_lines),
                    parse_mode="html"
                )
    except Exception as error:

        print(
            "[SECURITY] Inspect error:",
            error
        )

        await event.reply(
            "❌ <b>Inspect failed</b>\n\n"
            f"<code>{html.escape(str(error))}</code>",
            parse_mode="html"
        )

def register(security_bot):
    security_bot.on(events.NewMessage(pattern=r"^/inspect(?:\s+(\d+))?$"))(inspect_command)
