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
- QuickDL Credits are enabled: 50 free credits per UTC month; each video/audio download costs 2 credits.
- PayPal Checkout v6 is integrated for one-time real-money credit purchases. The server creates/captures Orders; the PayPal client secret never goes into frontend code.
- Built-in packages: 100/$1.99, 500/$6.99, 1,200/$14.99, 3,000/$29.99, 7,500/$59.99. Prices are defined server-side so users cannot alter the amount.
- PayPal webhook endpoint is included and verifies PayPal webhook signatures through PayPal before processing completed captures.
- Credit transactions are recorded and failed downloads automatically refund the credits used.
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
- `MONTHLY_FREE_CREDITS=50`
- `VIDEO_CREDIT_COST=2`
- `PAYPAL_MODE=sandbox` for testing, then `PAYPAL_MODE=live` for real payments
- `PAYPAL_CLIENT_ID=...`
- `PAYPAL_CLIENT_SECRET=...` (server only; never put this in HTML/JS)
- `PAYPAL_CURRENCY=USD`
- `PAYPAL_DOMAIN=https://your-domain.example` (recommended for v6 browser-safe token binding)
- `PAYPAL_WEBHOOK_ID=...` (the webhook ID from the PayPal Developer Dashboard)

## Important platform limitation
The downloader is for public media URLs. It does not bypass private posts, login walls, DRM, CAPTCHA, or platform access controls. Some platforms can temporarily rate-limit automated traffic. YouTube also changes its delivery requirements over time; yt-dlp documents current client/PO-token limitations.

## PWA install
Serve the site over HTTPS in production. Chromium-based browsers expose the in-page install prompt when the PWA meets their installability conditions. iOS Safari does not expose the `beforeinstallprompt` event, so users there should use Safari's Add to Home Screen menu.

## Docker
A Dockerfile is included with FFmpeg and Node.js so audio conversion and YouTube JavaScript extraction have their required runtime available.

## PayPal setup

1. In PayPal Developer Dashboard, create/configure the QuickDL app and copy its Client ID and Secret into server environment variables. PayPal's current v6 documentation supports the Web SDK and server-side Orders API; keep the secret server-side.
2. Start in Sandbox and test a complete purchase: select a package -> PayPal approval -> server capture -> credits added.
3. Create a PayPal webhook pointing to `https://YOUR-DOMAIN/paypal-api/webhook` and subscribe to `PAYMENT.CAPTURE.COMPLETED`. Put the resulting webhook ID in `PAYPAL_WEBHOOK_ID`.
4. After end-to-end sandbox testing, switch the server to `PAYPAL_MODE=live` and use the live credentials.

The frontend never sends the price as the source of truth. The backend maps the package ID to the fixed server-side package price and creates the PayPal order from that value.


## PayPal LIVE configuration
Use the same PayPal REST app's **Live** credentials for `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`. Set `PAYPAL_MODE=live`, `PAYPAL_CURRENCY=USD`, and `PAYPAL_DOMAIN=https://quickdl.site`. The browser uses the PayPal v6 SDK with the public client ID; the client secret is used only on the server for REST OAuth and is never returned to the browser. PayPal's current v6 documentation recommends client-ID authentication for standard one-time checkout and reserves browser-safe client tokens primarily for Fastlane.

Deployment check: `GET /paypal-api/health` returns a non-secret connectivity/configuration result and a PayPal debug ID when PayPal rejects the server credentials.
