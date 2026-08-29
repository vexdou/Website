# VEXDOU Fast Download System

Flow: Browser -> FastAPI -> PostgreSQL queue -> Render Worker -> yt-dlp/FFmpeg -> Cloudflare R2 -> signed direct URL -> Browser.

## Render environment variables (WEB + WORKER)
- DATABASE_URL
- R2_ENDPOINT
- R2_ACCESS_KEY_ID
- R2_SECRET_ACCESS_KEY
- R2_BUCKET
- R2_REGION=auto

WEB: SERVICE_ROLE=web
WORKER: SERVICE_ROLE=worker
WORKER_POLL_SECONDS=1 (worker only)

Use PostgreSQL, not SQLite, because web and worker are separate services.
The worker needs R2 write permission. The web service needs R2 read/signing permission.
Do not expose R2 secrets in frontend JavaScript.

The included Dockerfile installs FFmpeg and Deno and installs yt-dlp + yt-dlp-ejs.

The worker uploads finished files to R2, so large video files do not pass through FastAPI when the user plays/downloads them.
