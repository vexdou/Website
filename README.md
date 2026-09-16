# QuickDL — full fixed build

This build keeps the QuickDL backend structure and adds a production-oriented frontend/PWA layer.

## Fixed / improved
- YouTube normal videos and Shorts use multiple public yt-dlp client attempts.
- Instagram posts/reels use yt-dlp plus a public-page/embed fallback where the public page exposes media.
- Facebook, Pinterest, TikTok, X/Twitter, Snapchat and generic web URLs go through the public yt-dlp extractor.
- Stale per-platform database flags no longer block downloads by default. Set `STRICT_PLATFORM_TOGGLES=true` if you want admin platform switches to actively block them.
- YouTube JavaScript runtime is enabled only when Node.js exists, avoiding a missing-node crash on Python-only hosts.
- `/api/preview/{job}` provides an inline HTML5 preview response; `/api/file/{job}` remains the save/download endpoint.
- History is loaded from the server database and survives page reloads until the user clears it or the stored media file expires.
- Credits/Stripe UI is removed from the frontend build.
- PWA manifest + service worker + QuickDL icons are included.
- Install banner uses the browser's `beforeinstallprompt` event, disappears after 15 seconds, and can be closed immediately with X.

## Environment
Required:
- `DATABASE_URL`
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`

Useful:
- `MAX_FILE_MB=300`
- `KEEP_FILE_HOURS=6`
- `STRICT_PLATFORM_TOGGLES=false`
- `WORK_DIR=/tmp/quickdl`

## Important platform limitation
The downloader is for public media URLs. It does not bypass private posts, login walls, DRM, CAPTCHA, or platform access controls. Some platforms can temporarily rate-limit automated traffic. YouTube also changes its delivery requirements over time; yt-dlp documents current client/PO-token limitations.

## PWA install
Serve the site over HTTPS in production. Chromium-based browsers expose the in-page install prompt when the PWA meets their installability conditions. iOS Safari does not expose the `beforeinstallprompt` event, so users there should use Safari's Add to Home Screen menu.

## Docker
A Dockerfile is included with FFmpeg and Node.js so audio conversion and YouTube JavaScript extraction have their required runtime available.
