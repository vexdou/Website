import os, re, time, uuid, mimetypes, logging, threading, ipaddress, socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Cookie
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, String, Text, Integer, DateTime, select, update, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("quickdl")
BASE = Path(__file__).resolve().parent
WORK = Path(os.getenv("WORK_DIR", "/tmp/quickdl"))
WORK.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("DATABASE_URL", "").strip()
if not DB_URL:
    raise RuntimeError("DATABASE_URL is required")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DB_URL.startswith("postgresql://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=300, pool_size=3, max_overflow=2)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

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
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    kind: Mapped[str] = mapped_column(String(20), default="video")
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(engine)

UA = os.getenv(
    "DOWNLOADER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
)
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "300"))
KEEP_FILE_HOURS = float(os.getenv("KEEP_FILE_HOURS", "6"))

def hostname(url):
    return (urlparse(url).hostname or "").lower().rstrip(".")

def platform(url):
    h = hostname(url)
    if "youtube" in h or h == "youtu.be": return "youtube"
    if "tiktok" in h: return "tiktok"
    if "instagram" in h or h == "instagr.am": return "instagram"
    if "facebook" in h or h in {"fb.watch", "fb.me"}: return "facebook"
    if "pinterest" in h or h == "pin.it": return "pinterest"
    if h in {"x.com", "twitter.com"}: return "x"
    return "web"

def public_host(h):
    if not h or h in {"localhost", "localhost.localdomain"} or h.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        infos = socket.getaddrinfo(h, None, type=socket.SOCK_STREAM)
        return bool(infos) and all(
            not (a := ipaddress.ip_address(i[4][0])).is_private
            and not a.is_loopback and not a.is_link_local and not a.is_multicast
            and not a.is_reserved and not a.is_unspecified
            for i in infos
        )
    except Exception:
        return True

def allowed(url):
    try:
        p = urlparse(url)
        return p.scheme in {"http", "https"} and bool(p.hostname) and public_host(hostname(url))
    except Exception:
        return False

def human_error(exc):
    text = re.sub(r"\s+", " ", str(exc)).strip()
    low = text.lower()
    if "comfortable for some audiences" in low:
        return "TikTok restricted this post. Only accessible/public media can be downloaded."
    if "sign in" in low or "login required" in low or "authentication" in low:
        return "This media requires sign-in or authorization."
    if "private" in low:
        return "This media is private or unavailable to the downloader."
    if "drm" in low:
        return "This media is DRM-protected and cannot be downloaded."
    if "429" in low or "too many requests" in low or "rate-limit" in low:
        return "The source temporarily rate-limited this server. Please try again later."
    if "403" in low or "forbidden" in low:
        return "The source refused automated access to this media."
    if "unsupported url" in low or "no suitable extractor" in low:
        return "This URL is not supported by the media extractor."
    if "timed out" in low or "timeout" in low:
        return "The source took too long to respond. Please try again."
    return text[:700] or "Download failed. Please try another media URL."

def ytdlp_options(job, kind):
    out = str(WORK / f"{job}.%(ext)s")
    opts = {
        "outtmpl": out,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "file_access_retries": 2,
        "socket_timeout": 45,
        "concurrent_fragment_downloads": 1,
        "skip_unavailable_fragments": True,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "http_headers": {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" if kind == "video" else "ba/b",
        "merge_output_format": "mp4" if kind == "video" else None,
        "max_filesize": MAX_FILE_MB * 1024 * 1024,
    }
    if kind == "audio":
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    return {k: v for k, v in opts.items() if v is not None}

def cleanup_job(job):
    for f in WORK.glob(f"{job}.*"):
        try: f.unlink()
        except OSError: pass

def mark_failed(job, error):
    db = Session()
    try:
        db.execute(update(Download).where(Download.job_id == job).values(status="failed", error=human_error(error)))
        db.commit()
    finally:
        db.close()

def process(job, kind):
    cleanup_job(job)
    db = Session()
    try:
        row = db.scalar(select(Download).where(Download.job_id == job))
        if not row: return
        url = row.url
    finally:
        db.close()
    try:
        with yt_dlp.YoutubeDL(ytdlp_options(job, kind)) as ydl:
            info = ydl.extract_info(url, download=True)
        files = [f for f in WORK.glob(f"{job}.*") if f.is_file() and f.suffix not in {".part", ".ytdl"}]
        if not files: raise RuntimeError("No media file was created")
        media = max(files, key=lambda f: f.stat().st_size)
        if media.stat().st_size < 1: raise RuntimeError("Downloaded file is empty")
        ctype = mimetypes.guess_type(media.name)[0] or ("audio/mpeg" if kind == "audio" else "video/mp4")
        title = re.sub(r"\s+", " ", info.get("title") or "Media").strip()[:180]
        db = Session()
        try:
            db.execute(update(Download).where(Download.job_id == job).values(
                title=title, thumbnail=info.get("thumbnail"), filename=media.name,
                content_type=ctype, status="completed", error=None
            ))
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        log.exception("job=%s failed", job)
        mark_failed(job, exc)
        cleanup_job(job)

def claim_one():
    db = Session()
    try:
        row = db.scalar(select(Download).where(Download.status == "queued").order_by(Download.id).limit(1))
        if not row: return None
        result = db.execute(update(Download).where(
            Download.job_id == row.job_id, Download.status == "queued"
        ).values(status="downloading", error=None))
        if result.rowcount != 1:
            db.rollback(); return None
        db.commit()
        return row.job_id, row.kind
    finally:
        db.close()

def recover_stuck():
    db = Session()
    try:
        db.execute(update(Download).where(Download.status == "downloading").values(status="queued", error=None))
        db.commit()
    finally:
        db.close()

def cleanup_old():
    cutoff = time.time() - KEEP_FILE_HOURS * 3600
    for f in WORK.iterdir():
        if not f.is_file() or f.suffix in {".part", ".ytdl"}: continue
        try:
            if f.stat().st_mtime < cutoff: f.unlink()
        except OSError: pass

def worker_loop():
    recover_stuck()
    last = 0
    while True:
        try:
            if time.time() - last > 600:
                cleanup_old(); last = time.time()
            item = claim_one()
            if item: process(*item)
            else: time.sleep(float(os.getenv("WORKER_POLL_SECONDS", "0.7")))
        except Exception:
            log.exception("worker error"); time.sleep(2)

@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=worker_loop, daemon=True, name="quickdl-worker").start()
    yield

