# Render setup

Create a Web Service from this repository and keep Docker runtime enabled.

Set DATABASE_URL to your PostgreSQL connection string and configure the four R2 variables. The embedded worker is enabled with DISABLE_EMBEDDED_WORKER=0.

The free Render web service sleeps after inactivity and its local filesystem is ephemeral, so downloaded media is uploaded to R2 rather than stored permanently on the container.
