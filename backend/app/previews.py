import logging
import mimetypes
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from .config import get_settings
from .database import SessionLocal
from .models import Bookmark
from .url_safety import UnsafeUrlError, ensure_public_source_url

logger = logging.getLogger(__name__)

MAX_HTML_BYTES = 1_000_000
MAX_PREVIEW_IMAGE_BYTES = 6_000_000
MAX_REDIRECTS = 5
PREVIEW_IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
REQUEST_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "user-agent": "Bookmarks/1.0 (+http://localhost:8015)",
}


@dataclass
class PagePreview:
    title: str | None = None
    description: str | None = None
    image_url: str | None = None
    local_image_path: str | None = None


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True
            return

        if tag.lower() != "meta":
            return

        values = {name.lower(): value for name, value in attrs if value is not None}
        key = (values.get("property") or values.get("name") or "").lower()
        content = clean_text(values.get("content"))
        if key and content and key not in self.meta:
            self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str | None:
        return clean_text(" ".join(self.title_parts))


def process_bookmark_preview(bookmark_id: int) -> None:
    with SessionLocal() as db:
        bookmark = db.get(Bookmark, bookmark_id)
        if bookmark is None or bookmark.mode != "bookmark_only":
            return
        if youtube_video_id(bookmark.source_url):
            return

        try:
            preview = build_website_preview(bookmark.id, bookmark.source_url)
        except Exception as exc:
            logger.warning("bookmark %s preview generation failed: %s", bookmark_id, exc)
            return

        if should_replace_title(bookmark.title, bookmark.source_url) and preview.title:
            bookmark.title = preview.title[:500]
        if not bookmark.notes and preview.description:
            bookmark.notes = preview.description[:2000]
        if preview.local_image_path:
            bookmark.local_thumbnail_path = preview.local_image_path
            bookmark.thumbnail_url = preview.image_url
        elif preview.image_url:
            bookmark.thumbnail_url = preview.image_url
        if preview.local_image_path or preview.image_url:
            bookmark.media_type = "website"
        bookmark.error_message = None
        db.commit()


def build_website_preview(bookmark_id: int, source_url: str) -> PagePreview:
    ensure_public_source_url(source_url)
    try:
        preview = fetch_page_metadata(source_url)
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("bookmark %s metadata preview skipped: %s", bookmark_id, exc)
        preview = PagePreview()

    if preview.image_url:
        preview.local_image_path = download_preview_image(bookmark_id, preview.image_url)

    if not preview.local_image_path and not preview.image_url:
        preview.local_image_path = capture_page_screenshot(bookmark_id, source_url)
        if preview.local_image_path:
            preview.image_url = None

    return preview


def fetch_page_metadata(source_url: str) -> PagePreview:
    content, content_type, final_url = safe_fetch_bytes(source_url, max_bytes=MAX_HTML_BYTES)
    if "html" not in content_type.lower():
        return PagePreview()

    parser = MetadataParser()
    parser.feed(content.decode(encoding_from_content_type(content_type), errors="replace"))
    image_url = first_meta_value(
        parser.meta,
        "og:image:secure_url",
        "og:image:url",
        "og:image",
        "twitter:image",
        "twitter:image:src",
    )
    if image_url:
        image_url = urljoin(final_url, image_url)
        try:
            ensure_public_source_url(image_url)
        except UnsafeUrlError:
            image_url = None

    return PagePreview(
        title=first_meta_value(parser.meta, "og:title", "twitter:title") or parser.title,
        description=first_meta_value(
            parser.meta,
            "og:description",
            "twitter:description",
            "description",
        ),
        image_url=image_url,
    )


