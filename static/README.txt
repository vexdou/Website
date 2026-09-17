QuickDL frontend asset note
=============================
The files in static/legacy/ are the four uploaded assets supplied for inspection.
They are NOT loaded by the current QuickDL templates because their API contracts
do not match the current v30 backend. The active frontend remains in the templates
and current backend-compatible code.

In particular:
- legacy/app.js calls /api/credits and /api/credits/checkout.
- current backend exposes /api/account and /api/credits/packages,
/api/credits/transactions, plus PayPal checkout routes.
- legacy/admin.js calls /api/admin/credits, while current backend exposes
/api/admin/credit-users and grant/revoke/reset routes.

Activating these legacy files unchanged would reintroduce API errors.
