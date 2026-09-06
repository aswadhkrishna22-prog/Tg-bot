"""Adolf-StreamX configuration.

This module contains environment-backed settings and immutable application
constants only. Runtime state (locks, semaphores, metrics, caches, etc.) stays
in the main server during the first modularization step.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    API_ID = int(os.getenv("TG_API_ID", "0"))
except ValueError:
    raise RuntimeError("TG_API_ID must be a number")

API_HASH = os.getenv("TG_API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SECURITY_BOT_TOKEN = os.getenv("SECURITY_BOT_TOKEN", "").strip()

BOT_MODE = os.getenv("BOT_MODE", "false").strip().lower() in (
    "1", "true", "yes", "on"
)

try:
    SECURITY_OWNER_ID = int(os.getenv("SECURITY_OWNER_ID", "0"))
except ValueError:
    raise RuntimeError("SECURITY_OWNER_ID must be a number")

PUBLIC_URL = os.getenv(
    "PUBLIC_URL",
    "http://127.0.0.1:8000"
).strip().rstrip("/")

HOST = "0.0.0.0"
PORT = 8000
CHUNK_SIZE = 512 * 1024

# Temporary range-cache settings.
CACHE_CHUNK_SIZE = 4 * 1024 * 1024
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))
CACHE_MAX_SIZE = int(
    os.getenv("CACHE_MAX_SIZE", str(1024 * 1024 * 1024))
)
CACHE_DIR = Path(
    os.getenv("CACHE_DIR", "/tmp/stady_proxy_cache")
)
CACHE_PER_FILE_MAX_SIZE = int(
    os.getenv("CACHE_PER_FILE_MAX_SIZE", str(256 * 1024 * 1024))
)
CACHE_MIN_FREE_SPACE = int(
    os.getenv("CACHE_MIN_FREE_SPACE", str(512 * 1024 * 1024))
)
CACHE_CLEANUP_INTERVAL = int(
    os.getenv("CACHE_CLEANUP_INTERVAL", "300")
)

# Stream / Telegram protection settings.
MAX_CONCURRENT_STREAMS = int(
    os.getenv("MAX_CONCURRENT_STREAMS", "20")
)
MAX_CONCURRENT_PER_FILE = int(
    os.getenv("MAX_CONCURRENT_PER_FILE", "5")
)
STREAM_ACQUIRE_TIMEOUT = int(
    os.getenv("STREAM_ACQUIRE_TIMEOUT", "15")
)
MAX_CONCURRENT_TELEGRAM_DOWNLOADS = int(
    os.getenv("MAX_CONCURRENT_TELEGRAM_DOWNLOADS", "3")
)
TELEGRAM_FLOODWAIT_CAP = int(
    os.getenv("TELEGRAM_FLOODWAIT_CAP", "60")
)

# File / request safety settings.
MAX_FILE_SIZE = 6 * 1024 * 1024 * 1024
FILE_COOLDOWN = 10
STREAM_IDLE_TIMEOUT = float(os.getenv("STREAM_IDLE_TIMEOUT", "0"))
REQUEST_RATE_LIMIT = int(os.getenv("REQUEST_RATE_LIMIT", "300"))
REQUEST_RATE_WINDOW = int(os.getenv("REQUEST_RATE_WINDOW", "60"))
MAX_RATE_LIMIT_KEYS = int(os.getenv("MAX_RATE_LIMIT_KEYS", "10000"))
PAIR_MAX_ATTEMPTS = max(3, int(os.getenv("PAIR_MAX_ATTEMPTS", "8")))
PAIR_ATTEMPT_WINDOW = max(30, int(os.getenv("PAIR_ATTEMPT_WINDOW", "300")))
PAIR_LOCKOUT_SECONDS = max(30, int(os.getenv("PAIR_LOCKOUT_SECONDS", "300")))
PREFETCH_ENABLED = os.getenv("PREFETCH_ENABLED", "1").strip().lower() not in {
    "0", "false", "no", "off"
}
PREFETCH_MAX_TASKS = max(1, int(os.getenv("PREFETCH_MAX_TASKS", "8")))

# PostgreSQL connection settings.
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
DB_KEEPALIVES_IDLE = int(os.getenv("DB_KEEPALIVES_IDLE", "30"))
DB_KEEPALIVES_INTERVAL = int(os.getenv("DB_KEEPALIVES_INTERVAL", "10"))
DB_KEEPALIVES_COUNT = int(os.getenv("DB_KEEPALIVES_COUNT", "3"))

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

ERROR_PAGE = BASE_DIR / "stady_proxy_404.html"
ERROR_IMAGE = BASE_DIR / "adolf-streamx-404.png"
RAIN_OVERLAY = BASE_DIR / "stady-proxy-rain-overlay-v2.mp4"
RAIN_OVERLAY_WEBM = BASE_DIR / "stady-proxy-rain-overlay-v2.webm"

# Security V3 server-side settings.
SECURITY_V3_SERVER_ENABLED = os.getenv(
    "SECURITY_V3_ENABLED", "1"
).strip().lower() not in {"0", "false", "no", "off"}
SECURITY_V3_SERVER_CACHE_TTL = max(
    2, float(os.getenv("SECURITY_V3_SERVER_CACHE_TTL", "5"))
)
SECURITY_V3_SERVER_MAX_STREAMS_PER_USER = max(
    1, int(os.getenv("SECURITY_V3_SERVER_MAX_STREAMS_PER_USER", "5"))
)

# Preserve the existing startup validation behavior.
if API_ID <= 0:
    raise RuntimeError("TG_API_ID is missing or invalid")

if not API_HASH:
    raise RuntimeError("TG_API_HASH is missing")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing (required for Telegram streaming/authentication)"
    )

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")
