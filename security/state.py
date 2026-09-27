import os
from datetime import datetime

# Interactive admin action state
pending_actions = {}


def set_pending_action(user_id, action):
    uid = int(user_id)
    pending_actions[uid] = action
    security_v2_pending_times[uid] = int(datetime.now().timestamp())


def get_pending_action(user_id):
    uid = int(user_id)
    started = security_v2_pending_times.get(uid, 0)
    now = int(datetime.now().timestamp())
    if started and now - started > SECURITY_PENDING_TIMEOUT:
        pending_actions.pop(uid, None)
        security_v2_pending_times.pop(uid, None)
        return None
    return pending_actions.get(uid)


def clear_pending_action(user_id):
    uid = int(user_id)
    pending_actions.pop(uid, None)
    security_v2_pending_times.pop(uid, None)


# Security V2 runtime state
security_v2_state = {
    "started_at": int(datetime.now().timestamp()),
    "lockdown": False,
    "auto_blocks": 0,
    "requests_scanned": 0,
    "last_scan": 0,
}
security_v2_confirmations = {}
security_v2_ip_hits = {}
security_v2_user_hits = {}
security_v2_pending_times = {}

SECURITY_PENDING_TIMEOUT = max(60, int(os.getenv("SECURITY_PENDING_TIMEOUT", "300")))
