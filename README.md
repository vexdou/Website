# QuickDL — Admin18 Full Build

## Included platforms
- YouTube / Shorts
- TikTok
- Instagram public posts/reels
- Facebook public media
- Pinterest
- X / Twitter
- Snapchat public media
- Other web URLs supported by yt-dlp/direct media extraction

## Important Instagram fix
The downloader no longer treats a rate-limit response as the final result. It retries through yt-dlp and then tries Instagram's public embed metadata for public media. If the server IP itself is blocked by Instagram, no downloader can honestly guarantee access; the system reports the failure and can optionally use a Cobalt instance that you control/are authorized to use.

## Admin18
Open:
`/admin18`

Set these Render environment variables:
- `DATABASE_URL`
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`

Never commit the admin password.

Admin18 includes:
Dashboard, downloads, users, analytics, platform switches, error center, retry failed jobs, clear failed/completed/all records, maintenance mode, master download switch, audio switch, file-size limit, file retention, worker polling, timeout settings, rate-limit retry settings, optional Cobalt fallback, announcements, emergency controls, and audit logs.

## Cobalt fallback
The Cobalt fallback is disabled by default. If you deploy an instance you control or are authorized to use, set:
- `cobalt_enabled=true`
- `cobalt_api_url=https://YOUR-INSTANCE/`

You can also configure these from Admin18.

## Deployment
Push the complete folder to GitHub and deploy the Docker service on Render. Use PostgreSQL for `DATABASE_URL`.

Public/private/login-only/DRM protected media is not bypassed.
