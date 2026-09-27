from .start import register as register_start
from .users import register as register_users
from .inspect import register as register_inspect
from .remove import register as register_remove
from .block import register as register_block
from .unblock import register as register_unblock
from .blocked import register as register_blocked
from .purge import register as register_purge
from .stats import register as register_stats
from .check import register as register_check
from .dynamic import register as register_dynamic
from .ai import register as register_ai

def register_all(client):
    register_start(client)
    register_users(client)
    register_inspect(client)
    register_remove(client)
    register_block(client)
    register_unblock(client)
    register_blocked(client)
    register_purge(client)
    register_stats(client)
    register_check(client)
    register_dynamic(client)
    register_ai(client)


