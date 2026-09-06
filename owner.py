"""Telegram file-owner display helpers for Adolf-StreamX."""

_bot = None
_db_connect = None


def configure(*, bot, db_connect):
    """Inject Telegram and database dependencies without importing server."""
    global _bot, _db_connect
    _bot = bot
    _db_connect = db_connect


async def get_owner_display(row):
    """Return Telegram username/name, including for legacy file rows."""
    owner_username = str(row.get("owner_username") or "").strip()
    owner_name = str(row.get("owner_name") or "").strip()
    chat_id = row.get("chat_id")

    # New rows already store the sender directly.
    if owner_username:
        return "@" + owner_username.lstrip("@")

    # Recover legacy rows from the users table first.
    if chat_id is not None:
        try:
            with _db_connect() as db:
                with db.cursor() as cursor:
                    cursor.execute("""
                        SELECT username, first_name, last_name
                        FROM users
                        WHERE user_id = %s
                        LIMIT 1
                    """, (int(chat_id),))
                    user = cursor.fetchone()

            if user:
                username = str(user.get("username") or "").strip()
                if username:
                    return "@" + username.lstrip("@")
                name = " ".join(
                    part for part in [
                        str(user.get("first_name") or "").strip(),
                        str(user.get("last_name") or "").strip()
                    ] if part
                )
                if name:
                    return name
        except Exception as error:
            print("[OWNER] Legacy DB owner lookup failed:", error)

        # Final recovery for old file rows: ask Telegram for the current
        # profile. This fixes rows created before owner_username was added.
        try:
            sender = await _bot.get_entity(int(chat_id))
            username = str(getattr(sender, "username", "") or "").strip()
            if username:
                return "@" + username.lstrip("@")
            name = " ".join(
                part for part in [
                    str(getattr(sender, "first_name", "") or "").strip(),
                    str(getattr(sender, "last_name", "") or "").strip()
                ] if part
            )
            if name:
                return name
        except Exception as error:
            print("[OWNER] Telegram owner lookup failed:", error)

    if owner_name and not owner_name.isdigit():
        return owner_name

    # Never expose a raw Telegram numeric ID as the visible owner.
    return "Telegram User"
