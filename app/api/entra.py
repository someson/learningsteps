"""Sign-in with Microsoft Entra ID (OpenID Connect, authorization code + PKCE).

Who may sign in is decided by two settings:

  ENTRA_TENANT_ID        the tenant in the authority URL: a tenant GUID for a
                         single-tenant app, or "organizations" for a
                         multi-tenant one
  ENTRA_ALLOWED_TENANTS  comma-separated tenant GUIDs whose accounts are
                         accepted; defaults to ENTRA_TENANT_ID when that is a
                         GUID. "*" accepts every work or school account.

Nobody has to be created by hand: a user record is made on first sign-in,
keyed by the immutable (tid, oid) pair, never by e-mail or UPN, which can be
renamed or reassigned.

The app authenticates to Entra without a stored secret: in AKS it presents
the pod's Workload Identity token (AZURE_FEDERATED_TOKEN_FILE) as a client
assertion, trusted by a federated credential on the app registration
(infra-terraform/entra.tf). ENTRA_CLIENT_SECRET(_FILE) is supported for
running outside the cluster.

Only the standard library is used. The ID token's signature is not checked:
it is received directly from the token endpoint over verified TLS, in
exchange for a one-time code plus our client credential, which OpenID
Connect Core 1.0 §3.1.3.7 (6) permits in place of signature validation. All
claims that matter (iss, aud, tid, nonce, exp) are validated.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from functools import partial
from typing import Any, Dict

import asyncio

logger = logging.getLogger("entra")

AUTHORITY = os.getenv("ENTRA_AUTHORITY", "https://login.microsoftonline.com").rstrip("/")
TENANT_ID = os.getenv("ENTRA_TENANT_ID", "").strip().lower()
CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "").strip().lower()
REDIRECT_URI = os.getenv("ENTRA_REDIRECT_URI", "").strip()


def _is_guid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


_allowed = os.getenv("ENTRA_ALLOWED_TENANTS", "").replace(" ", "").lower()
ALLOWED_TENANTS = {t for t in _allowed.split(",") if t} or ({TENANT_ID} if _is_guid(TENANT_ID) else set())
ALLOW_ANY_TENANT = ALLOWED_TENANTS == {"*"}

ENABLED = bool(TENANT_ID and CLIENT_ID and REDIRECT_URI)

SCOPES = "openid profile"
# Value of the app role that makes a user an administrator of this app.
ADMIN_ROLE = "Admin"
CLOCK_SKEW_SECONDS = 300
TRANSACTION_TTL_SECONDS = 600


def _check_config() -> None:
    if not ENABLED:
        return
    parsed = urllib.parse.urlparse(AUTHORITY)
    local = parsed.hostname in {"localhost", "127.0.0.1"}
    # Plain HTTP only for a local test identity provider.
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise RuntimeError("ENTRA_AUTHORITY must be an https URL")
    # Fail closed: a multi-tenant app with no allow-list would admit anyone.
    if not ALLOWED_TENANTS:
        raise RuntimeError('Set ENTRA_ALLOWED_TENANTS (tenant GUIDs, or "*" for any work/school account)')
    if not ALLOW_ANY_TENANT and not all(_is_guid(t) for t in ALLOWED_TENANTS):
        raise RuntimeError("ENTRA_ALLOWED_TENANTS must be tenant GUIDs")


_check_config()


class EntraError(Exception):
    """Sign-in failed. The message is for the logs, never for the client."""


class TenantNotAllowed(EntraError):
    """A valid Microsoft account, but from a tenant that is not allowed."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_transaction() -> Dict[str, str]:
    """state (CSRF on the callback), nonce (binds the ID token to this
    browser) and the PKCE verifier (binds the code to this client)."""
    return {
        "state": secrets.token_urlsafe(32),
        "nonce": secrets.token_urlsafe(32),
        "verifier": secrets.token_urlsafe(48),
        "created": str(int(time.time())),
    }


def encode_transaction(tx: Dict[str, str]) -> str:
    return _b64url(json.dumps(tx, separators=(",", ":")).encode())


def decode_transaction(value: str | None) -> Dict[str, str] | None:
    if not value:
        return None
    try:
        tx = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if int(tx["created"]) + TRANSACTION_TTL_SECONDS < time.time():
            return None
        return {k: str(tx[k]) for k in ("state", "nonce", "verifier")}
    except (ValueError, KeyError, TypeError):
        return None


