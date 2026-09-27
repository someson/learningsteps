import json
import os
import uuid
import asyncpg
from datetime import datetime, timezone
from typing import Any, Dict, List
from contextlib import asynccontextmanager
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


class PostgresDB(DatabaseInterface):
    @staticmethod
    def datetime_serialize(obj):
        """Convert datetime objects to ISO format for JSON serialization."""
        if isinstance(obj, datetime):
                return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

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

    async def create_entry(self, entry_data: Dict[str, Any]) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            query = """
            INSERT INTO entries (id, data, created_at, updated_at)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """
            entry_id = entry_data.get("id") or str(uuid.uuid4())
            data_json = json.dumps(entry_data, default=PostgresDB.datetime_serialize)
            
            row = await conn.fetchrow(
                query, 
                entry_id, 
                data_json, 
                entry_data["created_at"], 
                entry_data["updated_at"]
            )
            
            # Return a clean entry format without duplication
            if row:
                data = json.loads(row["data"])
                return {
                    "id": row["id"],
                    "work": data.get("work", ""),
                    "struggle": data.get("struggle", ""),
                    "intention": data.get("intention", ""),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            return {}

    async def get_all_entries(self) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM entries"
            rows = await conn.fetch(query)
            entries = []
            for row in rows:
                data = json.loads(row["data"])
                entries.append({
                    "id": row["id"],
                    "work": data.get("work", ""),
                    "struggle": data.get("struggle", ""),
                    "intention": data.get("intention", ""),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                })
            return entries
        
    async def get_entry(self, entry_id: str) -> Dict[str, Any] | None:
        async with self.pool.acquire() as conn:
            query = "SELECT * FROM entries WHERE id = $1"
            row = await conn.fetchrow(query, entry_id)
            
            if row:
                data = json.loads(row["data"])
                return {
                    "id": row["id"],
                    "work": data.get("work", ""),
                    "struggle": data.get("struggle", ""),
                    "intention": data.get("intention", ""),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            return None
   
    async def update_entry(self, entry_id: str, updated_data: Dict[str, Any]) -> None:
        updated_at = datetime.now(timezone.utc)
        updated_data["id"] = entry_id
        updated_data["updated_at"] = updated_at

        data_json = json.dumps(updated_data, default=PostgresDB.datetime_serialize)

        async with self.pool.acquire() as conn:
            query = """
            UPDATE entries 
            SET data = $2, updated_at = $3
            WHERE id = $1
            """
            await conn.execute(query, entry_id, data_json, updated_at)

    async def delete_entry(self, entry_id: str) -> None:
        async with self.pool.acquire() as conn:
            query = "DELETE FROM entries WHERE id = $1"
            await conn.execute(query, entry_id)

    async def delete_all_entries(self) -> None:
        async with self.pool.acquire() as conn:
            query = "DELETE FROM entries"
            await conn.execute(query)
