# Render setup

Create one Render Web Service from this repository using the Docker runtime.

Required environment variable:

`DATABASE_URL`

No R2 endpoint, bucket, access key, or secret is required by this version.

The service includes an embedded queue worker because this setup is intended for one Render web instance. It downloads media to temporary local storage and exposes completed files through `/api/file/<job_id>`.

Important: Render Free web services have an ephemeral filesystem. Files disappear after restart, redeploy, or spin-down. This design is therefore intended for download-and-save use, not permanent file hosting.
