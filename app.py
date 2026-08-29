import os
import re
import uuid
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, Cookie, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import yt_dlp


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("vexdou")


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+psycopg2://",
        1,
    )

elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg2://",
        1,
    )


if DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
    )
else:
    engine = create_engine(
        f"sqlite:///{BASE_DIR / 'downloader.db'}",
        connect_args={"check_same_thread": False},
    )


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


class Download(Base):
    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    job_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )

    visitor_id: Mapped[str] = mapped_column(
        String(128),
        index=True,
    )

    url: Mapped[str] = mapped_column(
        Text,
    )

    title: Mapped[str] = mapped_column(
        Text,
        default="Media",
    )

    thumbnail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="queued",
    )

    kind: Mapped[str] = mapped_column(
        String(20),
        default="video",
    )

    filename: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


Base.metadata.create_all(engine)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="VEXDOU Downloader",
    version="2.0.0",
)


# Static folder
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)


# ============================================================
# SUPPORTED HOSTS
# ============================================================

ALLOWED_HOSTS = {
    # YouTube
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",

    # TikTok
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",

    # Instagram
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
    "www.instagr.am",

    # Facebook
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "mbasic.facebook.com",
    "fb.watch",
    "fb.me",

    # Pinterest
    "pinterest.com",
    "www.pinterest.com",
    "pin.it",

    # X / Twitter
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
    "x.com",
    "www.x.com",
}


# ============================================================
# REQUEST MODEL
# ============================================================

class DownloadRequest(BaseModel):
    url: HttpUrl
    kind: str = "video"


# ============================================================
# URL HELPERS
# ============================================================

def get_hostname(url: str) -> str:
    try:
        return (
            urlparse(url).hostname
            or ""
        ).lower().rstrip(".")
    except Exception:
        return ""


def host_allowed(url: str) -> bool:
    host = get_hostname(url)

    if not host:
        return False

    return any(
        host == allowed
        or host.endswith("." + allowed)
        for allowed in ALLOWED_HOSTS
    )


def detect_platform(url: str) -> str:
    host = get_hostname(url)

    if (
        "youtube.com" in host
        or host == "youtu.be"
    ):
        return "youtube"

    if "tiktok.com" in host:
        return "tiktok"

    if (
        "instagram.com" in host
        or "instagr.am" in host
    ):
        return "instagram"

    if (
        "facebook.com" in host
        or host in {"fb.watch", "fb.me"}
    ):
        return "facebook"

    if (
        "pinterest.com" in host
        or host == "pin.it"
    ):
        return "pinterest"

    if (
        "twitter.com" in host
        or host == "x.com"
    ):
        return "x"

    return "unknown"


# ============================================================
# FILE HELPERS
# ============================================================

def safe_name(value: str) -> str:
    value = value or "media"

    value = re.sub(
        r'[\\/:*?"<>|]+',
        "_",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return value[:160] or "media"


def find_output(job_id: str) -> Path | None:
    files = [
        path
        for path in DOWNLOAD_DIR.glob(
            f"{job_id}.*"
        )
        if path.is_file()
    ]

    if not files:
        return None

    # Prefer normal media extensions
    priority = [
        ".mp4",
        ".m4a",
        ".webm",
        ".mov",
        ".mkv",
        ".mp3",
        ".aac",
        ".wav",
    ]

    for extension in priority:
        for path in files:
            if path.suffix.lower() == extension:
                return path

    return files[0]


def cleanup_job_files(job_id: str):
    for path in DOWNLOAD_DIR.glob(
        f"{job_id}.*"
    ):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


# ============================================================
# PLATFORM HEADERS
# ============================================================

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)


def platform_headers(
    platform: str,
) -> dict:

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    referers = {
        "youtube": "https://www.youtube.com/",
        "tiktok": "https://www.tiktok.com/",
        "instagram": "https://www.instagram.com/",
        "facebook": "https://www.facebook.com/",
        "pinterest": "https://www.pinterest.com/",
        "x": "https://x.com/",
    }

    if platform in referers:
        headers["Referer"] = referers[platform]

    return headers


# ============================================================
# YT-DLP OPTIONS
# ============================================================

