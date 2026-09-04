import os, re, time, uuid, mimetypes, logging, threading, ipaddress, socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
import requests
from html import unescape
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
# Optional: path to a Netscape-format cookies.txt (see yt-dlp's --cookies docs).
# Only used if you choose to set it - never required, and never populated
# automatically. This is a per-deployment opt-in, not something this code does
# on its own.
COOKIES_FILE = Path(os.getenv("YTDLP_COOKIES_FILE")) if os.getenv("YTDLP_COOKIES_FILE") else None

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
    if "snapchat" in h: return "snapchat"
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



def instagram_public_fallback(job, url, kind):
    """Best-effort fallback for media that Instagram exposes publicly in OG metadata.
    This never supplies credentials and never attempts to bypass a login/private post:
    if a post needs a login, every URL below will also just return the login wall
    (or nothing), same as the main extractor, and this simply returns None.
    """
    if kind != "video":
        return None
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "Cache-Control": "no-cache",
    }
    # Instagram's own embed page is meant for third-party sites to render a
    # public post and is more likely to include a server-rendered <video>/OG
    # tag than the main post page, which increasingly leaves a plain,
    # logged-out fetch with an empty shell. Try it first, then fall back to
    # the direct URL.
    candidates = [url]
    shortcode_m = re.search(r"/(p|reel|tv)/([^/?#]+)", urlparse(url).path)
    if shortcode_m:
        candidates.insert(0, f"https://www.instagram.com/{shortcode_m.group(1)}/{shortcode_m.group(2)}/embed/captioned/")
    try:
        html = None
        for candidate in candidates:
            try:
                r = requests.get(candidate, headers=headers, timeout=(15, 30), allow_redirects=True)
                r.raise_for_status()
            except Exception as exc:
                log.info("job=%s: Instagram public fetch of %s unavailable: %s", job, candidate, exc)
                continue
            html = r.text
            if "og:video" in html or "video_url" in html:
                break
        if not html:
            return None
        # Only use media explicitly published in public OpenGraph/page metadata.
        patterns = [
            r'<meta[^>]+property=["\']og:video(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video(?::secure_url)?["\']',
            r'"video_url"\s*:\s*"([^"]+)"',
        ]
        media_url = None
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                media_url = unescape(m.group(1)).replace('\\/', '/').replace('&amp;', '&')
                break
        if not media_url or not media_url.startswith(('http://', 'https://')):
            return None
        out = WORK / f"{job}.mp4"
        with requests.get(media_url, headers={"User-Agent": UA, "Referer": "https://www.instagram.com/"}, stream=True, timeout=(15, 60), allow_redirects=True) as mr:
            mr.raise_for_status()
            total = 0
            with open(out, 'wb') as fh:
                for chunk in mr.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > int(setting_get("max_file_mb") or MAX_FILE_MB) * 1024 * 1024:
                        raise RuntimeError("Instagram media exceeds the configured file size limit")
                    fh.write(chunk)
        if total < 1:
            out.unlink(missing_ok=True)
            return None
        title_m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
        title = unescape(title_m.group(1)).strip()[:180] if title_m else "Instagram Media"
        image_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
        thumbnail = unescape(image_m.group(1)).replace('&amp;', '&') if image_m else None
        return {"title": title, "thumbnail": thumbnail}
    except Exception as exc:
        log.info("job=%s: Instagram public metadata fallback unavailable: %s", job, exc)
        return None

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
    if "javascript runtime" in low or "js runtime" in low:
        return "Server misconfiguration: no JavaScript runtime is installed for this platform. Contact the site operator."
    if "impersonat" in low or "curl_cffi" in low:
        return "Server misconfiguration: a required dependency (curl_cffi) is missing for this platform. Contact the site operator."
    return text[:700] or "Download failed. Please try another media URL."

