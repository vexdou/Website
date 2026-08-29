FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DENO_INSTALL=/usr/local
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl git && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/usr/local/bin:${PATH}"
RUN deno --version && ffmpeg -version
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . .
RUN mkdir -p /tmp/vexdou
EXPOSE 10000
CMD ["sh","-c","if [ \"${SERVICE_ROLE:-web}\" = \"worker\" ]; then python worker.py; else uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}; fi"]
