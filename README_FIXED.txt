# QuickDL — fixed Render build

## Render secrets
Create a Render Secret File named `cookies.txt` containing your own valid Netscape-format cookies file. Then set:

`YTDLP_COOKIES_FILE=/etc/secrets/cookies.txt`

Do not commit real cookies to GitHub.

Optional:
- `DATABASE_URL`
- `MAX_FILE_MB` (default 100)
- `KEEP_FILE_HOURS` (default 6)
- `COOKIES_CONTENT` (only if you understand the secret-handling implications)

YouTube/Instagram access can still be limited by the platforms. This build does not bypass access controls; it uses yt-dlp for URLs the configured account/session is authorized to access.
