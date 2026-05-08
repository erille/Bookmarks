# API

Base URL:

```text
http://localhost:8010
```

## Auth

### Browser extension

Use Bearer token:

```http
Authorization: Bearer <BOOKMARKS_API_TOKEN>
```

### Web UI

Uses session cookie after login.

## Health

### GET /health

Returns app status.

Response:

```json
{
  "status": "ok"
}
```

## Auth endpoints

### GET /login

Render login page.

### POST /login

Login with username/password.

Form fields:

```text
username
password
```

### POST /logout

Destroy session.

## Public pages

### GET /

Readonly public feed. Shows only bookmarks with `visibility=public`.

### GET /public/bookmarks/{id}

Readonly public bookmark detail page. Returns 404 for private bookmarks.

## Bookmarks

### GET /api/export

Export bookmark/category/tag metadata as JSON.

```bash
curl -s http://localhost:8010/api/export \
  -H "Authorization: Bearer $BOOKMARKS_API_TOKEN" \
  -o bookmarks-export.json
```

The export includes metadata and local media path references, but not the media file bytes.

### POST /api/import

Import bookmark/category/tag metadata from a JSON export.

Query parameters:

| Parameter | Description |
|---|---|
| `overwrite` | If `true`, update existing bookmarks matched by normalized source URL |

```bash
curl -s -X POST "http://localhost:8010/api/import?overwrite=false" \
  -H "Authorization: Bearer $BOOKMARKS_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @bookmarks-export.json
```

Response:

```json
{
  "categories_created": 0,
  "tags_created": 0,
  "bookmarks_created": 2,
  "bookmarks_updated": 0,
  "bookmarks_skipped": 1,
  "bookmarks_failed": 0,
  "errors": []
}
```

### GET /api/bookmarks

List bookmarks.

Query parameters:

| Parameter | Description |
|---|---|
| `q` | Search text across title, URL, uploader, categories, and tags |
| `category` | Filter by category slug/name |
| `status` | Filter by status |
| `visibility` | Filter by `public` or `private` |
| `limit` | Page size |
| `offset` | Pagination offset |

Example:

```bash
curl -s "http://localhost:8010/api/bookmarks?category=fitness&q=training" \
  -H "Authorization: Bearer $BOOKMARKS_API_TOKEN"
```

Response:

```json
{
  "items": [
    {
      "id": 42,
      "title": "Fitness routine",
      "source_url": "https://x.com/example/status/123",
      "uploader": "example",
      "duration": 62,
      "thumbnail_url": "https://...",
      "media_url": "/media/videos/42_7345b62b73.mp4",
      "source_platform": "X",
      "status": "ready",
      "visibility": "public",
      "categories": ["fitness", "training"],
      "tags": ["guitar", "live"],
      "created_at": "2026-05-07T12:00:00Z"
    }
  ],
  "limit": 50,
  "offset": 0,
  "total": 1
}
```

### POST /api/bookmarks

Create bookmark.

Request:

```json
{
  "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Optional custom title",
  "categories": ["music", "funny"],
  "tags": ["guitar", "live"],
  "create_missing_categories": true,
  "mode": "download_media",
  "visibility": "public"
}
```

Modes:

```text
bookmark_only
download_media
```

Behavior:

```text
If source_url already exists:
  return existing bookmark
  do not download again

If mode=bookmark_only:
  save metadata only

If mode=download_media:
  call ReClip and download media
```

Response for existing duplicate:

```json
{
  "created": false,
  "duplicate": true,
  "bookmark": {
    "id": 42,
    "status": "ready"
  }
}
```

Response for new bookmark:

```json
{
  "created": true,
  "duplicate": false,
  "bookmark": {
    "id": 43,
    "status": "downloading"
  }
}
```

### GET /api/bookmarks/{id}

Return one bookmark.

### PATCH /api/bookmarks/{id}

Update title, notes, visibility, categories, or tags.

Request:

```json
{
  "title": "Updated title",
  "visibility": "private",
  "categories": ["fitness", "cats"],
  "tags": ["guitar", "live"]
}
```

### DELETE /api/bookmarks/{id}

Delete bookmark.

Default behavior should delete DB row and local media file.

Optional safer behavior:

```text
soft delete first, cleanup later
```

## Categories

### GET /api/categories

List categories.

Response:

```json
{
  "items": [
    {
      "id": 1,
      "name": "fitness",
      "bookmark_count": 12
    }
  ]
}
```

### POST /api/categories

Create category.

Request:

```json
{
  "name": "fitness"
}
```

Response:

```json
{
  "id": 1,
  "name": "fitness"
}
```

### DELETE /api/categories/{id}

Delete category relation only if unused, or return error if still attached to bookmarks.

Recommended v1 behavior:

```text
If category is used: HTTP 409 Conflict
If unused: delete category
```

## Tags

### GET /api/tags

List tags.

Response:

```json
{
  "items": [
    {
      "id": 1,
      "name": "guitar",
      "bookmark_count": 12
    }
  ]
}
```

### POST /api/tags

Create tag.

Request:

```json
{
  "name": "guitar"
}
```

Response:

```json
{
  "id": 1,
  "name": "guitar"
}
```

## Download jobs

### GET /api/bookmarks/{id}/status

Return bookmark download status.

Response:

```json
{
  "id": 42,
  "status": "ready",
  "error_message": null,
  "media_url": "/media/videos/42_7345b62b73.mp4"
}
```

### POST /api/bookmarks/{id}/retry

Retry failed download.

Behavior:

```text
Only allowed when status=failed
Calls ReClip again
Updates reclip_job_id
Sets status=downloading
```

Response:

```json
{
  "id": 42,
  "status": "pending",
  "media_url": null
}
```

## Media

### GET /media/videos/{filename}

Serve local video file.

### GET /media/images/{filename}

Serve local image file.

### GET /media/thumbnails/{filename}

Serve local thumbnail file.

### GET /media/previews/{filename}

Serve bookmark-only website preview images and screenshots.

Media URLs are only served when they belong to a public bookmark or the requester has an authenticated web session.

## ReClip client contract

Bookmarks calls ReClip internally.

### POST /api/info

Request:

```json
{
  "url": "https://example.com/media-page"
}
```

Confirmed response example:

```json
{
  "duration": 213,
  "formats": [
    {
      "height": 360,
      "id": "18",
      "label": "360p"
    }
  ],
  "thumbnail": "https://i.ytimg.com/.../maxresdefault.jpg",
  "title": "Video title",
  "uploader": "Uploader name"
}
```

### POST /api/download

Request:

```json
{
  "url": "https://example.com/media-page",
  "format_id": "18"
}
```

Confirmed response:

```json
{
  "job_id": "7345b62b73"
}
```

### GET /api/status/{job_id}

Confirmed response:

```json
{
  "error": null,
  "filename": "7345b62b73.mp4",
  "status": "done"
}
```

### GET /api/file/{job_id}

Returns media file.

## Error format

Recommended API error response:

```json
{
  "error": "download_failed",
  "message": "ReClip returned an error",
  "details": "..."
}
```

## HTTP status guidance

| Status | Meaning |
|---|---|
| 200 | Success |
| 201 | Created |
| 400 | Invalid request |
| 401 | Not authenticated |
| 403 | Forbidden |
| 404 | Not found |
| 409 | Duplicate/conflict |
| 422 | Validation error |
| 500 | Server error |
| 502 | ReClip error |
| 504 | ReClip timeout |
