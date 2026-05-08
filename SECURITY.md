# Security Policy

Bookmarks is designed for self-hosted, single-user deployments.

For deployment guidance, threat model notes, and operational recommendations, see [docs/SECURITY.md](docs/SECURITY.md).

## Reporting Security Issues

Please do not open a public issue for a sensitive vulnerability.

If you find a security issue, contact the maintainer privately through GitHub.

## Important Defaults

- Do not commit `.env`.
- Use a strong `SESSION_SECRET_KEY`.
- Store only an Argon2 password hash in `BOOKMARKS_PASSWORD_HASH`.
- Use a long random `BOOKMARKS_API_TOKEN`.
- Keep private deployments behind HTTPS.
- Do not expose downloader backends directly to the internet.