def ytdlp_options(job, kind, youtube_player_client=None):
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
        "max_filesize": int(setting_get("max_file_mb") or MAX_FILE_MB) * 1024 * 1024,
        # YouTube's signature/throttling challenges now require executing the
        # site's own JS via an external runtime (yt-dlp's "EJS" system). List
        # every runtime this deployment might have installed rather than
        # forcing one - yt-dlp uses whichever is actually present instead of
        # hard failing when only one of them is available. Install at least
        # one of these on the host/container (Deno is the simplest: a single
        # static binary, no version-management needed) alongside the
        # `yt-dlp-ejs` package pulled in via requirements.txt.
        "js_runtimes": {"deno": {}, "node": {}, "quickjs": {}},
    }
    if COOKIES_FILE and COOKIES_FILE.exists():
        opts["cookiefile"] = str(COOKIES_FILE)
    # YouTube's anonymous "web" client increasingly hits a "Sign in to confirm
    # you're not a bot" wall. These are all official yt-dlp player clients that
    # YouTube itself serves video to - not a login bypass - but which one is
    # currently trusted shifts every few months, so the caller tries several
    # in sequence (see the client_chain in process()) instead of just one.
    if youtube_player_client:
        opts["extractor_args"] = {"youtube": {"player_client": [youtube_player_client]}}
    if kind == "audio":
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    return {k: v for k, v in opts.items() if v is not None}

def youtube_needs_fallback(exc):
    text = str(exc).lower()
    markers = (
        "sign in to confirm", "requires sign-in", "requires sign in",
        "login required", "authentication required", "confirm you're not a bot",
        "this content isn't available", "http error 403", "forbidden"
    )
    return any(marker in text for marker in markers)

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
        # Which YouTube player client currently avoids the "Sign in to confirm
        # you're not a bot" wall shifts every few months as YouTube adjusts
        # trust signals, so try several official clients in sequence instead
        # of betting on just one. None of these bypass a login - they're all
        # clients YouTube itself serves video to.
        client_chain = [None, "tv", "android", "web_embedded"]
        if platform(url) == "youtube":
            attempts = [ytdlp_options(job, kind, youtube_player_client=c) for c in client_chain]
        else:
            attempts = [ytdlp_options(job, kind)]

        last_exc = None
        info = None
        for attempt_no, opts in enumerate(attempts):
            try:
                cleanup_job(job)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                break
            except Exception as exc:
                last_exc = exc
                is_last_attempt = attempt_no == len(attempts) - 1
                if platform(url) == "youtube" and not is_last_attempt:
                    log.warning("job=%s: YouTube client %r failed (%s); trying next client", job,
                                client_chain[attempt_no],
                                "likely an auth wall" if youtube_needs_fallback(exc) else "error")
                    continue
                # Instagram can change its public web/GraphQL responses independently
                # of yt-dlp. For genuinely public posts, try the media URL exposed in
                # the page's OpenGraph metadata. This does not authenticate or bypass access controls.
                if platform(url) == "instagram":
                    cleanup_job(job)
                    fallback_info = instagram_public_fallback(job, url, kind)
                    if fallback_info:
                        info = fallback_info
                        log.info("job=%s: Instagram public OG fallback succeeded", job)
                        break
                raise
        if info is None:
            raise last_exc or RuntimeError("No media information was returned")

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
    cutoff = time.time() - float(setting_get("keep_file_hours") or KEEP_FILE_HOURS) * 3600
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

app = FastAPI(title="QuickDL", version="9.4.0", lifespan=lifespan)

@app.get("/")
def home():
    if "setting_bool" in globals() and setting_bool("maintenance"):
        return FileResponse(BASE / "templates" / "maintenance.html")
    return FileResponse(BASE / "templates" / "index.html")

@app.get("/static/{path:path}")
def static_file(path: str): return FileResponse(BASE / "static" / path)

@app.get("/manifest.json")
def manifest(): return FileResponse(BASE / "manifest.json", media_type="application/manifest+json")

@app.get("/sw.js")
def sw(): return FileResponse(BASE / "sw.js", media_type="application/javascript", headers={"Cache-Control":"no-cache"})

@app.get("/api/public-config")
def public_config():
    return {"announcement_enabled":setting_bool("announcement_enabled"),"announcement":setting_get("announcement"),"maintenance":setting_bool("maintenance")}

@app.get("/api/health")
def health():
    db = Session()
    try:
        db.execute(select(Download.id).limit(1))
        return {"ok": True, "service": "quickdl", "storage": "local-ephemeral", "version": "9.4.0"}
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
    if setting_bool("maintenance"):
        raise HTTPException(503, setting_get("maintenance_message"))
    if not setting_bool("downloads_enabled"):
        raise HTTPException(503, "Downloads are temporarily disabled by QuickDL.")
    url, kind = str(req.url).strip(), req.kind.lower().strip()
    p = platform(url)
    if not setting_bool(f"{p}_enabled"):
        raise HTTPException(503, f"{p.title()} downloads are temporarily unavailable.")
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

