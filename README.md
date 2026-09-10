# QuickDL Credits + Stripe

This build adds a server-side credit ledger and Stripe Checkout/webhooks.

## Default credit system
- New visitor: 100 free credits, once.
- Video or MP3: 2 credits.
- Starter: 100 credits / $1.
- Plus: 550 credits / $5.
- Pro: 1,200 credits / $10.

Packages are configurable through `CREDIT_PACKAGES_JSON`.

## Render environment variables
Set:
- DATABASE_URL
- ADMIN_PASSWORD
- ADMIN_SESSION_SECRET
- STRIPE_SECRET_KEY
- STRIPE_WEBHOOK_SECRET
- PUBLIC_BASE_URL=https://quickdl.site

Never commit Stripe secret/webhook keys to GitHub.

## Stripe webhook
Create a Stripe webhook endpoint:
`https://quickdl.site/api/stripe/webhook`

Enable:
- checkout.session.completed
- checkout.session.async_payment_succeeded

The webhook secret goes in `STRIPE_WEBHOOK_SECRET`.

Credits are granted only after a verified webhook and are idempotent by Stripe Checkout Session ID.

## Database
The app creates new tables automatically and includes a small additive migration for the new `downloads.credit_cost` and `downloads.credit_refunded` columns. Back up production data before deployment.

## Important identity note
Credits are tied to the server-side `vexdou_visitor` cookie. Clearing cookies loses the browser's link to that credit account. For production money flows, an account/email login is recommended.
