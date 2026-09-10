import os, re, time, uuid, mimetypes, logging, threading, ipaddress, socket, json, hashlib, hmac, base64
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp, requests, stripe
from html import unescape
from fastapi import FastAPI, HTTPException, Cookie, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, String, Text, Integer, DateTime, Boolean, select, update, delete, func, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log=logging.getLogger("quickdl")
BASE=Path(__file__).resolve().parent
WORK=Path(os.getenv("WORK_DIR","/tmp/quickdl")); WORK.mkdir(parents=True,exist_ok=True)
DB_URL=os.getenv("DATABASE_URL","").strip()
if not DB_URL: raise RuntimeError("DATABASE_URL is required")
if DB_URL.startswith("postgres://"): DB_URL=DB_URL.replace("postgres://","postgresql+psycopg2://",1)
elif DB_URL.startswith("postgresql://"): DB_URL=DB_URL.replace("postgresql://","postgresql+psycopg2://",1)
engine=create_engine(DB_URL,pool_pre_ping=True,pool_recycle=300,pool_size=3,max_overflow=2)
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
    credit_cost:Mapped[int]=mapped_column(Integer,default=2)
    credit_refunded:Mapped[bool]=mapped_column(Boolean,default=False)

class CreditAccount(Base):
    __tablename__="credit_accounts"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    visitor_id:Mapped[str]=mapped_column(String(128),unique=True,index=True)
    balance:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class CreditTransaction(Base):
    __tablename__="credit_transactions"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    visitor_id:Mapped[str]=mapped_column(String(128),index=True)
    amount:Mapped[int]=mapped_column(Integer)
    type:Mapped[str]=mapped_column(String(50),index=True)
    description:Mapped[str]=mapped_column(Text,default="")
    job_id:Mapped[str|None]=mapped_column(String(64),nullable=True,index=True)
    stripe_session_id:Mapped[str|None]=mapped_column(String(255),nullable=True,index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),index=True)
    __table_args__=(UniqueConstraint("stripe_session_id",name="uq_credit_stripe_session"),)

class AdminSetting(Base):
    __tablename__="admin_settings"
    key:Mapped[str]=mapped_column(String(80),primary_key=True)
    value:Mapped[str]=mapped_column(Text,default="")
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class AdminAudit(Base):
    __tablename__="admin_audit"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    action:Mapped[str]=mapped_column(String(160))
    detail:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),index=True)

Base.metadata.create_all(engine)

def ensure_additive_schema():
    # Safe additive migration for existing PostgreSQL installations.
    from sqlalchemy import text
    with engine.begin() as c:
        try: c.execute(text("ALTER TABLE downloads ADD COLUMN IF NOT EXISTS credit_cost INTEGER NOT NULL DEFAULT 2"))
        except Exception as e: log.warning("credit_cost migration: %s",e)
        try: c.execute(text("ALTER TABLE downloads ADD COLUMN IF NOT EXISTS credit_refunded BOOLEAN NOT NULL DEFAULT FALSE"))
        except Exception as e: log.warning("credit_refunded migration: %s",e)
ensure_additive_schema()

UA=os.getenv("DOWNLOADER_USER_AGENT","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36")
MAX_FILE_MB=int(os.getenv("MAX_FILE_MB","300")); KEEP_FILE_HOURS=float(os.getenv("KEEP_FILE_HOURS","6"))
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","").strip(); ADMIN_SESSION_SECRET=os.getenv("ADMIN_SESSION_SECRET","").strip(); ADMIN_COOKIE="quickdl_admin"
STRIPE_SECRET_KEY=os.getenv("STRIPE_SECRET_KEY","").strip(); STRIPE_WEBHOOK_SECRET=os.getenv("STRIPE_WEBHOOK_SECRET","").strip(); PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL","https://quickdl.site").rstrip("/")
if STRIPE_SECRET_KEY: stripe.api_key=STRIPE_SECRET_KEY

