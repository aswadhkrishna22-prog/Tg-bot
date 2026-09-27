"""
AI Repair Engine for Adolf-StreamX.

Gemini is used for diagnosis and repair planning.
Actual file modification is deliberately controlled.

Environment:
    GEMINI_API_KEY
    AI_MODEL              optional, defaults to gemini-3.6-flash
    AI_REPAIR_ROOT        optional, defaults to current project directory

Admin:
    OWNER_ID              Telegram numeric owner ID
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import py_compile
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai


log = logging.getLogger("security.ai_repair")


# -------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------

MODEL = os.getenv(
    "AI_MODEL",
    "gemini-3.6-flash",
)

ROOT = Path(
    os.getenv(
        "AI_REPAIR_ROOT",
        Path(__file__).resolve().parent.parent,
    )
).resolve()

BACKUP_ROOT = ROOT / ".ai_backups"

MAX_FILE_BYTES = 512 * 1024
MAX_CONTEXT_CHARS = 120_000


@dataclass
class Diagnosis:
    summary: str
    cause: str
    confidence: str
    suggested_fix: str
    files: list[str]


class AIRepairError(Exception):
    pass


class AIRepair:
    """
    Safe AI repair controller.

    Gemini:
        - diagnoses errors
        - proposes a repair
        - does NOT receive arbitrary shell execution authority

    Local engine:
        - validates paths
        - creates backups
        - applies explicitly supplied patches
        - runs syntax checks
        - rolls back failed changes
    """

    def __init__(self, root: Path = ROOT) -> None:
        self.root = root.resolve()

        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise AIRepairError(
                "GEMINI_API_KEY is not configured."
            )

        self.client = genai.Client(
            api_key=api_key
        )

    # ---------------------------------------------------------
    # SECURITY
    # ---------------------------------------------------------

    def is_admin(self, user_id: int | str) -> bool:
        """
        Owner-only authorization.

        Supports:
            OWNER_ID=123456789
        """

        configured = os.getenv(
            "OWNER_ID",
            "",
        ).strip()

        if not configured:
            log.warning(
                "OWNER_ID is not configured."
            )
            return False

        return str(user_id) == configured

    def safe_path(
        self,
        relative_path: str,
    ) -> Path:
        """
        Prevent AI/user supplied paths from escaping
        the project directory.
        """

        candidate = (
            self.root / relative_path
        ).resolve()

        try:
            candidate.relative_to(
                self.root
            )
        except ValueError as exc:
            raise AIRepairError(
                f"Unsafe path rejected: {relative_path}"
            ) from exc

        return candidate

    # ---------------------------------------------------------
    # PROJECT INSPECTION
    # ---------------------------------------------------------

    def collect_python_files(
        self,
    ) -> list[Path]:

        files: list[Path] = []

        for path in self.root.rglob("*.py"):

            if any(
                part in {
                    ".git",
                    ".venv",
                    "venv",
                    "__pycache__",
                    ".ai_backups",
                }
                for part in path.parts
            ):
                continue

            files.append(path)

        return sorted(files)

    def read_project_context(self) -> str:

        chunks: list[str] = []
        total = 0

        for path in self.collect_python_files():

            try:

                if path.stat().st_size > MAX_FILE_BYTES:
                    continue

                text = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

                relative = path.relative_to(
                    self.root
                )

                chunk = (
                    f"\n===== {relative} =====\n"
                    f"{text}\n"
                )

                if (
                    total + len(chunk)
                    > MAX_CONTEXT_CHARS
                ):
                    break

                chunks.append(chunk)
                total += len(chunk)

            except OSError:
                continue

        return "".join(chunks)

    # ---------------------------------------------------------
    # GEMINI RESPONSE CLEANUP
    # ---------------------------------------------------------

    @staticmethod
    def _clean_json_response(
        text: str,
    ) -> str:
        """
        Gemini may occasionally wrap JSON inside
        Markdown code fences.

        Convert:

            ```json
            {...}
            ```

        into plain JSON.
        """

        cleaned = text.strip()

        if cleaned.startswith("```"):
            lines = cleaned.splitlines()

            if lines:
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            cleaned = "\n".join(lines).strip()

        return cleaned

    # ---------------------------------------------------------
    # ERROR DIAGNOSIS
    # ---------------------------------------------------------

    async def diagnose(
        self,
        error_text: str,
        *,
        extra_context: str = "",
    ) -> Diagnosis:

        project = self.read_project_context()

        prompt = f"""
You are the diagnostic engine for Adolf-StreamX.

Analyze the Python/Telegram bot failure below.

IMPORTANT SECURITY RULES:

- Do not invent files.
- Do not invent database tables.
- Prefer existing migration or repository functions.
- Do not expose secrets, API keys, tokens, passwords,
  cookies, session strings, or DATABASE_URL values.
- Do not recommend destructive operations unless
  absolutely necessary.
- This is diagnosis only.
- Do NOT execute commands.
- Do NOT provide shell commands.
- Do NOT assume access to the operating system.
- Do NOT modify files yourself.
- Return ONLY valid JSON.
- Do not wrap the JSON in Markdown.

