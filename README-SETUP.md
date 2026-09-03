# QuickDL setup

1. Create a PostgreSQL database.
2. Create a Cloudflare R2 bucket.
3. Add DATABASE_URL, R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_BUCKET to Render.
4. Deploy with Docker.
5. Point quickdl.site DNS/custom domain to the Render web service.
6. Test `/api/health`, then paste a public media URL.