DEFAULT_SETTINGS={"maintenance":"false","maintenance_message":"QuickDL is temporarily under maintenance. Please try again shortly.","announcement_enabled":"false","announcement":"","max_file_mb":str(MAX_FILE_MB),"keep_file_hours":str(KEEP_FILE_HOURS),"downloads_enabled":"true","youtube_enabled":"true","tiktok_enabled":"true","instagram_enabled":"true","facebook_enabled":"true","pinterest_enabled":"true","x_enabled":"true","web_enabled":"true","credits_enabled":os.getenv("CREDITS_ENABLED","true"),"free_credits":os.getenv("FREE_CREDITS","100"),"download_credit_cost":os.getenv("DOWNLOAD_CREDIT_COST","2"),"starter_credits":"100","starter_amount_cents":"100","plus_credits":"550","plus_amount_cents":"500","pro_credits":"1200","pro_amount_cents":"1000"}

def setting_get(key):
    db=Session()
    try:
        row=db.get(AdminSetting,key); return row.value if row else DEFAULT_SETTINGS.get(key,"")
    finally: db.close()
def setting_bool(key): return setting_get(key).lower() in {"1","true","yes","on"}
def settings_all():
    db=Session()
    try:
        v=dict(DEFAULT_SETTINGS)
        for r in db.scalars(select(AdminSetting)).all(): v[r.key]=r.value
        return v
    finally: db.close()
def audit(action,detail=""):
    db=Session()
    try: db.add(AdminAudit(action=action,detail=str(detail)[:1000])); db.commit()
    finally: db.close()

def package_list():
    raw=os.getenv("CREDIT_PACKAGES_JSON","").strip()
    if raw:
        try:
            arr=json.loads(raw)
            if isinstance(arr,list): return arr
        except Exception: pass
    s=settings_all()
    return [{"id":"starter","name":"Starter","credits":int(s["starter_credits"]),"amount_cents":int(s["starter_amount_cents"])},{"id":"plus","name":"Plus","credits":int(s["plus_credits"]),"amount_cents":int(s["plus_amount_cents"])},{"id":"pro","name":"Pro","credits":int(s["pro_credits"]),"amount_cents":int(s["pro_amount_cents"])}]
def get_package(pid):
    return next((p for p in package_list() if str(p.get("id"))==str(pid)),None)

def account_for(visitor,free_if_new=True,db=None):
    own=db is None; db=db or Session()
    try:
        acct=db.scalar(select(CreditAccount).where(CreditAccount.visitor_id==visitor).with_for_update())
        if not acct:
            free=int(setting_get("free_credits") or 100) if free_if_new else 0
            acct=CreditAccount(visitor_id=visitor,balance=free); db.add(acct); db.flush()
            if free: db.add(CreditTransaction(visitor_id=visitor,amount=free,type="free_grant",description="New user free credits"))
            db.commit()
        return acct
    finally:
        if own: db.close()

def credit_balance(visitor):
    db=Session()
    try:
        acct=db.scalar(select(CreditAccount).where(CreditAccount.visitor_id==visitor))
        return acct.balance if acct else int(setting_get("free_credits") or 100)
    finally: db.close()

def charge_credits(visitor,cost,job_id):
    db=Session()
    try:
        acct=db.scalar(select(CreditAccount).where(CreditAccount.visitor_id==visitor).with_for_update())
        if not acct:
            free=int(setting_get("free_credits") or 100); acct=CreditAccount(visitor_id=visitor,balance=free); db.add(acct); db.flush()
            if free: db.add(CreditTransaction(visitor_id=visitor,amount=free,type="free_grant",description="New user free credits"))
        if acct.balance<cost: db.rollback(); return False,acct.balance
        acct.balance-=cost; acct.updated_at=datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=visitor,amount=-cost,type="download_charge",description=f"Download charge: {cost} credits",job_id=job_id)); db.commit()
        return True,acct.balance
    finally: db.close()
def refund_credits(visitor,cost,job_id):
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job_id).with_for_update())
        if not row or row.credit_refunded: return
        acct=db.scalar(select(CreditAccount).where(CreditAccount.visitor_id==visitor).with_for_update())
        if not acct: return
        acct.balance+=cost; acct.updated_at=datetime.now(timezone.utc); row.credit_refunded=True
        db.add(CreditTransaction(visitor_id=visitor,amount=cost,type="download_refund",description=f"Refund for failed download: {cost} credits",job_id=job_id)); db.commit()
    finally: db.close()

