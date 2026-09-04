import os, re, uuid, time, threading, logging, mimetypes
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone
import http.cookiejar

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, String, Text, Integer, DateTime, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log=logging.getLogger("quickdl")

BASE=Path(__file__).resolve().parent
WORK=Path(os.getenv("WORK_DIR","/tmp/quickdl"))
WORK.mkdir(parents=True,exist_ok=True)
MAX_FILE_MB=max(1,int(os.getenv("MAX_FILE_MB","100")))
KEEP_FILE_HOURS=float(os.getenv("KEEP_FILE_HOURS","6"))
UA=os.getenv("DOWNLOADER_USER_AGENT","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36")

db_url=os.getenv("DATABASE_URL","").strip()
if db_url.startswith("postgres://"): db_url=db_url.replace("postgres://","postgresql+psycopg2://",1)
elif db_url.startswith("postgresql://"): db_url=db_url.replace("postgresql://","postgresql+psycopg2://",1)
if not db_url: db_url=f"sqlite:///{WORK/'quickdl.db'}"
engine=create_engine(db_url,pool_pre_ping=True)
Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)

class Base(DeclarativeBase): pass
class Download(Base):
    __tablename__="downloads"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    job_id:Mapped[str]=mapped_column(String(64),unique=True,index=True)
    visitor_id:Mapped[str]=mapped_column(String(128),index=True)
    url:Mapped[str]=mapped_column(Text)
    title:Mapped[str]=mapped_column(Text,default="Media")
    thumbnail:Mapped[str|None]=mapped_column(Text,nullable=True)
    status:Mapped[str]=mapped_column(String(30),default="queued",index=True)
    kind:Mapped[str]=mapped_column(String(20),default="video")
    filename:Mapped[str|None]=mapped_column(Text,nullable=True)
    content_type:Mapped[str|None]=mapped_column(String(120),nullable=True)
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
Base.metadata.create_all(engine)

def cookie_file():
    # Preferred: Render Secret File mounted at /etc/secrets/cookies.txt.
    configured=os.getenv("YTDLP_COOKIES_FILE","").strip()
    candidates=[configured, "/etc/secrets/cookies.txt", str(BASE/"cookies.txt")]
    for p in candidates:
        if p and Path(p).is_file() and Path(p).stat().st_size>0:
            return Path(p)
    # Optional emergency/alternative: put the Netscape cookie text in an env var.
    content=os.getenv("COOKIES_CONTENT","")
    if content.strip():
        p=WORK/"cookies.txt"
        p.write_text(content,encoding="utf-8")
        return p
    return None

def platform(url):
    h=(urlparse(url).hostname or "").lower().rstrip(".")
    if h=="youtu.be" or "youtube." in h: return "youtube"
    if "instagram." in h or h=="instagr.am": return "instagram"
    if "tiktok." in h: return "tiktok"
    if "facebook." in h or h in {"fb.watch","fb.me"}: return "facebook"
    if "pinterest." in h or h=="pin.it": return "pinterest"
    if h in {"x.com","twitter.com"}: return "x"
    return "web"

def valid_url(url):
    p=urlparse(url)
    return p.scheme in {"http","https"} and bool(p.hostname)

def options(job,kind,client=None):
    opts={
        "outtmpl":str(WORK/f"{job}.%(ext)s"),
        "noplaylist":True,
        "quiet":True,
        "no_warnings":False,
        "retries":5,
        "fragment_retries":5,
        "file_access_retries":3,
        "socket_timeout":60,
        "concurrent_fragment_downloads":2,
        "http_headers":{"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"},
        "restrictfilenames":True,
        "windowsfilenames":True,
        "max_filesize":MAX_FILE_MB*1024*1024,
        "format":"bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" if kind=="video" else "ba/b",
        "merge_output_format":"mp4" if kind=="video" else None,
    }
    # Only use cookies if an explicit, readable file exists.
    cf=cookie_file()
    if cf: opts["cookiefile"]=str(cf)
    if client: opts["extractor_args"]={"youtube":{"player_client":[client]}}
    if kind=="audio":
        opts["postprocessors"]=[{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]
    return {k:v for k,v in opts.items() if v is not None}

def cleanup(job):
    for f in WORK.glob(f"{job}.*"):
        try:f.unlink()
        except OSError:pass

def friendly_error(exc):
    s=re.sub(r"\s+"," ",str(exc)).strip()
    l=s.lower()
    if "sign in" in l or "login required" in l or "authentication" in l:
        return "The source requires authorization. Configure a valid cookies.txt as a Render Secret File and set YTDLP_COOKIES_FILE=/etc/secrets/cookies.txt."
    if "429" in l or "too many requests" in l:
        return "The source rate-limited this server. Please try again later."
    if "403" in l or "forbidden" in l:
        return "The source refused automated access to this media."
    if "private" in l: return "This media is private or unavailable."
    if "unsupported url" in l or "no suitable extractor" in l: return "This URL is not supported."
    if "ffmpeg" in l: return "FFmpeg is required for this format and is not available."
    if "timed out" in l or "timeout" in l: return "The source took too long to respond."
    return s[:700] or "Download failed."

def set_status(job,**values):
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job))
        if row:
            for k,v in values.items(): setattr(row,k,v)
            db.commit()
    finally: db.close()

