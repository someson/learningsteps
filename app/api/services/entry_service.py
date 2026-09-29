import logging
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from repositories.postgres_repository import PostgresDB

logger = logging.getLogger("journal")


class EntryService:
    """Entry operations for one user. Every call is scoped to that user, so
    one account can neither see nor change another's entries."""

    def __init__(self, db: PostgresDB, user_id: UUID):
        self.db = db
        self.user_id = user_id

    async def create_entry(self, entry_data: Dict[str, Any]) -> Dict[str, Any]:
        entry = {**entry_data, "created_at": datetime.now(timezone.utc)}
        return await self.db.create_entry(self.user_id, entry)

    async def list_entries(self, **params: Any) -> Dict[str, Any]:
        return await self.db.list_entries(self.user_id, **params)

    async def get_entry(self, entry_id: str) -> Dict[str, Any] | None:
        return await self.db.get_entry(self.user_id, entry_id)

    async def update_entry(self, entry_id: str, changes: Dict[str, Any]) -> Dict[str, Any] | None:
        return await self.db.update_entry(self.user_id, entry_id, changes)

    async def delete_entry(self, entry_id: str) -> bool:
        return await self.db.delete_entry(self.user_id, entry_id)

    async def restore_entry(self, entry_id: str) -> Dict[str, Any] | None:
        return await self.db.restore_entry(self.user_id, entry_id)

    async def delete_all_entries(self) -> int:
        return await self.db.delete_all_entries(self.user_id)
