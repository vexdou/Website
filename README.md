# QuickDL v22

Production-oriented QuickDL build for Render + PostgreSQL.

## Major fixes in v22
- Hardened credit-account initialization with transaction-safe SAVEPOINT creation and race handling.
- Stable 10-digit User ID is shown only through the dedicated **Get ID** button.
- Rebuilt `index.html` with a cleaner responsive UI, organized buttons, polished downloader, progress state, preview/result card, History, Favorites, Credits and account sheets.
- Google Sign-In with server-side ID-token verification.
- Google first-login welcome email is optional and never blocks Google login if mail delivery fails.
- Email signup/verification/login/forgot/reset flow.
- Email delivery supports **Resend over HTTPS** and direct **Spacemail SMTP**.
- Admin email diagnostics identify the active provider and SMTP timeout cause.
- Admin credit management by 10-digit User ID: add, remove, unlimited, reset and view.
- Admin Ads Manager.
- Downloader worker diagnostics, retries, refunds and public-media extraction.
- FFmpeg + Node are installed in the Docker image for media post-processing.

## Email on Render
Render Free web services block outbound SMTP ports **25, 465 and 587**. Therefore direct Spacemail SMTP cannot work from a Free Render web service, and a timeout from `mail.spacemail.com:465` is expected in that environment. Use one of these configurations:

### Option A — Free Render + Resend (recommended for free hosting)
Keep the visible sender as `support@quickdl.site`, but verify `quickdl.site` in Resend and set:

```env
EMAIL_PROVIDER=auto
RESEND_API_KEY=YOUR_RESEND_API_KEY
RESEND_FROM=QuickDL <support@quickdl.site>
```

The app sends through Resend's HTTPS API, so it does not need outbound SMTP.

### Option B — Paid Render + Spacemail SMTP
If the Render service can make outbound SMTP connections, use:

```env
EMAIL_PROVIDER=smtp
SMTP_HOST=mail.spacemail.com
SMTP_PORT=465
SMTP_USER=support@quickdl.site
SMTP_PASSWORD=YOUR_SPACEMAIL_MAILBOX_PASSWORD
EMAIL_FROM=QuickDL <support@quickdl.site>
```

Spacemail officially documents `mail.spacemail.com:465` SSL and also supports port `587` STARTTLS.

## Other required environment variables
See `.env.example` for Google, PayPal Live, credits, cookies and admin configuration.

Never commit:
- `PAYPAL_CLIENT_SECRET`
- `SMTP_PASSWORD`
- `RESEND_API_KEY`
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`

## Downloader limitations
QuickDL handles public media only. It does not bypass private accounts, DRM, CAPTCHA, or authentication walls. Some platforms can change their anti-bot/extraction behavior, so no downloader can honestly guarantee every public URL forever. yt-dlp documents that some sources can require cookies, matching headers, or other platform-specific requirements. 
