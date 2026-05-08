# Database Design

Database:

```text
SQLite
/srv/webdata/bookmarks/data/bookmarks.sqlite
```

## Entity overview

```text
bookmarks
categories
bookmark_categories
tags
bookmark_tags
```

A bookmark can have multiple categories and multiple tags.

A category can belong to multiple bookmarks.

A tag can belong to multiple bookmarks.

## Schema

### bookmarks

```sql
CREATE TABLE bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_url_hash TEXT NOT NULL UNIQUE,
    uploader TEXT,
    duration INTEGER,
    thumbnail_url TEXT,
    local_thumbnail_path TEXT,
    media_filename TEXT,
    media_path TEXT,
    media_type TEXT,
    reclip_job_id TEXT,
    reclip_filename TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    visibility TEXT NOT NULL DEFAULT 'public',
    error_message TEXT,
    mode TEXT NOT NULL DEFAULT 'download_media',
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### categories

```sql
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### bookmark_categories

```sql
CREATE TABLE bookmark_categories (
    bookmark_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    PRIMARY KEY (bookmark_id, category_id),
    FOREIGN KEY (bookmark_id) REFERENCES bookmarks(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
);
```

### tags

```sql
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### bookmark_tags

```sql
CREATE TABLE bookmark_tags (
    bookmark_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (bookmark_id, tag_id),
    FOREIGN KEY (bookmark_id) REFERENCES bookmarks(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
```

## Indexes

```sql
CREATE INDEX idx_bookmarks_created_at ON bookmarks(created_at);
CREATE INDEX idx_bookmarks_status ON bookmarks(status);
CREATE INDEX idx_bookmarks_media_type ON bookmarks(media_type);
CREATE INDEX idx_bookmarks_visibility ON bookmarks(visibility);
CREATE INDEX idx_categories_slug ON categories(slug);
CREATE INDEX idx_bookmark_categories_bookmark_id ON bookmark_categories(bookmark_id);
CREATE INDEX idx_bookmark_categories_category_id ON bookmark_categories(category_id);
CREATE INDEX idx_tags_slug ON tags(slug);
CREATE INDEX idx_bookmark_tags_bookmark_id ON bookmark_tags(bookmark_id);
CREATE INDEX idx_bookmark_tags_tag_id ON bookmark_tags(tag_id);
```

## Full-text search option

For v1, simple `LIKE` search is enough.

Later, add SQLite FTS5:

```sql
CREATE VIRTUAL TABLE bookmarks_fts USING fts5(
    title,
    source_url,
    uploader,
    notes,
    content='bookmarks',
    content_rowid='id'
);
```

## Status values

```text
pending
info_fetching
downloading
ready
failed
bookmark_only
```

Meaning:

| Status | Meaning |
|---|---|
| `pending` | Bookmark created but no work started |
| `info_fetching` | App is calling ReClip `/api/info` |
| `downloading` | ReClip job is active or app is downloading file |
| `ready` | Media is saved locally and playable |
| `failed` | Download failed |
| `bookmark_only` | URL saved without media download |

## Mode values

```text
bookmark_only
download_media
```

## Visibility values

```text
public
private
```

Existing bookmarks are migrated to `public`. Public bookmarks appear on the readonly public feed at `/`. Private bookmarks are visible only in authenticated web/API views, and their local media files require a logged-in web session.

## Media type values

```text
video
image
website
unknown
```

## Duplicate detection

Use normalized URL hash.

Process:

```text
1. Normalize source_url.
2. SHA-256 hash normalized URL.
3. Store in source_url_hash.
4. Add UNIQUE constraint.
```

Recommended normalization:

- Trim whitespace.
- Lowercase scheme and hostname.
- Remove URL fragment.
- Optionally remove known tracking parameters:
  - `utm_source`
  - `utm_medium`
  - `utm_campaign`
  - `utm_term`
  - `utm_content`
  - `fbclid`
  - `gclid`

Do not over-normalize platform-specific URLs in v1.

## Category behavior

When saving a bookmark:

```text
Input categories: ["Fitness", "Cats"]
Normalize to slugs: ["fitness", "cats"]
Create missing categories if allowed
Attach bookmark to categories
```

## Tag behavior

Categories are broad shelves, such as `Music`, `Cooking`, or `Tech`.

Tags are flexible descriptors, such as `guitar`, `live`, `tutorial`, or `x-post`.

When saving a bookmark:

```text
Input tags: ["guitar", "live"]
Normalize to slugs: ["guitar", "live"]
Create missing tags automatically
Attach bookmark to tags
```

## Suggested bootstrap categories

Do not hardcode these permanently, but they may be created on first run:

```text
fitness
cooking
cats
funny
tech
other
```

## Example insert flow

```sql
INSERT INTO bookmarks (
    title,
    source_url,
    source_url_hash,
    uploader,
    duration,
    thumbnail_url,
    status,
    mode
) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
```

Then attach categories:

```sql
INSERT OR IGNORE INTO categories (name, slug) VALUES (?, ?);

INSERT OR IGNORE INTO bookmark_categories (bookmark_id, category_id)
VALUES (?, ?);
```

## Cleanup behavior

When deleting a bookmark:

```text
1. Delete DB row.
2. Delete local media file if present.
3. Delete local thumbnail file if present.
4. Keep categories unless explicitly removed.
```

Avoid deleting remote thumbnails because they are external URLs.

## Backup

Backup at minimum:

```text
/srv/webdata/bookmarks/data/bookmarks.sqlite
/srv/webdata/bookmarks/media
/srv/webdata/bookmarks/.env
```

The existing rclone backup job can be updated later.
