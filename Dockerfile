FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 DENO_INSTALL=/usr/local
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip && \
    curl -fsSL https://deno.land/install.sh | sh && \
    ln -sf /usr/local/bin/deno /usr/local/bin/deno && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh","-c","uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