Required JSON schema:

{{
  "summary": "...",
  "cause": "...",
  "confidence": "high|medium|low",
  "suggested_fix": "...",
  "files": ["relative/path.py"]
}}

ERROR:
{error_text[:20_000]}

EXTRA CONTEXT:
{extra_context[:20_000]}

PROJECT:
{project}
"""

        # Gemini can temporarily return 429/500/502/503/504
        # during rate-limit or server-demand spikes.
        # Retry only transient failures.
        response = None
        last_error: Exception | None = None

        for attempt in range(4):
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=MODEL,
                    contents=prompt,
                )
                break

            except Exception as exc:
                last_error = exc

                error_text = str(exc)

                transient = any(
                    marker in error_text
                    for marker in (
                        "429",
                        "500",
                        "502",
                        "503",
                        "504",
                        "UNAVAILABLE",
                        "RESOURCE_EXHAUSTED",
                        "INTERNAL",
                    )
                )

                if not transient or attempt >= 3:
                    log.exception(
                        "Gemini diagnostic request failed."
                    )
                    break

                delay = 2 ** attempt

                log.warning(
                    "Gemini temporary failure "
                    "(attempt %d/4). Retrying in %ds: %s",
                    attempt + 1,
                    delay,
                    exc,
                )

                await asyncio.sleep(delay)

        if response is None:

            raise AIRepairError(
                "Gemini diagnostic request failed after "
                "retries: "
                f"{type(last_error).__name__}: "
                f"{last_error}"
            ) from last_error

        raw = getattr(
            response,
            "text",
            None,
        )

        if not raw:
            raise AIRepairError(
                "Gemini returned an empty response."
            )

        raw = self._clean_json_response(
            raw
        )

        try:

            data = json.loads(raw)

        except json.JSONDecodeError as exc:

            raise AIRepairError(
                "Gemini returned invalid diagnostic JSON: "
                f"{raw[:2000]}"
            ) from exc

        if not isinstance(data, dict):
            raise AIRepairError(
                "Gemini diagnostic response "
                "was not a JSON object."
            )

        files_raw = data.get(
            "files",
            [],
        )

        if not isinstance(
            files_raw,
            list,
        ):
            files_raw = []

        files = [
            str(item)
            for item in files_raw
            if isinstance(item, str)
        ]

        return Diagnosis(
            summary=str(
                data.get(
                    "summary",
                    "",
                )
            ),
            cause=str(
                data.get(
                    "cause",
                    "",
                )
            ),
            confidence=str(
                data.get(
                    "confidence",
                    "low",
                )
            ),
            suggested_fix=str(
                data.get(
                    "suggested_fix",
                    "",
                )
            ),
            files=files,
        )

    # ---------------------------------------------------------
    # BACKUP
    # ---------------------------------------------------------

    def create_backup(
        self,
        files: list[str],
    ) -> Path:

        timestamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%d_%H%M%S"
        )

        backup = (
            BACKUP_ROOT / timestamp
        )

        backup.mkdir(
            parents=True,
            exist_ok=False,
        )

        manifest: list[str] = []

        for relative in files:

            source = self.safe_path(
                relative
            )

            if (
                not source.exists()
                or not source.is_file()
            ):
                continue

            destination = (
                backup / relative
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                source,
                destination,
            )

            manifest.append(
                relative
            )

        (
            backup / "manifest.json"
        ).write_text(
            json.dumps(
                {
                    "created_at": timestamp,
                    "files": manifest,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        return backup

    # ---------------------------------------------------------
    # ROLLBACK
    # ---------------------------------------------------------

    def rollback(
        self,
        backup: Path,
    ) -> None:

        manifest_file = (
            backup / "manifest.json"
        )

        if not manifest_file.exists():
            raise AIRepairError(
                "Backup manifest missing."
            )

        manifest = json.loads(
            manifest_file.read_text(
                encoding="utf-8"
            )
        )

        for relative in manifest.get(
            "files",
            [],
        ):

            source = (
                backup / relative
            )

            destination = self.safe_path(
                relative
            )

            if source.exists():

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                shutil.copy2(
                    source,
                    destination,
                )

        log.warning(
            "AI repair rollback completed: %s",
            backup,
        )

    # ---------------------------------------------------------
    # SYNTAX VALIDATION
    # ---------------------------------------------------------

    def syntax_check(
        self,
        files: list[str],
    ) -> tuple[bool, str]:

        errors: list[str] = []

        for relative in files:

            path = self.safe_path(
                relative
            )

            if not path.exists():
                continue

            try:

                py_compile.compile(
                    str(path),
                    doraise=True,
                )

            except py_compile.PyCompileError as exc:

                errors.append(
                    f"{relative}: {exc}"
                )

        if errors:
            return (
                False,
                "\n".join(errors),
            )

        return (
            True,
            "Python syntax check passed.",
        )

    # ---------------------------------------------------------
    # SAFE PATCH
    # ---------------------------------------------------------

    def apply_patch(
        self,
        relative_path: str,
        old_text: str,
        new_text: str,
    ) -> None:

        path = self.safe_path(
            relative_path
        )

        if not path.exists():
            raise AIRepairError(
                f"File does not exist: "
                f"{relative_path}"
            )

        if (
            path.stat().st_size
            > MAX_FILE_BYTES
        ):
            raise AIRepairError(
                f"File too large: "
                f"{relative_path}"
            )

        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        occurrences = text.count(
            old_text
        )

        if occurrences != 1:
            raise AIRepairError(
                "Patch requires exactly one "
                f"match in {relative_path}, "
                f"found {occurrences}."
            )

        updated = text.replace(
            old_text,
            new_text,
            1,
        )

        path.write_text(
            updated,
            encoding="utf-8",
        )

    # ---------------------------------------------------------
    # REPAIR TRANSACTION
    # ---------------------------------------------------------

    def repair_transaction(
        self,
        relative_path: str,
        old_text: str,
        new_text: str,
    ) -> tuple[bool, str]:

        backup = self.create_backup(
            [relative_path]
        )

        try:

            self.apply_patch(
                relative_path,
                old_text,
                new_text,
            )

            ok, result = self.syntax_check(
                [relative_path]
            )

            if not ok:

                self.rollback(
                    backup
                )

                return (
                    False,
                    "Syntax check failed. "
                    "Changes rolled back.\n\n"
                    + result,
                )

            return (
                True,
                "Patch applied and syntax "
                "check passed.\n"
                f"Backup: "
                f"{backup.relative_to(self.root)}",
            )

        except Exception as exc:

            try:

                self.rollback(
                    backup
                )

            except Exception:

                log.exception(
                    "Rollback itself failed."
                )

            return (
                False,
                "Repair failed and rollback "
                "was attempted:\n"
                f"{type(exc).__name__}: {exc}",
            )

    # ---------------------------------------------------------
    # HEALTH CHECK
    # ---------------------------------------------------------

    def health_check(
        self,
    ) -> dict[str, Any]:

        files = self.collect_python_files()

        failed: list[str] = []

        for path in files:

            relative = str(
                path.relative_to(
                    self.root
                )
            )

            try:

                py_compile.compile(
                    str(path),
                    doraise=True,
                )

            except py_compile.PyCompileError as exc:

                failed.append(
                    f"{relative}: {exc}"
                )

        return {
            "model": MODEL,
            "project": str(self.root),
            "python_files": len(files),
            "syntax_ok": not failed,
            "errors": failed,
        }


# -------------------------------------------------------------
# GLOBAL ERROR CAPTURE
# -------------------------------------------------------------

_repair_engine: AIRepair | None = None


def get_repair_engine() -> AIRepair:

    global _repair_engine

    if _repair_engine is None:
        _repair_engine = AIRepair()

    return _repair_engine


async def capture_error(
    exc: BaseException,
    *,
    context: str = "",
) -> Diagnosis:

    error_text = "".join(
        traceback.format_exception(
            type(exc),
            exc,
            exc.__traceback__,
        )
    )

    engine = get_repair_engine()

    log.error(
        "Captured application error:\n%s",
        error_text,
    )

    return await engine.diagnose(
        error_text,
        extra_context=context,
    )


# -------------------------------------------------------------
# TELEGRAM COMMAND HELPERS
# -------------------------------------------------------------

async def ai_status(
    user_id: int | str,
) -> str:

    engine = get_repair_engine()

    if not engine.is_admin(user_id):
        return "⛔ Admin only."

    result = engine.health_check()

    status = (
        "✅ HEALTHY"
        if result["syntax_ok"]
        else "❌ ERRORS FOUND"
    )

    return (
        f"🧠 AI Repair\n\n"
        f"Model: `{result['model']}`\n"
        f"Python files: `{result['python_files']}`\n"
        f"Status: {status}"
    )


async def ai_diagnose(
    user_id: int | str,
    error_text: str,
) -> str:

    engine = get_repair_engine()

    if not engine.is_admin(user_id):
        return "⛔ Admin only."

    diagnosis = await engine.diagnose(
        error_text
    )

    files = (
        "\n".join(
            f"• `{x}`"
            for x in diagnosis.files
        )
        or "• None identified"
    )

    return (
        "🧠 <b>Gemini Diagnosis</b>\n\n"
        f"<b>Summary:</b>\n"
        f"{diagnosis.summary}\n\n"
        f"<b>Cause:</b>\n"
        f"{diagnosis.cause}\n\n"
        f"<b>Confidence:</b> "
        f"{diagnosis.confidence}\n\n"
        f"<b>Suggested fix:</b>\n"
        f"{diagnosis.suggested_fix}\n\n"
        f"<b>Relevant files:</b>\n"
        f"{files}"
    )


__all__ = [
    "AIRepair",
    "AIRepairError",
    "Diagnosis",
    "capture_error",
    "get_repair_engine",
    "ai_status",
    "ai_diagnose",
]
