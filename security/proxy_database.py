"""STADY-PROXY PostgreSQL access layer for the security bot."""

import psycopg

from security.config import DATABASE_URL
from security.database import get_blocked_users


def files_pg_db():
    """Open a dictionary-row PostgreSQL connection to the STADY-PROXY DB."""
    return psycopg.connect(
        DATABASE_URL,
        row_factory=psycopg.rows.dict_row,
    )


def get_proxy_users():
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        u.user_id,
                        u.first_name,
                        u.last_name,
                        u.first_seen,
                        COUNT(f.token) AS file_count
                    FROM users u
                    LEFT JOIN files f
                        ON f.chat_id = u.user_id
                    GROUP BY
                        u.user_id,
                        u.first_name,
                        u.last_name,
                        u.first_seen
                    ORDER BY u.first_seen DESC
                """)
                return cursor.fetchall()
    except Exception as error:
        print("[SECURITY] PostgreSQL users error:", error)
        return []


def get_user_files(user_id):
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        token,
                        filename,
                        size,
                        mime
                    FROM files
                    WHERE chat_id = %s
                    ORDER BY token DESC
                """, (int(user_id),))
                return cursor.fetchall()
    except Exception as error:
        print("[SECURITY] PostgreSQL files error:", error)
        return []


def purge_user_files(user_id):
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM files WHERE chat_id = %s",
                    (int(user_id),),
                )
                removed = cursor.rowcount
            db.commit()
            return removed
    except Exception as error:
        print("[SECURITY] PostgreSQL purge error:", error)
        return 0


def remove_user_data(user_id):
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT token FROM files WHERE chat_id = %s",
                    (int(user_id),),
                )
                cursor.execute(
                    "DELETE FROM access_logs WHERE chat_id = %s",
                    (int(user_id),),
                )
                cursor.execute(
                    "DELETE FROM files WHERE chat_id = %s",
                    (int(user_id),),
                )
                removed = cursor.rowcount
            db.commit()
            return removed
    except Exception as error:
        print("[SECURITY] Remove user error:", error)
        raise


def remove_token_data(token):
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute("""
                    SELECT token, chat_id, filename
                    FROM files
                    WHERE token = %s
                """, (token,))
                row = cursor.fetchone()
                if not row:
                    return None

                cursor.execute(
                    "DELETE FROM access_logs WHERE token = %s",
                    (token,),
                )
                cursor.execute(
                    "DELETE FROM files WHERE token = %s",
                    (token,),
                )
                removed = cursor.rowcount
            db.commit()
            return {
                "removed": removed,
                "chat_id": row["chat_id"],
                "filename": row["filename"],
                "token": row["token"],
            }
    except Exception as error:
        print("[SECURITY] Remove token error:", error)
        raise


def remove_user_files(user_id):
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM files WHERE chat_id = %s",
                    (int(user_id),),
                )
                removed = cursor.rowcount
            db.commit()
            return removed
    except Exception as error:
        print("[SECURITY] Remove user error:", error)
        return -1


def remove_file_by_token(token):
    try:
        with files_pg_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM files WHERE token = %s",
                    (token,),
                )
                removed = cursor.rowcount
            db.commit()
            return removed
    except Exception as error:
        print("[SECURITY] Remove token error:", error)
        return -1


def purge_all_blocked_users():
    blocked = get_blocked_users()
    total_removed = 0
    for row in blocked:
        user_id = int(row["user_id"])
        total_removed += purge_user_files(user_id)
    return total_removed
