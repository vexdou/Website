# VEXDOU Downloader v4

Supports public URLs from YouTube, TikTok, Instagram, Facebook, Pinterest and X/Twitter using yt-dlp + FFmpeg. Jobs are stored in PostgreSQL and finished files are uploaded to Cloudflare R2, then served through short-lived signed URLs.

## Required Render environment variables

`DATABASE_URL`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.

Optional: `R2_REGION=auto`, `WORKER_POLL_SECONDS=0.7`.

Use exactly one Uvicorn worker (`WEB_CONCURRENCY=1`) because the embedded queue worker runs inside the web container. This avoids duplicate workers claiming jobs and keeps the setup simple on Render.

Only download public content you have permission to download. Platform restrictions and extractor availability can change over time.
