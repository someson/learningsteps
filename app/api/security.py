"""Passwords, session tokens and the HTTP hardening middleware.

Everything here uses the standard library only, so the runtime image gains
no new dependencies (and Trivy no new packages to track).
"""
import asyncio
import base64
import contextvars
import hashlib
import hmac
import logging
import os
import secrets
import uuid
from functools import partial
from pathlib import Path

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# --- Settings ---------------------------------------------------------------

def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


# Secure cookies need HTTPS. On by default; the local docker compose stack
# serves plain HTTP and turns it off in app/.env.
COOKIE_SECURE = env_flag("COOKIE_SECURE", True)
# The __Host- prefix makes the browser refuse the cookie unless it is Secure,
# host-only and path=/, so a sibling subdomain cannot set or shadow it.
SESSION_COOKIE = "__Host-session" if COOKIE_SECURE else "session"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_HOURS", "12")) * 3600

# Username/password sign-in. On by default for local development and CI;
# AKS turns it off so Microsoft Entra ID is the only way in.
PASSWORD_LOGIN = env_flag("PASSWORD_LOGIN", True)

# /docs, /redoc and /openapi.json map the whole API for an attacker; off
# unless explicitly enabled (the local docker compose stack enables it).
DOCS_ENABLED = env_flag("ENABLE_DOCS", False)

# Entries are three 256-character fields; 16 KiB is ample and caps the work a
# single request can cause before validation.
MAX_BODY_BYTES = 16 * 1024

# --- Passwords --------------------------------------------------------------
# scrypt with N=2^14, r=8, p=5: one of OWASP's equivalent scrypt settings,
# chosen for its 16 MiB memory use per hash (the API pod is limited to
# 256 MiB). Parameters are stored with each hash, so they can be raised later
# without invalidating existing passwords.

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 5
# Bounds concurrent hashing per process: each hash takes 16 MiB and ~50 ms of
# CPU, so a login flood must not be able to exhaust the pod's memory.
_hash_slots = asyncio.Semaphore(2)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password_sync(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password_sync(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, base64.b64decode(digest))


# Verified when the username does not exist, so a login for an unknown user
# costs the same time as one for a real user (no username enumeration).
DUMMY_HASH = hash_password_sync(secrets.token_urlsafe(16))


async def verify_password(password: str, stored: str | None) -> bool:
    async with _hash_slots:
        ok = await asyncio.get_running_loop().run_in_executor(
            None, partial(verify_password_sync, password, stored or DUMMY_HASH)
        )
    return ok and stored is not None


# --- Session tokens ---------------------------------------------------------

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


# --- Request context and logging -------------------------------------------

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Adds the current request ID to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def client_ip(scope: Scope) -> str:
    # uvicorn has already replaced this with X-Forwarded-For when the peer is
    # in FORWARDED_ALLOW_IPS (Caddy in AKS); otherwise it is the socket peer.
    client = scope.get("client")
    return client[0] if client else "unknown"


# --- Middleware -------------------------------------------------------------
# Pure ASGI rather than BaseHTTPMiddleware: they can reject a request before
# its body is read and never buffer a response.

def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None


async def _send_json(send: Send, status: int, detail: str) -> None:
    body = ('{"detail": "%s"}' % detail).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """413 for bodies over MAX_BODY_BYTES, declared or streamed (chunked)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _header(scope, b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
            await _send_json(send, 413, "Request body too large")
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise BodyTooLarge()
            return message

        await self.app(scope, limited_receive, send)


class BodyTooLarge(HTTPException):
    # An HTTPException so FastAPI's body parsing re-raises it as is (it wraps
    # any other error into a 400) and the exception handler answers 413.
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body too large")


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware:
    """Rejects cross-site state-changing requests to /api.

    The session cookie is SameSite=Strict already; this is the second layer.
    Browsers send Sec-Fetch-Site and Origin on such requests; non-browser
    clients (curl, tests) send neither and carry no ambient cookie, so they
    are not a CSRF vector. Requiring a JSON body also rules out plain HTML
    form posts, which cannot set that content type cross-site.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in UNSAFE_METHODS
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        fetch_site = _header(scope, b"sec-fetch-site")
        if fetch_site is not None and fetch_site not in {"same-origin", "none"}:
            await _send_json(send, 403, "Cross-site request rejected")
            return

        origin = _header(scope, b"origin")
        host = _header(scope, b"host")
        if origin is not None and (origin == "null" or origin.split("://", 1)[-1] != host):
            await _send_json(send, 403, "Cross-origin request rejected")
            return

        if scope["method"] in {"POST", "PUT", "PATCH"}:
            content_type = (_header(scope, b"content-type") or "").split(";")[0].strip().lower()
            has_body = (_header(scope, b"content-length") or "0") != "0" or _header(scope, b"transfer-encoding")
            if has_body and content_type != "application/json":
                await _send_json(send, 415, "Content-Type must be application/json")
                return

        await self.app(scope, receive, send)


def _inline_script_hashes(index_html: Path) -> list[str]:
    """CSP hashes of the inline scripts in the built index.html (the
    pre-paint theme script), so the policy needs no 'unsafe-inline'."""
    import re

    if not index_html.is_file():
        return []
    html = index_html.read_text()
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, flags=re.S)
    return [f"'sha256-{_b64(hashlib.sha256(s.encode()).digest())}'" for s in scripts]


class SecurityHeadersMiddleware:
    """Security headers on every response, plus a request ID.

    Set here rather than only in Caddy so they also apply to the local
    docker compose stack and cannot drift from the app that needs them.
    """

    def __init__(self, app: ASGIApp, index_html: Path) -> None:
        self.app = app
        script_src = " ".join(["'self'", *_inline_script_hashes(index_html)])
        # style-src needs 'unsafe-inline': Radix and Sonner position popovers
        # and toasts with inline styles. Scripts, the real XSS vector, do not.
        self.ui_csp = (
            f"default-src 'self'; script-src {script_src}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        ).encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        token = request_id_var.set(request_id)
        path = scope["path"]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"cross-origin-resource-policy", b"same-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
                ]
                if path.startswith("/api/"):
                    # Journal data is private: never cached by browsers or proxies.
                    headers += [
                        (b"cache-control", b"no-store"),
                        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
                    ]
                elif path == "/" or path.startswith("/assets/"):
                    headers.append((b"content-security-policy", self.ui_csp))
                # /docs is left without a CSP: Swagger UI loads from a CDN
                # with inline scripts. It is disabled unless ENABLE_DOCS=true.
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            request_id_var.reset(token)