def process(job):
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job))
        if not row:return
        url,kind=row.url,row.kind
        set_status(job,status="downloading",error=None)
        p=platform(url)
        # YouTube: try normal extractor first, then compatible clients.
        clients=[None,"tv","android","web_embedded"] if p=="youtube" else [None]
        last=None; info=None
        for client in clients:
            cleanup(job)
            try:
                log.info("job=%s platform=%s client=%s cookies=%s",job,p,client,bool(cookie_file()))
                with yt_dlp.YoutubeDL(options(job,kind,client)) as ydl:
                    info=ydl.extract_info(url,download=True)
                break
            except Exception as e:
                last=e
                log.warning("job=%s attempt client=%s failed: %s",job,client,e)
        if info is None:
            raise last or RuntimeError("No download result")
        files=[f for f in WORK.glob(f"{job}.*") if f.is_file() and f.suffix not in {".part",".ytdl"}]
        if not files: raise RuntimeError("yt-dlp completed without producing a file")
        f=max(files,key=lambda x:x.stat().st_size)
        title=str(info.get("title") or "Media")[:180]
        thumb=info.get("thumbnail")
        set_status(job,status="completed",title=title,thumbnail=thumb,filename=f.name,
                   content_type=mimetypes.guess_type(f.name)[0] or "application/octet-stream")
    except Exception as e:
        cleanup(job)
        set_status(job,status="failed",error=friendly_error(e))
        log.exception("job=%s failed",job)
    finally: db.close()

def start_job(job):
    threading.Thread(target=process,args=(job,),daemon=True).start()

class DownloadRequest(BaseModel):
    url:HttpUrl
    kind:str="video"

app=FastAPI(title="QuickDL")
templates=Jinja2Templates(directory=str(BASE/"templates"))

@app.get("/",response_class=HTMLResponse)
def home(request:Request):
    return templates.TemplateResponse("index.html",{"request":request})

@app.get("/health")
def health():
    return {"ok":True,"yt_dlp":getattr(yt_dlp,"version",__import__("yt_dlp").version.__version__),
            "cookies_configured":bool(cookie_file()),"max_file_mb":MAX_FILE_MB}

@app.post("/api/download")
def create_download(data:DownloadRequest,request:Request):
    url=str(data.url)
    if not valid_url(url): raise HTTPException(400,"Invalid URL")
    kind=data.kind if data.kind in {"video","audio"} else "video"
    visitor=request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    job=uuid.uuid4().hex
    db=Session()
    try:
        db.add(Download(job_id=job,visitor_id=visitor,url=url,kind=kind,status="queued"))
        db.commit()
    finally: db.close()
    start_job(job)
    return {"job_id":job,"status":"queued","platform":platform(url)}

@app.get("/api/status/{job}")
def status(job:str):
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job))
        if not row: raise HTTPException(404,"Job not found")
        return {"job_id":job,"status":row.status,"title":row.title,"thumbnail":row.thumbnail,
                "error":row.error,"filename":row.filename,
                "download_url":f"/api/file/{job}" if row.status=="completed" else None}
    finally:db.close()

@app.get("/api/file/{job}")
def file(job:str):
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job))
        if not row or row.status!="completed" or not row.filename: raise HTTPException(404,"File not ready")
        p=WORK/row.filename
        if not p.is_file(): raise HTTPException(404,"File expired")
        return FileResponse(p,media_type=row.content_type or "application/octet-stream",
                            filename=p.name)
    finally:db.close()

@app.get("/api/history")
def history(request:Request):
    visitor=request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.visitor_id==visitor).order_by(Download.created_at.desc()).limit(30)).all()
        return {"items":[{"job_id":r.job_id,"title":r.title,"url":r.url,"status":r.status,
                          "error":r.error,"created_at":r.created_at.isoformat()} for r in rows]}
    finally:db.close()

@app.on_event("startup")
def startup():
    log.info("QuickDL started; cookie file=%s",cookie_file())
    def janitor():
        while True:
            time.sleep(1800)
            cutoff=time.time()-KEEP_FILE_HOURS*3600
            for f in WORK.iterdir():
                try:
                    if f.is_file() and f.stat().st_mtime<cutoff and f.name not in {"quickdl.db"}: f.unlink()
                except OSError:pass
    threading.Thread(target=janitor,daemon=True).start()
