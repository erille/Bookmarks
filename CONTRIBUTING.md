# Contributing

Thanks for your interest in Bookmarks.

This project is intentionally scoped as a self-hosted, single-user app. Contributions that keep that focus are the easiest to review.

## Good Contribution Areas

- Bug fixes.
- Documentation improvements.
- Browser extension polish.
- Import/export improvements.
- Better downloader error handling.
- Small UI refinements.
- Tests for existing behavior.

## Before Opening a Pull Request

- Keep changes focused.
- Do not commit `.env`, SQLite databases, media files, or personal screenshots.
- Update documentation when behavior changes.
- Run a local syntax/check pass where possible:

```bash
python -m compileall backend/app
node --check backend/app/static/feed.js
node --check extension/popup.js
node --check extension/options.js
```

## Development

Copy the example environment and adjust secrets:

```bash
cp .env.example .env
```

Start the app:

```bash
docker compose up -d --build
```

The default local URL is:

```text
http://localhost:8015
```
