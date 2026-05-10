import io
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlencode, urlsplit

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from ..auth import is_web_authenticated, verify_login
from ..config import get_settings
from ..database import get_db
from ..downloads import process_bookmark_download
from ..export_import import export_library, import_library
from ..models import Bookmark, Category, Tag
from ..previews import process_bookmark_preview
from ..schemas import BookmarkCreate
from ..url_safety import UnsafeUrlError, ensure_public_source_url
from .api import (
    get_or_create_categories,
    get_or_create_tags,
    hash_url,
    media_url_for,
    source_platform_for,
    slugify,
    thumbnail_url_for,
)

APP_DIR = Path(__file__).resolve().parents[1]
EXTENSION_DIR_CANDIDATES = (
    APP_DIR.parent / "extension",
    APP_DIR.parent.parent / "extension",
)
EXTENSION_PACKAGE_FILES = (
    "manifest.json",
    "popup.html",
    "popup.js",
    "options.html",
    "options.js",
    "styles.css",
    "icons/icon-16.png",
    "icons/icon-32.png",
    "icons/icon-48.png",
    "icons/icon-128.png",
)
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["media_url_for"] = media_url_for
templates.env.globals["source_platform_for"] = source_platform_for
templates.env.globals["thumbnail_url_for"] = thumbnail_url_for
templates.env.globals["youtube_embed_url_for"] = lambda bookmark: youtube_embed_url_for(bookmark)
templates.env.globals["has_category_slug"] = lambda bookmark, slug: has_category_slug(bookmark, slug)
templates.env.globals["bookmark_path_for"] = lambda bookmark, public=False: (
    f"/public/bookmarks/{bookmark.id}" if public else f"/bookmarks/{bookmark.id}"
)
templates.env.globals["share_url_for"] = lambda request, bookmark, public=False: (
    f"{str(request.base_url).rstrip('/')}"
    f"{'/public/bookmarks/' if public else '/bookmarks/'}{bookmark.id}"
)
templates.env.globals["asset_version"] = lambda: static_asset_version()
router = APIRouter()
FEED_PAGE_SIZE = 20
VISIBILITY_VALUES = {"public", "private"}
MEDIA_DIRECTORIES = {
    "videos": "videos_dir",
    "images": "images_dir",
    "audio": "audio_dir",
    "thumbnails": "thumbnails_dir",
    "previews": "previews_dir",
}
MAX_IMPORT_BYTES = 10 * 1024 * 1024
STORAGE_COLORS = {
    "Videos": "#1f6fb2",
    "Images": "#4b8fd0",
    "Audio": "#6aa5d8",
    "Thumbnails": "#8bbbe5",
    "Previews": "#b7d7f0",
    "Temporary": "#d4e6f5",
    "Database": "#5b6f82",
    "Logs": "#9aa9b5",
}
BOOKMARK_STATUS_LABELS = {
    "ready": "Ready",
    "failed": "Failed",
    "pending": "Pending",
    "info_fetching": "Info",
    "downloading": "Downloading",
    "bookmark_only": "Bookmark only",
}
LABEL_TYPES = {"category", "tag"}
TO_WATCH_CATEGORY_SLUG = "to-watch"


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    return render_public_feed_page(request, db, q=q, category=category, tag=tag)


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return FileResponse(APP_DIR / "static" / "favicon.ico")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    if is_web_authenticated(request):
        return RedirectResponse(url="/bookmarks", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    if verify_login(username, password):
        request.session.clear()
        request.session.update({"authenticated": True, "username": username})
        return RedirectResponse(url="/bookmarks", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid username or password."},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@router.post("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


def pop_flash(request: Request) -> str | None:
    message = request.session.pop("flash", None)
    return str(message) if message else None


@router.get("/bookmarks", response_class=HTMLResponse)
def bookmarks_page(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    return render_bookmarks_page(request, db, q=q, category=category, tag=tag)


@router.post("/bookmarks")
def create_bookmark_from_form(
    request: Request,
    background_tasks: BackgroundTasks,
    source_url: str = Form(...),
    title: str = Form(""),
    categories: list[str] | None = Form(None),
    new_categories: str = Form(""),
    tags: str = Form(""),
    mode: str = Form("download_media"),
    visibility: str = Form("public"),
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    category_names = list(categories or [])
    category_names.extend(split_category_names(new_categories))
    tag_names = split_label_names(tags)

    try:
        payload = BookmarkCreate(
            source_url=source_url,
            title=title or None,
            categories=category_names,
            tags=tag_names,
            create_missing_categories=True,
            mode=mode,
            visibility=visibility,
        )
        ensure_public_source_url(payload.source_url)
    except (ValidationError, UnsafeUrlError) as exc:
        return render_bookmarks_page(
            request,
            db,
            form_error=str(exc),
            form_values={
                "source_url": source_url,
                "title": title,
                "categories": category_names,
                "new_categories": new_categories,
                "tags": tags,
                "mode": mode,
                "visibility": visibility,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    url_hash = hash_url(payload.source_url)
    existing = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.source_url_hash == url_hash)
        .one_or_none()
    )
    if existing:
        request.session["flash"] = "Already saved."
        return RedirectResponse(
            url=f"/bookmarks/{existing.id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    bookmark = Bookmark(
        title=payload.title or payload.source_url,
        source_url=payload.source_url,
        source_url_hash=url_hash,
        status="bookmark_only" if payload.mode == "bookmark_only" else "pending",
        visibility=payload.visibility,
        mode=payload.mode,
        media_type="unknown",
        categories=get_or_create_categories(db, payload.categories, True),
        tags=get_or_create_tags(db, payload.tags),
    )
    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)

    if bookmark.mode == "download_media":
        background_tasks.add_task(process_bookmark_download, bookmark.id)
    else:
        background_tasks.add_task(process_bookmark_preview, bookmark.id)

    request.session["flash"] = "Bookmark saved."
    return RedirectResponse(url=f"/bookmarks/{bookmark.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/bookmarks/feed", response_class=HTMLResponse)
def bookmark_feed_fragment(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=FEED_PAGE_SIZE, ge=1, le=50),
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return HTMLResponse("", status_code=status.HTTP_401_UNAUTHORIZED)

    bookmarks = (
        build_bookmark_query(db, q=q, category=category, tag=tag)
        .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return templates.TemplateResponse(
        "_bookmark_cards.html",
        {
            "request": request,
            "bookmarks": bookmarks,
            "public_feed": False,
            "active_category": category or "",
            "active_tag": tag or "",
            "watched_return_to": feed_path("/bookmarks", q=q, category=category, tag=tag),
            "username": request.session.get("username"),
        },
    )


@router.get("/public/feed", response_class=HTMLResponse)
def public_feed_fragment(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=FEED_PAGE_SIZE, ge=1, le=50),
    db: Session = Depends(get_db),
) -> Response:
    bookmarks = (
        build_bookmark_query(db, q=q, category=category, tag=tag, visibility="public")
        .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return templates.TemplateResponse(
        "_bookmark_cards.html",
        {
            "request": request,
            "bookmarks": bookmarks,
            "public_feed": True,
            "active_category": category or "",
            "active_tag": tag or "",
            "watched_return_to": "/",
            "username": request.session.get("username"),
        },
    )


@router.get("/public/bookmarks/{bookmark_id}", response_class=HTMLResponse)
def public_bookmark_detail(
    request: Request,
    bookmark_id: int,
    db: Session = Depends(get_db),
) -> Response:
    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.id == bookmark_id, Bookmark.visibility == "public")
        .one_or_none()
    )
    if bookmark is None:
        return templates.TemplateResponse(
            "not_found.html",
            {"request": request, "username": request.session.get("username")},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return templates.TemplateResponse(
        "bookmark_detail.html",
        {
            "request": request,
            "bookmark": bookmark,
            "media_url": media_url_for(bookmark),
            "flash": pop_flash(request),
            "public_detail": True,
            "username": request.session.get("username"),
        },
    )


@router.get("/bookmarks/{bookmark_id}", response_class=HTMLResponse)
def bookmark_detail(
    request: Request,
    bookmark_id: int,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.id == bookmark_id)
        .one_or_none()
    )
    if bookmark is None:
        return templates.TemplateResponse(
            "not_found.html",
            {"request": request, "username": request.session.get("username")},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return templates.TemplateResponse(
        "bookmark_detail.html",
        {
            "request": request,
            "bookmark": bookmark,
            "media_url": media_url_for(bookmark),
            "flash": pop_flash(request),
            "public_detail": False,
            "watched_return_to": "/bookmarks?category=to-watch",
            "username": request.session.get("username"),
        },
    )


@router.get("/bookmarks/{bookmark_id}/edit", response_class=HTMLResponse)
def edit_bookmark_page(
    request: Request,
    bookmark_id: int,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.id == bookmark_id)
        .one_or_none()
    )
    if bookmark is None:
        return templates.TemplateResponse(
            "not_found.html",
            {"request": request, "username": request.session.get("username")},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    categories = db.query(Category).order_by(Category.name.asc()).all()
    return templates.TemplateResponse(
        "bookmark_edit.html",
        {
            "request": request,
            "bookmark": bookmark,
            "categories": categories,
            "selected_category_ids": {category.id for category in bookmark.categories},
            "form_error": None,
            "username": request.session.get("username"),
        },
    )


@router.post("/bookmarks/{bookmark_id}/edit", response_class=HTMLResponse)
def update_bookmark_from_form(
    request: Request,
    bookmark_id: int,
    title: str = Form(...),
    notes: str = Form(""),
    visibility: str = Form("public"),
    categories: list[str] | None = Form(None),
    new_categories: str = Form(""),
    tags: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.id == bookmark_id)
        .one_or_none()
    )
    if bookmark is None:
        request.session["flash"] = "Bookmark not found."
        return RedirectResponse(url="/bookmarks", status_code=status.HTTP_303_SEE_OTHER)

    title = " ".join(title.strip().split())
    if not title:
        categories_for_page = db.query(Category).order_by(Category.name.asc()).all()
        return templates.TemplateResponse(
            "bookmark_edit.html",
            {
                "request": request,
                "bookmark": bookmark,
                "categories": categories_for_page,
                "selected_category_ids": {category.id for category in bookmark.categories},
                "form_error": "Title is required.",
                "username": request.session.get("username"),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if visibility not in VISIBILITY_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid visibility")

    category_names = list(categories or [])
    category_names.extend(split_category_names(new_categories))
    tag_names = split_label_names(tags)
    bookmark.title = title
    bookmark.notes = notes.strip() or None
    bookmark.visibility = visibility
    bookmark.categories = get_or_create_categories(db, category_names, True)
    bookmark.tags = get_or_create_tags(db, tag_names)
    db.commit()

    request.session["flash"] = "Bookmark updated."
    return RedirectResponse(url=f"/bookmarks/{bookmark.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/bookmarks/{bookmark_id}/watched")
def mark_bookmark_watched(
    request: Request,
    bookmark_id: int,
    return_to: str = Form("/bookmarks?category=to-watch"),
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    bookmark = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories))
        .filter(Bookmark.id == bookmark_id)
        .one_or_none()
    )
    if bookmark is None:
        request.session["flash"] = "Bookmark not found."
        return RedirectResponse(
            url=safe_internal_path(return_to, "/bookmarks?category=to-watch"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    category_count = len(bookmark.categories)
    bookmark.categories = [
        category for category in bookmark.categories if category.slug != TO_WATCH_CATEGORY_SLUG
    ]
    if len(bookmark.categories) != category_count:
        db.commit()
        request.session["flash"] = "Marked as watched."
    else:
        request.session["flash"] = "Bookmark was already watched."

    return RedirectResponse(
        url=safe_internal_path(return_to, "/bookmarks?category=to-watch"),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/bookmarks/{bookmark_id}/delete")
def delete_bookmark(
    request: Request,
    bookmark_id: int,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    bookmark = db.get(Bookmark, bookmark_id)
    if bookmark is None:
        request.session["flash"] = "Bookmark not found."
        return RedirectResponse(url="/bookmarks", status_code=status.HTTP_303_SEE_OTHER)

    paths_to_delete = [bookmark.media_path, bookmark.local_thumbnail_path]
    db.delete(bookmark)
    db.commit()

    for path in paths_to_delete:
        delete_local_media_file(path)

    request.session["flash"] = "Bookmark deleted."
    return RedirectResponse(url="/bookmarks", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/bookmarks/{bookmark_id}/retry")
def retry_bookmark_from_web(
    request: Request,
    bookmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    bookmark = db.get(Bookmark, bookmark_id)
    if bookmark is None:
        request.session["flash"] = "Bookmark not found."
        return RedirectResponse(url="/bookmarks", status_code=status.HTTP_303_SEE_OTHER)
    if bookmark.status != "failed":
        request.session["flash"] = "Only failed bookmarks can be retried."
        return RedirectResponse(url=f"/bookmarks/{bookmark.id}", status_code=status.HTTP_303_SEE_OTHER)

    bookmark.mode = "download_media"
    bookmark.status = "pending"
    bookmark.error_message = None
    bookmark.reclip_job_id = None
    bookmark.reclip_filename = None
    db.commit()
    background_tasks.add_task(process_bookmark_download, bookmark.id)

    request.session["flash"] = "Retry started."
    return RedirectResponse(url=f"/bookmarks/{bookmark.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    bookmarks = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .limit(200)
        .all()
    )
    categories = db.query(Category).order_by(Category.name.asc()).all()
    tags = db.query(Tag).order_by(Tag.name.asc()).all()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "bookmarks": bookmarks,
            "categories": categories,
            "tags": tags,
            "flash": pop_flash(request),
            "username": request.session.get("username"),
        },
    )


@router.get("/admin/status", response_class=HTMLResponse)
def admin_status_page(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "admin_status.html",
        {
            "request": request,
            "stats": build_admin_status(db),
            "username": request.session.get("username"),
        },
    )


@router.get("/admin/labels", response_class=HTMLResponse)
def admin_labels_page(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    return render_labels_page(request, db)


@router.post("/admin/labels/create")
def create_label_from_admin(
    request: Request,
    label_type: str = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if label_type not in LABEL_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid label type")

    clean_name = normalize_label_name(name)
    if not clean_name:
        request.session["flash"] = "Enter a label name."
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)
    if len(clean_name) > 80:
        request.session["flash"] = "Label names must be 80 characters or fewer."
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)

    model = label_model_for(label_type)
    slug = slugify(clean_name)
    existing = db.query(model).filter(model.slug == slug).one_or_none()
    if existing:
        request.session["flash"] = f"{label_title(label_type)} already exists."
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)

    db.add(model(name=clean_name, slug=slug))
    db.commit()
    request.session["flash"] = f"{label_title(label_type)} created."
    return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/labels/{label_type}/{label_id}/rename")
def rename_label_from_admin(
    request: Request,
    label_type: str,
    label_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if label_type not in LABEL_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid label type")

    model = label_model_for(label_type)
    label = db.get(model, label_id)
    if label is None:
        request.session["flash"] = f"{label_title(label_type)} not found."
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)

    clean_name = normalize_label_name(name)
    if not clean_name:
        request.session["flash"] = "Enter a label name."
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)
    if len(clean_name) > 80:
        request.session["flash"] = "Label names must be 80 characters or fewer."
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)

    new_slug = slugify(clean_name)
    existing = db.query(model).filter(model.slug == new_slug, model.id != label.id).one_or_none()
    if existing:
        request.session["flash"] = f"Another {label_type} already uses that name."
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)

    label.name = clean_name
    label.slug = new_slug
    db.commit()
    request.session["flash"] = f"{label_title(label_type)} renamed."
    return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/labels/{label_type}/{label_id}/delete")
def delete_label_from_admin(
    request: Request,
    label_type: str,
    label_id: int,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if label_type not in LABEL_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid label type")

    model = label_model_for(label_type)
    label = db.get(model, label_id)
    if label is None:
        request.session["flash"] = f"{label_title(label_type)} not found."
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)
    if label.bookmarks:
        request.session["flash"] = (
            f"{label_title(label_type)} is used by {len(label.bookmarks)} bookmark(s). "
            "Remove it from bookmarks before deleting."
        )
        return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)

    db.delete(label)
    db.commit()
    request.session["flash"] = f"{label_title(label_type)} deleted."
    return RedirectResponse(url="/admin/labels", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/export")
def export_bookmarks_from_admin(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    payload = export_library(db)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="bookmarks-export-{timestamp}.json"',
        },
    )


@router.get("/admin/extension.zip")
def download_extension_from_admin(request: Request) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    archive = build_extension_archive()
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="bookmarks-extension.zip"'},
    )


