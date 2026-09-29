import logging
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from routers.auth_router import require_admin
from security import client_ip

# Administration, for users with the "Admin" app role in Entra (or a local
# account created with create_user.py --admin). Deliberately no access to
# other users' journal entries: administrators see who uses the app and can
# block accounts, not what people wrote.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
audit = logging.getLogger("audit")


def get_db(request: Request):
    return request.app.state.db


@router.get("/users")
async def list_users(request: Request):
    """All accounts with their entry counts, plus entries that have no owner."""
    db = get_db(request)
    return {"users": await db.list_users(), "orphan_entries": await db.count_orphan_entries()}


async def _set_disabled(request: Request, user_id: UUID, disabled: bool, admin: Dict[str, Any]) -> Dict[str, Any]:
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="You cannot block or unblock your own account")
    if not await get_db(request).set_disabled(user_id, disabled):
        raise HTTPException(status_code=404, detail="User not found")
    audit.info(
        "admin.%s target=%s by=%s ip=%s",
        "block" if disabled else "unblock", user_id, admin["username"], client_ip(request.scope),
    )
    return {"id": str(user_id), "disabled": disabled}


@router.post("/users/{user_id}/block")
async def block_user(user_id: UUID, request: Request, admin: Dict[str, Any] = Depends(require_admin)):
    """Blocks sign-in for the user and ends all of their sessions immediately."""
    return await _set_disabled(request, user_id, True, admin)


@router.post("/users/{user_id}/unblock")
async def unblock_user(user_id: UUID, request: Request, admin: Dict[str, Any] = Depends(require_admin)):
    return await _set_disabled(request, user_id, False, admin)


@router.post("/orphans/adopt")
async def adopt_orphans(request: Request, admin: Dict[str, Any] = Depends(require_admin)):
    """Gives the entries created before accounts existed to the calling admin."""
    count = await get_db(request).adopt_orphan_entries(admin["id"])
    audit.info("admin.adopt_orphans count=%s by=%s ip=%s", count, admin["username"], client_ip(request.scope))
    return {"adopted": count}