def hostname(url): return (urlparse(url).hostname or "").lower().rstrip(".")
def platform(url):
    h=hostname(url)
    if "youtube" in h or h=="youtu.be": return "youtube"
    if "tiktok" in h:return "tiktok"
    if "instagram" in h or h=="instagr.am":return "instagram"
    if "facebook" in h or h in {"fb.watch","fb.me"}:return "facebook"
    if "pinterest" in h or h=="pin.it":return "pinterest"
    if h in {"x.com","twitter.com"}:return "x"
    return "web"
def public_host(h):
    if not h or h in {"localhost","localhost.localdomain"} or h.endswith((".local",".internal",".localhost")): return False
    try:
        infos=socket.getaddrinfo(h,None,type=socket.SOCK_STREAM)
        return bool(infos) and all(not (a:=ipaddress.ip_address(i[4][0])).is_private and not a.is_loopback and not a.is_link_local and not a.is_multicast and not a.is_reserved and not a.is_unspecified for i in infos)
    except Exception:return True
def allowed(url):
    try:
        p=urlparse(url); return p.scheme in {"http","https"} and bool(p.hostname) and public_host(hostname(url))
    except:return False

def human_error(exc):
    text=re.sub(r"\s+"," ",str(exc)).strip(); low=text.lower()
    for marker,msg in [("sign in","This media requires sign-in or authorization."),("login required","This media requires sign-in or authorization."),("authentication","This media requires sign-in or authorization."),("private","This media is private or unavailable to the downloader."),("drm","This media is DRM-protected and cannot be downloaded."),("429","The source temporarily rate-limited this server. Please try again later."),("403","The source refused automated access to this media."),("unsupported url","This URL is not supported by the media extractor."),("timeout","The source took too long to respond. Please try again.")]:
        if marker in low:return msg
    return text[:700] or "Download failed. Please try another media URL."
def ytdlp_options(job,kind,youtube_embedded=False):
    opts={"outtmpl":str(WORK/f"{job}.%(ext)s"),"noplaylist":True,"quiet":True,"no_warnings":True,"retries":3,"fragment_retries":3,"file_access_retries":2,"socket_timeout":45,"concurrent_fragment_downloads":1,"skip_unavailable_fragments":True,"restrictfilenames":True,"windowsfilenames":True,"http_headers":{"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"},"format":"bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" if kind=="video" else "ba/b","merge_output_format":"mp4" if kind=="video" else None,"max_filesize":int(setting_get("max_file_mb") or MAX_FILE_MB)*1024*1024,"js_runtimes":{"node":{}}}
    if youtube_embedded: opts["extractor_args"]={"youtube":{"player_client":["web_embedded"]}}
    if kind=="audio": opts["postprocessors"]=[{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]
    return {k:v for k,v in opts.items() if v is not None}
def youtube_needs_fallback(exc): return any(x in str(exc).lower() for x in ("sign in to confirm","requires sign-in","login required","authentication required","confirm you're not a bot","http error 403","forbidden"))
def cleanup_job(job):
    for f in WORK.glob(f"{job}.*"):
        try:f.unlink()
        except OSError:pass

def mark_failed(job,error):
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job));
        if row:
            row.status="failed"; row.error=human_error(error); db.commit(); refund_credits(row.visitor_id,row.credit_cost,row.job_id)
    finally:db.close()

