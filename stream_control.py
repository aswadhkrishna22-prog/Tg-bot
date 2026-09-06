"""HTTP stream concurrency controls for Adolf-StreamX."""

import asyncio

from config import MAX_CONCURRENT_STREAMS, MAX_CONCURRENT_PER_FILE


# Global viewer limit.
global_stream_semaphore = asyncio.Semaphore(
    MAX_CONCURRENT_STREAMS
)

# Per-file viewer limits.
file_stream_semaphores = {}
file_stream_semaphores_guard = asyncio.Lock()


async def get_file_stream_semaphore(token):
    async with file_stream_semaphores_guard:
        semaphore = file_stream_semaphores.get(token)

        if semaphore is None:
            semaphore = asyncio.Semaphore(
                MAX_CONCURRENT_PER_FILE
            )
            file_stream_semaphores[token] = semaphore

        return semaphore


async def remove_file_stream_semaphore(token):
    async with file_stream_semaphores_guard:
        semaphore = file_stream_semaphores.get(token)

        if semaphore is not None:
            if semaphore._value == MAX_CONCURRENT_PER_FILE:
                file_stream_semaphores.pop(
                    token,
                    None
                )
