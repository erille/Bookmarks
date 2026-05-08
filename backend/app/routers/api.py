import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..auth import require_api_token
from ..config import get_settings
from ..database import get_db
from ..downloads import process_bookmark_download
from ..export_import import export_library, import_library
from ..models import Bookmark, Category, Tag
from ..previews import process_bookmark_preview
from ..schemas import (
    BookmarkCreate,
    BookmarkCreateResponse,
    BookmarkListResponse,
    BookmarkResponse,
    BookmarkUpdate,
    CategoryCreate,
    CategoryListResponse,
    CategoryResponse,
    TagCreate,
    TagListResponse,
    TagResponse,
)
from ..url_safety import UnsafeUrlError, ensure_public_source_url

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_token)])

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


@router.get("/export")
def export_bookmarks(db: Session = Depends(get_db)) -> dict:
    return export_library(db)


@router.post("/import")
def import_bookmarks(
    payload: dict = Body(...),
    overwrite: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return import_library(db, payload, overwrite_existing=overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "category"


def normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    netloc = parsed.netloc.lower()
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        query=urlencode(query, doseq=True),
        fragment="",
    )
    return urlunsplit(normalized)


def hash_url(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def media_url_for(bookmark: Bookmark) -> str | None:
    return local_media_url_for(bookmark.media_path)


def thumbnail_url_for(bookmark: Bookmark) -> str | None:
    return local_media_url_for(bookmark.local_thumbnail_path) or bookmark.thumbnail_url


def local_media_url_for(path_value: str | None) -> str | None:
    if not path_value:
        return None

    settings = get_settings()
    media_root = settings.bookmarks_media_root.resolve()
    media_path = Path(path_value).resolve()
    try:
        relative_path = media_path.relative_to(media_root)
    except ValueError:
        return None
    return "/media/" + relative_path.as_posix()


def source_platform_for(bookmark: Bookmark) -> str:
    hostname = (urlsplit(bookmark.source_url).hostname or "").lower()
    for prefix in ("www.", "m.", "mobile."):
        if hostname.startswith(prefix):
            hostname = hostname.removeprefix(prefix)

    platform_names = {
        "facebook.com": "Facebook",
        "fb.watch": "Facebook",
        "instagram.com": "Instagram",
        "tiktok.com": "TikTok",
        "twitter.com": "X",
        "x.com": "X",
        "youtu.be": "YouTube",
        "youtube.com": "YouTube",
    }
    return platform_names.get(hostname, hostname or "Unknown")


def bookmark_response(bookmark: Bookmark) -> BookmarkResponse:
    return BookmarkResponse(
        id=bookmark.id,
        title=bookmark.title,
        source_url=bookmark.source_url,
        uploader=bookmark.uploader,
        duration=bookmark.duration,
        thumbnail_url=thumbnail_url_for(bookmark),
        media_url=media_url_for(bookmark),
        media_type=bookmark.media_type,
        source_platform=source_platform_for(bookmark),
        status=bookmark.status,
        visibility=bookmark.visibility,
        mode=bookmark.mode,
        categories=sorted(category.name for category in bookmark.categories),
        tags=sorted(tag.name for tag in bookmark.tags),
        created_at=bookmark.created_at,
        updated_at=bookmark.updated_at,
    )


def get_or_create_categories(
    db: Session,
    names: list[str],
    create_missing: bool,
) -> list[Category]:
    categories: list[Category] = []
    seen_slugs: set[str] = set()
    for name in names:
        slug = slugify(name)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        category = db.query(Category).filter(Category.slug == slug).one_or_none()
        if category is None:
            if not create_missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown category: {name}",
                )
            category = Category(name=name, slug=slug)
            db.add(category)
            db.flush()
        categories.append(category)
    return categories


def get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    seen_slugs: set[str] = set()
    for name in names:
        slug = slugify(name)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        tag = db.query(Tag).filter(Tag.slug == slug).one_or_none()
        if tag is None:
            tag = Tag(name=name, slug=slug)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(db: Session = Depends(get_db)) -> CategoryListResponse:
    rows = (
        db.query(Category, func.count(Bookmark.id).label("bookmark_count"))
        .outerjoin(Category.bookmarks)
        .group_by(Category.id)
        .order_by(Category.name.asc())
        .all()
    )
    return CategoryListResponse(
        items=[
            CategoryResponse(
                id=category.id,
                name=category.name,
                slug=category.slug,
                bookmark_count=bookmark_count,
            )
            for category, bookmark_count in rows
        ]
    )


@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> CategoryResponse:
    slug = slugify(payload.name)
    existing = db.query(Category).filter(Category.slug == slug).one_or_none()
    if existing:
        response.status_code = status.HTTP_200_OK
        return CategoryResponse(
            id=existing.id,
            name=existing.name,
            slug=existing.slug,
            bookmark_count=len(existing.bookmarks),
        )

    category = Category(name=payload.name, slug=slug)
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        response.status_code = status.HTTP_200_OK
        category = db.query(Category).filter(Category.slug == slug).one()
    else:
        db.refresh(category)

    return CategoryResponse(
        id=category.id,
        name=category.name,
        slug=category.slug,
        bookmark_count=len(category.bookmarks),
    )


@router.get("/tags", response_model=TagListResponse)
def list_tags(db: Session = Depends(get_db)) -> TagListResponse:
    rows = (
        db.query(Tag, func.count(Bookmark.id).label("bookmark_count"))
        .outerjoin(Tag.bookmarks)
        .group_by(Tag.id)
        .order_by(Tag.name.asc())
        .all()
    )
    return TagListResponse(
        items=[
            TagResponse(
                id=tag.id,
                name=tag.name,
                slug=tag.slug,
                bookmark_count=bookmark_count,
            )
            for tag, bookmark_count in rows
        ]
    )


@router.post("/tags", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: TagCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> TagResponse:
    slug = slugify(payload.name)
    existing = db.query(Tag).filter(Tag.slug == slug).one_or_none()
    if existing:
        response.status_code = status.HTTP_200_OK
        return TagResponse(
            id=existing.id,
            name=existing.name,
            slug=existing.slug,
            bookmark_count=len(existing.bookmarks),
        )

    tag = Tag(name=payload.name, slug=slug)
    db.add(tag)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        response.status_code = status.HTTP_200_OK
        tag = db.query(Tag).filter(Tag.slug == slug).one()
    else:
        db.refresh(tag)

    return TagResponse(
        id=tag.id,
        name=tag.name,
        slug=tag.slug,
        bookmark_count=len(tag.bookmarks),
    )


@router.get("/bookmarks", response_model=BookmarkListResponse)
def list_bookmarks(
    q: str | None = None,
    category: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    visibility: str | None = Query(default=None, pattern="^(public|private)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> BookmarkListResponse:
    query = db.query(Bookmark).options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
    joined_categories = False

    if category:
        query = query.join(Bookmark.categories)
        joined_categories = True
        category_slug = slugify(category)
        query = query.filter(or_(Category.slug == category_slug, Category.name == category))

    if status_filter:
        query = query.filter(Bookmark.status == status_filter)

    if visibility:
        query = query.filter(Bookmark.visibility == visibility)

    if q:
        if not joined_categories:
            query = query.outerjoin(Bookmark.categories)
        query = query.outerjoin(Bookmark.tags)
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Bookmark.title.ilike(like),
                Bookmark.source_url.ilike(like),
                Bookmark.uploader.ilike(like),
                Category.name.ilike(like),
                Tag.name.ilike(like),
            )
        ).distinct()

    total = query.count()
    bookmarks = (
        query.order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return BookmarkListResponse(
        items=[bookmark_response(bookmark) for bookmark in bookmarks],
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get("/bookmarks/{bookmark_id}", response_model=BookmarkResponse)
def get_bookmark(bookmark_id: int, db: Session = Depends(get_db)) -> BookmarkResponse:
    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.id == bookmark_id)
        .one_or_none()
    )
    if bookmark is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found")
    return bookmark_response(bookmark)


@router.patch("/bookmarks/{bookmark_id}", response_model=BookmarkResponse)
def update_bookmark(
    bookmark_id: int,
    payload: BookmarkUpdate,
    db: Session = Depends(get_db),
) -> BookmarkResponse:
    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.id == bookmark_id)
        .one_or_none()
    )
    if bookmark is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found")

    if "title" in payload.model_fields_set and payload.title:
        bookmark.title = payload.title
    if "notes" in payload.model_fields_set:
        bookmark.notes = payload.notes
    if payload.visibility:
        bookmark.visibility = payload.visibility
    if payload.categories is not None:
        bookmark.categories = get_or_create_categories(
            db,
            payload.categories,
            payload.create_missing_categories,
        )
    if payload.tags is not None:
        bookmark.tags = get_or_create_tags(db, payload.tags)

    db.commit()
    db.refresh(bookmark)
    return bookmark_response(bookmark)


