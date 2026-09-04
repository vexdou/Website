# QuickDL Website — Stability & Downloader Fix

This ZIP is the full repository based on the uploaded Website-main archive, with the downloader and Admin18 improvements applied.

## Downloader improvements

Supported platform routing:
- YouTube
- YouTube Shorts
- TikTok
- Facebook
- Instagram
- Pinterest
- Snapchat
- X / Twitter
- Other public web URLs

The downloader now:
- retries extractor failures and HTTP rate-limit responses;
- uses yt-dlp browser impersonation through curl-cffi;
- uses Node 22 for yt-dlp JavaScript/EJS support;
- retries YouTube with the public embedded client when appropriate;
- tries alternate browser profiles for Instagram and other supported sources;
- keeps the Instagram public OpenGraph fallback;
- returns cleaner errors instead of exposing raw extractor messages.

Private, login-required, DRM-protected, or otherwise access-restricted media is not bypassed.

## Admin18

Open `/admin18`.

Admin environment variables:
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`
- `DATABASE_URL`

New/expanded controls include:
- Dashboard
- Downloads
- Queue monitor
- Users
- Analytics
- Platform switches
- Error center
- System health/diagnostics
- Website settings
- Security/emergency controls
- Audit logs
- Retry failed jobs
- Clear failed/completed/queued jobs
- JSON metadata export

## Important deployment requirement

The production image needs network access to the source sites and should have enough temporary disk space for the configured maximum file size.

This project downloads only publicly accessible media and does not attempt to bypass private accounts, authentication, DRM, or access controls.
