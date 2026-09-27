"""AI administration commands.

Owner/admin-only interface for the Gemini-powered AI repair engine.
This module does not execute arbitrary shell commands or apply fixes.
"""

import html

from security.auth import is_admin
from security.ai_repair import AIRepair, AIRepairError, MODEL


def _engine():
    return AIRepair()


async def ai_status_command(event):
    if not is_admin(event):
        return

    try:
        engine = _engine()
        status = engine.health_check()

        errors = status.get("errors") or []

        lines = [
            "╭━━━━━━━━━━━━━━━━━━━━━━╮",
            "      🤖 AI STATUS",
            "╰━━━━━━━━━━━━━━━━━━━━━━╯",
            "",
            f"Model: <code>{html.escape(str(status.get('model', 'unknown')))}</code>",
            f"Python files: <code>{status.get('python_files', 0)}</code>",
            f"Syntax: <code>{'PASS' if status.get('syntax_ok') else 'FAIL'}</code>",
        ]

        if errors:
            lines.append("")
            lines.append("<b>Errors:</b>")
            for error in errors[:10]:
                lines.append(f"• <code>{html.escape(str(error))}</code>")

        await event.reply("\n".join(lines), parse_mode="html")

    except Exception as error:
        await event.reply(
            "❌ <b>AI STATUS FAILED</b>\n\n"
            f"<code>{html.escape(str(error))}</code>",
            parse_mode="html",
        )


async def ai_test_command(event):
    if not is_admin(event):
        return

    try:
        engine = _engine()

        result = await engine.test_connection()

        await event.reply(
            "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
            "      🧪 AI TEST\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
            f"Gemini: <code>{html.escape(str(result))}</code>",
            parse_mode="html",
        )

    except AttributeError:
        # Compatibility fallback if the current AIRepair class does not
        # yet expose test_connection().
        try:
            import asyncio

            response = await asyncio.to_thread(
                engine.client.models.generate_content,
                model=MODEL,
                contents="Reply with exactly: GEMINI OK",
            )

            text = (getattr(response, "text", "") or "").strip()

            await event.reply(
                "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
                "      🧪 AI TEST\n"
                "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
                f"Gemini: <code>{html.escape(text or 'NO RESPONSE')}</code>",
                parse_mode="html",
            )

        except Exception as inner_error:
            await event.reply(
                "❌ <b>GEMINI TEST FAILED</b>\n\n"
                f"<code>{html.escape(str(inner_error))}</code>",
                parse_mode="html",
            )

    except Exception as error:
        await event.reply(
            "❌ <b>GEMINI TEST FAILED</b>\n\n"
            f"<code>{html.escape(str(error))}</code>",
            parse_mode="html",
        )


async def ai_diagnose_command(event):
    if not is_admin(event):
        return

    parts = (event.raw_text or "").split(None, 1)

    if len(parts) != 2 or not parts[1].strip():
        await event.reply(
            "🧠 <b>AI DIAGNOSE</b>\n\n"
            "Usage:\n"
            "<code>/ai_diagnose &lt;error message&gt;</code>\n\n"
            "Example:\n"
            "<code>/ai_diagnose NameError: missing_function is not defined</code>",
            parse_mode="html",
        )
        return

    error_text = parts[1].strip()

    if len(error_text) > 12000:
        await event.reply(
            "❌ Error report is too large.\n"
            "Maximum: <code>12000</code> characters.",
            parse_mode="html",
        )
        return

    try:
        await event.reply(
            "🧠 <b>Gemini is analysing the error...</b>",
            parse_mode="html",
        )

        engine = _engine()
        diagnosis = await engine.diagnose(error_text)

        summary = getattr(diagnosis, "summary", "Unknown")
        cause = getattr(diagnosis, "cause", "Unknown")
        confidence = getattr(diagnosis, "confidence", "unknown")
        fix = getattr(diagnosis, "fix", "No fix suggested")
        files = getattr(diagnosis, "files", [])

        if isinstance(files, (list, tuple)):
            files_text = ", ".join(str(item) for item in files)
        else:
            files_text = str(files)

        message = (
            "╭━━━━━━━━━━━━━━━━━━━━━━╮\n"
            "      🧠 GEMINI DIAGNOSIS\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
            f"<b>Summary:</b>\n{html.escape(str(summary))}\n\n"
            f"<b>Cause:</b>\n{html.escape(str(cause))}\n\n"
            f"<b>Confidence:</b> "
            f"<code>{html.escape(str(confidence))}</code>\n\n"
            f"<b>Suggested fix:</b>\n{html.escape(str(fix))}\n\n"
            f"<b>Files:</b>\n<code>{html.escape(files_text or 'None')}</code>"
        )

        await event.reply(message, parse_mode="html")

    except AIRepairError as error:
        await event.reply(
            "❌ <b>AI DIAGNOSIS FAILED</b>\n\n"
            f"<code>{html.escape(str(error))}</code>",
            parse_mode="html",
        )

    except Exception as error:
        await event.reply(
            "❌ <b>AI DIAGNOSIS ERROR</b>\n\n"
            f"<code>{html.escape(str(error))}</code>",
            parse_mode="html",
        )


def register(client):
    """Register AI administration commands."""

    from telethon import events

    client.add_event_handler(
        ai_status_command,
        events.NewMessage(pattern=r"^/ai_status(?:\s+.*)?$"),
    )

    client.add_event_handler(
        ai_test_command,
        events.NewMessage(pattern=r"^/ai_test(?:\s+.*)?$"),
    )

    client.add_event_handler(
        ai_diagnose_command,
        events.NewMessage(pattern=r"^/ai_diagnose(?:\s+.*)?$"),
    )