# --- Admin18 control center ---
from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import Float, Boolean
import hashlib, hmac, base64, json

class AdminSetting(Base):
    __tablename__ = "admin_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AdminAudit(Base):
    __tablename__ = "admin_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

Base.metadata.create_all(engine)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "").strip()
ADMIN_COOKIE = "quickdl_admin"

DEFAULT_SETTINGS = {
    "maintenance": "false",
    "maintenance_message": "QuickDL is temporarily under maintenance. Please try again shortly.",
    "announcement_enabled": "false",
    "announcement": "",
    "max_file_mb": str(MAX_FILE_MB),
    "keep_file_hours": str(KEEP_FILE_HOURS),
    "downloads_enabled": "true",
    "youtube_enabled": "true",
    "tiktok_enabled": "true",
    "instagram_enabled": "true",
    "facebook_enabled": "true",
    "pinterest_enabled": "true",
    "x_enabled": "true",
    "snapchat_enabled": "true",
    "web_enabled": "true",
}

def setting_get(key):
    db = Session()
    try:
        row = db.get(AdminSetting, key)
        return row.value if row else DEFAULT_SETTINGS.get(key, "")
    finally:
        db.close()

def settings_all():
    db = Session()
    try:
        vals = dict(DEFAULT_SETTINGS)
        for row in db.scalars(select(AdminSetting)).all(): vals[row.key] = row.value
        return vals
    finally: db.close()

def setting_bool(key):
    return setting_get(key).lower() in {"1", "true", "yes", "on"}

def audit(action, detail=""):
    db = Session()
    try:
        db.add(AdminAudit(action=action, detail=detail[:1000]))
        db.commit()
    finally: db.close()

def sign_admin(value):
    if not ADMIN_SESSION_SECRET: return ""
    sig = hmac.new(ADMIN_SESSION_SECRET.encode(), value.encode(), hashlib.sha256).digest()
    return value + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")

