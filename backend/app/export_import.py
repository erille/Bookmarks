import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .models import Bookmark, Category, Tag

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}
STATUS_VALUES = {"pending", "info_fetching", "downloading", "ready", "failed", "bookmark_only"}
MODE_VALUES = {"bookmark_only", "download_media"}
VISIBILITY_VALUES = {"public", "private"}
MEDIA_TYPE_VALUES = {"video", "image", "website", "unknown"}


def export_library(db: Session) -> dict:
    categories = db.query(Category).order_by(Category.name.asc()).all()
    tags = db.query(Tag).order_by(Tag.name.asc()).all()
    bookmarks = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .order_by(Bookmark.created_at.asc(), Bookmark.id.asc())
        .all()
    )
    return {
        "app": "Bookmarks",
        "schema_version": 2,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "categories": [
            {
                "name": category.name,
                "slug": category.slug,
                "created_at": isoformat(category.created_at),
            }
            for category in categories
        ],
        "tags": [
            {
                "name": tag.name,
                "slug": tag.slug,
                "created_at": isoformat(tag.created_at),
            }
            for tag in tags
        ],
        "bookmarks": [bookmark_to_export_item(bookmark) for bookmark in bookmarks],
    }


def bookmark_to_export_item(bookmark: Bookmark) -> dict:
    return {
        "title": bookmark.title,
        "source_url": bookmark.source_url,
        "uploader": bookmark.uploader,
        "duration": bookmark.duration,
        "thumbnail_url": bookmark.thumbnail_url,
        "local_thumbnail_path": bookmark.local_thumbnail_path,
        "media_filename": bookmark.media_filename,
        "media_path": bookmark.media_path,
        "media_type": bookmark.media_type,
        "reclip_job_id": bookmark.reclip_job_id,
        "reclip_filename": bookmark.reclip_filename,
        "status": bookmark.status,
        "visibility": bookmark.visibility,
        "mode": bookmark.mode,
        "notes": bookmark.notes,
        "categories": sorted(category.name for category in bookmark.categories),
        "tags": sorted(tag.name for tag in bookmark.tags),
        "created_at": isoformat(bookmark.created_at),
        "updated_at": isoformat(bookmark.updated_at),
    }


def import_library(db: Session, payload: dict, *, overwrite_existing: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Import payload must be a JSON object.")

    category_items = payload.get("categories") or []
    tag_items = payload.get("tags") or []
    bookmark_items = payload.get("bookmarks") or []
    if (
        not isinstance(category_items, list)
        or not isinstance(tag_items, list)
        or not isinstance(bookmark_items, list)
    ):
        raise ValueError("Import payload must include categories, tags, and bookmarks lists.")

    summary = {
        "categories_created": 0,
        "tags_created": 0,
        "bookmarks_created": 0,
        "bookmarks_updated": 0,
        "bookmarks_skipped": 0,
        "bookmarks_failed": 0,
        "errors": [],
    }

    for item in category_items:
        name = import_category_name(item)
        if not name:
            continue
        _, created = get_or_create_category(db, name)
        if created:
            summary["categories_created"] += 1

    for item in tag_items:
        name = import_label_name(item)
        if not name:
            continue
        _, created = get_or_create_tag(db, name)
        if created:
            summary["tags_created"] += 1

    for index, item in enumerate(bookmark_items):
        try:
            result = import_bookmark_item(db, item, overwrite_existing=overwrite_existing)
        except ValueError as exc:
            summary["bookmarks_failed"] += 1
            summary["errors"].append({"index": index, "error": str(exc)})
            continue
        summary[result] += 1

    db.commit()
    return summary


def import_bookmark_item(
    db: Session,
    item: object,
    *,
    overwrite_existing: bool,
) -> str:
    if not isinstance(item, dict):
        raise ValueError("Bookmark item must be an object.")

    source_url = clean_string(item.get("source_url"), max_length=4096)
    if not source_url:
        raise ValueError("Bookmark source_url is required.")
    validate_http_url(source_url)

    url_hash = hash_url(source_url)
    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.source_url_hash == url_hash)
        .one_or_none()
    )
    if bookmark is not None and not overwrite_existing:
        return "bookmarks_skipped"

    category_names = clean_string_list(item.get("categories"))
    categories = [get_or_create_category(db, name)[0] for name in category_names]
    has_tags = "tags" in item
    tag_names = clean_string_list(item.get("tags")) if has_tags else []
    tags = [get_or_create_tag(db, name)[0] for name in tag_names]

    values = bookmark_values_from_item(item, source_url, url_hash)
    if values["created_at"] is None:
        del values["created_at"]
    if values["updated_at"] is None:
        del values["updated_at"]
    if bookmark is None:
        bookmark = Bookmark(**values, categories=categories, tags=tags)
        db.add(bookmark)
        return "bookmarks_created"

    for key, value in values.items():
        if key in {"created_at", "source_url_hash"}:
            continue
        setattr(bookmark, key, value)
    bookmark.categories = categories
    if has_tags:
        bookmark.tags = tags
    return "bookmarks_updated"


