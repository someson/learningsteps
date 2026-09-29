import logging
from typing import Any, Dict, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from models.entry import Entry, EntryCreate, EntryUpdate
from routers.auth_router import current_user
from security import client_ip
from services.entry_service import EntryService

# Every route requires a signed-in user and only sees that user's entries.
router = APIRouter(tags=["entries"], dependencies=[Depends(current_user)])
logger = logging.getLogger("journal")
audit = logging.getLogger("audit")

MAX_PAGE_SIZE = 100


def get_entry_service(request: Request, user: Dict[str, Any] = Depends(current_user)) -> EntryService:
    return EntryService(request.app.state.db, user["id"])


def _audit(request: Request, action: str, entry_id: Any = "-", **extra: Any) -> None:
    details = " ".join(f"{k}={v}" for k, v in extra.items())
    audit.info(
        "%s user=%s entry=%s ip=%s %s",
        action, request.state.user["username"], entry_id, client_ip(request.scope), details,
    )


@router.post("/entries")
async def create_entry(
    entry_data: EntryCreate, request: Request, entry_service: EntryService = Depends(get_entry_service)
):
    """Create a new journal entry."""
    try:
        entry = Entry(work=entry_data.work, struggle=entry_data.struggle, intention=entry_data.intention)
        created_entry = await entry_service.create_entry(entry.model_dump())
    except Exception:
        # Input is already validated by EntryCreate, so anything here is a
        # server-side failure. Log the details; never echo them to the client,
        # where they would disclose schema, driver and connection information.
        logger.exception("Error creating entry")
        raise HTTPException(status_code=500, detail="Error creating entry") from None
    _audit(request, "entry.create", created_entry["id"])
    return {"detail": "Entry created successfully", "entry": created_entry}


@router.get("/entries")
async def list_entries(
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    # Bounded so a huge OFFSET cannot make Postgres scan the whole table.
    offset: int = Query(0, ge=0, le=100_000),
    q: str = Query("", max_length=100, description="Case-insensitive search in work, struggle, intention; or an ID prefix"),
    sort: Literal["created_at", "updated_at", "work", "struggle", "intention"] = "created_at",
    dir: Literal["asc", "desc"] = "desc",
    entry_service: EntryService = Depends(get_entry_service),
):
    """One page of the signed-in user's entries.

    `count` is the number of entries matching `q`; `total` is all of the
    user's entries.
    """
    result = await entry_service.list_entries(
        limit=limit, offset=offset, query=q.strip(), sort=sort, direction=dir
    )
    return {**result, "limit": limit, "offset": offset}


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: UUID, entry_service: EntryService = Depends(get_entry_service)):
    """Get a single journal entry by ID."""
    result = await entry_service.get_entry(str(entry_id))
    if not result:
        raise HTTPException(status_code=404, detail="Entry not found")
    return result


@router.patch("/entries/{entry_id}")
async def update_entry(
    entry_id: UUID,
    entry_update: EntryUpdate,
    request: Request,
    entry_service: EntryService = Depends(get_entry_service),
):
    """Update a journal entry: only the fields sent are changed."""
    changes = entry_update.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await entry_service.update_entry(str(entry_id), changes)
    if not result:
        raise HTTPException(status_code=404, detail="Entry not found")
    _audit(request, "entry.update", entry_id, fields=",".join(changes))
    return result


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: UUID, request: Request, entry_service: EntryService = Depends(get_entry_service)):
    """Delete a journal entry. Soft: it can be restored."""
    if not await entry_service.delete_entry(str(entry_id)):
        raise HTTPException(status_code=404, detail="Entry not found")
    _audit(request, "entry.delete", entry_id)
    return {"detail": "Entry deleted successfully", "entry_id": str(entry_id)}


@router.post("/entries/{entry_id}/restore")
async def restore_entry(entry_id: UUID, request: Request, entry_service: EntryService = Depends(get_entry_service)):
    """Undo the deletion of a journal entry."""
    result = await entry_service.restore_entry(str(entry_id))
    if not result:
        raise HTTPException(status_code=404, detail="No deleted entry with this ID")
    _audit(request, "entry.restore", entry_id)
    return result


@router.delete("/entries")
async def delete_all_entries(request: Request, entry_service: EntryService = Depends(get_entry_service)):
    """Delete all of the signed-in user's entries (other users are not affected)."""
    deleted = await entry_service.delete_all_entries()
    _audit(request, "entry.delete_all", count=deleted)
    return {"detail": "All entries deleted", "deleted": deleted}
