
import os, re, time, uuid, mimetypes, logging, threading, ipaddress, socket, hashlib, hmac, base64, json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin, quote

import requests
import yt_dlp
from html import unescape
from fastapi import FastAPI, HTTPException, Cookie, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, String, Text, Integer, DateTime, select, update, delete, func, Boolean
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

engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5)
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
    extractor: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filesize: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AdminSetting(Base):
    __tablename__ = "admin_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AdminAudit(Base):
    __tablename__ = "admin_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(180))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

Base.metadata.create_all(engine)

UA = os.getenv("DOWNLOADER_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36")
DEFAULTS = {
    "maintenance":"false", "maintenance_message":"QuickDL is temporarily under maintenance.",
    "announcement_enabled":"false", "announcement":"",
    "downloads_enabled":"true", "max_file_mb":"300", "keep_file_hours":"6",
    "worker_poll_seconds":"0.7", "download_timeout_minutes":"20",
    "youtube_enabled":"true", "tiktok_enabled":"true", "instagram_enabled":"true",
    "facebook_enabled":"true", "pinterest_enabled":"true", "x_enabled":"true",
    "snapchat_enabled":"true", "web_enabled":"true",
    "max_concurrent_jobs":"1", "allow_audio":"true",
    "cobalt_enabled":"false", "cobalt_api_url":"",
    "rate_limit_retry_count":"4", "rate_limit_backoff_seconds":"3",
}
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD","").strip()
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET","").strip()
ADMIN_COOKIE = "quickdl_admin"

def setting_get(k):
    db=Session()
    try:
        r=db.get(AdminSetting,k)
        return r.value if r else DEFAULTS.get(k,"")
    finally: db.close()

def setting_bool(k): return setting_get(k).lower() in {"1","true","yes","on"}

def settings_all():
    db=Session()
    try:
        d=dict(DEFAULTS)
        for r in db.scalars(select(AdminSetting)).all(): d[r.key]=r.value
        return d
    finally: db.close()

def audit(action, detail=""):
    db=Session()
    try:
        db.add(AdminAudit(action=action,detail=str(detail)[:2000])); db.commit()
    finally: db.close()

def hostname(url):
    return (urlparse(url).hostname or "").lower().rstrip(".")

def platform(url):
    h=hostname(url)
    if h=="youtu.be" or "youtube." in h or h=="youtube.com" or h.endswith(".youtube.com"): return "youtube"
    if "tiktok." in h or h=="vm.tiktok.com": return "tiktok"
    if h in {"instagram.com","instagr.am"} or h.endswith(".instagram.com"): return "instagram"
    if h in {"facebook.com","fb.watch","fb.me"} or h.endswith(".facebook.com"): return "facebook"
    if h in {"pinterest.com","pin.it"} or h.endswith(".pinterest.com"): return "pinterest"
    if h in {"x.com","twitter.com"} or h.endswith(".x.com") or h.endswith(".twitter.com"): return "x"
    if h=="snapchat.com" or h.endswith(".snapchat.com"): return "snapchat"
    return "web"

def public_host(h):
    if not h or h in {"localhost","localhost.localdomain"} or h.endswith((".local",".internal",".localhost")): return False
    try:
        infos=socket.getaddrinfo(h,None,type=socket.SOCK_STREAM)
        return bool(infos) and all(
            not (a:=ipaddress.ip_address(i[4][0])).is_private and not a.is_loopback
            and not a.is_link_local and not a.is_multicast and not a.is_reserved and not a.is_unspecified
            for i in infos
        )
    except Exception:
        return True

def allowed(url):
    try:
        p=urlparse(url)
        return p.scheme in {"http","https"} and bool(p.hostname) and public_host(hostname(url))
    except Exception: return False

def clean_job(job):
    for f in WORK.glob(f"{job}.*"):
        try: f.unlink()
        except OSError: pass

