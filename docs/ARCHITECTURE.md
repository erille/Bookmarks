# Architecture

## Overview

Bookmarks is a single-user media bookmarking system with optional public sharing per bookmark. It stores bookmark metadata in SQLite and stores downloaded media files on local disk. Media extraction and downloading are handled by the internal `yt-dlp` downloader by default, with optional ReClip-compatible fallback support.

```text
Chrome Extension
Web UI
   ↓
FastAPI app
   ↓
SQLite database
Local media storage
   ↓
Internal yt-dlp downloader
```

## Components

### 1. FastAPI backend

Responsibilities:

- Serve the web UI.
- Provide JSON API endpoints.
- Authenticate web sessions.
- Authenticate extension API requests.
- Manage bookmarks, categories, and media metadata.
- Fetch metadata and download media through the configured downloader backend.
- Serve local media files only when bookmark visibility allows it.

### 2. SQLite database

Responsibilities:

- Store bookmarks.
- Store categories.
- Store bookmark/category relations.
- Store downloader job metadata.
- Store public/private visibility.
- Store download status and errors.

Database path:

```text
/srv/webdata/bookmarks/data/bookmarks.sqlite
```

### 3. Local storage

Media files are stored under:

```text
/srv/webdata/bookmarks/media
```

Recommended layout:

```text
media/
├── videos/
├── images/
├── thumbnails/
└── previews/
```

Filenames must be generated safely by the app. Do not trust remote titles as filenames.

Example:

```text
42_7345b62b73.mp4
```

Media files are served through application routes, not a raw static mount. Public bookmark media is readable by anyone. Private bookmark media requires a logged-in web session.

### 4. Downloader backend

Default:

```text
DOWNLOADER_BACKEND=internal
```

The internal backend uses `yt-dlp` for extraction/download and `ffmpeg` for media merging and video thumbnails.

Optional ReClip-compatible backend:

```text
DOWNLOADER_BACKEND=reclip
```

When ReClip mode is enabled, ReClip should be running and reachable locally:

```text
http://127.0.0.1:8899
```

Confirmed endpoints:

```text
POST /api/info
POST /api/download
GET  /api/status/<job_id>
GET  /api/file/<job_id>
```

Bookmarks should call ReClip locally, not through an external public downloader endpoint.

### 5. Browser extension

Chrome Manifest V3 extension.

Responsibilities:

- Read current tab URL and title.
- Show popup form.
- Let user select multiple categories.
- Let user create categories from the popup.
- Let user remove category selection before saving.
- Send save request to Bookmarks API using a Bearer token.

The extension must not call downloader backends directly.

## Bookmark creation flow

```text
1. User saves URL with categories.
2. Backend checks duplicate source_url.
3. If duplicate exists, return existing bookmark.
4. Backend fetches media metadata through the configured downloader.
5. Backend inserts bookmark metadata.
6. Backend starts media download.
7. Backend stores downloader job metadata and status=downloading.
8. Backend waits for the downloader to produce a media file.
9. Backend moves the file into local managed storage.
10. Backend stores file locally.
11. Backend updates bookmark status=ready.
```

## Duplicate behavior

A bookmark is considered duplicate when the normalized `source_url_hash` already exists.

Expected behavior:

```text
Same source_url detected
→ return existing bookmark
→ do not call downloader again
→ do not download again
```

## Category model

Categories are many-to-many.

A bookmark can have multiple categories:

```text
fitness + cooking
cats + funny
tech + tutorial
```

Categories can be created from:

- Web UI save form.
- Extension popup.

## Auth model

### Web UI

Single-user login/password.

Use a secure session cookie:

```text
HttpOnly
Secure
SameSite=Lax
```

### Extension API

Use Bearer token:

```http
Authorization: Bearer <token>
```

## Deployment model

Docker Compose runs the FastAPI app with the internal downloader enabled by default.

Public traffic:

```text
Cloudflare
  ↓
Reverse proxy
  ↓
Bookmarks container
```

Optional ReClip access:

```text
Bookmarks container/host
  ↓
http://127.0.0.1:8899
```

If Docker networking prevents access to host `127.0.0.1`, use one of:

```text
host.docker.internal
Docker host gateway
shared Docker network
host network mode
```

Preferred Linux Compose setting:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Then configure:

```text
DOWNLOADER_BACKEND=reclip
RECLIP_BASE_URL=http://host.docker.internal:8899
```

## Feed UI behavior

The feed should:

- Sort newest first.
- Filter by category.
- Search by text.
- Show thumbnail/title/uploader/source.
- Play local videos.
- Play local audio.
- Display local images.
- Support infinite scroll.
- Support muted autoplay on visible videos.
- Keep `/` as the public readonly feed.
- Keep `/bookmarks` as the authenticated management feed.

## Non-goals for v1

- Multi-user accounts.
- AI tagging.
- Automatic video detection inside the browser extension.
- Browser-side media downloading.
- Mobile app.
