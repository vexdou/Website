import os, re, time, uuid, mimetypes, logging, threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
import yt_dlp
from botocore.client import Config
from fastapi import FastAPI, HTTPException, Cookie
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, String, Text, Integer, DateTime, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('vexdou')
BASE = Path(__file__).resolve().parent
WORK = Path(os.getenv('WORK_DIR', '/tmp/vexdou'))
WORK.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv('DATABASE_URL', '').strip()
if DB_URL.startswith('postgres://'):
    DB_URL = DB_URL.replace('postgres://', 'postgresql+psycopg2://', 1)
elif DB_URL.startswith('postgresql://'):
    DB_URL = DB_URL.replace('postgresql://', 'postgresql+psycopg2://', 1)
if not DB_URL:
    raise RuntimeError('DATABASE_URL is required')

engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=300)
Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

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

HOSTS = {
    'youtube.com','youtu.be','youtube-nocookie.com',
    'tiktok.com','instagram.com','instagr.am',
    'facebook.com','fb.watch','fb.me',
    'pinterest.com','pin.it',
    'twitter.com','x.com'
}
UA = os.getenv('DOWNLOADER_USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36')


def hostname(url: str) -> str:
    return (urlparse(url).hostname or '').lower().split(':')[0]

def platform(url: str) -> str:
    h = hostname(url)
    if 'youtube' in h or h == 'youtu.be': return 'youtube'
    if 'tiktok' in h: return 'tiktok'
    if 'instagram' in h or h == 'instagr.am': return 'instagram'
    if 'facebook' in h or h in {'fb.watch','fb.me'}: return 'facebook'
    if 'pinterest' in h or h == 'pin.it': return 'pinterest'
    if h in {'x.com','twitter.com'}: return 'x'
    return 'unknown'

def allowed(url: str) -> bool:
    h = hostname(url)
    return any(h == x or h.endswith('.' + x) for x in HOSTS)

def r2_client():
    needed = ['R2_ENDPOINT','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET']
    if not all(os.getenv(x) for x in needed):
        raise RuntimeError('R2 storage is not configured')
    return boto3.client('s3', endpoint_url=os.environ['R2_ENDPOINT'],
        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
        region_name=os.getenv('R2_REGION','auto'),
        config=Config(signature_version='s3v4'))

def ytdlp_options(job: str, kind: str, p: str):
    out = str(WORK / f'{job}.%(ext)s')
    opts = {
        'outtmpl': out,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 4,
        'fragment_retries': 4,
        'socket_timeout': 30,
        'concurrent_fragment_downloads': 4,
        'skip_unavailable_fragments': True,
        'restrictfilenames': True,
        'windowsfilenames': True,
        'http_headers': {'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'},
        'format': 'bv*+ba/b' if kind == 'video' else 'ba/b',
        'merge_output_format': 'mp4' if kind == 'video' else None,
    }
    if p == 'youtube':
        opts['extractor_args'] = {'youtube': {'player_client': ['web','android']}}
    if kind == 'audio':
        opts['postprocessors'] = [{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'192'}]
    return {k:v for k,v in opts.items() if v is not None}

def cleanup(job):
    for f in WORK.glob(f'{job}.*'):
        try: f.unlink()
        except OSError: pass

def mark_failed(job, error):
    db = Session()
    try:
        msg = re.sub(r'\s+', ' ', str(error)).strip()[:700]
        db.execute(update(Download).where(Download.job_id == job).values(status='failed', error=msg))
        db.commit()
    finally: db.close()

def process(job: str, kind: str):
    cleanup(job)
    db = Session()
    try:
        row = db.scalar(select(Download).where(Download.job_id == job))
        if not row: return
        url = row.url
    finally: db.close()
    try:
        p = platform(url)
        log.info('job=%s platform=%s starting', job, p)
        with yt_dlp.YoutubeDL(ytdlp_options(job, kind, p)) as ydl:
            info = ydl.extract_info(url, download=True)
        files = [f for f in WORK.glob(f'{job}.*') if f.is_file() and f.suffix not in {'.part','.ytdl'}]
        if not files:
            raise RuntimeError('Downloader created no media file')
        media = max(files, key=lambda f: f.stat().st_size)
        if media.stat().st_size < 1:
            raise RuntimeError('Downloaded file is empty')
        key = f"media/{datetime.now(timezone.utc):%Y/%m/%d}/{uuid.uuid4().hex}{media.suffix.lower()}"
        ctype = mimetypes.guess_type(media.name)[0] or ('audio/mpeg' if kind == 'audio' else 'video/mp4')
        r2_client().upload_file(str(media), os.environ['R2_BUCKET'], key,
            ExtraArgs={'ContentType': ctype, 'CacheControl':'public,max-age=3600'})
        db = Session()
        try:
            db.execute(update(Download).where(Download.job_id == job).values(
                title=re.sub(r'\s+', ' ', info.get('title') or 'Media').strip()[:180],
                thumbnail=info.get('thumbnail'), filename=media.name, object_key=key,
                content_type=ctype, status='completed', error=None))
            db.commit()
        finally: db.close()
        log.info('job=%s completed', job)
    except Exception as exc:
        log.exception('job=%s failed', job)
        mark_failed(job, exc)
    finally:
        cleanup(job)