@router.post("/bookmarks/{bookmark_id}/retry", response_model=BookmarkResponse)
def retry_bookmark_download(
    bookmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> BookmarkResponse:
    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.id == bookmark_id)
        .one_or_none()
    )
    if bookmark is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bookmark not found")
    if bookmark.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed bookmarks can be retried",
        )

    bookmark.mode = "download_media"
    bookmark.status = "pending"
    bookmark.error_message = None
    bookmark.reclip_job_id = None
    bookmark.reclip_filename = None
    db.commit()
    db.refresh(bookmark)
    background_tasks.add_task(process_bookmark_download, bookmark.id)
    return bookmark_response(bookmark)


@router.post("/bookmarks", response_model=BookmarkCreateResponse, status_code=status.HTTP_201_CREATED)
def create_bookmark(
    payload: BookmarkCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
) -> BookmarkCreateResponse:
    try:
        ensure_public_source_url(payload.source_url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    url_hash = hash_url(payload.source_url)
    existing = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.source_url_hash == url_hash)
        .one_or_none()
    )
    if existing:
        response.status_code = status.HTTP_200_OK
        return BookmarkCreateResponse(
            created=False,
            duplicate=True,
            bookmark=bookmark_response(existing),
        )

    categories = get_or_create_categories(db, payload.categories, payload.create_missing_categories)
    tags = get_or_create_tags(db, payload.tags)
    status_value = "bookmark_only" if payload.mode == "bookmark_only" else "pending"
    bookmark = Bookmark(
        title=payload.title or payload.source_url,
        source_url=payload.source_url,
        source_url_hash=url_hash,
        status=status_value,
        visibility=payload.visibility,
        mode=payload.mode,
        media_type="unknown",
        categories=categories,
        tags=tags,
    )
    db.add(bookmark)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        response.status_code = status.HTTP_200_OK
        duplicate = (
            db.query(Bookmark)
            .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
            .filter(Bookmark.source_url_hash == url_hash)
            .one()
        )
        return BookmarkCreateResponse(
            created=False,
            duplicate=True,
            bookmark=bookmark_response(duplicate),
        )

    db.refresh(bookmark)
    if bookmark.mode == "download_media":
        background_tasks.add_task(process_bookmark_download, bookmark.id)
    else:
        background_tasks.add_task(process_bookmark_preview, bookmark.id)

    return BookmarkCreateResponse(
        created=True,
        duplicate=False,
        bookmark=bookmark_response(bookmark),
    )
