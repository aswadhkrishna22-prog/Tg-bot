"""PostgreSQL repository for dynamic Main Bot commands.

This module owns only the bot_commands control-plane data. It does not
modify existing Security Bot tables or hard-coded Telegram handlers.
"""

import json
import re
from typing import Any

from psycopg.types.json import Json

from security.proxy_database import files_pg_db

COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")
ALLOWED_PARSE_MODES = {"HTML", "Markdown", "MarkdownV2", "plain"}


class CommandRepositoryError(RuntimeError):
    """Controlled repository failure."""


def normalize_command(command: str) -> str:
    value = str(command or "").strip().lstrip("/").lower()
    if not COMMAND_RE.fullmatch(value):
        raise ValueError("Command must contain only a-z, 0-9 and _ (1-32 chars).")
    return value


def _normalize_parse_mode(parse_mode: str | None) -> str:
    value = str(parse_mode or "HTML").strip()
    if value not in ALLOWED_PARSE_MODES:
        raise ValueError("Unsupported parse mode.")
    return value


def _normalize_buttons(buttons: Any) -> Any:
    if buttons is None:
        return None
    if not isinstance(buttons, list):
        raise ValueError("Buttons must be a JSON array.")
    if len(buttons) > 20:
        raise ValueError("Maximum 20 button rows are allowed.")
    for row in buttons:
        if not isinstance(row, list) or len(row) > 4:
            raise ValueError("Each button row must contain 1-4 buttons.")
        for button in row:
            if not isinstance(button, dict):
                raise ValueError("Each button must be an object.")
            text = str(button.get("text", "")).strip()
            url = str(button.get("url", "")).strip()
            if not text or len(text) > 64:
                raise ValueError("Button text must be 1-64 characters.")
            if not url or not (url.startswith("https://") or url.startswith("http://") or url.startswith("tg://")):
                raise ValueError("Buttons may use only http(s):// or tg:// URLs.")
    return buttons


def ensure_schema() -> None:
    with files_pg_db() as db:
        with db.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_commands (
                    id BIGSERIAL PRIMARY KEY,
                    command TEXT NOT NULL UNIQUE,
                    response TEXT NOT NULL DEFAULT '',
                    parse_mode TEXT NOT NULL DEFAULT 'HTML',
                    buttons JSONB,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by BIGINT,
                    updated_by BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_command_audit (
                    id BIGSERIAL PRIMARY KEY,
                    command TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_id BIGINT NOT NULL,
                    success BOOLEAN NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_bot_commands_enabled_command
                ON bot_commands(enabled, command)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_bot_command_audit_created
                ON bot_command_audit(created_at DESC)
            """)
        db.commit()


def create_command(command: str, response: str, actor_id: int,
                   parse_mode: str = "HTML", buttons: Any = None) -> bool:
    command = normalize_command(command)
    parse_mode = _normalize_parse_mode(parse_mode)
    if not isinstance(response, str) or not response.strip() or len(response) > 4096:
        raise ValueError("Response must be 1-4096 characters.")
    buttons = _normalize_buttons(buttons)
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO bot_commands
                       (command, response, parse_mode, buttons, enabled, created_by, updated_by)
                       VALUES (%s, %s, %s, %s, TRUE, %s, %s)""",
                    (command, response, parse_mode, Json(buttons) if buttons is not None else None,
                     int(actor_id), int(actor_id)),
                )
                cursor.execute(
                    """INSERT INTO bot_command_audit(command, action, actor_id, success, details)
                       VALUES (%s, 'ADD', %s, TRUE, 'command created')""",
                    (command, int(actor_id)),
                )
            db.commit()
        return True
    except Exception as error:
        print("[COMMANDS] Create error:", error)
        _audit_failure(command, "ADD", actor_id, str(error))
        return False


def get_command(command: str, enabled_only: bool = True):
    command = normalize_command(command)
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                query = "SELECT id, command, response, parse_mode, buttons, enabled, created_by, updated_by, created_at, updated_at FROM bot_commands WHERE command=%s"
                params = [command]
                if enabled_only:
                    query += " AND enabled=TRUE"
                cursor.execute(query, params)
                return cursor.fetchone()
    except Exception as error:
        print("[COMMANDS] Get error:", error)
        return None


def update_command(command: str, response: str, actor_id: int,
                   parse_mode: str = "HTML", buttons: Any = None) -> bool:
    command = normalize_command(command)
    parse_mode = _normalize_parse_mode(parse_mode)
    if not isinstance(response, str) or not response.strip() or len(response) > 4096:
        raise ValueError("Response must be 1-4096 characters.")
    buttons = _normalize_buttons(buttons)
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """UPDATE bot_commands
                       SET response=%s, parse_mode=%s, buttons=%s, enabled=TRUE,
                           updated_by=%s, updated_at=NOW()
                       WHERE command=%s AND enabled=TRUE""",
                    (response, parse_mode, Json(buttons) if buttons is not None else None,
                     int(actor_id), command),
                )
                changed = cursor.rowcount == 1
                cursor.execute(
                    """INSERT INTO bot_command_audit(command, action, actor_id, success, details)
                       VALUES (%s, 'EDIT', %s, %s, %s)""",
                    (command, int(actor_id), changed, "command updated" if changed else "dynamic command not found"),
                )
            db.commit()
        return changed
    except Exception as error:
        print("[COMMANDS] Update error:", error)
        _audit_failure(command, "EDIT", actor_id, str(error))
        return False


def disable_command(command: str, actor_id: int) -> bool:
    command = normalize_command(command)
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """UPDATE bot_commands
                       SET enabled=FALSE, updated_by=%s, updated_at=NOW()
                       WHERE command=%s AND enabled=TRUE""",
                    (int(actor_id), command),
                )
                changed = cursor.rowcount == 1
                cursor.execute(
                    """INSERT INTO bot_command_audit(command, action, actor_id, success, details)
                       VALUES (%s, 'DELETE', %s, %s, %s)""",
                    (command, int(actor_id), changed, "command disabled" if changed else "dynamic command not found"),
                )
            db.commit()
        return changed
    except Exception as error:
        print("[COMMANDS] Disable error:", error)
        _audit_failure(command, "DELETE", actor_id, str(error))
        return False


def list_commands(limit: int = 100):
    limit = max(1, min(int(limit), 100))
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """SELECT id, command, enabled, parse_mode, created_by, updated_by,
                              created_at, updated_at
                       FROM bot_commands
                       ORDER BY command ASC
                       LIMIT %s""",
                    (limit,),
                )
                return cursor.fetchall()
    except Exception as error:
        print("[COMMANDS] List error:", error)
        return []


def command_exists(command: str, enabled_only: bool = False) -> bool:
    return get_command(command, enabled_only=enabled_only) is not None


def _audit_failure(command: str, action: str, actor_id: int, details: str) -> None:
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO bot_command_audit(command, action, actor_id, success, details)
                       VALUES (%s, %s, %s, FALSE, %s)""",
                    (str(command)[:32], action, int(actor_id), str(details)[:500]),
                )
            db.commit()
    except Exception as audit_error:
        print("[COMMANDS] Audit failure:", audit_error)