def process(job,kind):
    cleanup_job(job); db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job));
        if not row:return
        url=row.url
    finally:db.close()
    try:
        attempts=[ytdlp_options(job,kind)]
        if platform(url)=="youtube": attempts.append(ytdlp_options(job,kind,True))
        info=None; last=None
        for n,opts in enumerate(attempts):
            try:
                cleanup_job(job)
                with yt_dlp.YoutubeDL(opts) as ydl: info=ydl.extract_info(url,download=True)
                break
            except Exception as exc:
                last=exc
                if n==0 and platform(url)=="youtube" and youtube_needs_fallback(exc): continue
                raise
        if info is None:raise last or RuntimeError("No media information was returned")
        files=[f for f in WORK.glob(f"{job}.*") if f.is_file() and f.suffix not in {".part",".ytdl"}]
        if not files:raise RuntimeError("No media file was created")
        media=max(files,key=lambda f:f.stat().st_size)
        if media.stat().st_size<1:raise RuntimeError("Downloaded file is empty")
        db=Session(); row=db.scalar(select(Download).where(Download.job_id==job)); row.title=re.sub(r"\s+"," ",info.get("title") or "Media").strip()[:180]; row.thumbnail=info.get("thumbnail"); row.filename=media.name; row.content_type=mimetypes.guess_type(media.name)[0] or ("audio/mpeg" if kind=="audio" else "video/mp4"); row.status="completed"; row.error=None; db.commit(); db.close()
    except Exception as exc:
        log.exception("job=%s failed",job); mark_failed(job,exc); cleanup_job(job)

def claim_one():
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.status=="queued").order_by(Download.id).limit(1))
        if not row:return None
        r=db.execute(update(Download).where(Download.job_id==row.job_id,Download.status=="queued").values(status="downloading",error=None))
        if r.rowcount!=1:db.rollback();return None
        db.commit();return row.job_id,row.kind
    finally:db.close()
def recover_stuck():
    db=Session()
    try:db.execute(update(Download).where(Download.status=="downloading").values(status="queued",error=None));db.commit()
    finally:db.close()
def cleanup_old():
    cutoff=time.time()-float(setting_get("keep_file_hours") or KEEP_FILE_HOURS)*3600
    for f in WORK.iterdir():
        if not f.is_file() or f.suffix in {".part",".ytdl"}:continue
        try:
            if f.stat().st_mtime<cutoff:f.unlink()
        except OSError:pass
def worker_loop():
    recover_stuck();last=0
    while True:
        try:
            if time.time()-last>600:cleanup_old();last=time.time()
            item=claim_one(); process(*item) if item else time.sleep(.7)
        except Exception:log.exception("worker error");time.sleep(2)

@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=worker_loop,daemon=True,name="quickdl-worker").start();yield
app=FastAPI(title="QuickDL",version="10.0.0",lifespan=lifespan)

@app.get("/")
def home(): return FileResponse(BASE/"templates"/("maintenance.html" if setting_bool("maintenance") else "index.html"))
@app.get("/static/{path:path}")
def static_file(path:str):return FileResponse(BASE/"static"/path)
@app.get("/api/health")
def health():return {"ok":True,"service":"quickdl","version":"10.0.0"}
@app.get("/api/public-config")
def public_config():return {"announcement_enabled":setting_bool("announcement_enabled"),"announcement":setting_get("announcement"),"maintenance":setting_bool("maintenance"),"credits_enabled":setting_bool("credits_enabled"),"download_cost":int(setting_get("download_credit_cost") or 2)}

class DownloadRequest(BaseModel):url:HttpUrl;kind:str="video"
class CheckoutRequest(BaseModel):package_id:str
class AdminLogin(BaseModel):password:str
class AdminSettingUpdate(BaseModel):settings:dict[str,str]
class AdminAction(BaseModel):action:str;value:str|None=None
class CreditAdjust(BaseModel):visitor_id:str;amount:int;description:str="Admin adjustment"

def serialize(row):
    f=WORK/row.filename if row.filename else None;ready=row.status=="completed" and f is not None and f.exists();status="completed" if ready else ("expired" if row.status=="completed" else row.status)
    return {"job_id":row.job_id,"title":row.title,"status":status,"kind":row.kind,"thumbnail":row.thumbnail,"url":row.url,"platform":platform(row.url),"created_at":row.created_at.isoformat() if row.created_at else None,"download_url":f"/api/file/{row.job_id}" if ready else None,"preview_url":f"/api/file/{row.job_id}" if ready else None,"content_type":row.content_type,"error":row.error if status!="expired" else "This file is no longer stored on the server."}

