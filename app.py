import os, uuid, time, logging, mimetypes, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import boto3
from botocore.client import Config
import yt_dlp
from fastapi import Cookie, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select, update, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
import threading
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('vexdou-app')

BASE_DIR = Path(__file__).resolve().parent
DB = os.getenv('DATABASE_URL', '').strip()
if DB.startswith('postgres://'): DB = DB.replace('postgres://', 'postgresql+psycopg2://', 1)
if DB.startswith('postgresql://'): DB = DB.replace('postgresql://', 'postgresql+psycopg2://', 1)
if not DB: raise RuntimeError('DATABASE_URL is required in production')

engine = create_engine(DB, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase): pass

class Download(Base):
    __tablename__ = 'downloads'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    visitor_id: Mapped[str] = mapped_column(String(128), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default='Media')
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    kind: Mapped[str] = mapped_column(String(20), default='video')
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(engine)

# --- WORKER ENGINE ---
WORK = Path('/tmp/vexdou')
WORK.mkdir(parents=True, exist_ok=True)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def host(url):
    return (urlparse(url).hostname or '').lower()

def plat(url):
    h = host(url)
    if 'youtube' in h or 'youtu.be' in h: return 'youtube'
    if 'tiktok' in h: return 'tiktok'
    if 'instagram' in h or 'instagr.am' in h: return 'instagram'
    if 'facebook' in h or 'fb.watch' in h or 'fb.me' in h: return 'facebook'
    if 'pinterest' in h or 'pin.it' in h: return 'pinterest'
    return 'x'

