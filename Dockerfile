FROM node:22-bookworm-slim AS node22
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY --from=node22 /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . .
RUN mkdir -p /tmp/quickdl && node --version && python -c "import yt_dlp; print('yt-dlp', yt_dlp.version.__version__)"
EXPOSE 10000
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","10000"]