def human_error(exc):
    t=re.sub(r"\s+"," ",str(exc)).strip()
    l=t.lower()
    if "429" in l or "too many requests" in l or "rate-limit" in l:
        return "The source rate-limited this server. The downloader tried its available public fallbacks; please retry later or use another public URL."
    if "sign in" in l or "login required" in l or "authentication" in l:
        return "This media requires sign-in or authorization."
    if "private" in l: return "This media is private or unavailable publicly."
    if "drm" in l: return "This media is DRM-protected and cannot be downloaded."
    if "unsupported url" in l or "no suitable extractor" in l: return "This URL is not supported by the media extractor."
    if "timed out" in l or "timeout" in l: return "The source took too long to respond. Please try again."
    return t[:700] or "Download failed. Please try another public media URL."

def ytdlp_options(job, kind, client=None):
    out=str(WORK/f"{job}.%(ext)s")
    opts={
        "outtmpl":out, "noplaylist":True, "quiet":True, "no_warnings":True,
        "retries":4, "fragment_retries":4, "file_access_retries":3,
        "socket_timeout":60, "http_chunk_size":10485760,
        "concurrent_fragment_downloads":1, "skip_unavailable_fragments":True,
        "restrictfilenames":True, "windowsfilenames":True,
        "http_headers":{"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"},
        "format":"bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" if kind=="video" else "ba/b",
        "merge_output_format":"mp4" if kind=="video" else None,
        "max_filesize":int(setting_get("max_file_mb") or "300")*1024*1024,
        "js_runtimes":{"node":{}},
        "extractor_retries":3,
    }
    if client: opts["extractor_args"]={"youtube":{"player_client":[client]}}
    if kind=="audio":
        opts["postprocessors"]=[{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]
    return {k:v for k,v in opts.items() if v is not None}

def youtube_fallback_needed(exc):
    l=str(exc).lower()
    return any(x in l for x in ("sign in to confirm","requires sign-in","login required","confirm you're not a bot","http error 403","forbidden","po token"))

def instagram_public_fallback(job,url):
    # Public-only fallback: use Instagram's public embed page and explicit video metadata.
    headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml","Accept-Language":"en-US,en;q=0.9","Referer":"https://www.instagram.com/"}
    candidates=[url.rstrip("/")+"/embed/", url]
    for target in candidates:
        try:
            r=requests.get(target,headers=headers,timeout=(15,30),allow_redirects=True)
            if r.status_code==429: continue
            r.raise_for_status()
            html=r.text
            pats=[
                r'<meta[^>]+property=["\']og:video(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video(?::secure_url)?["\']',
                r'"video_url"\s*:\s*"([^"]+)"',
                r'"contentUrl"\s*:\s*"([^"]+)"',
            ]
            media=None
            for pat in pats:
                m=re.search(pat,html,re.I)
                if m:
                    media=unescape(m.group(1)).replace("\\u0026","&").replace("\\/","/")
                    break
            if not media or not media.startswith(("http://","https://")): continue
            out=WORK/f"{job}.mp4"
            with requests.get(media,headers={"User-Agent":UA,"Referer":"https://www.instagram.com/"},stream=True,timeout=(15,90)) as mr:
                mr.raise_for_status()
                total=0
                with open(out,"wb") as fh:
                    for chunk in mr.iter_content(1024*256):
                        if not chunk: continue
                        total+=len(chunk)
                        if total>int(setting_get("max_file_mb") or "300")*1024*1024:
                            raise RuntimeError("Instagram media exceeds the configured file size limit")
                        fh.write(chunk)
            if total:
                title="Instagram Video"
                tm=re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',html,re.I)
                if tm: title=unescape(tm.group(1))[:180]
                im=re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',html,re.I)
                thumb=unescape(im.group(1)).replace("&amp;","&") if im else None
                return {"title":title,"thumbnail":thumb,"extractor":"instagram-public-embed"}
        except Exception as e:
            log.info("instagram fallback %s: %s",target,e)
    return None

def cobalt_fallback(job,url,kind):
    if not setting_bool("cobalt_enabled"): return None
    endpoint=setting_get("cobalt_api_url").strip()
    if not endpoint: return None
    try:
        payload={"url":url,"downloadMode":"audio" if kind=="audio" else "auto","filenameStyle":"pretty"}
        r=requests.post(endpoint.rstrip("/"),json=payload,headers={"User-Agent":UA,"Accept":"application/json"},timeout=(20,45))
        r.raise_for_status(); data=r.json()
        direct=data.get("url")
        if not direct: return None
        out=WORK/f"{job}.mp4"
        with requests.get(direct,headers={"User-Agent":UA},stream=True,timeout=(20,120)) as mr:
            mr.raise_for_status(); total=0
            with open(out,"wb") as fh:
                for chunk in mr.iter_content(1024*256):
                    if not chunk: continue
                    total+=len(chunk)
                    if total>int(setting_get("max_file_mb") or "300")*1024*1024: raise RuntimeError("File exceeds limit")
                    fh.write(chunk)
        if not total: return None
        return {"title":data.get("filename") or "Media","thumbnail":None,"extractor":"cobalt"}
    except Exception as e:
        log.warning("cobalt fallback failed: %s",e)
        return None

def process(job,kind):
    clean_job(job)
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job))
        if not row: return
        url=row.url
    finally: db.close()
    p=platform(url)
    try:
        attempts=[None]
        if p=="youtube": attempts += ["web_embedded","mweb"]
        last=None; info=None; used=None
        for client in attempts:
            try:
                clean_job(job)
                with yt_dlp.YoutubeDL(ytdlp_options(job,kind,client)) as ydl:
                    info=ydl.extract_info(url,download=True)
                used="yt-dlp"+(f"/{client}" if client else "")
                break
            except Exception as e:
                last=e
                if p=="youtube" and client is None and youtube_fallback_needed(e): continue
                if p=="instagram":
                    clean_job(job)
                    fb=instagram_public_fallback(job,url)
                    if fb: info=fb; used=fb["extractor"]; break
                break
        if info is None:
            fb=cobalt_fallback(job,url,kind)
            if fb: info=fb; used=fb["extractor"]
        if info is None: raise last or RuntimeError("No media was returned by the extractors")
        files=[f for f in WORK.glob(f"{job}.*") if f.is_file() and f.suffix not in {".part",".ytdl"}]
        if not files: raise RuntimeError("No media file was created")
        media=max(files,key=lambda f:f.stat().st_size)
        if media.stat().st_size<1: raise RuntimeError("Downloaded file is empty")
        ctype=mimetypes.guess_type(media.name)[0] or ("audio/mpeg" if kind=="audio" else "video/mp4")
        title=re.sub(r"\s+"," ",str(info.get("title") or "Media")).strip()[:180]
        thumb=info.get("thumbnail")
        duration=int(info.get("duration")) if str(info.get("duration","")).isdigit() else None
        size=media.stat().st_size
        db=Session()
        try:
            db.execute(update(Download).where(Download.job_id==job).values(
                title=title,thumbnail=thumb,filename=media.name,content_type=ctype,
                status="completed",error=None,extractor=used,duration=duration,filesize=size))
            db.commit()
        finally: db.close()
    except Exception as e:
        log.exception("job=%s failed",job)
        db=Session()
        try:
            db.execute(update(Download).where(Download.job_id==job).values(status="failed",error=human_error(e)))
            db.commit()
        finally: db.close()
        clean_job(job)

