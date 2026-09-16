# QuickDL v21

Production-oriented QuickDL build for Render + PostgreSQL.

## Included in v21
- Public media downloader using yt-dlp with YouTube client fallbacks and FFmpeg/Node support.
- 50 monthly free credits by default; 2 credits per video.
- Stable 10-digit QuickDL User ID, now opened through a dedicated **Get ID** button instead of displaying the ID beside Sign in.
- Google Sign-In using Google Identity Services and server-side ID-token verification.
- First Google sign-in can send a polished welcome email from `support@quickdl.site`.
- Email signup, verification, login, forgot-password and reset-password flows.
- Spacemail SMTP support with a 465/587 delivery fallback and admin SMTP health check.
- PayPal Live credit purchases with server-side Orders v2 create/capture and webhook verification.
- Admin credit management by the user's 10-digit User ID: add, remove, unlimited, reset, view.
- Admin Ads Manager plus public-config driven promotional card.
- Downloader worker diagnostics and job counters.
- Admin download retry/delete/error center.

## Render environment
Set the values from `.env.example` in Render Environment Variables. Never commit PayPal client secrets, SMTP passwords, or admin secrets.

## Important
QuickDL only supports public media and does not bypass private accounts, DRM, CAPTCHAs, or login restrictions.
