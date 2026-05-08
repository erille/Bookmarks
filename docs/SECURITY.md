# Security

Bookmarks is a private single-user application. It still needs proper security because it can download remote media and stores private browsing interests.

## Exposure model

Public:

```text
http://localhost:8015
```

Private/internal:

```text
/srv/webdata/bookmarks SQLite/media storage
```

The browser extension must call Bookmarks, not downloader backends directly.

## Authentication

### Web UI

Use username/password login.

Session cookie requirements:

```text
HttpOnly=true
Secure=true
SameSite=Lax
```

Do not store the cleartext password in `.env`.

Store only a password hash.

Recommended hashing:

```text
argon2id
```

Acceptable alternative:

```text
bcrypt
```

### Extension API

Use Bearer token:

```http
Authorization: Bearer <token>
```

Token requirements:

- Long random value.
- Stored only in extension local storage.
- Stored in `.env` on the server.
- Never committed to Git.

Generate token:

```bash
openssl rand -hex 32
```

## Secrets

Never commit:

```text
.env
bookmarks.sqlite
media files
session secrets
API tokens
password hashes from real deployment
```

Add to `.gitignore`:

```gitignore
.env
*.sqlite
/srv/
media/
logs/
```

## Downloader protection

Default media downloads run inside the Bookmarks container through `yt-dlp` and `ffmpeg`.

If using optional ReClip mode:

Preferred:

```text
ReClip reachable only locally
Bookmarks calls ReClip through localhost or Docker host gateway
```

Avoid:

```text
Extension → public downloader endpoint
```

Reason:

- No centralized auth.
- Harder rate limiting.
- More attack surface.
- Harder audit trail.

## URL validation

Before calling the downloader, validate URLs.

Allow only:

```text
http://
https://
```

Block:

```text
file://
ftp://
gopher://
ldap://
```

## SSRF protection

Because the app sends URLs to the downloader and fetches bookmark-only website previews, protect against internal network abuse.

Block private/internal IP targets after DNS resolution:

```text
127.0.0.0/8
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
169.254.0.0/16
::1/128
fc00::/7
fe80::/10
```

Exception:

```text
The app itself may call ReClip at configured RECLIP_BASE_URL when DOWNLOADER_BACKEND=reclip.
User-submitted URLs must not target internal addresses.
```

Website preview fetching must use the same checks for the original URL, redirects, remote preview images, and screenshot subresources. Screenshot generation should run with JavaScript disabled and should abort non-HTTP(S) or private-network requests.

## File handling

Do not use remote titles as filenames.

Use generated names:

```text
<bookmark_id>_<downloader_job_id>.mp4
```

Never trust:

```text
../../evil.mp4
video;rm -rf.mp4
```

## File serving

Serve media only from configured media root.

Use safe path joining and ensure resolved path remains inside:

```text
/srv/webdata/bookmarks/media
```

Media serving must also check bookmark visibility:

```text
public bookmark media: readable by anyone
private bookmark media: requires a logged-in web session
orphan media files: not served
```

## Uploads

Manual uploads are not required for v1 unless added later.

If added:

- Enforce size limits.
- Validate MIME type.
- Store with generated filename.
- Do not execute uploaded files.

## Reverse proxy limits

Set reasonable limits:

```nginx
client_max_body_size 2G;
proxy_read_timeout 900s;
proxy_send_timeout 900s;
```

## Rate limiting

Recommended at reverse proxy or app level:

```text
/login          strict rate limit
/api/bookmarks  moderate rate limit
/media          moderate rate limit; visibility-checked file serving
```

## Logs

Log:

```text
login success/failure
bookmark creation
duplicate detection
Downloader job_id
Downloader errors
download completion
```

Do not log:

```text
passwords
API tokens
session cookies
full Authorization headers
```

## Import/export

JSON export contains bookmark URLs, titles, categories, notes, visibility, and local media path references. Treat export files as private data.

Import is available only through an authenticated web session or Bearer-token API request. Imported local media paths are kept only when they resolve inside the configured media root.

## Cloudflare

Current setup uses Cloudflare and geo fencing.

Keep:

```text
France-only access if desired
WAF enabled
HTTPS enforced
```

Optional:

```text
Cloudflare Access in front of bookmarks.example.com
```

## Security checklist

```text
[ ] .env not committed
[ ] API token generated
[ ] session secret generated
[ ] password hash generated
[ ] Downloader backend not called by extension directly
[ ] URL validation enabled
[ ] private IP URL blocking enabled
[ ] media path traversal protection enabled
[ ] private media requires login
[ ] reverse proxy HTTPS enabled
[ ] login rate limiting enabled
```