def claim_one():
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.status=="queued").order_by(Download.id).limit(1))
        if not row: return None
        q=db.execute(update(Download).where(Download.job_id==row.job_id,Download.status=="queued").values(status="downloading",error=None))
        if q.rowcount!=1: db.rollback(); return None
        db.commit(); return row.job_id,row.kind
    finally: db.close()

def recover_stuck():
    db=Session()
    try:
        db.execute(update(Download).where(Download.status=="downloading").values(status="queued",error=None)); db.commit()
    finally: db.close()

def cleanup_old():
    hours=float(setting_get("keep_file_hours") or "6")
    cutoff=time.time()-hours*3600
    for f in WORK.iterdir():
        if f.is_file() and f.suffix not in {".part",".ytdl"}:
            try:
                if f.stat().st_mtime<cutoff: f.unlink()
            except OSError: pass

def worker_loop():
    recover_stuck(); last=0
    while True:
        try:
            if time.time()-last>600: cleanup_old(); last=time.time()
            item=claim_one()
            if item: process(*item)
            else: time.sleep(float(setting_get("worker_poll_seconds") or "0.7"))
        except Exception:
            log.exception("worker loop"); time.sleep(2)

@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=worker_loop,daemon=True,name="quickdl-worker").start()
    yield

app=FastAPI(title="QuickDL",version="10.0.0",lifespan=lifespan)

