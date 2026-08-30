FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DENO_INSTALL=/usr/local

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | sh

ENV PATH="/usr/local/bin:${PATH}"

# Verify installations
RUN deno --version && \
    ffmpeg -version

WORKDIR /app

# Install Python dependencies first for better Docker caching
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Render uses SERVICE_ROLE:
# web    -> FastAPI/Uvicorn
# worker -> background downloader
CMD ["sh", "-c", "if [ \"${SERVICE_ROLE:-web}\" = \"worker\" ]; then exec python worker.py; else exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}; fi"]