def opts(job, kind, p):
    o = {
        'outtmpl': str(WORK / f'{job}.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 3,
        'fragment_retries': 3,
        'socket_timeout': 30,
        'skip_unavailable_fragments': True,
        'restrictfilenames': True,
        'windowsfilenames': True,
        'http_headers': {
            'User-Agent': UA,
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'format': 'best/bestvideo+bestaudio' if kind == 'video' else 'bestaudio/best'
    }
    if p == 'youtube':
        o['extractor_args'] = {'youtube': {'player_client': ['web', 'android']}}
    if kind == 'audio':
        o['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
    return o

def s3():
    return boto3.client('s3', endpoint_url=os.environ['R2_ENDPOINT'], aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name=os.getenv('R2_REGION', 'auto'), config=Config(signature_version='s3v4'))

def cleanup(job):
    for p in WORK.glob(f'{job}.*'):
        try: p.unlink()
        except OSError: pass

def claim():
    db = SessionLocal()
    try:
        x = db.scalar(select(Download).where(Download.status == 'queued').order_by(Download.id).limit(1))
        if not x: 
            return None, None
        job_id = x.job_id
        kind = x.kind
        r = db.execute(update(Download).where(Download.job_id == job_id, Download.status == 'queued').values(status='downloading', error=None))
        if r.rowcount != 1: 
            db.rollback()
            return None, None
        db.commit()
        return job_id, kind
    finally: 
        db.close()

def fail(job, msg):
    db = SessionLocal()
    try:
        clean_msg = str(msg).strip()
        if len(clean_msg) > 250:
            clean_msg = clean_msg[:250] + "..."
        db.execute(update(Download).where(Download.job_id == job).values(status='failed', error=clean_msg))
        db.commit()
    finally:
        db.close()

def process(job_id: str, kind: str):
    cleanup(job_id)
    db = SessionLocal()
    try:
        x = db.scalar(select(Download).where(Download.job_id == job_id))
        if not x: 
            return
        url = x.url
    finally:
        db.close()

    try:
        p = plat(url)
        log.info('Downloading %s from platform %s (URL: %s)', job_id, p, url)
        
        with yt_dlp.YoutubeDL(opts(job_id, kind, p)) as y: 
            info = y.extract_info(url, download=True)
            
        files = [f for f in WORK.glob(f'{job_id}.*') if f.is_file() and f.suffix not in {'.part', '.ytdl'}]
        if not files: 
            raise RuntimeError('No media file was created by downloader.')
        media = max(files, key=lambda f: f.stat().st_size)
        if media.stat().st_size <= 0: 
            raise RuntimeError('Downloaded media file is empty.')
            
        key = f"media/{datetime.now(timezone.utc):%Y/%m/%d}/{uuid.uuid4().hex}{media.suffix.lower()}"
        ctype = mimetypes.guess_type(media.name)[0] or ('audio/mpeg' if kind == 'audio' else 'video/mp4')
        
        s3().upload_file(str(media), os.environ['R2_BUCKET'], key, ExtraArgs={'ContentType': ctype, 'CacheControl': 'public,max-age=3600'})
        
        db = SessionLocal()
        try:
            db.execute(update(Download).where(Download.job_id == job_id).values(
                title=re.sub(r'\s+', ' ', info.get('title') or 'Media')[:160], 
                thumbnail=info.get('thumbnail'), 
                filename=media.name, 
                object_key=key, 
                content_type=ctype, 
                status='completed', 
                error=None
            ))
            db.commit()
        finally:
            db.close()
        log.info('Completed job %s', job_id)
    except Exception as e:
        log.exception('Failed job %s: %s', job_id, e)
        fail(job_id, e)
    finally:
        cleanup(job_id)

def background_worker_loop():
    log.info("Background worker started inside Web Service container.")
    while True:
        try:
            job_id, kind = claim()
            if job_id:
                process(job_id, kind)
            else:
                time.sleep(float(os.getenv('WORKER_POLL_SECONDS', '1')))
        except Exception as e:
            log.error(f"Error in worker loop: {e}")
            time.sleep(2)

@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=background_worker_loop, daemon=True)
    t.start()
    yield

# --- FASTAPI APP ---
app = FastAPI(title='VEXDOU Downloader', version='3.3.0', lifespan=lifespan)

if (BASE_DIR / 'static').exists():
    app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')

HOSTS = {'youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com', 'instagr.am', 'facebook.com', 'fb.watch', 'fb.me', 'pinterest.com', 'pin.it', 'twitter.com', 'x.com'}

class Req(BaseModel):
    url: HttpUrl
    kind: str = 'video'

def allowed(url):
    h = host(url); return any(h == x or h.endswith('.' + x) for x in HOSTS)

def media_url(x, expires=3600):
    if not x.object_key: return None
    return s3().generate_presigned_url('get_object', Params={'Bucket': os.environ['R2_BUCKET'], 'Key': x.object_key}, ExpiresIn=expires)

def serialize(x):
    return {
        'job_id': x.job_id,
        'title': x.title,
        'status': x.status,
        'kind': x.kind,
        'thumbnail': x.thumbnail,
        'url': x.url,
        'created_at': x.created_at.isoformat() if x.created_at else None,
        'download_url': media_url(x) if x.status == 'completed' else None,
        'platform': plat(x.url),
        'error': x.error
    }

@app.get('/')
def home(): return FileResponse(BASE_DIR / 'templates' / 'index.html')

@app.get('/manifest.json')
def manifest(): return FileResponse(BASE_DIR / 'manifest.json', media_type='application/manifest+json')

@app.get('/sw.js')
def sw(): return FileResponse(BASE_DIR / 'sw.js', media_type='application/javascript', headers={'Cache-Control': 'no-cache'})

@app.get('/api/health')
def health(): return {'ok': True, 'service': 'vexdou-web', 'storage': True}

@app.post('/api/download')
def create(req: Req, vexdou_visitor: str | None = Cookie(None)):
    url = str(req.url).strip(); kind = req.kind.lower().strip()
    if kind not in {'video', 'audio'}: raise HTTPException(400, 'Invalid download type.')
    if not allowed(url): raise HTTPException(400, 'Supported: YouTube, TikTok, Instagram, Facebook, Pinterest and X/Twitter.')
    for k in ('R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET'):
        if not os.getenv(k): raise HTTPException(503, 'Storage is not configured on Render.')
    
    visitor = vexdou_visitor or uuid.uuid4().hex
    job = uuid.uuid4().hex
    db = SessionLocal()
    try:
        db.add(Download(job_id=job, visitor_id=visitor, url=url, title='Preparing...', status='queued', kind=kind))
        db.commit()
    finally:
        db.close()

    r = JSONResponse({'ok': True, 'job_id': job, 'platform': plat(url), 'kind': kind, 'status': 'queued'})
    if not vexdou_visitor:
        r.set_cookie('vexdou_visitor', visitor, max_age=31536000, httponly=True, samesite='lax', secure=True)
    return r

@app.get('/api/download/{job}')
def status(job: str, vexdou_visitor: str | None = Cookie(None)):
    if not vexdou_visitor: raise HTTPException(404, 'Download not found.')
    db = SessionLocal()
    try:
        x = db.scalar(select(Download).where(Download.job_id == job, Download.visitor_id == vexdou_visitor))
        if not x: raise HTTPException(404, 'Download not found.')
        return serialize(x)
    finally: db.close()

@app.get('/api/history')
def history(vexdou_visitor: str | None = Cookie(None)):
    if not vexdou_visitor: return {'items': []}
    db = SessionLocal()
    try:
        xs = db.scalars(select(Download).where(Download.visitor_id == vexdou_visitor).order_by(Download.created_at.desc()).limit(50)).all()
        return {'items': [serialize(x) for x in xs]}
    finally: db.close()

@app.get('/api/file/{job}')
def file(job: str, vexdou_visitor: str | None = Cookie(None)):
    if not vexdou_visitor: raise HTTPException(404, 'File not found.')
    db.session = SessionLocal() # type: ignore
    try:
        x = db.session.scalar(select(Download).where(Download.job_id == job, Download.visitor_id == vexdou_visitor, Download.status == 'completed'))
        if not x: raise HTTPException(404, 'File not found.')
        u = media_url(x, 900)
        if not u: raise HTTPException(404, 'File not found.')
        return RedirectResponse(u, 302)
    finally: db.session.close() # type: ignore

@app.delete('/api/history')
def clear(vexdou_visitor: str | None = Cookie(None)):
    if not vexdou_visitor: return {'ok': True}
    db = SessionLocal()
    try:
        xs = db.scalars(select(Download).where(Download.visitor_id == vexdou_visitor)).all()
        client = s3(); bucket = os.environ['R2_BUCKET']
        for x in xs:
            if x.object_key:
                try: client.delete_object(Bucket=bucket, Key=x.object_key)
                except Exception: pass
        db.execute(delete(Download).where(Download.visitor_id == vexdou_visitor))
        db.commit()
        return {'ok': True}
    finally: db.close()
