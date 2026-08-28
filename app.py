import asyncio
import os
import re
import shutil
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, Cookie, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
import yt_dlp

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    engine = create_engine(
        f"sqlite:///{BASE_DIR / 'downloader.db'}",
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

class Download(Base):
    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    visitor_id: Mapped[str] = mapped_column(String(128), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="Media")
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    kind: Mapped[str] = mapped_column(String(20), default="video")
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(engine)

app = FastAPI(title="VEXDOU Downloader", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com", "m.tiktok.com",
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "fb.watch", "fb.me", "m.facebook.com",
    "pinterest.com", "www.pinterest.com", "pin.it",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
}

class DownloadRequest(BaseModel):
    url: HttpUrl
    kind: str = "video"

def host_allowed(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)
    except Exception:
        return False

def safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", value or "media")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:160] or "media"

def find_output(job_id: str) -> Path | None:
    matches = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
    return matches[0] if matches else None

def run_download(job_id: str, visitor_id: str, url: str, kind: str):
    db = SessionLocal()
    item = db.scalar(select(Download).where(Download.job_id == job_id))
    try:
        if not item:
            return

        if "instagram.com" in url.lower():
            raise RuntimeError("Instagram Wili Laguma Darin appkeena")

        item.status = "downloading"
        db.commit()

        outtmpl = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")
        
        options = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "retries": 3,
            "socket_timeout": 30,
            "format": "best",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"]
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        }

        if kind == "audio":
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            item.title = safe_name(info.get("title") or info.get("description") or "Media")
            item.thumbnail = info.get("thumbnail")

        output = find_output(job_id)
        if not output:
            raise RuntimeError("Downloaded file was not created.")

        item.filename = output.name
        item.status = "completed"
        item.error = None
        db.commit()
    except Exception as exc:
        item.status = "failed"
        err_msg = str(exc)
        if "Instagram Wili Laguma Darin appkeena" in err_msg or "instagram" in url.lower():
            item.error = "Instagram Wili Laguma Darin appkeena"
        elif "Sign in to confirm" in err_msg or "bot" in err_msg.lower() or "youtube" in url.lower():
            item.error = "YouTube wuxuu xannibay server-ka. Fadlan isku day TikTok ama Facebook."
        else:
            item.error = "Cillad ayaa dhacday ama link-ga waa mid gaار ah."
        db.commit()
        for p in DOWNLOAD_DIR.glob(f"{job_id}.*"):
            try:
                p.unlink()
            except OSError:
                pass
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def home():
    return FileResponse(BASE_DIR / "templates" / "index.html")

# Routing-ka loogu talagalay PWA Manifest iyo Service Worker
@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(BASE_DIR / "manifest.json", media_type="application/json")

@app.get("/sw.js")
def serve_sw():
    return FileResponse(BASE_DIR / "sw.js", media_type="application/javascript")

@app.get("/api/health")
def health():
    return {"ok": True, "service": "vexdou-downloader"}

@app.post("/api/download")
def create_download(payload: DownloadRequest, background_tasks: BackgroundTasks, vexdou_visitor: str | None = Cookie(default=None)):
    url = str(payload.url)
    kind = payload.kind.lower().strip()
    if kind not in {"video", "audio"}:
        raise HTTPException(400, "Invalid download type.")
    if not host_allowed(url):
        raise HTTPException(400, "Boggan waxaa laga taageeraa YouTube, TikTok, Facebook, Pinterest, iyo X.")

    visitor_id = vexdou_visitor or uuid.uuid4().hex
    job_id = uuid.uuid4().hex

    db = SessionLocal()
    item = Download(
        job_id=job_id,
        visitor_id=visitor_id,
        url=url,
        title="Downloading...",
        status="queued",
        kind=kind,
    )
    db.add(item)
    db.commit()
    db.close()

    background_tasks.add_task(run_download, job_id, visitor_id, url, kind)

    response = JSONResponse({
        "ok": True,
        "job_id": job_id,
        "visitor_id": visitor_id,
        "status": "queued",
    })
    if not vexdou_visitor:
        response.set_cookie(
            "vexdou_visitor",
            visitor_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            samesite="lax",
            secure=False,
        )
    return response

@app.get("/api/download/{job_id}")
def download_status(job_id: str, vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor:
        raise HTTPException(404, "Download not found.")

    db = SessionLocal()
    item = db.scalar(select(Download).where(
        Download.job_id == job_id,
        Download.visitor_id == vexdou_visitor
    ))
    db.close()

    if not item:
        raise HTTPException(404, "Download not found.")

    return {
        "job_id": item.job_id,
        "status": item.status,
        "title": item.title,
        "kind": item.kind,
        "error": item.error,
        "thumbnail": item.thumbnail,
        "url": item.url,
        "download_url": f"/api/file/{item.job_id}" if item.status == "completed" else None,
    }

@app.get("/api/history")
def history(vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor:
        return {"items": []}

    db = SessionLocal()
    items = db.scalars(
        select(Download)
        .where(Download.visitor_id == vexdou_visitor)
        .order_by(Download.created_at.desc())
        .limit(50)
    ).all()

    result = [{
        "job_id": x.job_id,
        "title": x.title,
        "status": x.status,
        "kind": x.kind,
        "thumbnail": x.thumbnail,
        "url": x.url,
        "created_at": x.created_at.isoformat() if x.created_at else None,
        "download_url": f"/api/file/{x.job_id}" if x.status == "completed" else None,
    } for x in items]
    db.close()
    return {"items": result}

@app.get("/api/file/{job_id}")
def get_file(job_id: str, vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor:
        raise HTTPException(404, "File not found.")

    db = SessionLocal()
    item = db.scalar(select(Download).where(
        Download.job_id == job_id,
        Download.visitor_id == vexdou_visitor,
        Download.status == "completed"
    ))
    db.close()

    if not item or not item.filename:
        raise HTTPException(404, "File not found.")

    path = DOWNLOAD_DIR / item.filename
    if not path.exists() or path.parent.resolve() != DOWNLOAD_DIR.resolve():
        raise HTTPException(404, "File not found.")

    return FileResponse(path, filename=f"{safe_name(item.title)}.{path.suffix.lstrip('.')}")

@app.delete("/api/history")
def clear_history(vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor:
        return {"ok": True}

    db = SessionLocal()
    items = db.scalars(select(Download).where(Download.visitor_id == vexdou_visitor)).all()
    for item in items:
        if item.filename:
            try:
                (DOWNLOAD_DIR / item.filename).unlink(missing_ok=True)
            except OSError:
                pass
        db.delete(item)
    db.commit()
    db.close()
    return {"ok": True}