def authorize_url(tx: Dict[str, str]) -> str:
    challenge = _b64url(hashlib.sha256(tx["verifier"].encode()).digest())
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        # query, not form_post: the callback stays a GET, which the CSRF
        # middleware (rightly) would refuse as a cross-site POST.
        "response_mode": "query",
        "scope": SCOPES,
        "state": tx["state"],
        "nonce": tx["nonce"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{AUTHORITY}/{TENANT_ID}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"


def _client_credential() -> Dict[str, str]:
    secret_file = os.getenv("ENTRA_CLIENT_SECRET_FILE")
    secret = os.getenv("ENTRA_CLIENT_SECRET")
    if secret_file:
        with open(secret_file) as f:
            secret = f.read().strip()
    if secret:
        return {"client_secret": secret}

    # Workload Identity: kubelet rotates this file; read it on every use.
    token_file = os.getenv("AZURE_FEDERATED_TOKEN_FILE")
    if not token_file:
        raise EntraError("no client credential: set ENTRA_CLIENT_SECRET(_FILE) or run with Workload Identity")
    with open(token_file) as f:
        assertion = f.read().strip()
    return {
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,
    }


def _post_form_sync(url: str, form: Dict[str, str]) -> Dict[str, Any]:
    # S310: the scheme is fixed by _check_config (https, or http to localhost).
    request = urllib.request.Request(  # noqa: S310
        url,
        data=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10, context=ssl.create_default_context()) as resp:  # noqa: S310
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read(2000).decode(errors="replace")
        raise EntraError(f"token endpoint returned {e.code}: {body}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise EntraError(f"token endpoint unreachable: {e}") from None


def _jwt_claims(token: str) -> Dict[str, Any]:
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as e:
        raise EntraError(f"malformed id_token: {e}") from None


def validate_claims(claims: Dict[str, Any], nonce: str, now: float | None = None) -> Dict[str, str]:
    """Checks the ID token's claims; returns the identity we store."""
    now = time.time() if now is None else now
    tid = str(claims.get("tid", "")).lower()
    if not _is_guid(tid) or not (ALLOW_ANY_TENANT or tid in ALLOWED_TENANTS):
        raise TenantNotAllowed(f"account from tenant {tid!r} is not allowed")
    # The v2.0 issuer names the account's own tenant, also for multi-tenant apps.
    if claims.get("iss") != f"{AUTHORITY}/{tid}/v2.0":
        raise EntraError(f"unexpected issuer {claims.get('iss')!r}")
    aud = claims.get("aud")
    if (aud if isinstance(aud, str) else "").lower() != CLIENT_ID:
        raise EntraError(f"unexpected audience {aud!r}")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise EntraError("nonce mismatch")
    try:
        exp, iat = float(claims["exp"]), float(claims["iat"])
    except (KeyError, TypeError, ValueError):
        raise EntraError("missing exp/iat") from None
    if exp < now - CLOCK_SKEW_SECONDS or iat > now + CLOCK_SKEW_SECONDS:
        raise EntraError("id_token expired or not yet valid")
    oid = str(claims.get("oid", ""))
    if not oid:
        raise EntraError("no oid claim")
    upn = str(claims.get("preferred_username", ""))[:256]
    # App roles assigned to the user in Entra (infra-terraform/entra.tf).
    roles = claims.get("roles")
    is_admin = isinstance(roles, list) and ADMIN_ROLE in roles
    return {
        "is_admin": is_admin,
        "tenant_id": tid,
        "object_id": oid.lower(),
        "upn": upn.lower() or None,
        "display_name": str(claims.get("name", "") or upn or "Microsoft user")[:256],
    }


async def redeem_code(code: str, tx: Dict[str, str]) -> Dict[str, str]:
    """Exchanges the authorization code for an ID token and validates it."""
    form = {
        "client_id": CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": tx["verifier"],
        "scope": SCOPES,
        **_client_credential(),
    }
    url = f"{AUTHORITY}/{TENANT_ID}/oauth2/v2.0/token"
    result = await asyncio.get_running_loop().run_in_executor(None, partial(_post_form_sync, url, form))
    id_token = result.get("id_token")
    if not isinstance(id_token, str):
        raise EntraError("no id_token in token response")
    return validate_claims(_jwt_claims(id_token), tx["nonce"])
