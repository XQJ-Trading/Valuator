import os
import secrets

from fastapi import Header, HTTPException, Query

_KEY = os.getenv("AUTH_KEY", "")
_SECRET = os.getenv("AUTH_SECRET", "")


async def verify_auth(
    x_auth_key: str = Header(default=""),
    x_auth_secret: str = Header(default=""),
    auth_key: str = Query(default=""),
    auth_secret: str = Query(default=""),
) -> None:
    """Verify auth credentials from headers or query params. Disabled if env vars not set."""
    # auth disabled when env vars not set
    if not _KEY and not _SECRET:
        return

    key = x_auth_key or auth_key
    secret = x_auth_secret or auth_secret

    key_ok = secrets.compare_digest(key, _KEY)
    secret_ok = secrets.compare_digest(secret, _SECRET)

    if not key_ok or not secret_ok:
        raise HTTPException(status_code=401, detail="Unauthorized")
