# QuickDL v33 FULL COMPLEX FIXED

This release is a complete repository package.

## Important deployment settings

Required:
- DATABASE_URL
- ADMIN_PASSWORD
- ADMIN_SESSION_SECRET

For live PayPal purchases:
- PAYPAL_MODE=live
- PAYPAL_CLIENT_ID
- PAYPAL_CLIENT_SECRET
- PAYPAL_DOMAIN=https://quickdl.site
- PAYPAL_WEBHOOK_ID (for webhook verification)

For email verification:
- EMAIL_PROVIDER=resend
- RESEND_API_KEY
- RESEND_FROM using a verified Resend domain

If no email provider is configured, email/password signup remains usable and creates an immediately active account. Set EMAIL_AUTH_REQUIRE_VERIFICATION=true when you require verification.

Google sign-in requires GOOGLE_CLIENT_ID and the matching Google OAuth configuration.
