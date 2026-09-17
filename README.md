# QuickDL v32 — Full Complete

QuickDL is a FastAPI + PostgreSQL media downloader with a credit system, email/password authentication, optional Google Sign-In, PayPal LIVE checkout, admin controls, history/favorites, background downloads, diagnostics and PWA assets.

## Deploy

1. Push/upload the entire project directory to the repository used by Render.
2. Use Docker deployment.
3. Set `DATABASE_URL` to the production PostgreSQL connection string.
4. Set `ADMIN_PASSWORD` and a long random `ADMIN_SESSION_SECRET`.
5. For email verification on Render Free, configure Resend HTTPS and a verified sending domain.
6. For payments, configure valid PayPal LIVE client credentials and the LIVE webhook ID.
7. For Google Sign-In, configure the Google Web Client ID and the authorized JavaScript origin for the production domain.

## Runtime diagnostics

- `/healthz` checks database connectivity and downloader worker startup.
- `/api/health` checks core database tables and returns safe runtime information.
- `/api/ready` checks database readiness.
- `/paypal-api/health` reports non-secret PayPal configuration/connectivity status.
- Admin Error Center stores server-side application failures without exposing provider/database details to public users.

## Credits

- 50 free credits per month by default.
- Video downloads cost 2 credits by default.
- Purchased credits do not expire.
- Admin can grant, revoke and enable unlimited access.
- Packages: 100/$1.99, 500/$6.99, 1,200/$14.99, 3,000/$29.99, 7,500/$59.99.

## Important

Third-party media providers can change their delivery systems. QuickDL supports public media only and does not bypass private access, DRM or CAPTCHA protections.