def bookmark_values_from_item(item: dict, source_url: str, url_hash: str) -> dict:
    mode = clean_choice(item.get("mode"), MODE_VALUES, "download_media")
    return {
        "title": clean_string(item.get("title"), max_length=500) or source_url,
        "source_url": source_url,
        "source_url_hash": url_hash,
        "uploader": clean_string(item.get("uploader"), max_length=500),
        "duration": clean_int(item.get("duration")),
        "thumbnail_url": clean_string(item.get("thumbnail_url"), max_length=4096),
        "local_thumbnail_path": safe_media_path(item.get("local_thumbnail_path")),
        "media_filename": clean_string(item.get("media_filename"), max_length=500),
        "media_path": safe_media_path(item.get("media_path")),
        "media_type": clean_choice(item.get("media_type"), MEDIA_TYPE_VALUES, "unknown"),
        "reclip_job_id": clean_string(item.get("reclip_job_id"), max_length=500),
        "reclip_filename": clean_string(item.get("reclip_filename"), max_length=500),
        "status": clean_choice(
            item.get("status"),
            STATUS_VALUES,
            "bookmark_only" if mode == "bookmark_only" else "pending",
        ),
        "visibility": clean_choice(item.get("visibility"), VISIBILITY_VALUES, "public"),
        "mode": mode,
        "notes": clean_string(item.get("notes"), max_length=2000),
        "created_at": parse_datetime(item.get("created_at")),
        "updated_at": parse_datetime(item.get("updated_at")),
    }


def import_category_name(item: object) -> str | None:
    return import_label_name(item)


def import_label_name(item: object) -> str | None:
    if isinstance(item, str):
        return clean_category_name(item)
    if isinstance(item, dict):
        return clean_category_name(item.get("name"))
    return None


def get_or_create_category(db: Session, name: str) -> tuple[Category, bool]:
    slug = slugify(name)
    category = db.query(Category).filter(Category.slug == slug).one_or_none()
    if category is not None:
        return category, False
    category = Category(name=name, slug=slug)
    db.add(category)
    db.flush()
    return category, True


def get_or_create_tag(db: Session, name: str) -> tuple[Tag, bool]:
    slug = slugify(name)
    tag = db.query(Tag).filter(Tag.slug == slug).one_or_none()
    if tag is not None:
        return tag, False
    tag = Tag(name=name, slug=slug)
    db.add(tag)
    db.flush()
    return tag, True


def normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(query, doseq=True),
        fragment="",
    )
    return urlunsplit(normalized)


def hash_url(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "category"


def validate_http_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only http and https URLs are supported.")


def safe_media_path(value: object) -> str | None:
    path_value = clean_string(value, max_length=4096)
    if not path_value:
        return None

    media_root = get_settings().bookmarks_media_root.resolve()
    path = Path(path_value).resolve(strict=False)
    try:
        path.relative_to(media_root)
    except ValueError:
        return None
    return str(path)


def clean_category_name(value: object) -> str | None:
    return clean_string(value, max_length=80)


def clean_string(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value[:max_length] or None


def clean_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        name = clean_category_name(item)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        names.append(name)
        seen.add(key)
    return names


def clean_choice(value: object, allowed: set[str], default: str) -> str:
    value = clean_string(value, max_length=80)
    return value if value in allowed else default


def clean_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