@app.get("/")
def home():
    if setting_bool("maintenance"): return FileResponse(BASE/"templates"/"maintenance.html")
    return FileResponse(BASE/"templates"/"index.html")

@app.get("/static/{path:path}")
def static_file(path): return FileResponse(BASE/"static"/path)

@app.get("/admin18",response_class=HTMLResponse)
def admin18(request:Request):
    return FileResponse(BASE/"templates"/("admin.html" if admin_ok(request) else "admin_login.html"))

@app.get("/api/health")
def health():
    db=Session()
    try:
        db.execute(select(Download.id).limit(1))
        return {"ok":True,"service":"quickdl","version":"10.0.0","worker":"running","platforms":["youtube","tiktok","instagram","facebook","pinterest","x","snapchat","web"]}
    finally: db.close()

@app.get("/api/public-config")
def public_config():
    return {"announcement_enabled":setting_bool("announcement_enabled"),"announcement":setting_get("announcement"),"maintenance":setting_bool("maintenance")}

class DownloadRequest(BaseModel):
    url: HttpUrl
    kind: str="video"

def serialize(r):
    f=WORK/r.filename if r.filename else None
    ready=r.status=="completed" and f is not None and f.exists()
    status="completed" if ready else ("expired" if r.status=="completed" else r.status)
    return {"job_id":r.job_id,"title":r.title,"status":status,"kind":r.kind,"thumbnail":r.thumbnail,"url":r.url,
            "platform":platform(r.url),"created_at":r.created_at.isoformat() if r.created_at else None,
            "download_url":f"/api/file/{r.job_id}" if ready else None,"preview_url":f"/api/file/{r.job_id}" if ready else None,
            "content_type":r.content_type,"error":r.error if status!="expired" else "This file is no longer stored on the server.",
            "extractor":r.extractor,"duration":r.duration,"filesize":r.filesize}

@app.post("/api/download")
def create_download(req:DownloadRequest,vexdou_visitor:str|None=Cookie(default=None)):
    if setting_bool("maintenance"): raise HTTPException(503,setting_get("maintenance_message"))
    if not setting_bool("downloads_enabled"): raise HTTPException(503,"Downloads are temporarily disabled.")
    url,kind=str(req.url).strip(),req.kind.lower().strip()
    if kind=="audio" and not setting_bool("allow_audio"): raise HTTPException(503,"Audio downloads are disabled.")
    p=platform(url)
    if not setting_bool(f"{p}_enabled"): raise HTTPException(503,f"{p.title()} downloads are disabled.")
    if kind not in {"video","audio"}: raise HTTPException(400,"Invalid download type")
    if not allowed(url): raise HTTPException(400,"Please enter a valid public HTTP/HTTPS URL")
    visitor=vexdou_visitor or uuid.uuid4().hex
    job=uuid.uuid4().hex
    db=Session()
    try:
        db.add(Download(job_id=job,visitor_id=visitor,url=url,title="Preparing…",status="queued",kind=kind)); db.commit()
    finally: db.close()
    out=JSONResponse({"ok":True,"job_id":job,"status":"queued","platform":p,"kind":kind})
    if not vexdou_visitor: out.set_cookie("vexdou_visitor",visitor,max_age=31536000,httponly=True,samesite="lax",secure=True)
    return out

@app.get("/api/download/{job}")
def get_download(job:str,vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(404,"Download not found")
    db=Session()
    try:
        r=db.scalar(select(Download).where(Download.job_id==job,Download.visitor_id==vexdou_visitor))
        if not r: raise HTTPException(404,"Download not found")
        return serialize(r)
    finally: db.close()

@app.get("/api/history")
def history(vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor:return {"items":[]}
    db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.visitor_id==vexdou_visitor,Download.status=="completed").order_by(Download.created_at.desc()).limit(100)).all()
        return {"items":[serialize(r) for r in rows if serialize(r)["status"]=="completed"]}
    finally: db.close()