@app.get("/api/credits")
def credits(vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor:return {"balance":0,"cost":int(setting_get("download_credit_cost") or 2),"packages":package_list()}
    return {"balance":credit_balance(vexdou_visitor),"cost":int(setting_get("download_credit_cost") or 2),"packages":package_list()}
@app.post("/api/credits/checkout")
def checkout(data:CheckoutRequest,vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(400,"Please enable cookies and try again.")
    if not setting_bool("credits_enabled"):raise HTTPException(503,"Credits are temporarily disabled.")
    if not STRIPE_SECRET_KEY:raise HTTPException(503,"Stripe payments are not configured.")
    p=get_package(data.package_id)
    if not p or int(p.get("credits",0))<1 or int(p.get("amount_cents",0))<1:raise HTTPException(400,"Invalid credit package")
    try:
        s=stripe.checkout.Session.create(mode="payment",line_items=[{"price_data":{"currency":"usd","product_data":{"name":f"QuickDL {p['name']} Credits"},"unit_amount":int(p["amount_cents"])},"quantity":1}],success_url=f"{PUBLIC_BASE_URL}/?credits=success",cancel_url=f"{PUBLIC_BASE_URL}/?credits=cancelled",metadata={"visitor_id":vexdou_visitor,"credits":str(int(p["credits"])),"package_id":str(p["id"]),"amount_cents":str(int(p["amount_cents"]))},client_reference_id=vexdou_visitor)
        audit("stripe_checkout_created",f"package={p['id']} credits={p['credits']}")
        return {"ok":True,"url":s.url}
    except Exception as e:raise HTTPException(502,f"Stripe checkout could not be created: {e}")

@app.post("/api/stripe/webhook")
async def stripe_webhook(request:Request):
    if not STRIPE_WEBHOOK_SECRET:raise HTTPException(503,"Stripe webhook is not configured.")
    payload=await request.body(); sig=request.headers.get("stripe-signature","")
    try:event=stripe.Webhook.construct_event(payload,sig,STRIPE_WEBHOOK_SECRET)
    except Exception as e:raise HTTPException(400,f"Invalid Stripe webhook: {e}")
    if event["type"] not in {"checkout.session.completed","checkout.session.async_payment_succeeded"}:return {"received":True}
    session_obj=event["data"]["object"]; session_id=session_obj.get("id")
    if event["type"]=="checkout.session.completed" and session_obj.get("payment_status") not in {"paid","no_payment_required"}:return {"received":True}
    meta=session_obj.get("metadata") or {}; visitor=meta.get("visitor_id"); credits=int(meta.get("credits","0") or 0)
    if not visitor or credits<1:return {"received":True}
    db=Session()
    try:
        existing=db.scalar(select(CreditTransaction).where(CreditTransaction.stripe_session_id==session_id))
        if existing:return {"received":True,"duplicate":True}
        acct=db.scalar(select(CreditAccount).where(CreditAccount.visitor_id==visitor).with_for_update())
        if not acct:acct=CreditAccount(visitor_id=visitor,balance=0);db.add(acct);db.flush()
        acct.balance+=credits;acct.updated_at=datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=visitor,amount=credits,type="stripe_purchase",description=f"Stripe purchase: {meta.get('package_id','credits')} / {credits} credits",stripe_session_id=session_id));db.commit();audit("stripe_credits_granted",f"session={session_id} visitor={visitor} credits={credits}")
        return {"received":True}
    except Exception:
        db.rollback();raise
    finally:db.close()

