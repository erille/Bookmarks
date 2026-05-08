from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import ensure_storage_dirs, get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
DATABASE_URL = f"sqlite:///{settings.bookmarks_db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    ensure_storage_dirs(settings)
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_schema_updates()


def ensure_schema_updates() -> None:
    with engine.begin() as connection:
        bookmark_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(bookmarks)").fetchall()
        }
        if "visibility" not in bookmark_columns:
            connection.exec_driver_sql(
                "ALTER TABLE bookmarks ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public'"
            )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_bookmarks_visibility ON bookmarks(visibility)"
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_tags_slug ON tags(slug)")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_bookmark_tags_bookmark_id "
            "ON bookmark_tags(bookmark_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_bookmark_tags_tag_id ON bookmark_tags(tag_id)"
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