def claim_one():
    db = Session()
    try:
        row = db.scalar(select(Download).where(Download.status=='queued').order_by(Download.id).limit(1))
        if not row: return None
        result = db.execute(update(Download).where(Download.job_id==row.job_id, Download.status=='queued').values(status='downloading', error=None))
        if result.rowcount != 1:
            db.rollback(); return None
        db.commit(); return row.job_id, row.kind
    finally: db.close()

def worker_loop():
    log.info('worker started')
    while True:
        try:
            item = claim_one()
            if item: process(*item)
            else: time.sleep(float(os.getenv('WORKER_POLL_SECONDS','0.7')))
        except Exception:
            log.exception('worker loop error'); time.sleep(2)

@asynccontextmanager
async def lifespan(app):
    if os.getenv('DISABLE_EMBEDDED_WORKER','0') != '1':
        threading.Thread(target=worker_loop, daemon=True, name='vexdou-worker').start()
    yield

app = FastAPI(title='VEXDOU Downloader', version='4.0.0', lifespan=lifespan)

@app.get('/')
def home(): return FileResponse(BASE/'templates'/'index.html')
@app.get('/manifest.json')
def manifest(): return FileResponse(BASE/'manifest.json', media_type='application/manifest+json')
@app.get('/sw.js')
def sw(): return FileResponse(BASE/'sw.js', media_type='application/javascript', headers={'Cache-Control':'no-cache'})
@app.get('/api/health')
def health(): return {'ok':True,'service':'vexdou-web','worker':os.getenv('DISABLE_EMBEDDED_WORKER','0')!='1'}

class DownloadRequest(BaseModel):
    url: HttpUrl
    kind: str = 'video'


def serialize(row):
    signed = None
    if row.status == 'completed' and row.object_key:
        try:
            signed = r2_client().generate_presigned_url('get_object', Params={'Bucket':os.environ['R2_BUCKET'],'Key':row.object_key}, ExpiresIn=900)
        except Exception: pass
    return {'job_id':row.job_id,'title':row.title,'status':row.status,'kind':row.kind,'thumbnail':row.thumbnail,
            'url':row.url,'platform':platform(row.url),'created_at':row.created_at.isoformat() if row.created_at else None,
            'download_url':signed,'error':row.error}

@app.post('/api/download')
def create_download(req: DownloadRequest, vexdou_visitor: str|None=Cookie(default=None)):
    url=str(req.url).strip(); kind=req.kind.lower().strip()
    if kind not in {'video','audio'}: raise HTTPException(400,'Invalid download type')
    if not allowed(url): raise HTTPException(400,'Supported platforms: YouTube, TikTok, Instagram, Facebook, Pinterest and X/Twitter')
    try: r2_client()
    except Exception: raise HTTPException(503,'Storage is not configured on the server')
    visitor=vexdou_visitor or uuid.uuid4().hex
    job=uuid.uuid4().hex
    db=Session()
    try:
        db.add(Download(job_id=job,visitor_id=visitor,url=url,title='Preparing...',status='queued',kind=kind)); db.commit()
    finally: db.close()
    out=JSONResponse({'ok':True,'job_id':job,'status':'queued','platform':platform(url),'kind':kind})
    if not vexdou_visitor:
        out.set_cookie('vexdou_visitor',visitor,max_age=31536000,httponly=True,samesite='lax',secure=True)
    return out

@app.get('/api/download/{job}')
def get_download(job: str, vexdou_visitor: str|None=Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(404,'Download not found')
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job,Download.visitor_id==vexdou_visitor))
        if not row: raise HTTPException(404,'Download not found')
        return serialize(row)
    finally: db.close()

@app.get('/api/history')
def history(vexdou_visitor: str|None=Cookie(default=None)):
    if not vexdou_visitor: return {'items':[]}
    db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.visitor_id==vexdou_visitor).order_by(Download.created_at.desc()).limit(50)).all()
        return {'items':[serialize(x) for x in rows]}
    finally: db.close()

@app.get('/api/file/{job}')
def file_redirect(job: str, vexdou_visitor: str|None=Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(404,'File not found')
    db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==job,Download.visitor_id==vexdou_visitor,Download.status=='completed'))
        if not row or not row.object_key: raise HTTPException(404,'File not found')
        url=r2_client().generate_presigned_url('get_object',Params={'Bucket':os.environ['R2_BUCKET'],'Key':row.object_key},ExpiresIn=900)
        return RedirectResponse(url,302)
    finally: db.close()

@app.delete('/api/history')
def clear_history(vexdou_visitor: str|None=Cookie(default=None)):
    if not vexdou_visitor: return {'ok':True}
    db=Session()
    try:
        rows=db.scalars(select(Download).where(Download.visitor_id==vexdou_visitor)).all()
        client=r2_client()
        for row in rows:
            if row.object_key:
                try: client.delete_object(Bucket=os.environ['R2_BUCKET'],Key=row.object_key)
                except Exception: log.warning('failed deleting %s',row.object_key)
        for row in rows: db.delete(row)
        db.commit(); return {'ok':True}
    finally: db.close()
