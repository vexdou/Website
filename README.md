# QuickDL

Modern FastAPI + yt-dlp media downloader for one Render Web Service.

## Storage
R2 is not required. Completed files are temporarily stored in `/tmp/quickdl` and served directly to the same visitor. Render Free storage is ephemeral, so users should save files promptly.

## History behavior
History is success-only: queued, downloading and failed jobs never appear in History. The UI shows relative download time (`Now`, `1 day ago`, etc.) and exact `day/month/year · time` for older items.

## Features
- Video / MP3
- In-page video/audio preview
- Clear input immediately after a download starts
- Multiple downloads without refreshing
- History and favorites
- PWA
- Complaint/support email: Cosrumer@quickdl.site

## Required Render variable
`DATABASE_URL`