def valid_admin_cookie(cookie):
    if not cookie or not ADMIN_SESSION_SECRET: return False
    try:
        value, sig = cookie.rsplit(".", 1)
        expected = hmac.new(ADMIN_SESSION_SECRET.encode(), value.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        if not hmac.compare_digest(expected, supplied): return False
        ts = int(value)
        return time.time() - ts < 12 * 3600
    except Exception:
        return False

def admin_ok(request: Request):
    return valid_admin_cookie(request.cookies.get(ADMIN_COOKIE))

def require_admin(request: Request):
    if not admin_ok(request): raise HTTPException(401, "Admin authentication required")

def admin_file(name):
    return FileResponse(BASE / "templates" / name)

@app.get("/admin18", response_class=HTMLResponse)
def admin_page(request: Request):
    if not admin_ok(request): return admin_file("admin_login.html")
    return admin_file("admin.html")

class AdminLogin(BaseModel):
    password: str

class AdminSettingUpdate(BaseModel):
    settings: dict[str, str]

class AdminAction(BaseModel):
    action: str
    value: str | None = None

@app.post("/api/admin/login")
def admin_login(data: AdminLogin):
    if not ADMIN_PASSWORD or not ADMIN_SESSION_SECRET:
        raise HTTPException(503, "Admin authentication is not configured. Set ADMIN_PASSWORD and ADMIN_SESSION_SECRET.")
    if not hmac.compare_digest(data.password, ADMIN_PASSWORD):
        audit("admin_login_failed", "Invalid password")
        raise HTTPException(401, "Invalid admin password")
    token = sign_admin(str(int(time.time())))
    out = JSONResponse({"ok": True})
    out.set_cookie(ADMIN_COOKIE, token, max_age=43200, httponly=True, secure=True, samesite="strict", path="/")
    audit("admin_login", "Admin session started")
    return out

@app.post("/api/admin/logout")
def admin_logout(request: Request):
    require_admin(request)
    out = JSONResponse({"ok": True})
    out.delete_cookie(ADMIN_COOKIE, path="/")
    audit("admin_logout", "Admin session ended")
    return out

@app.get("/api/admin/overview")
def admin_overview(request: Request):
    require_admin(request)
    db = Session()
    try:
        total = db.scalar(select(Download.id).count()) if False else None
        rows = db.scalars(select(Download)).all()
        now = datetime.now(timezone.utc)
        today = [r for r in rows if r.created_at and (now-r.created_at).total_seconds() < 86400]
        week = [r for r in rows if r.created_at and (now-r.created_at).total_seconds() < 604800]
        status = {}
        plats = {}
        for r in rows:
            status[r.status] = status.get(r.status, 0) + 1
            p = platform(r.url); plats[p] = plats.get(p, 0) + 1
        users = len({r.visitor_id for r in rows})
        return {"version":"9.2.0-admin18", "users":users, "downloads":len(rows), "today":len(today), "week":len(week), "completed":status.get("completed",0), "failed":status.get("failed",0), "queued":status.get("queued",0), "downloading":status.get("downloading",0), "platforms":plats, "settings":settings_all(), "worker":"running"}
    finally: db.close()

@app.get("/api/admin/users")
def admin_users(request: Request, limit: int = 100):
    require_admin(request); limit=max(1,min(limit,500)); db=Session()
    try:
        rows=db.scalars(select(Download).order_by(Download.created_at.desc())).all(); groups={}
        for r in rows:
            g=groups.setdefault(r.visitor_id,{"visitor_id":r.visitor_id,"first_seen":r.created_at,"last_seen":r.created_at,"downloads":0,"completed":0,"failed":0})
            g["downloads"]+=1; g["completed"]+=r.status=="completed"; g["failed"]+=r.status=="failed"
            if r.created_at and (not g["first_seen"] or r.created_at<g["first_seen"]): g["first_seen"]=r.created_at
            if r.created_at and (not g["last_seen"] or r.created_at>g["last_seen"]): g["last_seen"]=r.created_at
        items=list(groups.values())[:limit]
        for x in items:
            x["first_seen"]=x["first_seen"].isoformat() if x["first_seen"] else None; x["last_seen"]=x["last_seen"].isoformat() if x["last_seen"] else None
        return {"items":items}
    finally: db.close()

@app.get("/api/admin/downloads")
def admin_downloads(request: Request, status: str = "", limit: int = 200):
    require_admin(request); limit=max(1,min(limit,500)); db=Session()
    try:
        q=select(Download).order_by(Download.created_at.desc()).limit(limit)
        if status: q=select(Download).where(Download.status==status).order_by(Download.created_at.desc()).limit(limit)
        rows=db.scalars(q).all()
        return {"items":[{"job_id":r.job_id,"visitor_id":r.visitor_id,"title":r.title,"url":r.url,"platform":platform(r.url),"kind":r.kind,"status":r.status,"error":r.error,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

@app.get("/api/admin/errors")
def admin_errors(request: Request, limit: int = 100):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.status=="failed").order_by(Download.created_at.desc()).limit(max(1,min(limit,300)))).all(); return {"items":[{"job_id":r.job_id,"platform":platform(r.url),"error":r.error or "Unknown error","url":r.url,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

@app.get("/api/admin/audit")
def admin_audit(request: Request, limit: int = 100):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(max(1,min(limit,300)))).all(); return {"items":[{"action":r.action,"detail":r.detail,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

@app.post("/api/admin/settings")
def admin_settings(data: AdminSettingUpdate, request: Request):
    require_admin(request); allowed_keys=set(DEFAULT_SETTINGS); db=Session()
    try:
        changed=[]
        for key,val in data.settings.items():
            if key not in allowed_keys: continue
            val=str(val)[:2000]
            row=db.get(AdminSetting,key)
            if row: row.value=val; row.updated_at=datetime.now(timezone.utc)
            else: db.add(AdminSetting(key=key,value=val))
            changed.append(key)
        db.commit(); audit("settings_updated", ", ".join(changed)); return {"ok":True,"settings":settings_all()}
    finally: db.close()

@app.post("/api/admin/action")
def admin_action(data: AdminAction, request: Request):
    require_admin(request)
    actions={"clear_failed","clear_completed","clear_all"}
    if data.action not in actions: raise HTTPException(400,"Unknown action")
    db=Session()
    try:
        if data.action=="clear_failed": rows=db.scalars(select(Download).where(Download.status=="failed")).all()
        elif data.action=="clear_completed": rows=db.scalars(select(Download).where(Download.status=="completed")).all()
        else: rows=db.scalars(select(Download)).all()
        for r in rows: cleanup_job(r.job_id)
        if data.action=="clear_failed": db.execute(delete(Download).where(Download.status=="failed"))
        elif data.action=="clear_completed": db.execute(delete(Download).where(Download.status=="completed"))
        else: db.execute(delete(Download))
        db.commit(); audit("admin_action",data.action); return {"ok":True,"removed":len(rows)}
    finally: db.close()