@app.post("/api/download")
def create_download(req:DownloadRequest,vexdou_visitor:str|None=Cookie(default=None)):
    if setting_bool("maintenance"):raise HTTPException(503,setting_get("maintenance_message"))
    if not setting_bool("downloads_enabled"):raise HTTPException(503,"Downloads are temporarily disabled by QuickDL.")
    url,kind=str(req.url).strip(),req.kind.lower().strip();p=platform(url)
    if not setting_bool(f"{p}_enabled"):raise HTTPException(503,f"{p.title()} downloads are temporarily unavailable.")
    if kind not in {"video","audio"}:raise HTTPException(400,"Invalid download type")
    if not allowed(url):raise HTTPException(400,"Please enter a valid public HTTP/HTTPS URL")
    visitor=vexdou_visitor or uuid.uuid4().hex; job=uuid.uuid4().hex;cost=int(setting_get("download_credit_cost") or 2)
    if setting_bool("credits_enabled"):
        ok,balance=charge_credits(visitor,cost,job)
        if not ok:raise HTTPException(402,f"Not enough credits. You have {balance} credits and need {cost}.")
    db=Session()
    try:
        db.add(Download(job_id=job,visitor_id=visitor,url=url,title="Preparing...",status="queued",kind=kind,credit_cost=cost))
        db.commit()
    except Exception:
        db.rollback()
        if setting_bool("credits_enabled"):
            acct=db.scalar(select(CreditAccount).where(CreditAccount.visitor_id==visitor).with_for_update())
            if acct:
                acct.balance+=cost; acct.updated_at=datetime.now(timezone.utc)
                db.add(CreditTransaction(visitor_id=visitor,amount=cost,type="download_refund",description="Refund because job creation failed",job_id=job))
                db.commit()
        raise
    finally:db.close()
    out=JSONResponse({"ok":True,"job_id":job,"status":"queued","platform":p,"kind":kind,"credit_cost":cost,"credits_remaining":credit_balance(visitor) if setting_bool("credits_enabled") else None})
    if not vexdou_visitor:out.set_cookie("vexdou_visitor",visitor,max_age=31536000,httponly=True,samesite="lax",secure=True)
    return out
@app.get("/api/download/{job}")
def get_download(job:str,vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor:raise HTTPException(404,"Download not found")
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job,Download.visitor_id==vexdou_visitor));
        if not row:raise HTTPException(404,"Download not found")
        return serialize(row)
    finally:db.close()
@app.get("/api/history")
def history(vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor:return {"items":[]}
    db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.visitor_id==vexdou_visitor,Download.status=="completed").order_by(Download.created_at.desc()).limit(100)).all();return {"items":[s for r in rows if (s:=serialize(r))["status"]=="completed"]}
    finally:db.close()
@app.delete("/api/history")
def clear_history(vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor:return {"ok":True}
    db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.visitor_id==vexdou_visitor)).all()
        for r in rows:cleanup_job(r.job_id)
        db.execute(delete(Download).where(Download.visitor_id==vexdou_visitor));db.commit();return {"ok":True}
    finally:db.close()
@app.get("/api/file/{job}")
def file(job:str,vexdou_visitor:str|None=Cookie(default=None)):
    if not vexdou_visitor:raise HTTPException(404,"File not found")
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job,Download.visitor_id==vexdou_visitor,Download.status=="completed"))
        if not row or not row.filename:raise HTTPException(404,"File not found")
        path=WORK/row.filename
        if not path.exists():raise HTTPException(410,"File expired")
        return FileResponse(path,media_type=row.content_type or "application/octet-stream",filename=path.name,headers={"Accept-Ranges":"bytes","Cache-Control":"private,max-age=3600"})
    finally:db.close()

# Admin

def sign_admin(value):
    if not ADMIN_SESSION_SECRET:return ""
    sig=hmac.new(ADMIN_SESSION_SECRET.encode(),value.encode(),hashlib.sha256).digest();return value+"."+base64.urlsafe_b64encode(sig).decode().rstrip("=")
def valid_admin_cookie(cookie):
    if not cookie or not ADMIN_SESSION_SECRET:return False
    try:
        value,sig=cookie.rsplit(".",1);expected=hmac.new(ADMIN_SESSION_SECRET.encode(),value.encode(),hashlib.sha256).digest();supplied=base64.urlsafe_b64decode(sig+"="*(-len(sig)%4));return hmac.compare_digest(expected,supplied) and time.time()-int(value)<43200
    except:return False
def admin_ok(request):return valid_admin_cookie(request.cookies.get(ADMIN_COOKIE))
def require_admin(request):
    if not admin_ok(request):raise HTTPException(401,"Admin authentication required")