@app.delete("/api/history")
def clear_history(vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor:return {"ok":True}
    db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.visitor_id==vexdou_visitor)).all()
        for r in rows: clean_job(r.job_id)
        db.execute(delete(Download).where(Download.visitor_id==vexdou_visitor)); db.commit(); return {"ok":True}
    finally: db.close()

@app.get("/api/file/{job}")
def file(job:str,vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(404,"File not found")
    db=Session()
    try:
        r=db.scalar(select(Download).where(Download.job_id==job,Download.visitor_id==vexdou_visitor,Download.status=="completed"))
        if not r or not r.filename: raise HTTPException(404,"File not found")
        p=WORK/r.filename
        if not p.exists(): raise HTTPException(410,"File expired")
        return FileResponse(p,media_type=r.content_type or "application/octet-stream",filename=p.name,headers={"Accept-Ranges":"bytes","Cache-Control":"private,max-age=3600"})
    finally: db.close()

def sign_admin(value):
    sig=hmac.new(ADMIN_SESSION_SECRET.encode(),value.encode(),hashlib.sha256).digest()
    return value+"."+base64.urlsafe_b64encode(sig).decode().rstrip("=")

def admin_ok(request):
    c=request.cookies.get(ADMIN_COOKIE)
    if not c or not ADMIN_SESSION_SECRET:return False
    try:
        value,sig=c.rsplit(".",1); exp=hmac.new(ADMIN_SESSION_SECRET.encode(),value.encode(),hashlib.sha256).digest()
        got=base64.urlsafe_b64decode(sig+"="*(-len(sig)%4))
        return hmac.compare_digest(exp,got) and time.time()-int(value)<12*3600
    except Exception:return False

def require_admin(request):
    if not ADMIN_PASSWORD or not ADMIN_SESSION_SECRET: raise HTTPException(503,"Set ADMIN_PASSWORD and ADMIN_SESSION_SECRET.")
    if not admin_ok(request): raise HTTPException(401,"Admin authentication required")

class Login(BaseModel): password:str
class SettingUpdate(BaseModel): settings:dict[str,str]
class AdminAction(BaseModel): action:str

@app.post("/api/admin/login")
def admin_login(data:Login):
    if not ADMIN_PASSWORD or not ADMIN_SESSION_SECRET: raise HTTPException(503,"Admin authentication is not configured.")
    if not hmac.compare_digest(data.password,ADMIN_PASSWORD):
        audit("admin_login_failed","Invalid password"); raise HTTPException(401,"Invalid admin password")
    out=JSONResponse({"ok":True}); out.set_cookie(ADMIN_COOKIE,sign_admin(str(int(time.time()))),max_age=43200,httponly=True,secure=True,samesite="strict",path="/")
    audit("admin_login","Admin session started"); return out

@app.post("/api/admin/logout")
def admin_logout(request:Request):
    require_admin(request); out=JSONResponse({"ok":True}); out.delete_cookie(ADMIN_COOKIE,path="/"); audit("admin_logout","Session ended"); return out

@app.get("/api/admin/overview")
def admin_overview(request:Request):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(Download)).all(); now=datetime.now(timezone.utc)
        today=sum(1 for r in rows if r.created_at and (now-r.created_at).total_seconds()<86400)
        week=sum(1 for r in rows if r.created_at and (now-r.created_at).total_seconds()<604800)
        status={}; plats={}; extractors={}
        for r in rows:
            status[r.status]=status.get(r.status,0)+1; p=platform(r.url); plats[p]=plats.get(p,0)+1
            if r.extractor: extractors[r.extractor]=extractors.get(r.extractor,0)+1
        users=len({r.visitor_id for r in rows})
        return {"version":"10.0.0","users":users,"downloads":len(rows),"today":today,"week":week,
                "completed":status.get("completed",0),"failed":status.get("failed",0),
                "queued":status.get("queued",0),"downloading":status.get("downloading",0),
                "platforms":plats,"extractors":extractors,"settings":settings_all(),"worker":"running"}
    finally: db.close()

