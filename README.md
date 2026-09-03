# QuickDL

QuickDL is a FastAPI + yt-dlp public-media downloader designed for a single Render Web Service.

## Storage

This version intentionally removes Cloudflare R2. Downloaded media is stored temporarily in `/tmp/quickdl` and served directly by the web service. The database stores job/history metadata only.

Because Render Free has an ephemeral filesystem, completed files can disappear when the service restarts, redeploys, or spins down. Users should save the file after it becomes ready.

## Required Render variable

`DATABASE_URL`

## Optional variables

- `MAX_FILE_MB` (default 300)
- `KEEP_FILE_HOURS` (default 6)
- `WORKER_POLL_SECONDS` (default 0.7)

## Supported URL behavior

The server accepts public HTTP/HTTPS URLs and lets yt-dlp determine whether the source is supported. Login-required, private, DRM-protected, or source-blocked media cannot be guaranteed.

## Run

```bash
docker build -t quickdl .
docker run -p 10000:10000 -e DATABASE_URL='...' quickdl
```