@app.get("/admin18",response_class=HTMLResponse)
def admin_page(request:Request):return FileResponse(BASE/"templates"/("admin.html" if admin_ok(request) else "admin_login.html"))
@app.post("/api/admin/login")
def admin_login(data:AdminLogin):
    if not ADMIN_PASSWORD or not ADMIN_SESSION_SECRET:raise HTTPException(503,"Admin authentication is not configured.")
    if not hmac.compare_digest(data.password,ADMIN_PASSWORD):audit("admin_login_failed","Invalid password");raise HTTPException(401,"Invalid admin password")
    out=JSONResponse({"ok":True});out.set_cookie(ADMIN_COOKIE,sign_admin(str(int(time.time()))),max_age=43200,httponly=True,secure=True,samesite="strict",path="/");audit("admin_login","Admin session started");return out
@app.post("/api/admin/logout")
def admin_logout(request:Request):require_admin(request);out=JSONResponse({"ok":True});out.delete_cookie(ADMIN_COOKIE,path="/");audit("admin_logout","Admin session ended");return out
@app.get("/api/admin/overview")
def admin_overview(request:Request):
    require_admin(request);db=Session()
    try:
        rows=db.scalars(select(Download)).all();now=datetime.now(timezone.utc);today=[r for r in rows if r.created_at and (now-r.created_at).total_seconds()<86400];week=[r for r in rows if r.created_at and (now-r.created_at).total_seconds()<604800];status={};plats={}
        for r in rows:status[r.status]=status.get(r.status,0)+1;p=platform(r.url);plats[p]=plats.get(p,0)+1
        users=len({r.visitor_id for r in rows});credits_total=db.scalar(select(func.coalesce(func.sum(CreditAccount.balance),0))) or 0;purchases=db.scalars(select(CreditTransaction).where(CreditTransaction.type=="stripe_purchase")).all();revenue=sum(int((get_package((json.loads(os.getenv("CREDIT_PACKAGES_JSON","[]")) if os.getenv("CREDIT_PACKAGES_JSON") else [{}]) or [{}])[0].get("amount_cents",0)) if False else 0) for _ in [])
        return {"version":"10.0.0","users":users,"downloads":len(rows),"today":len(today),"week":len(week),"completed":status.get("completed",0),"failed":status.get("failed",0),"queued":status.get("queued",0),"downloading":status.get("downloading",0),"platforms":plats,"settings":settings_all(),"worker":"running","credits_balance_total":int(credits_total),"credit_purchase_transactions":len(purchases)}
    finally:db.close()
@app.get("/api/admin/users")
def admin_users(request:Request,limit:int=100):
    require_admin(request);limit=max(1,min(limit,500));db=Session()
    try:
        rows=db.scalars(select(Download).order_by(Download.created_at.desc())).all();groups={}
        for r in rows:
            g=groups.setdefault(r.visitor_id,{"visitor_id":r.visitor_id,"first_seen":r.created_at,"last_seen":r.created_at,"downloads":0,"completed":0,"failed":0})
            g["downloads"]+=1;g["completed"]+=r.status=="completed";g["failed"]+=r.status=="failed"
        accts={a.visitor_id:a.balance for a in db.scalars(select(CreditAccount)).all()}
        for x in groups.values():x["balance"]=accts.get(x["visitor_id"],0);x["first_seen"]=x["first_seen"].isoformat();x["last_seen"]=x["last_seen"].isoformat()
        return {"items":list(groups.values())[:limit]}
    finally:db.close()
@app.get("/api/admin/downloads")
def admin_downloads(request:Request,status:str="",limit:int=200):
    require_admin(request);limit=max(1,min(limit,500));db=Session()
    try:
        q=select(Download).order_by(Download.created_at.desc()).limit(limit)
        if status:q=select(Download).where(Download.status==status).order_by(Download.created_at.desc()).limit(limit)
        return {"items":[{"job_id":r.job_id,"visitor_id":r.visitor_id,"title":r.title,"url":r.url,"platform":platform(r.url),"kind":r.kind,"status":r.status,"error":r.error,"credit_cost":r.credit_cost,"created_at":r.created_at.isoformat()} for r in db.scalars(q).all()]}
    finally:db.close()
@app.get("/api/admin/errors")
def admin_errors(request:Request,limit:int=100):
    require_admin(request);db=Session()
    try:return {"items":[{"job_id":r.job_id,"platform":platform(r.url),"error":r.error or "Unknown error","url":r.url,"created_at":r.created_at.isoformat()} for r in db.scalars(select(Download).where(Download.status=="failed").order_by(Download.created_at.desc()).limit(max(1,min(limit,300)))).all()]}
    finally:db.close()
