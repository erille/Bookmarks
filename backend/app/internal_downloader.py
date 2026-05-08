import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .config import get_settings


class InternalDownloaderError(RuntimeError):
    pass


@dataclass
class DownloadedMedia:
    job_id: str
    info: dict[str, Any]
    original_filename: str
    temp_path: Path


def get_info(url: str) -> dict[str, Any]:
    try:
        with YoutubeDL(_base_options(download=False)) as ydl:
            return _single_info(ydl.extract_info(url, download=False))
    except DownloadError as exc:
        raise InternalDownloaderError(str(exc)) from exc
    except Exception as exc:
        raise InternalDownloaderError(f"Could not fetch media info: {exc}") from exc


def download(url: str, bookmark_id: int) -> DownloadedMedia:
    settings = get_settings()
    temp_root = settings.tmp_dir
    temp_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"bookmark-{bookmark_id}-", dir=temp_root) as temp_dir:
        temp_path = Path(temp_dir)
        options = _base_options(download=True)
        options["outtmpl"] = str(temp_path / "%(extractor_key)s-%(id)s.%(ext)s")

        try:
            with YoutubeDL(options) as ydl:
                info = _single_info(ydl.extract_info(url, download=True))
                downloaded_path = _find_downloaded_file(ydl, info, temp_path)
        except DownloadError as exc:
            raise InternalDownloaderError(str(exc)) from exc
        except Exception as exc:
            raise InternalDownloaderError(f"Download failed: {exc}") from exc

        stable_temp_path = settings.tmp_dir / f"{bookmark_id}_{downloaded_path.name}"
        downloaded_path.replace(stable_temp_path)

    job_id = _job_id_for(info)
    return DownloadedMedia(
        job_id=job_id,
        info=info,
        original_filename=stable_temp_path.name,
        temp_path=stable_temp_path,
    )


def _base_options(*, download: bool) -> dict[str, Any]:
    settings = get_settings()
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
        "trim_file_name": 180,
        "socket_timeout": settings.ytdlp_socket_timeout_seconds,
        "continuedl": True,
        "retries": 3,
        "fragment_retries": 3,
        "format": settings.ytdlp_format,
        "merge_output_format": "mp4",
        "overwrites": True,
        "ignoreerrors": False,
        "skip_download": not download,
    }


def _single_info(info: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(info, dict):
        raise InternalDownloaderError("yt-dlp returned no metadata")

    entries = info.get("entries")
    if entries:
        first = next((entry for entry in entries if isinstance(entry, dict)), None)
        if first is None:
            raise InternalDownloaderError("yt-dlp returned an empty playlist")
        return first

    return info


def _find_downloaded_file(ydl: YoutubeDL, info: dict[str, Any], temp_path: Path) -> Path:
    candidates: list[Path] = []
    for item in info.get("requested_downloads") or []:
        if not isinstance(item, dict):
            continue
        for key in ("filepath", "_filename", "filename"):
            value = item.get(key)
            if value:
                candidates.append(Path(value))

    for key in ("filepath", "_filename", "filename"):
        value = info.get(key)
        if value:
            candidates.append(Path(value))

    try:
        candidates.append(Path(ydl.prepare_filename(info)))
    except Exception:
        pass

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    files = [
        path
        for path in temp_path.iterdir()
        if path.is_file() and path.suffix not in {".part", ".ytdl", ".temp"}
    ]
    if not files:
        raise InternalDownloaderError("yt-dlp did not produce a downloadable file")

    return max(files, key=lambda path: path.stat().st_size)


def _job_id_for(info: dict[str, Any]) -> str:
    extractor = str(info.get("extractor_key") or info.get("extractor") or "ytdlp")
    media_id = str(info.get("id") or "download")
    return f"{extractor}-{media_id}"
