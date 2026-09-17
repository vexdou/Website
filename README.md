# QuickDL v29 — audited Render build

QuickDL is a FastAPI + PostgreSQL media downloader with monthly credits, account authentication, Google Sign-In, PayPal LIVE credit purchases, an admin control center, PWA support, and a background download worker.

## v29 audit fixes

- Fixed Render/production connection-pool pressure by reusing the active SQLAlchemy session for account/settings reads instead of opening nested database sessions on the same request.
- Added configurable `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, and PostgreSQL `DB_CONNECT_TIMEOUT`.
- `/healthz` now verifies both the database connection and the downloads table instead of returning OK when the application process is alive but the database is unavailable.
- Render Blueprint health check is `/healthz`.
- Preserved the existing safe public error masking and admin Error Center.
- Preserved 50 monthly free credits, 2-credit video downloads, purchased credits, admin adjustments, and PayPal LIVE flow.
- Preserved Deno + yt-dlp EJS support. `requirements.txt` uses a valid stable 2026 yt-dlp constraint.
- Added `og:video:url` to the public metadata fallback.

## Render

Use Docker. Keep the required environment variables in Render. Never commit secrets to GitHub.

Recommended Blueprint health check:

`/healthz`

The Dockerfile listens on Render's `$PORT` and installs FFmpeg plus Deno.

## Email

For Render Free, use Resend over HTTPS:

- `EMAIL_PROVIDER=resend`
- `RESEND_API_KEY=...`
- `RESEND_FROM=QuickDL <support@quickdl.site>`
- `RESEND_REPLY_TO=support@quickdl.site`

The sender domain must be verified in Resend.

## Important limitation

The downloader only handles public media. It does not bypass private accounts, authentication walls, DRM, CAPTCHAs, or other access controls. Social platforms can change their public pages or rate-limit automated requests, so source-specific availability can change independently of QuickDL's code.
