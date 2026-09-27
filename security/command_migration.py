"""Explicit production migration for dynamic Main Bot commands.

Run manually with the production DATABASE_URL:
    python -m security.command_migration
Nothing in normal bot startup calls this module automatically.
"""

from security.command_repository import ensure_schema


if __name__ == "__main__":
    ensure_schema()
    print("[COMMANDS] bot_commands schema ready.")
