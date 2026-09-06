"""Background cleanup orchestration for Adolf-StreamX."""

import asyncio


_cache_cleanup_sync = None
_cache_locks = None
_cache_locks_guard = None
_file_stream_semaphores = None
_file_stream_semaphores_guard = None
_max_concurrent_per_file = 5
_cache_cleanup_interval = 60
_cleanup_request_rate_state = None
_cleanup_pair_attempts = None
_db_connect = None
_remove_cache_token = None
_bot = None


def configure(
    *,
    cleanup_cache_sync,
    cache_locks,
    cache_locks_guard,
    file_stream_semaphores,
    file_stream_semaphores_guard,
    max_concurrent_per_file,
    cache_cleanup_interval,
    cleanup_request_rate_state,
    cleanup_pair_attempts,
    db_connect,
    remove_cache_token,
    bot,
):
    global _cache_cleanup_sync, _cache_locks, _cache_locks_guard
    global _file_stream_semaphores, _file_stream_semaphores_guard
    global _max_concurrent_per_file, _cache_cleanup_interval
    global _cleanup_request_rate_state, _cleanup_pair_attempts
    global _db_connect, _remove_cache_token, _bot

    _cache_cleanup_sync = cleanup_cache_sync
    _cache_locks = cache_locks
    _cache_locks_guard = cache_locks_guard
    _file_stream_semaphores = file_stream_semaphores
    _file_stream_semaphores_guard = file_stream_semaphores_guard
    _max_concurrent_per_file = max_concurrent_per_file
    _cache_cleanup_interval = cache_cleanup_interval
    _cleanup_request_rate_state = cleanup_request_rate_state
    _cleanup_pair_attempts = cleanup_pair_attempts
    _db_connect = db_connect
    _remove_cache_token = remove_cache_token
    _bot = bot


async def cleanup_cache_loop():
    while True:
        try:
            await asyncio.to_thread(_cache_cleanup_sync)

            # Keep in-memory coordination maps bounded during long uptime.
            async with _cache_locks_guard:
                if len(_cache_locks) > 5000:
                    for key, lock in list(_cache_locks.items()):
                        if not lock.locked():
                            _cache_locks.pop(key, None)
                            if len(_cache_locks) <= 3500:
                                break

            async with _file_stream_semaphores_guard:
                if len(_file_stream_semaphores) > 5000:
                    for token, semaphore in list(_file_stream_semaphores.items()):
                        if semaphore._value == _max_concurrent_per_file:
                            _file_stream_semaphores.pop(token, None)
                            if len(_file_stream_semaphores) <= 3500:
                                break

            _cleanup_request_rate_state()
            _cleanup_pair_attempts()

        except asyncio.CancelledError:
            raise
        except Exception as error:
            print("[CACHE] Background cleanup error:", error)

        await asyncio.sleep(_cache_cleanup_interval)


async def cleanup_expired_files():
    while True:
        try:
            expired_files = []

            with _db_connect() as db:
                with db.cursor() as cursor:
                    cursor.execute("""
                        SELECT
                            token,
                            bot_chat_id,
                            bot_message_id
                        FROM files
                        WHERE expires_at IS NOT NULL
                        AND expires_at <= NOW()
                    """)
                    expired_files = cursor.fetchall()

            for row in expired_files:
                token = row["token"]
                bot_chat_id = row["bot_chat_id"]
                bot_message_id = row["bot_message_id"]

                if bot_chat_id and bot_message_id:
                    try:
                        await _bot.delete_messages(
                            int(bot_chat_id),
                            int(bot_message_id)
                        )
                    except Exception as error:
                        print(
                            "[CLEANUP] Telegram message delete failed:",
                            error
                        )

                with _db_connect() as db:
                    with db.cursor() as cursor:
                        cursor.execute("""
                            DELETE FROM tv_pairings
                            WHERE token = %s
                        """, (token,))
                        cursor.execute("""
                            DELETE FROM files
                            WHERE token = %s
                        """, (token,))
                    db.commit()

                _remove_cache_token(token)

                print(
                    "[CLEANUP] Expired file removed:",
                    token
                )

        except Exception as error:
            print(
                "[CLEANUP] Error:",
                error
            )

        await asyncio.sleep(60)