@router.post("/admin/import")
async def import_bookmarks_from_admin(
    request: Request,
    import_file: UploadFile = File(...),
    overwrite_existing: bool = Form(False),
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    content = await import_file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        request.session["flash"] = "Import file is too large."
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    try:
        payload = json.loads(content.decode("utf-8"))
        summary = import_library(db, payload, overwrite_existing=overwrite_existing)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        request.session["flash"] = f"Import failed: {exc}"
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    request.session["flash"] = (
        "Import complete: "
        f"{summary['categories_created']} categories, "
        f"{summary['tags_created']} tags, "
        f"{summary['bookmarks_created']} created, "
        f"{summary['bookmarks_updated']} updated, "
        f"{summary['bookmarks_skipped']} skipped, "
        f"{summary['bookmarks_failed']} failed."
    )
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/bookmarks/bulk")
def bulk_update_bookmarks(
    request: Request,
    background_tasks: BackgroundTasks,
    bookmark_ids: list[int] | None = Form(None),
    action: str = Form(...),
    visibility: str = Form("public"),
    category_name: str = Form(""),
    tag_name: str = Form(""),
    db: Session = Depends(get_db),
) -> Response:
    if not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    ids = sorted(set(bookmark_ids or []))
    if not ids:
        request.session["flash"] = "Select at least one bookmark."
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    bookmarks = (
        db.query(Bookmark)
        .options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
        .filter(Bookmark.id.in_(ids))
        .all()
    )
    if not bookmarks:
        request.session["flash"] = "No matching bookmarks found."
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    changed = 0
    paths_to_delete: list[str | None] = []

    if action == "set_visibility":
        if visibility not in VISIBILITY_VALUES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid visibility")
        for bookmark in bookmarks:
            bookmark.visibility = visibility
            changed += 1
    elif action == "add_category":
        category_names = split_category_names(category_name)
        if not category_names:
            request.session["flash"] = "Enter a category to add."
            return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        category = get_or_create_categories(db, [category_names[0]], True)[0]
        for bookmark in bookmarks:
            if all(existing.id != category.id for existing in bookmark.categories):
                bookmark.categories.append(category)
                changed += 1
    elif action == "remove_category":
        category_names = split_category_names(category_name)
        if not category_names:
            request.session["flash"] = "Enter a category to remove."
            return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        category_slug = slugify(category_names[0])
        for bookmark in bookmarks:
            before_count = len(bookmark.categories)
            bookmark.categories = [
                category for category in bookmark.categories if category.slug != category_slug
            ]
            if len(bookmark.categories) != before_count:
                changed += 1
    elif action == "add_tag":
        tag_names = split_label_names(tag_name)
        if not tag_names:
            request.session["flash"] = "Enter a tag to add."
            return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        tag = get_or_create_tags(db, [tag_names[0]])[0]
        for bookmark in bookmarks:
            if all(existing.id != tag.id for existing in bookmark.tags):
                bookmark.tags.append(tag)
                changed += 1
    elif action == "remove_tag":
        tag_names = split_label_names(tag_name)
        if not tag_names:
            request.session["flash"] = "Enter a tag to remove."
            return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        tag_slug = slugify(tag_names[0])
        for bookmark in bookmarks:
            before_count = len(bookmark.tags)
            bookmark.tags = [tag for tag in bookmark.tags if tag.slug != tag_slug]
            if len(bookmark.tags) != before_count:
                changed += 1
    elif action == "retry_failed":
        for bookmark in bookmarks:
            if bookmark.status != "failed":
                continue
            bookmark.mode = "download_media"
            bookmark.status = "pending"
            bookmark.error_message = None
            bookmark.reclip_job_id = None
            bookmark.reclip_filename = None
            background_tasks.add_task(process_bookmark_download, bookmark.id)
            changed += 1
    elif action == "delete":
        for bookmark in bookmarks:
            paths_to_delete.extend([bookmark.media_path, bookmark.local_thumbnail_path])
            db.delete(bookmark)
            changed += 1
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown bulk action")

    db.commit()
    for path in paths_to_delete:
        delete_local_media_file(path)

    request.session["flash"] = f"Bulk action applied to {changed} bookmark(s)."
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/media/{media_kind}/{filename:path}")
def serve_media_file(
    request: Request,
    media_kind: str,
    filename: str,
    db: Session = Depends(get_db),
) -> Response:
    if media_kind not in MEDIA_DIRECTORIES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    settings = get_settings()
    directory = getattr(settings, MEDIA_DIRECTORIES[media_kind]).resolve()
    media_path = (directory / filename).resolve()
    try:
        media_path.relative_to(directory)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found") from exc
    if not media_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    path_values = {str(media_path), media_path.as_posix()}
    bookmark = (
        db.query(Bookmark)
        .filter(
            or_(
                Bookmark.media_path.in_(path_values),
                Bookmark.local_thumbnail_path.in_(path_values),
            )
        )
        .first()
    )
    if bookmark is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
    if bookmark.visibility != "public" and not is_web_authenticated(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    return FileResponse(media_path)


def render_bookmarks_page(
    request: Request,
    db: Session,
    *,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    form_error: str | None = None,
    form_values: dict | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    query = build_bookmark_query(db, q=q, category=category, tag=tag)
    total = query.count()
    bookmarks = (
        query.order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .limit(FEED_PAGE_SIZE)
        .all()
    )
    categories = db.query(Category).order_by(Category.name.asc()).all()
    form_values = form_values or {
        "source_url": "",
        "title": "",
        "categories": [],
        "new_categories": "",
        "tags": "",
        "mode": "download_media",
        "visibility": "public",
    }
    return templates.TemplateResponse(
        "bookmarks.html",
        {
            "request": request,
            "bookmarks": bookmarks,
            "categories": categories,
            "active_category": category or "",
            "active_tag": tag or "",
            "q": q or "",
            "watched_return_to": feed_path("/bookmarks", q=q, category=category, tag=tag),
            "flash": pop_flash(request),
            "form_error": form_error,
            "form_values": form_values,
            "feed_limit": FEED_PAGE_SIZE,
            "has_more": total > len(bookmarks),
            "public_feed": False,
            "show_add_button": True,
            "username": request.session.get("username"),
        },
        status_code=status_code,
    )


def render_public_feed_page(
    request: Request,
    db: Session,
    *,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
) -> Response:
    query = build_bookmark_query(db, q=q, category=category, tag=tag, visibility="public")
    total = query.count()
    bookmarks = (
        query.order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .limit(FEED_PAGE_SIZE)
        .all()
    )
    categories = public_categories(db)
    return templates.TemplateResponse(
        "public_feed.html",
        {
            "request": request,
            "bookmarks": bookmarks,
            "categories": categories,
            "active_category": category or "",
            "active_tag": tag or "",
            "q": q or "",
            "feed_limit": FEED_PAGE_SIZE,
            "has_more": total > len(bookmarks),
            "public_feed": True,
            "username": request.session.get("username"),
        },
    )


def render_labels_page(request: Request, db: Session) -> Response:
    return templates.TemplateResponse(
        "admin_labels.html",
        {
            "request": request,
            "categories": category_label_rows(db),
            "tags": tag_label_rows(db),
            "flash": pop_flash(request),
            "username": request.session.get("username"),
        },
    )


def category_label_rows(db: Session) -> list[dict]:
    rows = (
        db.query(Category, func.count(Bookmark.id).label("bookmark_count"))
        .outerjoin(Category.bookmarks)
        .group_by(Category.id)
        .order_by(Category.name.asc())
        .all()
    )
    return [
        {
            "id": category.id,
            "name": category.name,
            "slug": category.slug,
            "bookmark_count": bookmark_count,
            "filter_url": f"/bookmarks?category={category.slug}",
        }
        for category, bookmark_count in rows
    ]


def tag_label_rows(db: Session) -> list[dict]:
    rows = (
        db.query(Tag, func.count(Bookmark.id).label("bookmark_count"))
        .outerjoin(Tag.bookmarks)
        .group_by(Tag.id)
        .order_by(Tag.name.asc())
        .all()
    )
    return [
        {
            "id": tag.id,
            "name": tag.name,
            "slug": tag.slug,
            "bookmark_count": bookmark_count,
            "filter_url": f"/bookmarks?q={quote_plus(tag.name)}",
        }
        for tag, bookmark_count in rows
    ]


def build_bookmark_query(
    db: Session,
    *,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    visibility: str | None = None,
):
    query = db.query(Bookmark).options(selectinload(Bookmark.categories), selectinload(Bookmark.tags))
    joined_categories = False
    joined_tags = False
    if visibility:
        query = query.filter(Bookmark.visibility == visibility)

    if category:
        query = query.join(Bookmark.categories)
        joined_categories = True
        query = query.filter(or_(Category.slug == slugify(category), Category.name == category))

    if tag:
        query = query.join(Bookmark.tags)
        joined_tags = True
        query = query.filter(or_(Tag.slug == slugify(tag), Tag.name == tag))

    if q:
        if not joined_categories:
            query = query.outerjoin(Bookmark.categories)
        if not joined_tags:
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

    return query


def public_categories(db: Session) -> list[Category]:
    return (
        db.query(Category)
        .join(Category.bookmarks)
        .filter(Bookmark.visibility == "public")
        .distinct()
        .order_by(Category.name.asc())
        .all()
    )


def feed_path(
    path: str,
    *,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
) -> str:
    params = []
    if q:
        params.append(("q", q))
    if category:
        params.append(("category", category))
    if tag:
        params.append(("tag", tag))
    return f"{path}?{urlencode(params)}" if params else path


def build_admin_status(db: Session) -> dict:
    settings = get_settings()
    bookmark_total = db.query(func.count(Bookmark.id)).scalar() or 0
    category_total = db.query(func.count(Category.id)).scalar() or 0
    tag_total = db.query(func.count(Tag.id)).scalar() or 0
    visibility_counts = counts_by_field(db, Bookmark.visibility)
    status_counts = counts_by_field(db, Bookmark.status)
    media_type_counts = counts_by_field(db, Bookmark.media_type)
    latest_bookmark = db.query(Bookmark).order_by(Bookmark.created_at.desc(), Bookmark.id.desc()).first()

    storage_items = storage_breakdown(settings)
    storage_total = sum(item["bytes"] for item in storage_items)
    apply_percentages(storage_items, storage_total)

    public_count = visibility_counts.get("public", 0)
    private_count = visibility_counts.get("private", 0)
    public_percent = percentage(public_count, bookmark_total)
    private_percent = percentage(private_count, bookmark_total)

    disk_usage = safe_disk_usage(settings.bookmarks_root)
    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "app_base_url": settings.app_base_url,
        "storage_root": str(settings.bookmarks_root),
        "database_path": str(settings.bookmarks_db_path),
        "media_root": str(settings.bookmarks_media_root),
        "downloader_backend": settings.downloader_backend,
        "downloader": check_downloader_status(settings),
        "generated_at": datetime.now(timezone.utc),
        "bookmark_total": bookmark_total,
        "category_total": category_total,
        "tag_total": tag_total,
        "public_count": public_count,
        "private_count": private_count,
        "public_percent": public_percent,
        "private_percent": private_percent,
        "visibility_counts": visibility_counts,
        "status_items": status_items(status_counts, bookmark_total),
        "media_type_items": named_count_items(media_type_counts, bookmark_total),
        "latest_bookmark": latest_bookmark,
        "storage_items": storage_items,
        "storage_total": storage_total,
        "storage_total_label": format_bytes(storage_total),
        "disk_usage": disk_usage,
    }


def counts_by_field(db: Session, field) -> dict[str, int]:
    rows = db.query(field, func.count(Bookmark.id)).group_by(field).all()
    return {str(value or "unknown"): count for value, count in rows}


def status_items(counts: dict[str, int], total: int) -> list[dict]:
    ordered_keys = ["ready", "failed", "pending", "info_fetching", "downloading", "bookmark_only"]
    items = []
    for key in ordered_keys:
        count = counts.get(key, 0)
        items.append(
            {
                "key": key,
                "label": BOOKMARK_STATUS_LABELS.get(key, key.replace("_", " ").title()),
                "count": count,
                "percent": percentage(count, total),
            }
        )
    for key, count in sorted(counts.items()):
        if key not in ordered_keys:
            items.append(
                {
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "count": count,
                    "percent": percentage(count, total),
                }
            )
    return items


def named_count_items(counts: dict[str, int], total: int) -> list[dict]:
    return [
        {
            "label": key.replace("_", " ").title(),
            "count": count,
            "percent": percentage(count, total),
        }
        for key, count in sorted(counts.items())
    ]


def storage_breakdown(settings) -> list[dict]:
    entries = [
        ("Videos", settings.videos_dir),
        ("Images", settings.images_dir),
        ("Audio", settings.audio_dir),
        ("Thumbnails", settings.thumbnails_dir),
        ("Previews", settings.previews_dir),
        ("Temporary", settings.tmp_dir),
        ("Database", settings.bookmarks_db_path),
        ("Logs", settings.bookmarks_log_dir),
    ]
    items = []
    for label, path in entries:
        bytes_used, file_count = storage_size(path)
        items.append(
            {
                "label": label,
                "path": str(path),
                "bytes": bytes_used,
                "bytes_label": format_bytes(bytes_used),
                "files": file_count,
                "color": STORAGE_COLORS[label],
                "percent": 0,
            }
        )
    return items


def storage_size(path: Path) -> tuple[int, int]:
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 0
    if not path.exists():
        return 0, 0

    total = 0
    count = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            total += item.stat().st_size
            count += 1
        except OSError:
            continue
    return total, count


def apply_percentages(items: list[dict], total: int) -> None:
    for item in items:
        item["percent"] = percentage(item["bytes"], total)


def percentage(value: int, total: int) -> float:
    if total <= 0:
        return 0
    return round((value / total) * 100, 1)


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def safe_disk_usage(path: Path) -> dict | None:
    try:
        usage = shutil.disk_usage(path if path.exists() else path.parent)
    except OSError:
        return None
    used = usage.total - usage.free
    return {
        "total": usage.total,
        "used": used,
        "free": usage.free,
        "total_label": format_bytes(usage.total),
        "used_label": format_bytes(used),
        "free_label": format_bytes(usage.free),
        "used_percent": percentage(used, usage.total),
        "free_percent": percentage(usage.free, usage.total),
    }


def check_downloader_status(settings) -> dict:
    backend = settings.downloader_backend.strip().lower()
    if backend == "reclip":
        status_payload = check_reclip_status(settings.reclip_base_url)
        status_payload["name"] = "ReClip"
        status_payload["endpoint"] = settings.reclip_base_url
        return status_payload

    if backend in {"internal", "yt-dlp", "ytdlp"}:
        try:
            ytdlp_version = version("yt-dlp")
        except PackageNotFoundError:
            return {
                "ok": False,
                "name": "Internal yt-dlp",
                "status": "Missing",
                "detail": "yt-dlp package is not installed",
                "endpoint": "local",
            }

        has_ffmpeg = shutil.which("ffmpeg") is not None
        ffmpeg_status = "ffmpeg available" if has_ffmpeg else "ffmpeg missing"
        return {
            "ok": has_ffmpeg,
            "name": "Internal yt-dlp",
            "status": "Ready" if has_ffmpeg else "Limited",
            "detail": f"yt-dlp {ytdlp_version}, {ffmpeg_status}",
            "endpoint": "local",
        }

    return {
        "ok": False,
        "name": "Unknown",
        "status": "Invalid",
        "detail": "DOWNLOADER_BACKEND must be internal or reclip",
        "endpoint": backend or "unset",
    }


def check_reclip_status(base_url: str) -> dict:
    try:
        with httpx.Client(timeout=2.0, follow_redirects=True, trust_env=False) as client:
            response = client.get(base_url.rstrip("/") + "/")
        ok = response.status_code < 500
        return {
            "ok": ok,
            "status": "Online" if ok else "Error",
            "detail": f"HTTP {response.status_code}",
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "status": "Offline", "detail": str(exc)}


def split_category_names(value: str) -> list[str]:
    return split_label_names(value)


def split_label_names(value: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        name = " ".join(item.strip().split())
        key = name.lower()
        if name and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def normalize_label_name(value: str) -> str:
    return " ".join(value.strip().split())


def label_model_for(label_type: str):
    return Category if label_type == "category" else Tag


def label_title(label_type: str) -> str:
    return "Category" if label_type == "category" else "Tag"


def has_category_slug(bookmark: Bookmark, slug: str) -> bool:
    return any(category.slug == slug for category in bookmark.categories)


def safe_internal_path(value: str, fallback: str) -> str:
    parsed = urlsplit((value or "").strip())
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return fallback
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path


def youtube_embed_url_for(bookmark: Bookmark) -> str | None:
    if bookmark.mode != "bookmark_only" and bookmark.status != "bookmark_only":
        return None

    video_id = youtube_video_id(bookmark.source_url)
    if video_id is None:
        return None
    return f"https://www.youtube-nocookie.com/embed/{video_id}"


def youtube_video_id(source_url: str) -> str | None:
    parsed = urlsplit(source_url.strip())
    hostname = (parsed.hostname or "").lower()
    for prefix in ("www.", "m.", "mobile."):
        if hostname.startswith(prefix):
            hostname = hostname.removeprefix(prefix)

    video_id: str | None = None
    path_parts = [part for part in parsed.path.split("/") if part]
    if hostname == "youtu.be" and path_parts:
        video_id = path_parts[0]
    elif hostname in {"youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        if path_parts and path_parts[0] in {"embed", "shorts", "live"} and len(path_parts) >= 2:
            video_id = path_parts[1]
        else:
            video_id = parse_qs(parsed.query).get("v", [None])[0]

    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        return None
    return video_id


def static_asset_version() -> int:
    versions = []
    for path in (APP_DIR / "static" / "styles.css", APP_DIR / "static" / "feed.js"):
        try:
            versions.append(path.stat().st_mtime_ns)
        except OSError:
            continue
    return max(versions, default=0)


def build_extension_archive() -> bytes:
    extension_dir = find_extension_dir()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in EXTENSION_PACKAGE_FILES:
            source = (extension_dir / filename).resolve()
            try:
                source.relative_to(extension_dir.resolve())
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
            if not source.is_file():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Extension package files are missing.",
                )
            archive.write(source, arcname=f"bookmarks-extension/{filename}")
    return buffer.getvalue()


def find_extension_dir() -> Path:
    for candidate in EXTENSION_DIR_CANDIDATES:
        if (candidate / "manifest.json").is_file():
            return candidate
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Extension files are missing from the app container.",
    )


def delete_local_media_file(path_value: str | None) -> None:
    if not path_value:
        return

    settings = get_settings()
    media_root = settings.bookmarks_media_root.resolve()
    path = Path(path_value).resolve()
    try:
        path.relative_to(media_root)
    except ValueError:
        return
    if path.is_file():
        path.unlink()
