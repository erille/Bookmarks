# Roadmap

## v0.1 - Backend MVP

Goal: save URL, call the configured downloader, store media, list bookmarks.

Tasks:

- FastAPI skeleton.
- SQLite database.
- Bookmark model.
- Category model.
- Downloader client.
- Create bookmark API.
- Duplicate URL detection.
- Download media to local storage.
- List bookmarks API.
- Serve local media.

Acceptance criteria:

```text
POST /api/bookmarks with a YouTube URL downloads media
GET /api/bookmarks lists the item
GET /media/videos/<file> plays the file
Duplicate URL does not download again
```

## v0.2 - Web UI

Goal: usable private web app.

Tasks:

- Login page.
- Session auth.
- Feed page.
- Save URL form.
- Category filter.
- Search box.
- Video player.
- Image/thumbnail display.
- Bookmark detail page.
- Delete bookmark.

Acceptance criteria:

```text
User can login
User can save URL from web UI
User can browse latest saved items
User can filter by category
User can search bookmarks
```

## v0.3 - Browser extension

Goal: save current page from Chrome-compatible browser.

Tasks:

- Manifest V3 extension.
- Popup UI.
- Options page for base URL/token.
- Load categories from API.
- Create category from popup.
- Save current tab URL/title.
- Support bookmark_only/download_media modes.

Acceptance criteria:

```text
Click extension icon
Select/create categories
Save current page
Bookmark appears in web feed
```

## v0.4 - Feed improvements

Goal: better viewing experience.

Tasks:

- Infinite scroll.
- Muted autoplay when video is visible.
- Pause video when off-screen.
- Better mobile layout.
- Keyboard shortcuts.
- Open original source link.

Acceptance criteria:

```text
Category feed feels similar to a lightweight social feed
Videos play smoothly while scrolling
```

## v0.5 - Media polish

Goal: improve media metadata and previews.

Tasks:

- Download thumbnails locally.
- Generate fallback thumbnails with ffmpeg.
- Detect image vs video.
- Show duration.
- Show uploader/source platform.
- Add retry failed download button.

## v0.6 - Maintenance

Goal: production quality.

Tasks:

- Backup documentation. `[done]`
- Cleanup orphan files. `[done]`
- Export bookmarks as JSON. `[done]`
- Import bookmarks from JSON. `[done]`
- Disk usage view. `[done]`
- Admin status page. `[done]`
- Log viewer.

## v0.7 - Sharing and admin workflow

Goal: make the private archive usable as a small public collection when desired.

Tasks:

- Add public/private visibility per bookmark.
- Make `/` a readonly public feed.
- Keep `/bookmarks` as the logged-in app feed.
- Protect private local media files.
- Hide the Save URL panel by default behind a top `+` action.
- Add share buttons for bookmark detail URLs.
- Add edit bookmark page.
- Add backend admin page with bulk visibility/category/delete/retry actions.

## Later ideas

- Tags separate from categories.
- Favorite/star bookmarks.
- Archive bookmarks.
- AI-generated titles/descriptions.
- Automatic category suggestions.
- Duplicate detection by media hash.
- Share-to-mobile shortcut.
- PWA support.