app = FastAPI(title="QuickDL", version="8.0.0", lifespan=lifespan)

@app.get("/")
def home(): return FileResponse(BASE / "templates" / "index.html")

@app.get("/static/{path:path}")
def static_file(path: str): return FileResponse(BASE / "static" / path)

@app.get("/manifest.json")
def manifest(): return FileResponse(BASE / "manifest.json", media_type="application/manifest+json")

@app.get("/sw.js")
def sw(): return FileResponse(BASE / "sw.js", media_type="application/javascript", headers={"Cache-Control":"no-cache"})

@app.get("/api/health")
def health():
    db = Session()
    try:
        db.execute(select(Download.id).limit(1))
        return {"ok": True, "service": "quickdl", "storage": "local-ephemeral", "version": "8.0.0"}
    finally: db.close()

class DownloadRequest(BaseModel):
    url: HttpUrl
    kind: str = "video"

def serialize(row):
    f = WORK / row.filename if row.filename else None
    ready = row.status == "completed" and f is not None and f.exists()
    status = "completed" if ready else ("expired" if row.status == "completed" else row.status)
    return {
        "job_id": row.job_id, "title": row.title, "status": status, "kind": row.kind,
        "thumbnail": row.thumbnail, "url": row.url, "platform": platform(row.url),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "download_url": f"/api/file/{row.job_id}" if ready else None,
        "preview_url": f"/api/file/{row.job_id}" if ready else None,
        "content_type": row.content_type,
        "error": row.error if status != "expired" else "This file is no longer stored on the server."
    }

@app.post("/api/download")
def create_download(req: DownloadRequest, vexdou_visitor: str | None = Cookie(default=None)):
    url, kind = str(req.url).strip(), req.kind.lower().strip()
    if kind not in {"video", "audio"}: raise HTTPException(400, "Invalid download type")
    if not allowed(url): raise HTTPException(400, "Please enter a valid public HTTP/HTTPS URL")
    visitor, job = vexdou_visitor or uuid.uuid4().hex, uuid.uuid4().hex
    db = Session()
    try:
        db.add(Download(job_id=job, visitor_id=visitor, url=url, title="Preparing...", status="queued", kind=kind))
        db.commit()
    finally: db.close()
    out = JSONResponse({"ok":True, "job_id":job, "status":"queued", "platform":platform(url), "kind":kind})
    if not vexdou_visitor:
        out.set_cookie("vexdou_visitor", visitor, max_age=31536000, httponly=True, samesite="lax", secure=True)
    return out

@app.get("/api/download/{job}")
def get_download(job: str, vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(404, "Download not found")
    db = Session()
    try:
        row = db.scalar(select(Download).where(Download.job_id == job, Download.visitor_id == vexdou_visitor))
        if not row: raise HTTPException(404, "Download not found")
        return serialize(row)
    finally: db.close()

@app.get("/api/history")
def history(vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor: return {"items":[]}
    db = Session()
    try:
        rows = db.scalars(select(Download).where(
            Download.visitor_id == vexdou_visitor, Download.status == "completed"
        ).order_by(Download.created_at.desc()).limit(100)).all()
        items = []
        for r in rows:
            s = serialize(r)
            if s["status"] == "completed": items.append(s)
        return {"items":items}
    finally: db.close()

@app.delete("/api/history")
def clear_history(vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor: return {"ok":True}
    db = Session()
    try:
        rows = db.scalars(select(Download).where(Download.visitor_id == vexdou_visitor)).all()
        for r in rows: cleanup_job(r.job_id)
        db.execute(delete(Download).where(Download.visitor_id == vexdou_visitor))
        db.commit()
        return {"ok":True}
    finally: db.close()

@app.get("/api/file/{job}")
def file(job: str, vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(404, "File not found")
    db = Session()
    try:
        row = db.scalar(select(Download).where(
            Download.job_id == job, Download.visitor_id == vexdou_visitor, Download.status == "completed"
        ))
        if not row or not row.filename: raise HTTPException(404, "File not found")
        path = WORK / row.filename
        if not path.exists(): raise HTTPException(410, "File expired")
        return FileResponse(path, media_type=row.content_type or "application/octet-stream",
                            filename=path.name,
                            headers={"Accept-Ranges":"bytes", "Cache-Control":"private,max-age=3600"})
    finally:
        db.close()
