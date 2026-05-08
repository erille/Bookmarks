import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .config import get_settings
from .database import SessionLocal
from .models import Bookmark

MEDIA_SUBDIR_NAMES = ("videos", "images", "thumbnails", "previews", "tmp")


def main() -> int:
    parser = argparse.ArgumentParser(description="Find or remove orphan Bookmarks media files.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="show orphan files without deleting them; this is the default",
    )
    mode.add_argument(
        "--delete",
        action="store_true",
        help="delete orphan files under the configured media directory",
    )
    args = parser.parse_args()

    settings = get_settings()
    database_path = settings.bookmarks_db_path
    media_root = settings.bookmarks_media_root.resolve()

    if not database_path.exists():
        print(f"Database not found: {database_path}", file=sys.stderr)
        print("Cleanup needs the existing SQLite database to avoid deleting valid media.", file=sys.stderr)
        return 2

    try:
        referenced_files, missing_files, ignored_references = collect_referenced_files(media_root)
    except SQLAlchemyError as exc:
        print(f"Could not read bookmarks database: {exc}", file=sys.stderr)
        return 2

    media_files = sorted(iter_media_files(media_root))
    orphan_files = [path for path in media_files if path not in referenced_files]
    delete_files = args.delete

    print("Bookmarks cleanup")
    print(f"Media root: {media_root}")
    print(f"Mode: {'delete' if delete_files else 'dry-run'}")
    print(f"Referenced files: {len(referenced_files)}")
    print(f"Media files on disk: {len(media_files)}")
    print(f"Orphan files: {len(orphan_files)}")
    print(f"Missing referenced files: {len(missing_files)}")
    print(f"Ignored unsafe references: {len(ignored_references)}")

    if orphan_files:
        print()
        for path in orphan_files:
            prefix = "delete" if delete_files else "would delete"
            print(f"{prefix}: {path}")

    deleted_count = 0
    if delete_files:
        for path in orphan_files:
            try:
                path.unlink()
            except OSError as exc:
                print(f"failed to delete {path}: {exc}", file=sys.stderr)
                return 1
            deleted_count += 1
        print()
        print(f"Deleted files: {deleted_count}")

    if missing_files:
        print()
        print("Missing files still referenced by bookmarks:")
        for path in missing_files:
            print(f"missing: {path}")

    if ignored_references:
        print()
        print("Ignored references outside media root:")
        for raw_path in ignored_references:
            print(f"ignored: {raw_path}")

    return 0


def collect_referenced_files(media_root: Path) -> tuple[set[Path], list[Path], list[str]]:
    referenced_files: set[Path] = set()
    missing_files: list[Path] = []
    ignored_references: list[str] = []

    with SessionLocal() as db:
        bookmarks = db.query(Bookmark.media_path, Bookmark.local_thumbnail_path).all()

    for media_path, thumbnail_path in bookmarks:
        for raw_path in (media_path, thumbnail_path):
            if not raw_path:
                continue

            path = resolve_inside_media_root(str(raw_path), media_root)
            if path is None:
                ignored_references.append(str(raw_path))
                continue

            referenced_files.add(path)
            if not path.exists():
                missing_files.append(path)

    return referenced_files, sorted(missing_files), sorted(ignored_references)


def iter_media_files(media_root: Path) -> set[Path]:
    files: set[Path] = set()
    for subdir_name in MEDIA_SUBDIR_NAMES:
        subdir = media_root / subdir_name
        if not subdir.exists():
            continue
        for path in subdir.rglob("*"):
            if path.is_file():
                resolved = resolve_inside_media_root(str(path), media_root)
                if resolved is not None:
                    files.add(resolved)
    return files


def resolve_inside_media_root(raw_path: str, media_root: Path) -> Path | None:
    path = Path(raw_path).resolve(strict=False)
    try:
        path.relative_to(media_root)
    except ValueError:
        return None
    return path


if __name__ == "__main__":
    raise SystemExit(main())