@app.get("/api/admin/users")
def admin_users(request:Request,limit:int=300):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(Download).order_by(Download.created_at.desc())).all(); groups={}
        for r in rows:
            g=groups.setdefault(r.visitor_id,{"visitor_id":r.visitor_id,"first_seen":r.created_at,"last_seen":r.created_at,"downloads":0,"completed":0,"failed":0})
            g["downloads"]+=1; g["completed"]+=int(r.status=="completed"); g["failed"]+=int(r.status=="failed")
            if r.created_at and r.created_at<g["first_seen"]:g["first_seen"]=r.created_at
            if r.created_at and r.created_at>g["last_seen"]:g["last_seen"]=r.created_at
        items=list(groups.values())[:max(1,min(limit,500))]
        for x in items:
            x["first_seen"]=x["first_seen"].isoformat() if x["first_seen"] else None;x["last_seen"]=x["last_seen"].isoformat() if x["last_seen"] else None
        return {"items":items}
    finally: db.close()

@app.get("/api/admin/downloads")
def admin_downloads(request:Request,status:str="",limit:int=300):
    require_admin(request); db=Session()
    try:
        q=select(Download).order_by(Download.created_at.desc()).limit(max(1,min(limit,500)))
        if status:q=select(Download).where(Download.status==status).order_by(Download.created_at.desc()).limit(max(1,min(limit,500)))
        return {"items":[{"job_id":r.job_id,"visitor_id":r.visitor_id,"title":r.title,"url":r.url,"platform":platform(r.url),"kind":r.kind,"status":r.status,"error":r.error,"extractor":r.extractor,"filesize":r.filesize,"created_at":r.created_at.isoformat() if r.created_at else None} for r in db.scalars(q).all()]}
    finally: db.close()

@app.get("/api/admin/errors")
def admin_errors(request:Request,limit:int=300):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.status=="failed").order_by(Download.created_at.desc()).limit(max(1,min(limit,500)))).all()
        return {"items":[{"job_id":r.job_id,"platform":platform(r.url),"error":r.error or "Unknown error","url":r.url,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

@app.get("/api/admin/audit")
def admin_audit(request:Request,limit:int=300):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(max(1,min(limit,500)))).all()
        return {"items":[{"action":r.action,"detail":r.detail,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

@app.post("/api/admin/settings")
def admin_settings(data:SettingUpdate,request:Request):
    require_admin(request); allowed_keys=set(DEFAULTS); db=Session(); changed=[]
    try:
        for k,v in data.settings.items():
            if k not in allowed_keys: continue
            v=str(v)[:4000]; row=db.get(AdminSetting,k)
            if row: row.value=v; row.updated_at=datetime.now(timezone.utc)
            else: db.add(AdminSetting(key=k,value=v))
            changed.append(k)
        db.commit(); audit("settings_updated",", ".join(changed)); return {"ok":True,"settings":settings_all()}
    finally: db.close()

@app.post("/api/admin/action")
def admin_action(data:AdminAction,request:Request):
    require_admin(request)
    db=Session()
    try:
        if data.action=="clear_failed": rows=db.scalars(select(Download).where(Download.status=="failed")).all()
        elif data.action=="clear_completed": rows=db.scalars(select(Download).where(Download.status=="completed")).all()
        elif data.action=="clear_all": rows=db.scalars(select(Download)).all()
        elif data.action=="requeue_failed": rows=db.scalars(select(Download).where(Download.status=="failed")).all()
        else: raise HTTPException(400,"Unknown action")
        for r in rows:
            if data.action=="requeue_failed":
                clean_job(r.job_id); r.status="queued"; r.error=None; r.filename=None; r.content_type=None
            else: clean_job(r.job_id)
        if data.action=="clear_failed": db.execute(delete(Download).where(Download.status=="failed"))
        elif data.action=="clear_completed": db.execute(delete(Download).where(Download.status=="completed"))
        elif data.action=="clear_all": db.execute(delete(Download))
        db.commit(); audit("admin_action",data.action); return {"ok":True,"affected":len(rows)}
    finally: db.close()
