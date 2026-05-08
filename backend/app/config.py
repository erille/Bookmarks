from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Bookmarks"
    app_env: str = "production"
    app_base_url: str = "http://localhost:8015"

    bookmarks_root: Path = Path("/srv/webdata/bookmarks")
    bookmarks_db_path: Path = Path("/srv/webdata/bookmarks/data/bookmarks.sqlite")
    bookmarks_media_root: Path = Path("/srv/webdata/bookmarks/media")
    bookmarks_log_dir: Path = Path("/srv/webdata/bookmarks/logs")

    downloader_backend: str = "internal"
    ytdlp_format: str = (
        "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
        "best[height<=720][ext=mp4]/best[height<=720]/best"
    )
    ytdlp_socket_timeout_seconds: int = 30

    reclip_base_url: str = "http://127.0.0.1:8899"
    reclip_default_format_id: str = "18"
    reclip_poll_interval_seconds: int = 2
    reclip_download_timeout_seconds: int = 900

    bookmarks_username: str = "admin"
    bookmarks_password_hash: str = Field(default="CHANGE_ME", min_length=1)
    bookmarks_api_token: str = Field(default="CHANGE_ME_LONG_RANDOM_TOKEN", min_length=1)

    session_secret_key: str = Field(default="CHANGE_ME_LONG_RANDOM_SECRET", min_length=1)
    session_cookie_name: str = "bookmarks_session"
    session_cookie_secure: bool = True
    session_cookie_samesite: str = "lax"

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    @property
    def data_dir(self) -> Path:
        return self.bookmarks_db_path.parent

    @property
    def videos_dir(self) -> Path:
        return self.bookmarks_media_root / "videos"

    @property
    def images_dir(self) -> Path:
        return self.bookmarks_media_root / "images"

    @property
    def audio_dir(self) -> Path:
        return self.bookmarks_media_root / "audio"

    @property
    def thumbnails_dir(self) -> Path:
        return self.bookmarks_media_root / "thumbnails"

    @property
    def previews_dir(self) -> Path:
        return self.bookmarks_media_root / "previews"

    @property
    def tmp_dir(self) -> Path:
        return self.bookmarks_media_root / "tmp"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_storage_dirs(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    for path in (
        settings.bookmarks_root,
        settings.data_dir,
        settings.videos_dir,
        settings.images_dir,
        settings.audio_dir,
        settings.thumbnails_dir,
        settings.previews_dir,
        settings.tmp_dir,
        settings.bookmarks_log_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
