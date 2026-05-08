# Codex Tasks

Use this file to guide implementation with small, safe tasks.

## Rules for Codex

- Make one logical change per task.
- Keep the app simple.
- Prefer FastAPI, SQLite, Jinja2, vanilla JavaScript.
- Do not introduce React unless explicitly requested later.
- Do not commit secrets.
- Do not hardcode personal API tokens.
- Keep ReClip behind the backend.
- Use `/srv/webdata/bookmarks` paths from environment variables.
- Add verification commands after each major change.

## Task 01 - Create repository skeleton

Create this structure:

```text
backend/app/
backend/app/templates/
backend/app/static/
extension/
deploy/
docs/
```

Add:

```text
backend/requirements.txt
backend/Dockerfile
deploy/docker-compose.yml
.gitignore
```

Acceptance:

```bash
find . -maxdepth 3 -type d | sort
```

## Task 02 - Add FastAPI app skeleton

Create:

```text
backend/app/main.py
backend/app/config.py
```

Routes:

```text
GET /
GET /health
```

Acceptance:

```bash
docker compose -f deploy/docker-compose.yml up -d --build
curl -s http://127.0.0.1:8010/health
```

Expected:

```json
{"status":"ok"}
```

## Task 03 - Add SQLite database bootstrap

Create:

```text
backend/app/database.py
```

On startup, create tables:

```text
bookmarks
categories
bookmark_categories
```

Acceptance:

```bash
sqlite3 /srv/webdata/bookmarks/data/bookmarks.sqlite '.tables'
```

Expected:

```text
bookmark_categories bookmarks categories
```

## Task 04 - Add models and schemas

Create:

```text
backend/app/models.py
backend/app/schemas.py
```

Define Pydantic schemas:

```text
BookmarkCreate
BookmarkResponse
CategoryCreate
CategoryResponse
```

Acceptance:

```bash
python -m compileall backend/app
```

## Task 05 - Add category API

Implement:

```text
GET /api/categories
POST /api/categories
DELETE /api/categories/{id}
```

Acceptance:

```bash
curl -s -X POST http://127.0.0.1:8010/api/categories \
  -H "Authorization: Bearer $BOOKMARKS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"fitness"}'
```

## Task 06 - Add auth middleware for API token

Protect `/api/*` endpoints using:

```http
Authorization: Bearer <token>
```

Do not protect `/health`.

Acceptance:

```bash
curl -i http://127.0.0.1:8010/api/categories
```

Expected:

```text
401 Unauthorized
```

## Task 07 - Add ReClip client

Create:

```text
backend/app/reclip.py
```

Functions:

```text
get_info(url)
start_download(url, format_id)
get_status(job_id)
download_file(job_id, destination_path)
```

Acceptance from container:

```bash
curl -s http://host.docker.internal:8899/ >/dev/null && echo OK
```

## Task 08 - Add bookmark create API

Implement:

```text
POST /api/bookmarks
GET /api/bookmarks
GET /api/bookmarks/{id}
```

Initial behavior:

```text
Save metadata
Create missing categories
Detect duplicate source_url_hash
Return existing bookmark if duplicate
```

Acceptance:

```bash
curl -s -X POST http://127.0.0.1:8010/api/bookmarks \
  -H "Authorization: Bearer $BOOKMARKS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "categories":["music","funny"],
    "create_missing_categories":true,
    "mode":"bookmark_only"
  }'
```

## Task 09 - Add media download workflow

For `mode=download_media`:

```text
Call /api/info
Call /api/download
Poll /api/status/<job_id>
Download /api/file/<job_id>
Save under media/videos
Update bookmark status=ready
```

Acceptance:

```bash
curl -s http://127.0.0.1:8010/api/bookmarks \
  -H "Authorization: Bearer $BOOKMARKS_API_TOKEN" | jq
ls -lh /srv/webdata/bookmarks/media/videos
```

## Task 10 - Serve media files

Implement:

```text
GET /media/videos/{filename}
GET /media/images/{filename}
GET /media/thumbnails/{filename}
GET /media/previews/{filename}
```

Ensure safe path handling.

Acceptance:

```bash
curl -I http://127.0.0.1:8010/media/videos/<filename>
```

Expected:

```text
HTTP/1.1 200 OK
```

## Task 11 - Add web login

Implement:

```text
GET /login
POST /login
POST /logout
```

Use session cookie.

Acceptance:

```bash
curl -I http://127.0.0.1:8010/login
```

## Task 12 - Add feed UI

Create server-rendered pages:

```text
/
/bookmarks/{id}
```

Features:

```text
latest first
category filter
search box
video player
thumbnail display
source link
```

Acceptance:

```text
Open http://localhost:8010 and browse saved items
```

## Task 13 - Add save form in web UI

Add form fields:

```text
URL
Title optional
Categories multi-select
New category input
Mode
Save
```

Acceptance:

```text
Save URL from web UI and see it appear in feed
```

## Task 14 - Add Chrome extension skeleton

Create:

```text
extension/manifest.json
extension/popup.html
extension/popup.js
extension/options.html
extension/options.js
extension/styles.css
```

Acceptance:

```text
Load unpacked extension in Chrome/Brave
Popup opens without errors
```

## Task 15 - Add extension options

Store:

```text
baseUrl
apiToken
```

Acceptance:

```text
Open extension options
Save base URL and token
Reload options page and values remain
```

## Task 16 - Add extension save flow

Implement:

```text
Read active tab URL/title
Load categories from API
Allow category creation in popup
POST /api/bookmarks
Show success/error
```

Acceptance:

```text
Click extension on YouTube/X page
Save with category
Bookmark appears in web UI
```

## Task 17 - Add retry failed download

Implement:

```text
POST /api/bookmarks/{id}/retry
```

Acceptance:

```text
Failed bookmark can be retried from API or UI
```

## Task 18 - Add feed autoplay

Use `IntersectionObserver`.

Behavior:

```text
When video is mostly visible: play muted
When video leaves viewport: pause
```

Acceptance:

```text
Scrolling the feed autoplays visible videos only
```

## Task 19 - Add cleanup command

Add CLI/admin endpoint to find orphan files.

Acceptance:

```bash
python -m app.cleanup --dry-run
```

## Task 20 - Add backup notes

Document how to add these paths to the existing rclone job:

```text
/srv/webdata/bookmarks/data
/srv/webdata/bookmarks/media
/srv/webdata/bookmarks/.env
```

## Task 21 - Add public feed and visibility

Implement:

```text
visibility=public/private on bookmarks
GET /
GET /public/bookmarks/{id}
protected local media serving for private bookmarks
```

Acceptance:

```text
Existing bookmarks default to public
Public bookmarks appear on /
Private bookmarks do not appear on /
Private media URLs require login
```

## Task 22 - Add edit and admin workflows

Implement:

```text
hidden Save URL panel behind top + button
share bookmark button
edit bookmark page
admin bulk page
```

Acceptance:

```text
User can edit title, notes, categories, and visibility
User can bulk change visibility/category/delete/retry from admin page
```

## Task 23 - Add JSON export/import

Implement:

```text
GET /api/export
POST /api/import
GET /admin/export
POST /admin/import
```

Acceptance:

```text
User can export bookmark/category metadata as JSON
User can import JSON without duplicating existing source URLs
Optional overwrite updates existing duplicate source URLs
Media files remain backed up separately under /srv/webdata/bookmarks/media
```

## Task 24 - Add admin app stats

Implement:

```text
GET /admin/status
bookmark count
public/private count
status counts
storage usage by data/media/logs
ReClip connectivity
```

Acceptance:

```text
Admin can open a dedicated App Stats page
Storage is shown with a colored chart
ReClip connectivity is visible
```

## Task 25 - Add tags and clearer bookmark metadata

Implement:

```text
separate tags table and bookmark_tags relation
tags in bookmark create/update/API responses
tags in web save/edit forms and extension popup
labeled compact metadata chips on feed/detail cards
tag count on App Stats
```

Acceptance:

```text
User can save/edit tags separately from categories
Feed cards show Category, Tag, Source, and Date as labeled compact chips
Search matches tag names
JSON export/import preserves tags
```

## Task 26 - Add category/tag management page

Implement:

```text
authenticated Labels page at /admin/labels
create categories and tags
rename categories and tags
delete unused categories and tags
block deleting labels still attached to bookmarks
top navigation link
```

Acceptance:

```text
Admin can add a category/tag without editing a bookmark
Admin can rename a category/tag and existing bookmark relations stay intact
Admin can delete an unused category/tag
Used categories/tags show their bookmark count and cannot be deleted
```

## Task 27 - Add YouTube embeds for bookmark-only items

Implement:

```text
detect YouTube watch, youtu.be, shorts, live, and embed URLs
render a youtube-nocookie iframe for bookmark_only YouTube bookmarks
show embeds on feed cards and detail pages
keep local media player behavior unchanged for downloaded videos
```

Acceptance:

```text
Bookmark-only YouTube links show an embedded player
Downloaded/local videos still use the local video player
Non-YouTube bookmark-only links still show as normal link cards
```

## Task 28 - Add exact tag feed filters

Implement:

```text
support tag query parameter on public and authenticated feeds
allow category and tag filters together
make tag metadata chips clickable
preserve active category when clicking a tag
preserve active tag during infinite scroll
```

Acceptance:

```text
/?category=video-games&tag=crimson-desert shows public bookmarks matching both labels
/bookmarks?category=to-watch&tag=youtube shows authenticated bookmarks matching both labels
Tag chips link to exact tag filters instead of broad text search
```

## Task 29 - Add website previews for bookmark-only links

Implement:

```text
for bookmark_only non-YouTube URLs, fetch page metadata in a background task
save Open Graph title, description, and preview image when available
download preview images under /srv/webdata/bookmarks/media/previews
generate a Chromium screenshot fallback when no preview image is available
keep YouTube bookmark_only items using the existing embedded player
do not fail the bookmark if preview generation fails
show preview descriptions on feed/detail pages
```

Acceptance:

```text
bookmark_only YouTube links still render youtube-nocookie embeds
bookmark_only website links show an Open Graph image or local screenshot preview
local preview files are served from /media/previews/<filename>
private bookmark previews still require an authenticated web session
```

## Task 30 - Add To Watch completion action

Implement:

```text
show a Watched action for authenticated bookmarks in the To Watch category
remove only the To Watch category when the action is clicked
keep all other categories and tags attached to the bookmark
return to the current feed/filter after marking watched
show the action on feed cards and bookmark detail pages
```

Acceptance:

```text
/bookmarks?category=to-watch shows Watched buttons
clicking Watched removes the bookmark from the To Watch feed
other categories remain attached to the bookmark
public feed users do not see the Watched action
```
