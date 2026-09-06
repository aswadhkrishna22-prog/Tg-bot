"""Pure Adolf-StreamX helper functions.

These helpers intentionally have no dependency on FastAPI, Telethon, the
PostgreSQL connection, or mutable server state. Keeping them pure makes the
next modularization steps safer.
"""

import mimetypes
import os
import re
from pathlib import Path


def format_uptime(seconds):
    seconds = int(seconds)

    days = seconds // 86400
    seconds %= 86400

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60
    seconds %= 60

    return f"{days}d {hours}h {minutes}m {seconds}s"


def usage_bar(percent, total=10):
    filled = round(percent / 100 * total)
    filled = max(0, min(total, filled))

    return "●" * filled + "○" * (total - filled)


def clean_filename(name):
    if not name:
        return "file"

    name = os.path.basename(name)

    name = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        name
    )

    return name[:180] or "file"


def get_mime(filename):
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def get_stream_mime(filename, stored_mime=None):
    """Return a browser-appropriate MIME type from the real filename."""
    ext = Path(filename or "").suffix.lower()
    media_mimes = {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".webm": "video/webm",
        ".ogv": "video/ogg",
        ".ogg": "audio/ogg",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".ts": "video/mp2t",
        ".m2ts": "video/mp2t",
        ".mts": "video/mp2t",
        ".flv": "video/x-flv",
        ".wmv": "video/x-ms-wmv",
        ".3gp": "video/3gpp",
        ".3g2": "video/3gpp2",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
    }
    if ext in media_mimes:
        return media_mimes[ext]
    return stored_mime or get_mime(filename) or "application/octet-stream"


def detect_media_profile(filename, mime=None):
    """Conservatively classify files for browser-vs-external playback."""
    name = (filename or "").lower()
    ext = Path(name).suffix
    mime = (mime or get_mime(filename)).lower()

    codec_markers = (
        "hevc", "h.265", "h265", "x265", "10bit", "10-bit",
        "hdr10", "dolbyvision", "dvhe"
    )
    has_incompatible_marker = any(marker in name for marker in codec_markers)

    browser_containers = {".mp4", ".m4v", ".webm", ".ogv", ".ogg"}
    external_containers = {
        ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".mts", ".flv", ".wmv"
    }

    if has_incompatible_marker or ext in external_containers:
        return {
            "browser_ok": False,
            "reason": "MKV/HEVC/10-bit or another browser-inconsistent format detected",
            "label": "Direct Browser Stream",
            "mime": mime,
            "extension": ext or "unknown",
        }

    if ext in browser_containers and mime.startswith(("video/", "audio/")):
        return {
            "browser_ok": True,
            "reason": "Browser-friendly container detected; codec is not guaranteed by filename",
            "label": "Browser Playback",
            "mime": mime,
            "extension": ext or "unknown",
        }

    return {
        "browser_ok": False,
        "reason": "Direct browser stream",
        "label": "Direct Browser Stream",
        "mime": mime,
        "extension": ext or "unknown",
    }


def parse_range(range_header, file_size):
    if not range_header:
        return 0, file_size - 1

    if not range_header.startswith("bytes="):
        raise ValueError("Invalid range")

    value = range_header[6:]

    if "," in value:
        raise ValueError("Multiple ranges not supported")

    start_text, end_text = value.split("-", 1)

    if start_text:
        start = int(start_text)

        if start >= file_size:
            raise ValueError("Range outside file")

        if end_text:
            end = min(int(end_text), file_size - 1)
        else:
            end = file_size - 1

        if start > end:
            raise ValueError("Invalid range")

        return start, end

    end = int(end_text)

    if end <= 0:
        raise ValueError("Invalid suffix range")

    start = max(file_size - end, 0)

    return start, file_size - 1
