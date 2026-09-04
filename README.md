# QuickDL v9.2

Modern responsive QuickDL build with FastAPI + yt-dlp, local ephemeral storage, and DATABASE_URL/Postgres for job/history metadata. R2 is not required.

## YouTube improvements
- Docker now supplies Node.js 22.
- yt-dlp EJS support is installed through `yt-dlp[default]`.
- The Python backend explicitly enables the Node.js runtime for YouTube JavaScript challenge solving.
- Public, embeddable YouTube media can use the `web_embedded` fallback when the normal public client is rejected.

These changes improve compatibility with current public YouTube extraction. They do not bypass private, members-only, age-restricted, or other media that legitimately requires account authorization. YouTube can also impose server-side rate limits or access controls that no downloader can guarantee to overcome.

## Deploy
Deploy the repository to Render using the included Dockerfile/render.yaml. The Docker build prints the Node.js and yt-dlp versions so runtime problems are easier to diagnose.

Support: costumer@quickdl.site

For a quick emergency stop, use **Settings → Downloads enabled** or **Security → Disable downloads**. The public site remains separate from the admin console.