def download_preview_image(bookmark_id: int, image_url: str) -> str | None:
    try:
        content, content_type, final_url = safe_fetch_bytes(
            image_url,
            max_bytes=MAX_PREVIEW_IMAGE_BYTES,
            headers={"accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        )
    except (httpx.HTTPError, UnsafeUrlError, ValueError) as exc:
        logger.info("bookmark %s preview image download skipped: %s", bookmark_id, exc)
        return None

    extension = preview_image_extension(final_url, content_type)
    if extension is None:
        return None

    destination = get_settings().previews_dir / f"{bookmark_id}_preview{extension}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return str(destination)


def capture_page_screenshot(bookmark_id: int, source_url: str) -> str | None:
    ensure_public_source_url(source_url)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("playwright is not installed; skipping screenshot for bookmark %s", bookmark_id)
        return None

    destination = get_settings().previews_dir / f"{bookmark_id}_screenshot.png"
    destination.parent.mkdir(parents=True, exist_ok=True)

    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                device_scale_factor=1,
                java_script_enabled=False,
            )
            context.route("**/*", guarded_browser_route)
            page = context.new_page()
            page.goto(source_url, wait_until="domcontentloaded", timeout=12_000)
            page.wait_for_timeout(500)
            page.screenshot(path=str(destination), full_page=False, type="png")
    except (PlaywrightError, PlaywrightTimeoutError, UnsafeUrlError, OSError) as exc:
        logger.info("bookmark %s screenshot skipped: %s", bookmark_id, exc)
        return None
    finally:
        if browser is not None:
            try:
                browser.close()
            except PlaywrightError:
                pass

    return str(destination) if destination.exists() else None


def guarded_browser_route(route) -> None:
    request_url = route.request.url
    parsed = urlsplit(request_url)
    if parsed.scheme not in {"http", "https"}:
        route.abort()
        return

    try:
        ensure_public_source_url(request_url)
    except UnsafeUrlError:
        route.abort()
        return

    route.continue_()


def safe_fetch_bytes(
    url: str,
    *,
    max_bytes: int,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str, str]:
    ensure_public_source_url(url)
    current_url = url
    request_headers = {**REQUEST_HEADERS, **(headers or {})}

    with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            ensure_public_source_url(current_url)
            with client.stream("GET", current_url, headers=request_headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect response was missing a location")
                    current_url = urljoin(current_url, location)
                    continue

                response.raise_for_status()
                content_length = (response.headers.get("content-length") or "").strip()
                if content_length.isdigit() and int(content_length) > max_bytes:
                    raise ValueError("Response was too large")

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Response was too large")
                    chunks.append(chunk)

                return (
                    b"".join(chunks),
                    response.headers.get("content-type", ""),
                    str(response.url),
                )

    raise ValueError("Too many redirects")


def first_meta_value(values: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = clean_text(values.get(key))
        if value:
            return value
    return None


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def encoding_from_content_type(content_type: str) -> str:
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip() or "utf-8"
    return "utf-8"


def preview_image_extension(url: str, content_type: str) -> str | None:
    media_type = content_type.split(";")[0].strip().lower()
    if media_type and not media_type.startswith("image/"):
        return None

    extension = Path(urlsplit(url).path).suffix.lower()
    if extension in PREVIEW_IMAGE_EXTENSIONS:
        return extension

    guessed = mimetypes.guess_extension(media_type)
    if guessed == ".jpe":
        guessed = ".jpg"
    return guessed if guessed in PREVIEW_IMAGE_EXTENSIONS else None


def should_replace_title(title: str | None, source_url: str) -> bool:
    if not title:
        return True
    return title.strip() == source_url.strip()


def youtube_video_id(source_url: str) -> str | None:
    parsed = urlsplit(source_url.strip())
    hostname = (parsed.hostname or "").lower()
    for prefix in ("www.", "m.", "mobile."):
        if hostname.startswith(prefix):
            hostname = hostname.removeprefix(prefix)

    path_parts = [part for part in parsed.path.split("/") if part]
    if hostname == "youtu.be" and path_parts:
        video_id = path_parts[0]
    elif hostname not in {"youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        video_id = None
    elif path_parts and path_parts[0] in {"embed", "shorts", "live"} and len(path_parts) >= 2:
        video_id = path_parts[1]
    else:
        video_id = parse_qs(parsed.query).get("v", [None])[0]

    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        return None
    return video_id
