# Browser Extension

Bookmarks includes a Chrome-compatible extension using Manifest V3.

## Goal

Save the current page URL quickly into Bookmarks.

The extension should not download media itself. It sends the URL to the Bookmarks API, and the backend calls ReClip.

## Extension v1 features

- Popup form.
- Auto-fill current tab URL.
- Auto-fill current tab title.
- Select one or more categories.
- Create a category from the popup.
- Add comma-separated tags.
- Remove selected categories before saving.
- Choose mode:
  - `download_media`
  - `bookmark_only`
- Choose visibility:
  - `public`
  - `private`
- Save via API token.
- Options page for base URL and API token.

## Extension v1 non-goals

- Browser-side media extraction.
- Browser-side video downloading.
- Twitter/X DOM scraping.
- Automatic video detection.
- Background sync.

## Permissions

Recommended `manifest.json` permissions:

```json
{
  "permissions": [
    "activeTab",
    "storage"
  ],
  "host_permissions": [
    "http://*/*",
    "https://*/*"
  ]
}
```

## Popup fields

```text
Title
URL
Categories
New category
Tags
Mode
Visibility
Save button
Status message
```

Mode values:

```text
download_media
bookmark_only
```

Visibility defaults to:

```text
public
```

## Options page

Fields:

```text
Base URL: http://localhost:8010
API token: <token>
```

Store using Chrome extension storage:

```javascript
chrome.storage.sync.set({ baseUrl, apiToken });
```

Do not commit the API token. Enter it only in the installed extension options page.

## API calls

### Load categories

```http
GET /api/categories
Authorization: Bearer <token>
```

### Save bookmark

```http
POST /api/bookmarks
Authorization: Bearer <token>
Content-Type: application/json
```

Request:

```json
{
  "source_url": "https://x.com/example/status/123",
  "title": "Optional page title",
  "categories": ["fitness", "cats"],
  "tags": ["guitar", "live"],
  "create_missing_categories": true,
  "mode": "download_media",
  "visibility": "public"
}
```

## Popup behavior

```text
1. User clicks extension icon.
2. Extension reads active tab URL/title.
3. Extension loads saved settings.
4. Extension loads existing categories from API.
5. User selects categories or creates new ones.
6. User optionally adds tags.
7. User selects mode and visibility.
8. User clicks Save.
9. Extension POSTs to /api/bookmarks.
10. Extension shows success or error.
```

## Duplicate response handling

If API returns:

```json
{
  "duplicate": true
}
```

Show:

```text
Already saved
```

Do not treat as an error.

## Extension files

```text
extension/
├── manifest.json
├── icons/
│   ├── icon-16.png
│   ├── icon-32.png
│   ├── icon-48.png
│   └── icon-128.png
├── popup.html
├── popup.js
├── options.html
├── options.js
└── styles.css
```

The admin page provides a `Download extension` link that serves these files as:

```text
/admin/extension.zip
```

The zip can be extracted and loaded as an unpacked extension in Chrome/Brave.

## Minimal manifest draft

```json
{
  "manifest_version": 3,
  "name": "Bookmarks",
  "version": "0.1.0",
  "description": "Save media URLs to Bookmarks.",
  "permissions": ["activeTab", "storage"],
  "host_permissions": [
    "http://*/*",
    "https://*/*"
  ],
  "icons": {
    "16": "icons/icon-16.png",
    "32": "icons/icon-32.png",
    "48": "icons/icon-48.png",
    "128": "icons/icon-128.png"
  },
  "action": {
    "default_icon": {
      "16": "icons/icon-16.png",
      "32": "icons/icon-32.png",
      "48": "icons/icon-48.png",
      "128": "icons/icon-128.png"
    },
    "default_popup": "popup.html",
    "default_title": "Save to Bookmarks"
  },
  "options_page": "options.html"
}
```

## Error messages

Use clear messages:

```text
Missing API token. Open extension options.
Cannot reach Bookmarks API.
Login token rejected.
Bookmark already exists.
Saved. Download started.
Saved as bookmark only.
```

## Security notes

- Do not hardcode the API token in source code.
- Do not commit personal token to Git.
- Do not call public ReClip from the extension.
- Use HTTPS for API calls when the app is exposed outside localhost.
- The packaged manifest allows arbitrary HTTP/HTTPS self-hosted base URLs. Restrict `host_permissions` to your own domain if you want a tighter installed extension.