@app.get("/api/admin/audit")
def admin_audit(request:Request,limit:int=100):
    require_admin(request);db=Session()
    try:return {"items":[{"action":r.action,"detail":r.detail,"created_at":r.created_at.isoformat()} for r in db.scalars(select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(max(1,min(limit,300)))).all()]}
    finally:db.close()
@app.get("/api/admin/credits")
def admin_credits(request:Request,limit:int=200):
    require_admin(request);db=Session()
    try:
        tx=db.scalars(select(CreditTransaction).order_by(CreditTransaction.created_at.desc()).limit(max(1,min(limit,500)))).all();total=db.scalar(select(func.coalesce(func.sum(CreditAccount.balance),0))) or 0;purchased=db.scalar(select(func.coalesce(func.sum(CreditTransaction.amount),0)).where(CreditTransaction.type=="stripe_purchase")) or 0;spent=abs(db.scalar(select(func.coalesce(func.sum(CreditTransaction.amount),0)).where(CreditTransaction.type=="download_charge")))
        return {"total_balance":int(total),"purchased_credits":int(purchased),"spent_credits":int(spent or 0),"transactions":[{"visitor_id":r.visitor_id,"amount":r.amount,"type":r.type,"description":r.description,"job_id":r.job_id,"stripe_session_id":r.stripe_session_id,"created_at":r.created_at.isoformat()} for r in tx],"packages":package_list()}
    finally:db.close()
@app.post("/api/admin/credits/adjust")
def admin_credit_adjust(data:CreditAdjust,request:Request):
    require_admin(request)
    if not data.visitor_id or data.amount==0 or abs(data.amount)>1000000:raise HTTPException(400,"Invalid adjustment")
    db=Session()
    try:
        acct=db.scalar(select(CreditAccount).where(CreditAccount.visitor_id==data.visitor_id).with_for_update())
        if not acct:acct=CreditAccount(visitor_id=data.visitor_id,balance=0);db.add(acct);db.flush()
        if acct.balance+data.amount<0:raise HTTPException(400,"Balance cannot become negative")
        acct.balance+=data.amount;acct.updated_at=datetime.now(timezone.utc);db.add(CreditTransaction(visitor_id=data.visor_id if False else data.visitor_id,amount=data.amount,type="admin_adjustment",description=data.description));db.commit();audit("credit_adjustment",f"visitor={data.visitor_id} amount={data.amount}");return {"ok":True,"balance":acct.balance}
    finally:db.close()
@app.post("/api/admin/settings")
def admin_settings(data:AdminSettingUpdate,request:Request):
    require_admin(request);allowed_keys=set(DEFAULT_SETTINGS);db=Session()
    try:
        changed=[]
        for k,v in data.settings.items():
            if k not in allowed_keys:continue
            row=db.get(AdminSetting,k);v=str(v)[:2000]
            if row:row.value=v;row.updated_at=datetime.now(timezone.utc)
            else:db.add(AdminSetting(key=k,value=v))
            changed.append(k)
        db.commit();audit("settings_updated",", ".join(changed));return {"ok":True,"settings":settings_all()}
    finally:db.close()
@app.post("/api/admin/action")
def admin_action(data:AdminAction,request:Request):
    require_admin(request);actions={"clear_failed","clear_completed","clear_all"}
    if data.action not in actions:raise HTTPException(400,"Unknown action")
    db=Session()
    try:
        if data.action=="clear_failed":rows=db.scalars(select(Download).where(Download.status=="failed")).all()
        elif data.action=="clear_completed":rows=db.scalars(select(Download).where(Download.status=="completed")).all()
        else:rows=db.scalars(select(Download)).all()
        for r in rows:cleanup_job(r.job_id)
        q={"clear_failed":delete(Download).where(Download.status=="failed"),"clear_completed":delete(Download).where(Download.status=="completed"),"clear_all":delete(Download)}[data.action];db.execute(q);db.commit();audit("admin_action",data.action);return {"ok":True,"removed":len(rows)}
    finally:db.close()
