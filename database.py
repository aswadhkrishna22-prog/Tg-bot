import re
import secrets
import uuid

import psycopg2
from psycopg2.extras import RealDictCursor

from config import (
    DATABASE_URL,
    DB_CONNECT_TIMEOUT,
    DB_KEEPALIVES_IDLE,
    DB_KEEPALIVES_INTERVAL,
    DB_KEEPALIVES_COUNT,
)


_metric_callback = lambda name, amount=1: None


def set_metric_callback(callback):
    """Register the server metric increment callback without importing server."""
    global _metric_callback
    _metric_callback = callback or (lambda name, amount=1: None)


def db_connect():
    last_error = None
    for attempt in range(3):
        try:
            return psycopg2.connect(
                DATABASE_URL, sslmode="require", cursor_factory=RealDictCursor,
                connect_timeout=DB_CONNECT_TIMEOUT, keepalives=1,
                keepalives_idle=DB_KEEPALIVES_IDLE, keepalives_interval=DB_KEEPALIVES_INTERVAL,
                keepalives_count=DB_KEEPALIVES_COUNT
            )
        except Exception as error:
            last_error = error
            _metric_callback("db_failures")
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
    raise last_error


def init_database():

    with db_connect() as db:

        with db.cursor() as cursor:

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    token TEXT PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    filename TEXT NOT NULL,
                    size BIGINT NOT NULL,
                    mime TEXT NOT NULL,
                    expires_at TIMESTAMPTZ
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT NOT NULL DEFAULT '',
                    last_name TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ
            """)

            cursor.execute("""
                UPDATE files
                SET expires_at = NOW() + INTERVAL '12 hours'
                WHERE expires_at IS NULL
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS bot_chat_id BIGINT
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS bot_message_id BIGINT
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS share_token TEXT
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_files_share_token
                ON files (share_token)
                WHERE share_token IS NOT NULL
            """)

            cursor.execute("""
                ALTER TABLE files
                ADD COLUMN IF NOT EXISTS pair_code TEXT
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_files_pair_code
                ON files (pair_code)
                WHERE pair_code IS NOT NULL
            """)

            # Dedicated pairing table.  Pairing must not depend on the legacy
            # files.pair_code column, because older deployments may have a
            # different schema/type or stale rows.  Both creation and lookup
            # use this table and the same DATABASE_URL.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tv_pairings (
                    code TEXT PRIMARY KEY,
                    token TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tv_pairings_expires
                ON tv_pairings (expires_at)
            """)

            for column_sql in (
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS owner_name TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS owner_username TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMPTZ",
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS last_stream_started TIMESTAMPTZ",
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS view_count BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS download_count BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE files ADD COLUMN IF NOT EXISTS total_bytes_served BIGINT NOT NULL DEFAULT 0",
            ):
                cursor.execute(column_sql)

        db.commit()


def add_file(
    token,
    chat_id,
    message_id,
    filename,
    size,
    mime,
    owner_name="",
    owner_username=""
):
    with db_connect() as db:

        with db.cursor() as cursor:

            cursor.execute("""
                INSERT INTO files
                (
                    token,
                    chat_id,
                    message_id,
                    filename,
                    size,
                    mime,
                    expires_at,
                    owner_name,
                    owner_username
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NOW() + INTERVAL '12 hours',
                    %s,
                    %s
                )
            """, (
                token,
                chat_id,
                message_id,
                filename,
                size,
                mime,
                owner_name,
                owner_username
            ))

        db.commit()
        
def save_bot_message_id(
    token,
    bot_chat_id,
    bot_message_id
):
    with db_connect() as db:

        with db.cursor() as cursor:

            cursor.execute("""
                UPDATE files
                SET
                    bot_chat_id = %s,
                    bot_message_id = %s
                WHERE token = %s
            """, (
                int(bot_chat_id),
                int(bot_message_id),
                token
            ))

        db.commit()





def create_share_token(token):
    """Create a short token used only for device sharing."""
    for _ in range(10):
        share_token = uuid.uuid4().hex[:10]
        try:
            with db_connect() as db:
                with db.cursor() as cursor:
                    cursor.execute("""
                        UPDATE files
                        SET share_token = %s
                        WHERE token = %s
                    """, (share_token, token))
                db.commit()
            return share_token
        except psycopg2.errors.UniqueViolation:
            continue

    raise RuntimeError("Could not create a unique share token")


