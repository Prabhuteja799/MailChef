import secrets

from fastapi import Header, HTTPException, status

from app.config import settings


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    """Guards every CLI-facing route. This is a personal, single-user API:
    one shared bearer token (MAILCHEF_API_TOKEN), not a full user/session system.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, settings.mailchef_api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")
