import logging
import mimetypes
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import selectinload

from . import internal_downloader
from . import reclip
from .config import get_settings
from .database import SessionLocal
from .models import Bookmark
from .url_safety import UnsafeUrlError, ensure_public_source_url

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
THUMBNAIL_EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp"}


def process_bookmark_download(bookmark_id: int) -> None:
    settings = get_settings()

    with SessionLocal() as db:
        bookmark = db.get(Bookmark, bookmark_id, options=[selectinload(Bookmark.categories)])
        if bookmark is None or bookmark.mode != "download_media":
            return

        try:
            bookmark.status = "info_fetching"
            bookmark.error_message = None
            db.commit()

            backend = settings.downloader_backend.strip().lower()
            info = _get_media_info(backend, bookmark.source_url)
            if bookmark.title == bookmark.source_url and info.get("title"):
                bookmark.title = str(info["title"])
            bookmark.uploader = info.get("uploader")
            bookmark.duration = _safe_int(info.get("duration"))
            bookmark.thumbnail_url = info.get("thumbnail")
            bookmark.local_thumbnail_path = _download_remote_thumbnail(
                bookmark.id,
                bookmark.thumbnail_url,
            )
            bookmark.status = "downloading"
            db.commit()

            if backend == "reclip":
                job_id, original_filename, source_path = _download_with_reclip(bookmark.source_url)
            elif backend in {"internal", "yt-dlp", "ytdlp"}:
                downloaded = internal_downloader.download(bookmark.source_url, bookmark.id)
                job_id = downloaded.job_id
                original_filename = downloaded.original_filename
                source_path = downloaded.temp_path
            else:
                raise ValueError("DOWNLOADER_BACKEND must be 'internal' or 'reclip'")

            bookmark.reclip_job_id = job_id
            db.commit()

            target_dir, media_type = _target_dir_for(original_filename)
            media_filename = _safe_media_filename(bookmark.id, job_id, original_filename, media_type)
            destination = target_dir / media_filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_path.replace(destination)

            if not bookmark.local_thumbnail_path and media_type == "video":
                bookmark.local_thumbnail_path = _generate_video_thumbnail(bookmark.id, destination)

            bookmark.reclip_filename = original_filename
            bookmark.media_filename = media_filename
            bookmark.media_path = str(destination)
            bookmark.media_type = media_type
            bookmark.status = "ready"
            bookmark.error_message = None
            db.commit()
            logger.info("bookmark %s download completed", bookmark_id)
        except Exception as exc:
            db.rollback()
            failed = db.get(Bookmark, bookmark_id)
            if failed is not None:
                failed.status = "failed"
                failed.error_message = str(exc)[:1000]
                db.commit()
            logger.exception("bookmark %s download failed", bookmark_id)


def _get_media_info(backend: str, url: str) -> dict:
    if backend == "reclip":
        return reclip.get_info(url)
    if backend in {"internal", "yt-dlp", "ytdlp"}:
        return internal_downloader.get_info(url)
    raise ValueError("DOWNLOADER_BACKEND must be 'internal' or 'reclip'")


def _download_with_reclip(url: str) -> tuple[str, str, Path]:
    settings = get_settings()
    job_id = reclip.start_download(
        url,
        format_id=settings.reclip_default_format_id,
    )
    status_payload = _wait_for_reclip_job(job_id)
    original_filename = status_payload.get("filename") or f"{job_id}.mp4"
    temp_path = settings.tmp_dir / f"{job_id}_{Path(original_filename).name}"
    reclip.download_file(job_id, temp_path)
    return job_id, original_filename, temp_path


def _wait_for_reclip_job(job_id: str) -> dict:
    settings = get_settings()
    deadline = time.monotonic() + settings.reclip_download_timeout_seconds

    while time.monotonic() < deadline:
        payload = reclip.get_status(job_id)
        status_value = str(payload.get("status") or "").lower()
        if status_value == "done":
            return payload
        if status_value in {"error", "failed"} or payload.get("error"):
            raise reclip.ReClipError(str(payload.get("error") or "ReClip download failed"))
        time.sleep(settings.reclip_poll_interval_seconds)

    raise reclip.ReClipError("ReClip download timed out")


def _target_dir_for(filename: str) -> tuple[Path, str]:
    settings = get_settings()
    media_type = _media_type_for(filename)
    if media_type == "image":
        return settings.images_dir, "image"
    if media_type == "audio":
        return settings.audio_dir, "audio"
    return settings.videos_dir, "video"


def _media_type_for(filename: str, content_type: str | None = None) -> str:
    if content_type:
        content_type = content_type.split(";")[0].strip().lower()
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("audio/"):
            return "audio"

    extension = Path(filename).suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "unknown"


def _safe_media_filename(bookmark_id: int, job_id: str, original_filename: str, media_type: str) -> str:
    extension = Path(original_filename).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension or ""):
        if media_type == "image":
            extension = ".jpg"
        elif media_type == "audio":
            extension = ".mp3"
        else:
            extension = ".mp4"
    safe_job_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", job_id).strip("-") or "reclip"
    return f"{bookmark_id}_{safe_job_id}{extension}"


def _download_remote_thumbnail(bookmark_id: int, thumbnail_url: object) -> str | None:
    if not isinstance(thumbnail_url, str) or not thumbnail_url.strip():
        return None

    thumbnail_url = thumbnail_url.strip()
    try:
        ensure_public_source_url(thumbnail_url)
    except UnsafeUrlError:
        logger.warning("bookmark %s thumbnail URL was blocked", bookmark_id)
        return None

    settings = get_settings()
    try:
        with httpx.Client(timeout=30, follow_redirects=True, trust_env=False) as client:
            response = client.get(thumbnail_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type")
            media_type = _media_type_for(thumbnail_url, content_type)
            if media_type != "image":
                return None

            extension = _thumbnail_extension(thumbnail_url, content_type)
            destination = settings.thumbnails_dir / f"{bookmark_id}_thumb{extension}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(response.content)
            return str(destination)
    except httpx.HTTPError as exc:
        logger.warning("bookmark %s thumbnail download failed: %s", bookmark_id, exc)
        return None


def _generate_video_thumbnail(bookmark_id: int, media_path: Path) -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.info("ffmpeg not available; skipping fallback thumbnail for bookmark %s", bookmark_id)
        return None

    destination = get_settings().thumbnails_dir / f"{bookmark_id}_thumb.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-ss",
        "00:00:01",
        "-i",
        str(media_path),
        "-frames:v",
        "1",
        "-vf",
        "scale='min(720,iw)':-2",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("bookmark %s fallback thumbnail generation failed: %s", bookmark_id, exc)
        return None
    return str(destination) if destination.exists() else None


def _thumbnail_extension(url: str, content_type: str | None) -> str:
    extension = Path(urlsplit(url).path).suffix.lower()
    if extension in THUMBNAIL_EXTENSIONS:
        return extension

    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if guessed in THUMBNAIL_EXTENSIONS:
        return ".jpg" if guessed == ".jpe" else guessed

    return ".jpg"


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
