# QuickDL 9.4: FastAPI + Node 22 + yt-dlp EJS + local YouTube PO-token provider
FROM node:22-bookworm-slim AS pot-builder
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/bgutil
RUN git clone --depth 1 --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git . \
    && cd server \
    && npm ci --no-audit --no-fund \
    && npx tsc

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Node 22 is required by current yt-dlp EJS support.
COPY --from=pot-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=pot-builder /opt/bgutil/server /opt/bgutil/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . .
RUN mkdir -p /tmp/quickdl \
    && node --version \
    && python -c "import yt_dlp; print('yt-dlp', yt_dlp.version.__version__)"

EXPOSE 10000
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","10000"]
