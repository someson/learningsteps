import json
import os
import uuid
import asyncpg
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from dotenv import load_dotenv
from repositories.interface_repository import DatabaseInterface

load_dotenv()


def get_database_url() -> str:
    """Read the DSN from DATABASE_URL_FILE (a mounted secret) or DATABASE_URL.

    The file variant keeps the password out of the process environment, where
    it would be visible in `kubectl describe pod` and inherited by children.
    """
    path = os.getenv("DATABASE_URL_FILE")
    if path:
        with open(path) as f:
            return f.read().strip()
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL or DATABASE_URL_FILE")
    return url


# Sort keys the API accepts, mapped to fixed SQL. Never interpolate client
# input into ORDER BY; only these literals are.
SORT_COLUMNS = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "work": "lower(data->>'work')",
    "struggle": "lower(data->>'struggle')",
    "intention": "lower(data->>'intention')",
}

# Every entry query below is scoped to its owner ($1) and hides soft-deleted
# rows: "user_id = $1 AND deleted_at IS NULL". Queries are plain literals;
# only list_entries composes SQL, and only from the fixed pieces above.


def _row_to_entry(row: asyncpg.Record) -> Dict[str, Any]:
    data = json.loads(row["data"])
    return {
        "id": row["id"],
        "work": data.get("work", ""),
        "struggle": data.get("struggle", ""),
        "intention": data.get("intention", ""),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _like_escape(text: str) -> str:
    """Escape LIKE wildcards so `text` matches literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PostgresDB(DatabaseInterface):
    # One pool per process, opened at startup (see main.py lifespan). Sized so
    # that max HPA replicas x max_size stays well under the server's
    # max_connections (~50 on B1ms).
    async def __aenter__(self):
        self.pool = await asyncpg.create_pool(
            get_database_url(),
            min_size=1,
            max_size=int(os.getenv("DB_POOL_MAX_SIZE", "5")),
        )
        return self

    async def ping(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.pool.close()

    # --- Entries ------------------------------------------------------------

    async def create_entry(self, user_id: uuid.UUID, entry_data: Dict[str, Any]) -> Dict[str, Any]:
        data = {k: entry_data[k] for k in ("work", "struggle", "intention")}
        row = await self.pool.fetchrow(
            """
            INSERT INTO entries (id, user_id, data, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $4)
            RETURNING id, data, created_at, updated_at
            """,
            entry_data["id"], user_id, json.dumps(data), entry_data["created_at"],
        )
        return _row_to_entry(row)

    async def list_entries(
        self, user_id: uuid.UUID, *, limit: int, offset: int, query: str, sort: str, direction: str
    ) -> Dict[str, Any]:
        order = SORT_COLUMNS[sort]
        direction = "ASC" if direction == "asc" else "DESC"
        params: List[Any] = [user_id]
        where = "user_id = $1 AND deleted_at IS NULL"
        if query:
            params += [f"%{_like_escape(query)}%", _like_escape(query.lower()) + "%"]
            where += (
                " AND (data->>'work' ILIKE $2 OR data->>'struggle' ILIKE $2"
                " OR data->>'intention' ILIKE $2 OR id LIKE $3)"
            )

        async with self.pool.acquire() as conn:
            # S608: `where`, `order` and `direction` come from the fixed strings
            # above, limit/offset are ints; all client values are bind params.
            rows = await conn.fetch(
                f"""
                SELECT id, data, created_at, updated_at FROM entries WHERE {where}
                ORDER BY {order} {direction}, id {direction}
                LIMIT {int(limit)} OFFSET {int(offset)}
                """,  # noqa: S608
                *params,
            )
            count = await conn.fetchval(f"SELECT count(*) FROM entries WHERE {where}", *params)  # noqa: S608
            totals = await conn.fetchrow(
                """
                SELECT count(*) AS total, max(created_at) AS latest FROM entries
                WHERE user_id = $1 AND deleted_at IS NULL
                """,
                user_id,
            )
        return {
            "entries": [_row_to_entry(r) for r in rows],
            "count": count,
            "total": totals["total"],
            "latest_created_at": totals["latest"],
        }

    async def get_entry(self, user_id: uuid.UUID, entry_id: str) -> Dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            SELECT id, data, created_at, updated_at FROM entries
            WHERE user_id = $1 AND deleted_at IS NULL AND id = $2
            """,
            user_id, entry_id,
        )
        return _row_to_entry(row) if row else None

    async def update_entry(
        self, user_id: uuid.UUID, entry_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        # One atomic statement: JSONB `||` merges only the sent fields, so two
        # concurrent PATCHes of different fields cannot overwrite each other
        # (the previous read-merge-write could).
        row = await self.pool.fetchrow(
            """
            UPDATE entries SET data = data || $3::jsonb, updated_at = $4
            WHERE user_id = $1 AND deleted_at IS NULL AND id = $2
            RETURNING id, data, created_at, updated_at
            """,
            user_id, entry_id, json.dumps(changes), datetime.now(timezone.utc),
        )
        return _row_to_entry(row) if row else None

    async def delete_entry(self, user_id: uuid.UUID, entry_id: str) -> bool:
        result = await self.pool.execute(
            "UPDATE entries SET deleted_at = now() WHERE user_id = $1 AND deleted_at IS NULL AND id = $2",
            user_id, entry_id,
        )
        return result != "UPDATE 0"

    async def restore_entry(self, user_id: uuid.UUID, entry_id: str) -> Dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            UPDATE entries SET deleted_at = NULL
            WHERE user_id = $1 AND id = $2 AND deleted_at IS NOT NULL
            RETURNING id, data, created_at, updated_at
            """,
            user_id, entry_id,
        )
        return _row_to_entry(row) if row else None

    async def delete_all_entries(self, user_id: uuid.UUID) -> int:
        result = await self.pool.execute(
            "UPDATE entries SET deleted_at = now() WHERE user_id = $1 AND deleted_at IS NULL", user_id
        )
        return int(result.split()[-1])

    # --- Users and sessions -------------------------------------------------

    async def get_user_by_username(self, username: str) -> Dict[str, Any] | None:
        row = await self.pool.fetchrow(
            "SELECT id, username, password_hash, is_admin, disabled_at FROM users WHERE username = $1", username
        )
        return dict(row) if row else None

    async def create_user(self, username: str, password_hash: str, is_admin: bool = False) -> Dict[str, Any]:
        row = await self.pool.fetchrow(
            """
            INSERT INTO users (id, username, password_hash, is_admin) VALUES ($1, $2, $3, $4)
            RETURNING id, username
            """,
            uuid.uuid4(), username, password_hash, is_admin,
        )
        return dict(row)

    async def set_admin(self, user_id: uuid.UUID, is_admin: bool) -> None:
        await self.pool.execute("UPDATE users SET is_admin = $2 WHERE id = $1", user_id, is_admin)

    async def mark_login(self, user_id: uuid.UUID) -> None:
        await self.pool.execute("UPDATE users SET last_login_at = now() WHERE id = $1", user_id)

    async def set_password(self, user_id: uuid.UUID, password_hash: str) -> None:
        # A new password ends every existing session of that user.
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("UPDATE users SET password_hash = $2 WHERE id = $1", user_id, password_hash)
            await conn.execute("DELETE FROM sessions WHERE user_id = $1", user_id)

    async def adopt_orphan_entries(self, user_id: uuid.UUID) -> int:
        result = await self.pool.execute("UPDATE entries SET user_id = $1 WHERE user_id IS NULL", user_id)
        return int(result.split()[-1])

    async def upsert_entra_user(self, identity: Dict[str, Any]) -> Dict[str, Any]:
        """Finds the Entra user by (tenant, object ID), creating it on first
        sign-in; refreshes the UPN and display name every time."""
        row = await self.pool.fetchrow(
            """
            INSERT INTO users (id, entra_tenant_id, entra_object_id, upn, display_name, is_admin, last_login_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (entra_tenant_id, entra_object_id)
            DO UPDATE SET upn = EXCLUDED.upn, display_name = EXCLUDED.display_name,
                          is_admin = EXCLUDED.is_admin, last_login_at = now()
            RETURNING id, display_name AS username, is_admin, disabled_at, (xmax = 0) AS created
            """,
            uuid.uuid4(), uuid.UUID(identity["tenant_id"]), uuid.UUID(identity["object_id"]),
            identity["upn"], identity["display_name"], identity["is_admin"],
        )
        return dict(row)

    async def find_user(self, name: str) -> Dict[str, Any] | None:
        """By local username or Entra UPN (for operator tools)."""
        row = await self.pool.fetchrow(
            "SELECT id, coalesce(upn, username) AS name FROM users WHERE username = $1 OR upn = $1", name
        )
        return dict(row) if row else None

    async def create_session(self, user_id: uuid.UUID, token_hash: bytes, ttl_seconds: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE expires_at < now()")
            await conn.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ($1, $2, $3)",
                token_hash, user_id, datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            )

    async def get_session_user(self, token_hash: bytes) -> Dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            SELECT u.id, coalesce(u.display_name, u.username) AS username, u.is_admin
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = $1 AND s.expires_at > now() AND u.disabled_at IS NULL
            """,
            token_hash,
        )
        return dict(row) if row else None

    async def delete_session(self, token_hash: bytes) -> None:
        await self.pool.execute("DELETE FROM sessions WHERE token_hash = $1", token_hash)

    # --- Administration -----------------------------------------------------

    async def list_users(self) -> List[Dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT u.id, coalesce(u.display_name, u.username) AS name, coalesce(u.upn, u.username) AS login,
                   CASE WHEN u.entra_object_id IS NULL THEN 'local' ELSE 'entra' END AS kind,
                   u.is_admin, u.disabled_at, u.created_at, u.last_login_at,
                   count(e.id) FILTER (WHERE e.deleted_at IS NULL) AS entries
            FROM users u LEFT JOIN entries e ON e.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at
            """
        )
        return [dict(r) for r in rows]

    async def count_orphan_entries(self) -> int:
        return await self.pool.fetchval(
            "SELECT count(*) FROM entries WHERE user_id IS NULL AND deleted_at IS NULL"
        )

    async def set_disabled(self, user_id: uuid.UUID, disabled: bool) -> bool:
        """Blocks or unblocks a user; blocking also ends every session."""
        async with self.pool.acquire() as conn, conn.transaction():
            result = await conn.execute(
                "UPDATE users SET disabled_at = CASE WHEN $2 THEN now() ELSE NULL END WHERE id = $1",
                user_id, disabled,
            )
            if disabled:
                await conn.execute("DELETE FROM sessions WHERE user_id = $1", user_id)
        return result != "UPDATE 0"

    # --- Login throttling ---------------------------------------------------

    async def recent_login_failures(self, username: str, ip: str, window_seconds: int) -> Dict[str, int]:
        since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        row = await self.pool.fetchrow(
            """
            SELECT
              (SELECT count(*) FROM login_failures WHERE username = $1 AND failed_at > $3) AS by_user,
              (SELECT count(*) FROM login_failures WHERE client_ip = $2 AND failed_at > $3) AS by_ip
            """,
            username, ip, since,
        )
        return {"by_user": row["by_user"], "by_ip": row["by_ip"]}

    async def record_login_failure(self, username: str, ip: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM login_failures WHERE failed_at < now() - interval '1 day'")
            await conn.execute(
                "INSERT INTO login_failures (username, client_ip) VALUES ($1, $2)", username, ip
            )

    async def clear_login_failures(self, username: str) -> None:
        await self.pool.execute("DELETE FROM login_failures WHERE username = $1", username)
