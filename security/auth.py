from security.config import OWNER_ID


def is_admin(event):
    try:
        return int(event.sender_id or 0) == OWNER_ID
    except Exception:
        return False
