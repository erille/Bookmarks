# Architecture

## Overview

Bookmarks is a single-user media bookmarking system with optional public sharing per bookmark. It stores bookmark metadata in SQLite and stores downloaded media files on local disk. Media extraction and downloading are delegated to an existing ReClip instance running locally.

```text
Chrome Extension
Web UI
   ↓
FastAPI app
   ↓
SQLite database
Local media storage
   ↓
ReClip API on http://127.0.0.1:8899
```

## Components

### 1. FastAPI backend

Responsibilities:

- Serve the web UI.
- Provide JSON API endpoints.
- Authenticate web sessions.
- Authenticate extension API requests.
- Manage bookmarks, categories, and media metadata.
- Call ReClip to fetch metadata and download media.
- Serve local media files only when bookmark visibility allows it.

### 2. SQLite database

Responsibilities:

- Store bookmarks.
- Store categories.
- Store bookmark/category relations.
- Store ReClip job metadata.
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

### 4. ReClip service

ReClip is already running and reachable locally:

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

The extension must not call ReClip directly.

## Bookmark creation flow

```text
1. User saves URL with categories.
2. Backend checks duplicate source_url.
3. If duplicate exists, return existing bookmark.
4. Backend calls ReClip /api/info.
5. Backend inserts bookmark metadata.
6. Backend calls ReClip /api/download.
7. Backend stores reclip_job_id and status=downloading.
8. Backend polls /api/status/<job_id>.
9. When status=done, backend downloads /api/file/<job_id>.
10. Backend stores file locally.
11. Backend updates bookmark status=ready.
```

## Duplicate behavior

A bookmark is considered duplicate when the normalized `source_url_hash` already exists.

Expected behavior:

```text
Same source_url detected
→ return existing bookmark
→ do not call ReClip again
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

Docker Compose runs the FastAPI app. ReClip remains separate and local.

Public traffic:

```text
Cloudflare
  ↓
Reverse proxy
  ↓
Bookmarks container
```

ReClip access:

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
RECLIP_BASE_URL=http://host.docker.internal:8899
```

## Feed UI behavior

The feed should:

- Sort newest first.
- Filter by category.
- Search by text.
- Show thumbnail/title/uploader/source.
- Play local videos.
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
