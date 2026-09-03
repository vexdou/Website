# QuickDL

Render-ready public media downloader using FastAPI, yt-dlp, PostgreSQL and Cloudflare R2.

## Required Render environment variables
- DATABASE_URL
- R2_ENDPOINT
- R2_ACCESS_KEY_ID
- R2_SECRET_ACCESS_KEY
- R2_BUCKET

The free Render web service runs an embedded single worker so a separate paid Background Worker is not required. Render's free web service is suitable for testing, but long media jobs consume CPU/RAM/bandwidth.

The downloader accepts public HTTP/HTTPS URLs. yt-dlp decides whether a public website URL has a supported extractor. Login-only, DRM-protected, or sites that block automated access may still fail.

## Local
`uvicorn app:app --host 0.0.0.0 --port 10000`