def build_ydl_options(
    job_id: str,
    kind: str,
    platform: str,
    use_impersonation: bool = True,
) -> dict:

    output_template = str(
        DOWNLOAD_DIR /
        f"{job_id}.%(ext)s"
    )

    options = {
        "outtmpl": output_template,

        # Never download playlists
        "noplaylist": True,

        # Keep logs quiet
        "quiet": True,
        "no_warnings": True,

        # Better network reliability
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 5,

        "socket_timeout": 45,

        # Do not stop after one bad fragment
        "skip_unavailable_fragments": True,

        # Avoid filename problems
        "restrictfilenames": True,

        # Browser-like headers
        "http_headers": platform_headers(platform),

        # Prefer MP4 when possible.
        #
        # This avoids unnecessary video/audio merging for
        # platforms that already provide a combined MP4.
        "format": (
            "best[ext=mp4]/"
            "best[ext=mp4][vcodec!=none]/"
            "best"
        ),

        # Metadata
        "writethumbnail": False,
        "writeinfojson": False,

        # Don't accidentally download a playlist
        "extract_flat": False,

        # Network configuration
        "sleep_interval": 0,
        "max_sleep_interval": 0,

        # Safer file naming
        "windowsfilenames": True,
    }


    # ========================================================
    # CURL-CFFI BROWSER IMPERSONATION
    # ========================================================

    if use_impersonation:
        options["impersonate"] = "chrome"


    # ========================================================
    # PLATFORM-SPECIFIC SETTINGS
    # ========================================================

    if platform == "youtube":
        options["extractor_args"] = {
            "youtube": {
                "player_client": [
                    "web",
                    "android",
                ],
            }
        }

    elif platform == "tiktok":
        options["extractor_args"] = {
            "tiktok": {
                "app_name": ["musical_ly"],
            }
        }

    elif platform == "instagram":
        options["extractor_args"] = {
            "instagram": {}
        }

    elif platform == "facebook":
        options["extractor_args"] = {
            "facebook": {}
        }

    elif platform == "pinterest":
        options["extractor_args"] = {
            "pinterest": {}
        }

    elif platform == "x":
        options["extractor_args"] = {
            "twitter": {}
        }


    # ========================================================
    # AUDIO / MP3
    # ========================================================

    if kind == "audio":

        # FFmpeg is required for MP3 conversion.
        if not shutil.which("ffmpeg"):
            raise RuntimeError(
                "FFmpeg lama rakibin server-ka. "
                "MP3 conversion ma shaqayn karto ilaa "
                "FFmpeg lagu daro Render."
            )

        options["format"] = (
            "bestaudio/best"
        )

        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]


    return options


# ============================================================
# ERROR TRANSLATION
# ============================================================

def friendly_error(
    error: Exception,
    platform: str,
) -> str:

    message = str(error or "").strip()

    lower = message.lower()


    # YouTube
    if (
        "sign in to confirm" in lower
        or "confirm you're not a bot" in lower
        or "not a bot" in lower
        or "po token" in lower
    ):
        return (
            "YouTube ayaa xannibay request-ka server-ka. "
            "Isku day link kale ama mar kale isku day."
        )


    # Private / unavailable
    if (
        "private video" in lower
        or "video is private" in lower
        or "content is private" in lower
    ):
        return (
            "Media-kan waa private mana la soo dejisan karo."
        )


    if (
        "login required" in lower
        or "log in" in lower
        or "sign in" in lower
    ):
        return (
            f"{platform.title()} wuxuu u baahan yahay "
            "login ama content-ku ma aha public."
        )


    # Removed / deleted
    if (
        "video unavailable" in lower
        or "not available" in lower
        or "does not exist" in lower
        or "has been removed" in lower
    ):
        return (
            "Media-kan lama heli karo ama waa la tirtiray."
        )


    # Age restriction
    if (
        "age-restricted" in lower
        or "age restricted" in lower
    ):
        return (
            "Media-kan wuxuu leeyahay age restriction "
            "oo server-ku ma soo dejin karo."
        )


    # Geo restriction
    if (
        "geo-restricted" in lower
        or "not available in your country" in lower
    ):
        return (
            "Media-kan waxaa xaddiday goobta/region-ka."
        )


    # Generic
    clean = re.sub(
        r"\s+",
        " ",
        message,
    ).strip()

    if not clean:
        return (
            "Server-ku ma awoodin inuu soo dejiyo "
            "media-kan."
        )

    return (
        f"Download failed: {clean[:220]}"
    )