def get_file_by_share_token(share_token):
    with db_connect() as db:
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM files
                WHERE share_token = %s
                AND (
                    expires_at IS NULL
                    OR expires_at > NOW()
                )
            """, (share_token,))
            return cursor.fetchone()


def create_pair_code(token):
    """Create a verified TV pairing code in the dedicated pairing table."""
    for _ in range(50):
        pair_code = f"{secrets.randbelow(1000000):06d}"
        try:
            with db_connect() as db:
                with db.cursor() as cursor:
                    # The file must exist and still be valid before a code can
                    # be issued.  Store the exact six-digit string separately
                    # from the legacy files.pair_code field.
                    cursor.execute("""
                        SELECT token, expires_at
                        FROM files
                        WHERE token = %s
                        AND (expires_at IS NULL OR expires_at > NOW())
                        FOR UPDATE
                    """, (token,))
                    file_row = cursor.fetchone()
                    if not file_row:
                        raise RuntimeError("File row missing or already expired")

                    expires_at = file_row.get("expires_at")
                    if expires_at is None:
                        cursor.execute("""
                            UPDATE files
                            SET expires_at = NOW() + INTERVAL '12 hours'
                            WHERE token = %s
                            RETURNING expires_at
                        """, (token,))
                        expires_at = cursor.fetchone()["expires_at"]

                    # Replace any older code for this file.  This keeps
                    # regeneration safe with the UNIQUE(token) constraint.
                    cursor.execute("""
                        DELETE FROM tv_pairings
                        WHERE token = %s
                    """, (token,))

                    cursor.execute("""
                        INSERT INTO tv_pairings(code, token, expires_at)
                        VALUES (%s, %s, %s)
                    """, (pair_code, token, expires_at))

                    # Keep the legacy column populated for compatibility with
                    # older share/inspection code, but it is NOT the source of
                    # truth for pairing anymore.
                    cursor.execute("""
                        UPDATE files
                        SET pair_code = %s
                        WHERE token = %s
                    """, (pair_code, token))

                db.commit()

            # Hard verification through the same resolver used by /pair/{code}.
            if get_file_by_pair_code(pair_code):
                print(f"[PAIR] Created verified code {pair_code} for token {token}")
                return pair_code

            print(f"[PAIR] ERROR: code {pair_code} was stored but resolver could not find it")

        except psycopg2.errors.UniqueViolation:
            # Either the random code or token already exists.  Generate another.
            continue
        except Exception as error:
            print(f"[PAIR] create_pair_code failed for token {token}: {error}")
            raise

    raise RuntimeError("Could not create a verified unique TV pairing code")


def get_file_by_pair_code(pair_code):
    """Resolve a currently valid TV pairing code.

    Dedicated tv_pairings is the source of truth.  The legacy files.pair_code
    lookup remains as a compatibility fallback for codes created by older
    server versions.
    """
    normalized = str(pair_code or "").strip()
    if not re.fullmatch(r"\d{6}", normalized):
        return None

    with db_connect() as db:
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT f.*
                FROM tv_pairings p
                JOIN files f ON f.token = p.token
                WHERE p.code = %s
                  AND p.expires_at > NOW()
                  AND (f.expires_at IS NULL OR f.expires_at > NOW())
                LIMIT 1
            """, (normalized,))
            row = cursor.fetchone()
            if row:
                return row

            # Compatibility with codes issued by the previous implementation.
            cursor.execute("""
                SELECT *
                FROM files
                WHERE TRIM(COALESCE(pair_code::text, '')) = %s
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY expires_at DESC NULLS LAST
                LIMIT 1
            """, (normalized,))
            row = cursor.fetchone()
            if row:
                return row

    return None



def record_file_access(token, action="stream"):
    try:
        with db_connect() as db:
            with db.cursor() as cursor:
                cursor.execute("""UPDATE files SET last_accessed=NOW(), last_stream_started=CASE WHEN %s='stream' THEN NOW() ELSE last_stream_started END, view_count=view_count+CASE WHEN %s='stream' THEN 1 ELSE 0 END, download_count=download_count+CASE WHEN %s='download' THEN 1 ELSE 0 END WHERE token=%s""", (action, action, action, token))
            db.commit()
    except Exception as error:
        print("[STATS] File access update failed:", error)


def record_bytes_served(token, bytes_served):
    if not bytes_served:
        return
    try:
        with db_connect() as db:
            with db.cursor() as cursor:
                cursor.execute("UPDATE files SET last_accessed=NOW(), total_bytes_served=total_bytes_served+%s WHERE token=%s", (int(bytes_served), token))
            db.commit()
    except Exception as error:
        print("[STATS] Byte counter update failed:", error)


def get_file(token):

    with db_connect() as db:

        with db.cursor() as cursor:

            cursor.execute("""
                SELECT *
                FROM files
                WHERE token = %s
                AND (
                    expires_at IS NULL
                    OR expires_at > NOW()
                )
            """, (
                token,
            ))

            return cursor.fetchone()

