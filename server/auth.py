import os
import secrets
import time

from fastapi import Header, HTTPException, Query

_KEY = os.getenv("AUTH_KEY", "")
_SECRET = os.getenv("AUTH_SECRET", "")

_authenticated_sessions: dict[str, float] = {}
SESSION_TTL = 86400  # 24 hours


def register_session(session_id: str) -> None:
    """Register a session_id as authenticated for SSE/stream access."""
    _authenticated_sessions[session_id] = time.time() + SESSION_TTL


def is_session_authenticated(session_id: str) -> bool:
    """Check if a session_id is authenticated and not expired."""
    expiry = _authenticated_sessions.get(session_id)
    return expiry is not None and time.time() < expiry


async def verify_auth(
    x_auth_key: str = Header(default=""),
    x_auth_secret: str = Header(default=""),
    auth_key: str = Query(default=""),
    auth_secret: str = Query(default=""),
    session_id: str = Query(default=""),
) -> None:
    """Verify auth credentials from headers, query params, or session_id. Disabled if env vars not set."""
    # auth disabled when env vars not set
    if not _KEY and not _SECRET:
        return

    # session_id-based auth takes precedence (no key/secret needed)
    if session_id and is_session_authenticated(session_id):
        return

    # fallback to key+secret verification
    key = x_auth_key or auth_key
    secret = x_auth_secret or auth_secret

    key_ok = secrets.compare_digest(key, _KEY)
    secret_ok = secrets.compare_digest(secret, _SECRET)

    if not key_ok or not secret_ok:
        raise HTTPException(status_code=401, detail="Unauthorized")