# ============================================================
# DOWNLOAD WORKER
# ============================================================

def run_download(
    job_id: str,
    url: str,
    kind: str,
):

    db = SessionLocal()

    item = None

    try:

        item = db.scalar(
            select(Download).where(
                Download.job_id == job_id
            )
        )

        if not item:
            logger.error(
                "Job %s not found",
                job_id,
            )
            return


        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        item.status = "downloading"
        item.error = None

        db.commit()


        platform = detect_platform(url)

        logger.info(
            "Starting download | job=%s | platform=%s | kind=%s",
            job_id,
            platform,
            kind,
        )


        # ----------------------------------------------------
        # FIRST ATTEMPT
        # ----------------------------------------------------

        try:

            options = build_ydl_options(
                job_id=job_id,
                kind=kind,
                platform=platform,
                use_impersonation=True,
            )

            with yt_dlp.YoutubeDL(
                options
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=True,
                )

                if info:
                    item.title = safe_name(
                        info.get("title")
                        or info.get("fulltitle")
                        or info.get("description")
                        or "Media"
                    )

                    item.thumbnail = (
                        info.get("thumbnail")
                    )


        except Exception as first_error:

            logger.warning(
                "First attempt failed | job=%s | platform=%s | error=%s",
                job_id,
                platform,
                first_error,
            )

            cleanup_job_files(job_id)


            # ------------------------------------------------
            # SECOND ATTEMPT
            #
            # Some servers behave differently when browser
            # impersonation is enabled.
            # ------------------------------------------------

            try:

                options = build_ydl_options(
                    job_id=job_id,
                    kind=kind,
                    platform=platform,
                    use_impersonation=False,
                )

                with yt_dlp.YoutubeDL(
                    options
                ) as ydl:

                    info = ydl.extract_info(
                        url,
                        download=True,
                    )

                    if info:
                        item.title = safe_name(
                            info.get("title")
                            or info.get("fulltitle")
                            or info.get("description")
                            or "Media"
                        )

                        item.thumbnail = (
                            info.get("thumbnail")
                        )


            except Exception as second_error:

                logger.error(
                    "Second attempt failed | job=%s | platform=%s | error=%s",
                    job_id,
                    platform,
                    second_error,
                )

                raise second_error


        # ----------------------------------------------------
        # FIND FILE
        # ----------------------------------------------------

        output = find_output(job_id)

        if not output:

            raise RuntimeError(
                "Downloaded file was not created."
            )


        # ----------------------------------------------------
        # VERIFY FILE
        # ----------------------------------------------------

        if not output.exists():
            raise RuntimeError(
                "Downloaded file does not exist."
            )

        if output.stat().st_size <= 0:
            raise RuntimeError(
                "Downloaded file is empty."
            )


        # ----------------------------------------------------
        # SAVE SUCCESS
        # ----------------------------------------------------

        item.filename = output.name
        item.status = "completed"
        item.error = None

        db.commit()

        logger.info(
            "Download completed | job=%s | file=%s | size=%s",
            job_id,
            output.name,
            output.stat().st_size,
        )


    except Exception as exc:

        logger.exception(
            "Download failed | job=%s",
            job_id,
        )

        if item:

            item.status = "failed"

            platform = detect_platform(url)

            item.error = friendly_error(
                exc,
                platform,
            )

            db.commit()


        cleanup_job_files(job_id)


    finally:

        db.close()


# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
def home():

    return FileResponse(
        BASE_DIR /
        "templates" /
        "index.html"
    )


# ============================================================
# PWA MANIFEST
# ============================================================

@app.get("/manifest.json")
def serve_manifest():

    path = BASE_DIR / "manifest.json"

    if not path.exists():
        raise HTTPException(
            404,
            "manifest.json not found",
        )

    return FileResponse(
        path,
        media_type="application/manifest+json",
    )


# ============================================================
# SERVICE WORKER
# ============================================================

