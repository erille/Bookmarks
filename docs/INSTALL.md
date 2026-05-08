# Install Guide

## Target server

Bookmarks is intended to run on a self-hosted server using Docker Compose.

Storage root:

```text
/srv/webdata/bookmarks
```

Public URL:

```text
http://localhost:8010
```

ReClip local URL:

```text
http://127.0.0.1:8899
```

## 1. Prepare directories

```bash
sudo mkdir -p /srv/webdata/bookmarks/{data,media/videos,media/images,media/thumbnails,media/previews,logs}
sudo chown -R $USER:$USER /srv/webdata/bookmarks
chmod 750 /srv/webdata/bookmarks
```

Verify:

```bash
ls -la /srv/webdata/bookmarks
```

## 2. Clone repo

```bash
cd /srv/webdata
git clone https://github.com/erille/Bookmarks.git
cd Bookmarks
```

If the repo is already cloned elsewhere, deploy from that working tree instead.

## 3. Create environment file

```bash
cp .env.example .env
nano .env
```

Minimum values to update:

```text
BOOKMARKS_PASSWORD_HASH
BOOKMARKS_API_TOKEN
SESSION_SECRET_KEY
```

When setting `BOOKMARKS_PASSWORD_HASH`, wrap the Argon2 hash in single quotes. Argon2 hashes contain `$`, and Docker Compose expands `$name` in `.env` values unless quoted literally:

```text
BOOKMARKS_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...'
```

Generate random secrets:

```bash
openssl rand -hex 32
```

## 4. ReClip access from Docker

If the app runs in Docker, `127.0.0.1` inside the container is the container itself, not the host.

Use this in Docker Compose:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Then set:

```text
RECLIP_BASE_URL=http://host.docker.internal:8899
```

If the app uses host networking, this is also valid:

```text
RECLIP_BASE_URL=http://127.0.0.1:8899
```

For the default Docker Compose setup in this repository, use:

```text
RECLIP_BASE_URL=http://host.docker.internal:8899
```

## 5. Build and start

By default, Bookmarks publishes the container on host port `8010`.

The Docker image installs `ffmpeg` so the app can generate fallback thumbnails for videos. It also installs Playwright Chromium so bookmark-only website links can get screenshot previews when no Open Graph image exists.

To choose another host port:

```bash
echo 'BOOKMARKS_HOST_PORT=8011' >> .env
```

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

Verify:

```bash
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f bookmarks
```

## 6. Reverse proxy

For a public deployment, the reverse proxy should send traffic for your chosen domain:

```text
https://bookmarks.example.com
```

to:

```text
http://127.0.0.1:8010
```

Nginx example:

```nginx
server {
    listen 443 ssl http2;
    server_name bookmarks.example.com;

    client_max_body_size 2G;

    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

If Cloudflare handles TLS, adapt the certificate configuration to the existing reverse proxy setup.

## 7. First login

Open:

```text
http://localhost:8010
```

The root page is the readonly public feed. Use the Login button, then login with the configured single-user account to manage bookmarks at:

```text
http://localhost:8010/bookmarks
```

## 8. Test ReClip integration

From the host:

```bash
curl -s http://127.0.0.1:8899/ >/dev/null && echo OK
```

From inside the container:

```bash
docker exec -it bookmarks sh
curl -s http://host.docker.internal:8899/ >/dev/null && echo OK
```

## 9. Logs

Container logs:

```bash
docker compose -f deploy/docker-compose.yml logs -f bookmarks
```

Application logs:

```bash
tail -f /srv/webdata/bookmarks/logs/app.log
```

Download logs:

```bash
tail -f /srv/webdata/bookmarks/logs/downloads.log
```

## 10. Basic health checks

```bash
curl -I http://localhost:8010
curl -s http://localhost:8010/health
```

Expected:

```text
HTTP 200
```

## 11. Cleanup orphan media

Review orphan media files:

```bash
docker exec bookmarks python -m app.cleanup --dry-run
```

Delete orphan media files only after reviewing the dry-run output:

```bash
docker exec bookmarks python -m app.cleanup --delete
```

The cleanup command only considers files under:

```text
/srv/webdata/bookmarks/media/videos
/srv/webdata/bookmarks/media/images
/srv/webdata/bookmarks/media/thumbnails
/srv/webdata/bookmarks/media/previews
```

It refuses to run if the SQLite database is missing.

## 12. Backups

Add these paths to the existing backup job:

```text
/srv/webdata/bookmarks/data
/srv/webdata/bookmarks/media
/srv/webdata/bookmarks/.env
```

JSON metadata export is available from the admin page or API:

```bash
curl -s http://127.0.0.1:8010/api/export \
  -H "Authorization: Bearer $BOOKMARKS_API_TOKEN" \
  -o bookmarks-export.json
```

The JSON export does not include media file bytes. Keep `/srv/webdata/bookmarks/media` in the normal backup job.

Manual archive example:

```bash
sudo tar -czf bookmarks-backup-$(date +%F).tar.gz \
  /srv/webdata/bookmarks/data \
  /srv/webdata/bookmarks/media \
  /srv/webdata/bookmarks/.env
```

## Pitfalls

- `127.0.0.1` inside Docker is not the host.
- Large downloads require sufficient reverse proxy body/time limits.
- SQLite file must be writable by the container user.
- Media directory must be writable by the container user.
- Do not expose ReClip directly to the extension.
- Do not commit `.env` to git.
