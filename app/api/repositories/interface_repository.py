from abc import ABC, abstractmethod
from typing import Any, Dict
from uuid import UUID


class DatabaseInterface(ABC):
    """Abstract interface for entry storage. Every operation is scoped to the
    owning user; deletes are soft and can be undone with restore_entry."""

    @abstractmethod
    async def create_entry(self, user_id: UUID, entry_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new journal entry."""

    @abstractmethod
    async def list_entries(
        self, user_id: UUID, *, limit: int, offset: int, query: str, sort: str, direction: str
    ) -> Dict[str, Any]:
        """One page of the user's entries, with match and total counts."""

    @abstractmethod
    async def get_entry(self, user_id: UUID, entry_id: str) -> Dict[str, Any] | None:
        """Retrieve a specific journal entry by ID."""

    @abstractmethod
    async def update_entry(self, user_id: UUID, entry_id: str, changes: Dict[str, Any]) -> Dict[str, Any] | None:
        """Merge the given fields into an entry."""

    @abstractmethod
    async def delete_entry(self, user_id: UUID, entry_id: str) -> bool:
        """Soft-delete one entry. False if it did not exist."""

    @abstractmethod
    async def restore_entry(self, user_id: UUID, entry_id: str) -> Dict[str, Any] | None:
        """Undo a soft delete."""

    @abstractmethod
    async def delete_all_entries(self, user_id: UUID) -> int:
        """Soft-delete all of the user's entries; returns how many."""
