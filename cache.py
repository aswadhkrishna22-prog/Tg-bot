import asyncio
import os
import shutil
import threading
import time
from pathlib import Path

from config import (
    CACHE_CHUNK_SIZE, CACHE_TTL, CACHE_MAX_SIZE, CACHE_DIR,
    CACHE_PER_FILE_MAX_SIZE, CACHE_MIN_FREE_SPACE,
    PREFETCH_ENABLED, PREFETCH_MAX_TASKS, CHUNK_SIZE,
)

_metric_callback = lambda name, amount=1: None
_telegram_stream = None


def configure(metric_callback=None, telegram_stream_func=None):
    global _metric_callback, _telegram_stream
    _metric_callback = metric_callback or (lambda name, amount=1: None)
    _telegram_stream = telegram_stream_func


def metric_inc(name, amount=1):
    _metric_callback(name, amount)


CACHE_DIR.mkdir(parents=True, exist_ok=True)

cache_active_files = set()
cache_active_guard = threading.Lock()
cache_locks = {}
cache_locks_guard = asyncio.Lock()
prefetch_tasks = set()
prefetch_tasks_lock = threading.Lock()


def cache_path(token, chunk_index):
    token_dir = CACHE_DIR / token
    token_dir.mkdir(
        parents=True,
        exist_ok=True
    )
    return token_dir / f"{chunk_index}.cache"


async def get_cache_lock(cache_key):
    async with cache_locks_guard:
        lock = cache_locks.get(cache_key)

        if lock is None:
            lock = asyncio.Lock()
            cache_locks[cache_key] = lock

        return lock


def _cache_file_is_active(path):
    try:
        with cache_active_guard:
            return str(path) in cache_active_files
    except Exception:
        return False


def _mark_cache_active(path):
    with cache_active_guard:
        cache_active_files.add(str(path))


def _unmark_cache_active(path):
    with cache_active_guard:
        cache_active_files.discard(str(path))


def remove_cache_token(token):
    token_dir = CACHE_DIR / token

    if not token_dir.exists():
        return

    # Never delete a token directory while one of its chunks is being
    # read or written. The next cleanup pass will remove it safely.
    try:
        with cache_active_guard:
            active = any(
                item == str(token_dir)
                or item.startswith(str(token_dir) + os.sep)
                for item in cache_active_files
            )
        if active:
            print("[CACHE] Token cache is active; delaying removal:", token)
            return

        shutil.rmtree(token_dir, ignore_errors=True)
    except Exception as error:
        print("[CACHE] Token cache cleanup failed:", error)


def _cache_usage_snapshot():
    now = time.time()
    total_size = 0
    cache_files = []

    try:
        for part in CACHE_DIR.rglob("*.cache.part"):
            try:
                if not _cache_file_is_active(part) and now - part.stat().st_mtime > CACHE_TTL:
                    part.unlink()
            except OSError:
                pass

        for path in CACHE_DIR.rglob("*.cache"):
            try:
                stat = path.stat()
            except OSError:
                continue

            age = now - stat.st_mtime
            if age > CACHE_TTL and not _cache_file_is_active(path):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue

            total_size += stat.st_size
            cache_files.append((stat.st_mtime, stat.st_size, path))
    except OSError:
        pass

    return total_size, cache_files


def cleanup_cache_sync(required_bytes=0):
    """Enforce TTL, global/per-file quotas and a minimum free-space reserve."""
    try:
        total_size, cache_files = _cache_usage_snapshot()

        # First enforce the per-file quota. Oldest chunks from the same
        # token are evicted first, but active chunks are never touched.
        by_token = {}
        for mtime, size, path in cache_files:
            token = path.parent.name
            by_token.setdefault(token, []).append((mtime, size, path))

        for token, items in by_token.items():
            file_total = sum(size for _, size, _ in items)
            if file_total <= CACHE_PER_FILE_MAX_SIZE:
                continue

            items.sort(key=lambda item: item[0])
            for _, size, path in items:
                if file_total <= CACHE_PER_FILE_MAX_SIZE:
                    break
                if _cache_file_is_active(path):
                    continue
                try:
                    path.unlink()
                    file_total -= size
                    total_size -= size
                except OSError:
                    pass

        # Determine how much must be removed to satisfy both the global
        # cache cap and the disk free-space reserve.
        try:
            free_space = shutil.disk_usage(CACHE_DIR).free
        except OSError:
            free_space = CACHE_MIN_FREE_SPACE

        target_total = min(
            CACHE_MAX_SIZE,
            max(0, total_size - max(0, CACHE_MIN_FREE_SPACE - free_space))
        )
        required_total = min(
            total_size,
            max(0, target_total - max(0, required_bytes))
        )

        if total_size > required_total:
            # Refresh mtimes after the per-file pass so eviction remains
            # true LRU-ish (recently served chunks naturally move forward).
            _, refreshed = _cache_usage_snapshot()
            refreshed.sort(key=lambda item: item[0])

            for _, size, path in refreshed:
                if total_size <= required_total:
                    break
                if _cache_file_is_active(path):
                    continue
                try:
                    path.unlink()
                    total_size -= size
                except OSError:
                    pass

        # Remove empty token directories.
        for directory in sorted(
            CACHE_DIR.rglob("*"),
            key=lambda item: len(item.parts),
            reverse=True
        ):
            if not directory.is_dir():
                continue
            try:
                directory.rmdir()
            except OSError:
                pass

    except Exception as error:
        print("[CACHE] Cleanup error:", error)


