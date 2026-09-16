# QuickDL v19

Production-oriented public-media downloader with a persistent browser account, 10-digit User IDs, credits, PayPal Live checkout, Google Sign-In controls, support messages, and admin controls.

## Important deployment settings

```env
DATABASE_URL=postgresql://...
ADMIN_PASSWORD=...
ADMIN_SESSION_SECRET=...
MONTHLY_FREE_CREDITS=50
VIDEO_CREDIT_COST=2
MAX_CONCURRENT_JOBS=2
COOKIE_SECURE=true

PAYPAL_MODE=live
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_CURRENCY=USD
PAYPAL_DOMAIN=https://quickdl.site
PAYPAL_WEBHOOK_ID=...

GOOGLE_CLIENT_ID=YOUR_GOOGLE_WEB_CLIENT_ID
```

### Google Sign-In

Create a Google OAuth/Web client and add `https://quickdl.site` as an Authorized JavaScript origin. Put the Web Client ID in `GOOGLE_CLIENT_ID`.

Admin controls are under **Settings → Google Login Control**:
- **Open Login**: new visitors can connect Google.
- **Close Login**: hides Google login for new visitors; already-linked Google accounts can still connect.

### Stable User ID

Each browser gets a first-party `vexdou_visitor` cookie valid for one year. The same opaque visitor token is also kept as a browser fallback so refreshes do not create a new account. The account receives one permanent 10-digit User ID stored in PostgreSQL.

### Credits

- 50 free credits/month by default.
- 2 credits per video by default.
- Free credits are used before purchased credits.
- Purchased credits do not expire.
- Admin can add/remove any number of credits and enable/disable Unlimited per user.

### Support

Users can use `/contact`; messages appear in **Admin → Messages**.

### Public-media limitation

The downloader is for publicly accessible media. It does not bypass private accounts, DRM, CAPTCHA, login/access controls, or other access restrictions.
