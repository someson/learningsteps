import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from security import (
    COOKIE_SECURE,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    client_ip,
    new_session_token,
    token_hash,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
audit = logging.getLogger("audit")

# Brute-force throttling, shared by all replicas through the database.
# Per username: slows guessing one account. Per IP: slows spraying many; kept
# looser so users behind one NAT do not lock each other out (in AKS, Caddy
# caps login attempts per IP at 10/min on top of this).
FAILURE_WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_USER = 5
MAX_FAILURES_PER_IP = 50


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def get_db(request: Request):
    return request.app.state.db


async def current_user(request: Request) -> Dict[str, Any]:
    """Dependency: the signed-in user, or 401."""
    token = request.cookies.get(SESSION_COOKIE)
    user = await get_db(request).get_session_user(token_hash(token)) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    request.state.user = user
    return user


def _user_out(request: Request, user: Dict[str, Any]) -> Dict[str, Any]:
    return {"username": user["username"], "docs_url": request.app.docs_url}


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    db = get_db(request)
    username = body.username.strip().lower()
    ip = client_ip(request.scope)

    failures = await db.recent_login_failures(username, ip, FAILURE_WINDOW_SECONDS)
    if failures["by_user"] >= MAX_FAILURES_PER_USER or failures["by_ip"] >= MAX_FAILURES_PER_IP:
        audit.warning("login throttled user=%s ip=%s", username, ip)
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(FAILURE_WINDOW_SECONDS)},
        )

    user = await db.get_user_by_username(username)
    # Runs a full hash check even for unknown users, so response time does not
    # reveal which usernames exist; the error message is the same too.
    if not await verify_password(body.password, user["password_hash"] if user else None):
        await db.record_login_failure(username, ip)
        audit.warning("login failed user=%s ip=%s", username, ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    await db.clear_login_failures(username)
    token = new_session_token()
    await db.create_session(user["id"], token_hash(token), SESSION_TTL_SECONDS)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )
    audit.info("login ok user=%s ip=%s", username, ip)
    return _user_out(request, user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await get_db(request).delete_session(token_hash(token))
    response.delete_cookie(SESSION_COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="strict")
    audit.info("logout ip=%s", client_ip(request.scope))


@router.get("/me")
async def me(request: Request, user: Dict[str, Any] = Depends(current_user)):
    return _user_out(request, user)

