# VEXDOU Downloader — fixed package

Replace the matching files in your GitHub repository with this package.

Included:
- Working Home / Downloads / History / Favorites navigation
- Working download flow against the existing FastAPI endpoints
- Video playback from History and Downloads
- Favorites stored in browser localStorage
- Working Clear History
- Android/Chrome PWA install button
- PWA manifest using real 192x192 and 512x512 PNG icons
- Service worker with API/media cache protection
- Existing FastAPI/yt-dlp backend
- Render Docker configuration

Important:
1. Upload/replace the files while keeping the folder structure.
2. Commit and push to GitHub.
3. Let Render redeploy.
4. Open https://quickdl.site in Chrome.
5. Hard refresh / clear the old PWA cache if an older service worker remains.
6. On Chrome Android, the Install App button uses the native install prompt when Chrome exposes it. If Chrome has not exposed that prompt yet, the button gives the browser-menu fallback.
