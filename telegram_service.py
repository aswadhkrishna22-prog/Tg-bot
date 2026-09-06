"""Telegram streaming service for Adolf-StreamX."""

import asyncio
import os
import time
from telethon import errors

_bot = None
_telegram_download_semaphore = None
_telegram_cooldown_lock = None
_telegram_cooldown_until = 0.0
_metric_inc = lambda *_args, **_kwargs: None
_CHUNK_SIZE = 512 * 1024
_TELEGRAM_FLOODWAIT_CAP = 60
_STREAM_IDLE_TIMEOUT = 0.0


def configure(*, bot, telegram_download_semaphore, telegram_cooldown_lock,
               chunk_size, telegram_floodwait_cap, stream_idle_timeout, metric_inc):
    """Inject server-owned Telegram runtime state without circular imports."""
    global _bot, _telegram_download_semaphore, _telegram_cooldown_lock
    global _CHUNK_SIZE, _TELEGRAM_FLOODWAIT_CAP, _STREAM_IDLE_TIMEOUT, _metric_inc
    _bot = bot
    _telegram_download_semaphore = telegram_download_semaphore
    _telegram_cooldown_lock = telegram_cooldown_lock
    _CHUNK_SIZE = chunk_size
    _TELEGRAM_FLOODWAIT_CAP = telegram_floodwait_cap
    _STREAM_IDLE_TIMEOUT = stream_idle_timeout
    _metric_inc = metric_inc


async def wait_for_telegram_cooldown():
    """Wait for the shared FloodWait cooldown, if one is active."""
    while True:
        async with _telegram_cooldown_lock:
            remaining = _telegram_cooldown_until - time.monotonic()

        if remaining <= 0:
            return

        await asyncio.sleep(min(remaining, 2.0))

async def set_telegram_cooldown(seconds):
    """Extend the shared Telegram cooldown without shortening an existing one."""
    global _telegram_cooldown_until

    seconds = max(0.0, min(float(seconds), float(_TELEGRAM_FLOODWAIT_CAP)))

    async with _telegram_cooldown_lock:
        _telegram_cooldown_until = max(
            _telegram_cooldown_until,
            time.monotonic() + seconds
        )

async def telegram_stream(
    message,
    offset,
    length
):
    """Stream a Telegram byte range with bounded reconnect/retry support.

    If Telegram fails after some bytes were delivered, the next attempt
    resumes exactly at the undelivered byte instead of restarting the range.
    """
    sent = 0
    retries = 0

    max_retries = max(
        0,
        int(os.getenv("TELEGRAM_STREAM_MAX_RETRIES", "3"))
    )
    base_delay = max(
        0.25,
        float(os.getenv("TELEGRAM_STREAM_RETRY_DELAY", "0.5"))
    )
    max_delay = max(
        base_delay,
        float(os.getenv("TELEGRAM_STREAM_MAX_RETRY_DELAY", "8"))
    )

    while sent < length:
        current_offset = offset + sent
        remaining = length - sent

        try:
            # All Telegram media downloads pass through the same small gate.
            # This is deliberately separate from the viewer semaphore.
            await wait_for_telegram_cooldown()

            async with _telegram_download_semaphore:
                await wait_for_telegram_cooldown()

                iterator = _bot.iter_download(
                    message.media, offset=current_offset, limit=remaining, request_size=_CHUNK_SIZE
                ).__aiter__()
                while True:
                    try:
                        if _STREAM_IDLE_TIMEOUT > 0:
                            chunk = await asyncio.wait_for(
                                iterator.__anext__(),
                                timeout=_STREAM_IDLE_TIMEOUT
                            )
                        else:
                            chunk = await iterator.__anext__()
                    except StopAsyncIteration:
                        break
                    if not chunk:
                        continue
                    remaining_now = length - sent
                    if len(chunk) > remaining_now:
                        chunk = chunk[:remaining_now]
                    sent += len(chunk)
                    yield chunk
                    if sent >= length:
                        return

            # Telegram ended the iterator before the requested range was
            # completely delivered. Treat that as a recoverable failure.
            if sent < length:
                raise IOError(
                    f"Telegram stream ended early: {sent}/{length} bytes"
                )

            return

        except asyncio.CancelledError:
            raise

        except Exception as error:
            if retries >= max_retries:
                print(
                    f"[!] Telegram stream failed after {retries} retries: {error}"
                )
                raise

            retries += 1

            # Telethon exposes FloodWaitError.seconds. Respect it, but cap
            # the delay so a browser/TV connection is not held forever.
            flood_wait = getattr(error, "seconds", None)
            if isinstance(error, errors.FloodWaitError) and flood_wait is not None:
                _metric_inc("telegram_floodwaits")
                delay = min(
                    float(flood_wait),
                    float(_TELEGRAM_FLOODWAIT_CAP)
                )
                await set_telegram_cooldown(delay)
            else:
                delay = min(
                    base_delay * (2 ** (retries - 1)),
                    max_delay
                )

            print(
                f"[!] Telegram stream interrupted at {sent}/{length} bytes; "
                f"retry {retries}/{max_retries} in {delay:.1f}s: {error}"
            )

            await asyncio.sleep(delay)

