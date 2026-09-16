# QuickDL v15

QuickDL v15 is a public-media downloader with a server-side credit wallet, LIVE PayPal checkout, daily gifts, unlimited-user admin controls, download recovery, revenue reporting, and a full admin control center.

## Core systems
- 50 monthly free credits by default.
- 2 credits per video/audio download by default.
- Purchased credits do not expire.
- Daily 🎁 gift system; default gift is 10 credits every 24 hours.
- Admin can grant any number of credits, revoke credits, reset a user, or enable/disable Unlimited for a visitor.
- Unlimited users are not charged credits for downloads.
- All manual credit changes are written to the audit/transaction history.

## LIVE PayPal
Required Render variables:
- `PAYPAL_MODE=live`
- `PAYPAL_CLIENT_ID=<Live REST app client id>`
- `PAYPAL_CLIENT_SECRET=<Live REST app secret>`
- `PAYPAL_CURRENCY=USD`
- `PAYPAL_DOMAIN=https://quickdl.site`
- `PAYPAL_WEBHOOK_ID=<Live webhook id>`

The browser uses the standard PayPal Live JS SDK button. The client secret remains server-side. Server creates the Orders API order and captures it. PayPal `PayPal-Request-Id` is used for idempotent create calls. The webhook listens for `PAYMENT.CAPTURE.COMPLETED` and verifies the signature before crediting the account.

## PayPal verification
Open:
`https://quickdl.site/paypal-api/health`

Never publish the client secret. A successful health response should show `ok: true`, `configured: true`, `mode: live`, and the Live API base URL.

## Admin
Open `/admin18`.

Features:
- Overview and worker health
- User search by visitor ID
- Give credits / revoke / reset
- Unlimited on/off
- Gift system settings
- Monthly free credit setting
- PayPal revenue and captured orders
- Download retry/delete controls
- Download errors
- Maintenance and announcement controls
- Platform switches
- File retention and size settings
- Audit log

Set:
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`

## Download reliability
The worker recovers jobs left in `downloading` after a restart. Failed jobs refund their credit charge. Admin can retry failed/stuck jobs. `/api/health` reports a worker heartbeat and last processed job.

Supported public media sources are passed through yt-dlp. Sites can change their delivery systems or rate-limit automated traffic, so no extractor can guarantee every public URL forever. Private/login/DRM/CAPTCHA access controls are not bypassed.

## Deployment
Render should run the Dockerfile. Use a persistent PostgreSQL database for accounts, credits, payments, history, and audit records. The local media workspace is ephemeral; files are kept only for the configured retention period.
