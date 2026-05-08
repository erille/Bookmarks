from pathlib import Path
from typing import Any

import httpx

from .config import get_settings


class ReClipError(RuntimeError):
    pass


def get_info(url: str) -> dict[str, Any]:
    return _request_json("POST", "/api/info", json={"url": url}, timeout=30)


def start_download(url: str, format_id: str | None = None) -> str:
    payload: dict[str, Any] = {"url": url}
    if format_id:
        payload["format_id"] = format_id
    data = _request_json("POST", "/api/download", json=payload, timeout=30)
    job_id = data.get("job_id")
    if not job_id:
        raise ReClipError("ReClip did not return a job_id")
    return str(job_id)


def get_status(job_id: str) -> dict[str, Any]:
    return _request_json("GET", f"/api/status/{job_id}", timeout=30)


def download_file(job_id: str, destination_path: Path) -> Path:
    settings = get_settings()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(30.0, read=settings.reclip_download_timeout_seconds)

    try:
        with httpx.Client(base_url=_base_url(), timeout=timeout, trust_env=False) as client:
            with client.stream("GET", f"/api/file/{job_id}") as response:
                response.raise_for_status()
                with destination_path.open("wb") as output:
                    for chunk in response.iter_bytes():
                        if chunk:
                            output.write(chunk)
    except httpx.HTTPError as exc:
        raise ReClipError(f"ReClip file download failed: {exc}") from exc

    return destination_path


def _request_json(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    try:
        with httpx.Client(base_url=_base_url(), timeout=timeout, trust_env=False) as client:
            response = client.request(method, path, json=json)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ReClipError(f"ReClip request failed: {exc}") from exc
    except ValueError as exc:
        raise ReClipError("ReClip returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise ReClipError("ReClip returned an unexpected response")
    return data


def _base_url() -> str:
    return get_settings().reclip_base_url.rstrip("/")
