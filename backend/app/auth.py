import secrets
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException, Request, status

from .config import Settings, get_settings

password_hasher = PasswordHasher()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError, VerifyMismatchError):
        return False


def verify_login(username: str, password: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not secrets.compare_digest(username, settings.bookmarks_username):
        return False
    return verify_password(password, settings.bookmarks_password_hash)


def is_web_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated")) and bool(request.session.get("username"))


def require_web_session(request: Request) -> str:
    if not is_web_authenticated(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return str(request.session["username"])


def require_api_token(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API token")

    expected = settings.bookmarks_api_token
    if expected.startswith("CHANGE_ME"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API token is not configured",
        )
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