@app.get("/sw.js")
def serve_sw():

    path = BASE_DIR / "sw.js"

    if not path.exists():
        raise HTTPException(
            404,
            "sw.js not found",
        )

    response = FileResponse(
        path,
        media_type="application/javascript",
    )

    response.headers[
        "Service-Worker-Allowed"
    ] = "/"

    response.headers[
        "Cache-Control"
    ] = "no-cache, no-store, must-revalidate"

    return response


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():

    return {
        "ok": True,
        "service": "vexdou-downloader",
        "version": "2.0.0",
    }


# ============================================================
# CREATE DOWNLOAD
# ============================================================

@app.post("/api/download")
def create_download(
    payload: DownloadRequest,
    background_tasks: BackgroundTasks,
    vexdou_visitor: str | None = Cookie(
        default=None
    ),
):

    url = str(payload.url).strip()

    kind = (
        payload.kind
        or "video"
    ).lower().strip()


    # --------------------------------------------------------
    # KIND
    # --------------------------------------------------------

    if kind not in {
        "video",
        "audio",
    }:
        raise HTTPException(
            status_code=400,
            detail="Invalid download type.",
        )


    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    if not host_allowed(url):

        raise HTTPException(
            status_code=400,
            detail=(
                "Boggan waxaa laga taageeraa "
                "YouTube, TikTok, Instagram, "
                "Facebook, Pinterest iyo X/Twitter."
            ),
        )


    platform = detect_platform(url)

    if platform == "unknown":

        raise HTTPException(
            status_code=400,
            detail="Platform-kan lama taageero.",
        )


    # --------------------------------------------------------
    # VISITOR
    # --------------------------------------------------------

    visitor_id = (
        vexdou_visitor
        or uuid.uuid4().hex
    )


    # --------------------------------------------------------
    # JOB
    # --------------------------------------------------------

    job_id = uuid.uuid4().hex


    db = SessionLocal()

    try:

        db.add(
            Download(
                job_id=job_id,
                visitor_id=visitor_id,
                url=url,
                title="Downloading...",
                status="queued",
                kind=kind,
            )
        )

        db.commit()

    finally:
        db.close()


    # --------------------------------------------------------
    # BACKGROUND
    # --------------------------------------------------------

    background_tasks.add_task(
        run_download,
        job_id,
        url,
        kind,
    )


    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    response = JSONResponse(
        {
            "ok": True,
            "job_id": job_id,
            "visitor_id": visitor_id,
            "platform": platform,
            "kind": kind,
            "status": "queued",
        }
    )


    # --------------------------------------------------------
    # COOKIE
    # --------------------------------------------------------

    if not vexdou_visitor:

        response.set_cookie(
            key="vexdou_visitor",
            value=visitor_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            samesite="lax",
            secure=True,
        )


    return response


# ============================================================
# DOWNLOAD STATUS
# ============================================================

@app.get(
    "/api/download/{job_id}"
)
def download_status(
    job_id: str,
    vexdou_visitor: str | None = Cookie(
        default=None
    ),
):

    if not vexdou_visitor:
        raise HTTPException(
            status_code=404,
            detail="Download not found.",
        )


    db = SessionLocal()

    try:

        item = db.scalar(
            select(Download).where(
                Download.job_id == job_id,
                Download.visitor_id == vexdou_visitor,
            )
        )

        if not item:

            raise HTTPException(
                status_code=404,
                detail="Download not found.",
            )


        return {
            "job_id": item.job_id,
            "status": item.status,
            "title": item.title,
            "kind": item.kind,
            "error": item.error,
            "thumbnail": item.thumbnail,
            "url": item.url,
            "download_url": (
                f"/api/file/{item.job_id}"
                if item.status == "completed"
                else None
            ),
        }

    finally:
        db.close()


# ============================================================
# HISTORY
# ============================================================

