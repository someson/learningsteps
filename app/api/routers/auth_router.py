import hmac
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

import entra
from metrics import LOGINS
from security import (
    COOKIE_SECURE,
    LOCAL_LOGIN,
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
    # Every signed-in user may open the API docs (see main.py).
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "docs_url": "/docs",
        "is_admin": bool(user.get("is_admin")),
    }


async def require_admin(request: Request) -> Dict[str, Any]:
    """Dependency: a signed-in administrator, or 401/403."""
    user = await current_user(request)
    if not user.get("is_admin"):
        audit.warning("admin access denied user=%s ip=%s path=%s", user["username"], client_ip(request.scope), request.url.path)
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user


# Short-lived cookie carrying state, nonce and the PKCE verifier across the
# round trip to Microsoft. SameSite=Lax, unlike the session cookie: it must
# come back on the top-level redirect from login.microsoftonline.com.
ENTRA_TX_COOKIE = "__Host-entra-tx" if COOKIE_SECURE else "entra-tx"


def _start_session(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )


@router.get("/config")
async def auth_config():
    """Which sign-in methods the login screen should offer. Public."""
    return {"password": LOCAL_LOGIN, "entra": entra.ENABLED}


@router.get("/entra/login", include_in_schema=False)
async def entra_login():
    if not entra.ENABLED:
        raise HTTPException(status_code=404, detail="Microsoft sign-in is not configured")
    tx = entra.new_transaction()
    response = RedirectResponse(entra.authorize_url(tx), status_code=303)
    response.set_cookie(
        ENTRA_TX_COOKIE,
        entra.encode_transaction(tx),
        max_age=entra.TRANSACTION_TTL_SECONDS,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/entra/callback", include_in_schema=False)
async def entra_callback(request: Request):
    """Microsoft redirects here. Every outcome is a redirect back to the UI;
    details of a failure go to the logs only."""
    if not entra.ENABLED:
        raise HTTPException(status_code=404, detail="Microsoft sign-in is not configured")
    ip = client_ip(request.scope)
    params = request.query_params
    tx = entra.decode_transaction(request.cookies.get(ENTRA_TX_COOKIE))

    def back(error: str | None = None) -> RedirectResponse:
        LOGINS.labels("entra", "ok" if not error else "disabled" if error == "account_disabled" else "failed").inc()
        response = RedirectResponse("/" + (f"?login_error={error}" if error else ""), status_code=303)
        response.delete_cookie(ENTRA_TX_COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax")
        return response

    if params.get("error"):
        audit.warning("entra login refused by Microsoft ip=%s error=%s", ip, params.get("error"))
        return back("entra_cancelled" if params.get("error") == "access_denied" else "entra_failed")
    if not tx or not params.get("code") or not hmac.compare_digest(params.get("state", ""), tx["state"]):
        audit.warning("entra login rejected: missing or mismatched state ip=%s", ip)
        return back("entra_failed")

    try:
        identity = await entra.redeem_code(params["code"], tx)
    except entra.TenantNotAllowed as e:
        audit.warning("entra login rejected ip=%s: %s", ip, e)
        return back("entra_tenant")
    except entra.EntraError as e:
        audit.warning("entra login failed ip=%s: %s", ip, e)
        return back("entra_failed")

    user = await get_db(request).upsert_entra_user(identity)
    if user["disabled_at"]:
        audit.warning("entra login refused: account disabled user=%s ip=%s", identity["upn"], ip)
        return back("account_disabled")
    token = new_session_token()
    await get_db(request).create_session(user["id"], token_hash(token), SESSION_TTL_SECONDS)
    response = back()
    _start_session(response, token)
    audit.info(
        "login ok via entra user=%s tid=%s oid=%s new=%s admin=%s ip=%s",
        identity["upn"], identity["tenant_id"], identity["object_id"], user["created"], user["is_admin"], ip,
    )
    return response


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    if not LOCAL_LOGIN:
        raise HTTPException(status_code=404, detail="Password sign-in is disabled")
    db = get_db(request)
    username = body.username.strip().lower()
    ip = client_ip(request.scope)

    failures = await db.recent_login_failures(username, ip, FAILURE_WINDOW_SECONDS)
    if failures["by_user"] >= MAX_FAILURES_PER_USER or failures["by_ip"] >= MAX_FAILURES_PER_IP:
        audit.warning("login throttled user=%s ip=%s", username, ip)
        LOGINS.labels("password", "throttled").inc()
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
        LOGINS.labels("password", "failed").inc()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    await db.clear_login_failures(username)
    # Checked only after the password: a blocked account's existence is not
    # revealed to someone who does not know its password.
    if user["disabled_at"]:
        audit.warning("login refused: account disabled user=%s ip=%s", username, ip)
        LOGINS.labels("password", "disabled").inc()
        raise HTTPException(status_code=403, detail="This account is disabled")
    await db.mark_login(user["id"])
    token = new_session_token()
    await db.create_session(user["id"], token_hash(token), SESSION_TTL_SECONDS)
    _start_session(response, token)
    audit.info("login ok user=%s ip=%s", username, ip)
    LOGINS.labels("password", "ok").inc()
    # Same shape as /me (display name, admin flag), read back from the session.
    return _user_out(request, await db.get_session_user(token_hash(token)))


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

