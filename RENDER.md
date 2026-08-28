# Render deployment

1. Push this repository to GitHub.
2. In Render, choose **New → Blueprint** and select the repository.
3. Render will read `render.yaml` and build the Docker service.
4. Open the generated `onrender.com` URL and test the downloader.
5. For persistent history/database in production, create a Render PostgreSQL database and set `DATABASE_URL` on the web service.
6. The app currently stores downloaded files on the service filesystem. Render free web-service files are not permanent across every restart/redeploy, so this first version is intended for testing. A persistent object-storage layer can be added later if needed.

## Important

The site only accepts the public platforms listed in `app.py`. Respect each platform's terms and copyright rules and only download media you are allowed to use.