@app.get("/api/history")
def history(
    vexdou_visitor: str | None = Cookie(
        default=None
    ),
):

    if not vexdou_visitor:
        return {
            "items": []
        }


    db = SessionLocal()

    try:

        items = db.scalars(
            select(Download)
            .where(
                Download.visitor_id ==
                vexdou_visitor
            )
            .order_by(
                Download.created_at.desc()
            )
            .limit(50)
        ).all()


        result = []

        for item in items:

            result.append(
                {
                    "job_id": item.job_id,
                    "title": item.title,
                    "status": item.status,
                    "kind": item.kind,
                    "thumbnail": item.thumbnail,
                    "url": item.url,
                    "created_at": (
                        item.created_at.isoformat()
                        if item.created_at
                        else None
                    ),
                    "download_url": (
                        f"/api/file/{item.job_id}"
                        if item.status == "completed"
                        else None
                    ),
                }
            )


        return {
            "items": result
        }

    finally:
        db.close()


# ============================================================
# SERVE FILE
# ============================================================

@app.get(
    "/api/file/{job_id}"
)
def get_file(
    job_id: str,
    vexdou_visitor: str | None = Cookie(
        default=None
    ),
):

    if not vexdou_visitor:

        raise HTTPException(
            status_code=404,
            detail="File not found.",
        )


    db = SessionLocal()

    try:

        item = db.scalar(
            select(Download).where(
                Download.job_id == job_id,
                Download.visitor_id ==
                vexdou_visitor,
                Download.status ==
                "completed",
            )
        )

        if not item:

            raise HTTPException(
                status_code=404,
                detail="File not found.",
            )


        if not item.filename:

            raise HTTPException(
                status_code=404,
                detail="File not found.",
            )


        # Prevent path traversal
        filename = Path(
            item.filename
        ).name

        path = (
            DOWNLOAD_DIR /
            filename
        ).resolve()


        if (
            path.parent !=
            DOWNLOAD_DIR.resolve()
        ):

            raise HTTPException(
                status_code=404,
                detail="File not found.",
            )


        if not path.exists():

            raise HTTPException(
                status_code=404,
                detail="File not found.",
            )


        return FileResponse(
            path,
            filename=(
                f"{safe_name(item.title)}"
                f".{path.suffix.lstrip('.')}"
            ),
        )

    finally:
        db.close()


# ============================================================
# CLEAR HISTORY
# ============================================================

@app.delete("/api/history")
def clear_history(
    vexdou_visitor: str | None = Cookie(
        default=None
    ),
):

    if not vexdou_visitor:
        return {
            "ok": True
        }


    db = SessionLocal()

    try:

        items = db.scalars(
            select(Download).where(
                Download.visitor_id ==
                vexdou_visitor
            )
        ).all()


        for item in items:

            if item.filename:

                try:

                    path = (
                        DOWNLOAD_DIR /
                        Path(item.filename).name
                    )

                    path.unlink(
                        missing_ok=True
                    )

                except OSError:
                    pass


            db.delete(item)


        db.commit()


        return {
            "ok": True
        }

    finally:
        db.close()


# ============================================================
# OPTIONAL: DELETE ONE HISTORY ITEM
# ============================================================

@app.delete(
    "/api/history/{job_id}"
)
def delete_history_item(
    job_id: str,
    vexdou_visitor: str | None = Cookie(
        default=None
    ),
):

    if not vexdou_visitor:

        raise HTTPException(
            status_code=404,
            detail="Download not found.",
        )


    db = SessionLocal()

    try:

        item = db.scalar(
            select(Download).where(
                Download.job_id == job_id,
                Download.visitor_id ==
                vexdou_visitor,
            )
        )


        if not item:

            raise HTTPException(
                status_code=404,
                detail="Download not found.",
            )


        if item.filename:

            try:

                path = (
                    DOWNLOAD_DIR /
                    Path(item.filename).name
                )

                path.unlink(
                    missing_ok=True
                )

            except OSError:
                pass


        db.delete(item)
        db.commit()


        return {
            "ok": True
        }

    finally:
        db.close()


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup_event():

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    logger.info(
        "VEXDOU Downloader started"
    )

    logger.info(
        "Download directory: %s",
        DOWNLOAD_DIR,
    )

    logger.info(
        "FFmpeg available: %s",
        bool(shutil.which("ffmpeg")),
    )

    logger.info(
        "yt-dlp version: %s",
        getattr(
            yt_dlp.version,
            "__version__",
            "unknown",
        ),
)
