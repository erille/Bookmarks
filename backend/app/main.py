from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import ensure_storage_dirs, get_settings
from .database import init_db
from .routers import api, web


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_storage_dirs()
    init_db()
    yield


settings = get_settings()
APP_DIR = Path(__file__).resolve().parent
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie=settings.session_cookie_name,
    https_only=settings.session_cookie_secure,
    same_site=settings.session_cookie_samesite,
)

app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.include_router(web.router)
app.include_router(api.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