async def download_cache_chunk(
    message,
    cache_file,
    chunk_start,
    chunk_length
):
    part_file = cache_file.with_suffix(".cache.part")
    sent = 0

    _mark_cache_active(cache_file)
    try:
        # Make room before writing. A cache miss should not be allowed to
        # fill a nearly-full disk.
        await asyncio.to_thread(cleanup_cache_sync, chunk_length)

        try:
            free_space = shutil.disk_usage(CACHE_DIR).free
        except OSError:
            free_space = CACHE_MIN_FREE_SPACE

        if free_space < CACHE_MIN_FREE_SPACE + chunk_length:
            raise OSError(
                "Not enough free disk space for temporary cache"
            )

        if part_file.exists():
            try:
                part_file.unlink()
            except OSError:
                pass

        with part_file.open("wb") as output:
            async for chunk in _telegram_stream(
                message,
                offset=chunk_start,
                length=chunk_length
            ):
                if not chunk:
                    continue

                remaining = chunk_length - sent
                if remaining <= 0:
                    break

                if len(chunk) > remaining:
                    chunk = chunk[:remaining]

                output.write(chunk)
                sent += len(chunk)

                if sent >= chunk_length:
                    break

        if sent != chunk_length:
            raise IOError(
                f"Cache chunk incomplete: expected {chunk_length} bytes, got {sent} bytes"
            )

        os.replace(part_file, cache_file)
        os.utime(cache_file, None)

    except asyncio.CancelledError:
        try:
            if part_file.exists():
                part_file.unlink()
        except OSError:
            pass
        raise

    except Exception:
        try:
            if part_file.exists():
                part_file.unlink()
        except OSError:
            pass
        raise

    finally:
        _unmark_cache_active(cache_file)


async def ensure_cache_chunk(
    token,
    message,
    chunk_index,
    chunk_start,
    chunk_length
):
    cache_file = cache_path(token, chunk_index)

    def valid_cache_file():
        try:
            stat = cache_file.stat()
            return (
                stat.st_size == chunk_length
                and time.time() - stat.st_mtime <= CACHE_TTL
            )
        except OSError:
            return False

    if valid_cache_file():
        metric_inc("cache_hits")
        # mtime doubles as the lightweight last-access timestamp.
        os.utime(cache_file, None)
        return cache_file

    metric_inc("cache_misses")
    # Per-chunk lock is request deduplication: if 10 viewers miss the
    # same chunk simultaneously, only the first one talks to Telegram.
    # The remaining requests wait and then reuse the completed cache file.
    cache_key = f"{token}:{chunk_index}"
    lock = await get_cache_lock(cache_key)

    async with lock:
        if valid_cache_file():
            os.utime(cache_file, None)
            return cache_file

        await download_cache_chunk(
            message,
            cache_file,
            chunk_start,
            chunk_length
        )

        # Re-check quotas immediately after a successful write.
        await asyncio.to_thread(cleanup_cache_sync)

        if not valid_cache_file():
            raise IOError("Temporary cache chunk was evicted or invalidated")

        os.utime(cache_file, None)
        return cache_file


async def prefetch_cache_chunk(token, message, file_size, chunk_index):
    if not PREFETCH_ENABLED or len(prefetch_tasks) >= PREFETCH_MAX_TASKS:
        return
    chunk_start = chunk_index * CACHE_CHUNK_SIZE
    if chunk_start >= file_size:
        return
    chunk_end = min(chunk_start + CACHE_CHUNK_SIZE, file_size)
    try:
        metric_inc("prefetch_started")
        await ensure_cache_chunk(token, message, chunk_index, chunk_start, chunk_end - chunk_start)
        metric_inc("prefetch_completed")
    except asyncio.CancelledError:
        raise
    except Exception as error:
        print("[PREFETCH] skipped:", error)


def launch_prefetch(token, message, file_size, chunk_index):
    if not PREFETCH_ENABLED:
        return
    with prefetch_tasks_lock:
        if len(prefetch_tasks) >= PREFETCH_MAX_TASKS:
            return
    task = asyncio.create_task(prefetch_cache_chunk(token, message, file_size, chunk_index))
    with prefetch_tasks_lock:
        prefetch_tasks.add(task)
    task.add_done_callback(lambda t: prefetch_tasks.discard(t))


async def cached_telegram_stream(
    token,
    message,
    file_size,
    offset,
    length
):
    end_position = offset + length

    first_chunk = offset // CACHE_CHUNK_SIZE
    last_chunk = (end_position - 1) // CACHE_CHUNK_SIZE

    for chunk_index in range(first_chunk, last_chunk + 1):
        chunk_start = chunk_index * CACHE_CHUNK_SIZE
        chunk_end = min(chunk_start + CACHE_CHUNK_SIZE, file_size)
        chunk_length = chunk_end - chunk_start

        cache_file = await ensure_cache_chunk(
            token, message, chunk_index, chunk_start, chunk_length
        )

        # Warm the next chunk in the background while the current chunk is served.
        if chunk_index == first_chunk:
            launch_prefetch(token, message, file_size, chunk_index + 1)

        requested_start = max(offset, chunk_start)
        requested_end = min(end_position, chunk_end)
        read_start = requested_start - chunk_start
        read_length = requested_end - requested_start

        if read_length <= 0:
            continue

        _mark_cache_active(cache_file)
        try:
            os.utime(cache_file, None)

            with cache_file.open("rb") as cached_file:
                cached_file.seek(read_start)
                remaining = read_length

                while remaining > 0:
                    piece = await asyncio.to_thread(
                        cached_file.read, min(CHUNK_SIZE, remaining)
                    )

                    if not piece:
                        raise IOError(
                            "Temporary cache file ended unexpectedly"
                        )

                    remaining -= len(piece)
                    yield piece

            os.utime(cache_file, None)
        finally:
            _unmark_cache_active(cache_file)


