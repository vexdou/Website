import os, uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import boto3
from botocore.client import Config
from fastapi import Cookie, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BASE_DIR=Path(__file__).resolve().parent
DB=os.getenv('DATABASE_URL','').strip()
if DB.startswith('postgres://'): DB=DB.replace('postgres://','postgresql+psycopg2://',1)
if DB.startswith('postgresql://'): DB=DB.replace('postgresql://','postgresql+psycopg2://',1)
if not DB: raise RuntimeError('DATABASE_URL is required in production')
engine=create_engine(DB,pool_pre_ping=True,pool_recycle=300)
SessionLocal=sessionmaker(bind=engine,autoflush=False,autocommit=False)
class Base(DeclarativeBase): pass
class Download(Base):
    __tablename__='downloads'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    job_id:Mapped[str]=mapped_column(String(64),unique=True,index=True)
    visitor_id:Mapped[str]=mapped_column(String(128),index=True)
    url:Mapped[str]=mapped_column(Text)
    title:Mapped[str]=mapped_column(Text,default='Media')
    thumbnail:Mapped[str|None]=mapped_column(Text,nullable=True)
    status:Mapped[str]=mapped_column(String(30),default='queued',index=True)
    kind:Mapped[str]=mapped_column(String(20),default='video')
    filename:Mapped[str|None]=mapped_column(Text,nullable=True)
    object_key:Mapped[str|None]=mapped_column(Text,nullable=True)
    content_type:Mapped[str|None]=mapped_column(String(120),nullable=True)
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
Base.metadata.create_all(engine)
app=FastAPI(title='VEXDOU Downloader',version='3.0.0')
if (BASE_DIR/'static').exists(): app.mount('/static',StaticFiles(directory=BASE_DIR/'static'),name='static')
HOSTS={'youtube.com','youtu.be','tiktok.com','instagram.com','instagr.am','facebook.com','fb.watch','pinterest.com','pin.it','twitter.com','x.com'}
class Req(BaseModel): url:HttpUrl; kind:str='video'
def host(url): return (urlparse(url).hostname or '').lower().rstrip('.')
def platform(url):
    h=host(url)
    if 'youtube.com' in h or h=='youtu.be': return 'youtube'
    if 'tiktok.com' in h:return 'tiktok'
    if 'instagram.com' in h or 'instagr.am' in h:return 'instagram'
    if 'facebook.com' in h or h in {'fb.watch','fb.me'}:return 'facebook'
    if 'pinterest.com' in h or h=='pin.it':return 'pinterest'
    if 'twitter.com' in h or 'x.com'==h:return 'x'
    return 'unknown'
def allowed(url):
    h=host(url); return any(h==x or h.endswith('.'+x) for x in HOSTS)
def s3():
    return boto3.client('s3',endpoint_url=os.environ['R2_ENDPOINT'],aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],region_name=os.getenv('R2_REGION','auto'),config=Config(signature_version='s3v4'))
def media_url(x,expires=3600):
    if not x.object_key:return None
    return s3().generate_presigned_url('get_object',Params={'Bucket':os.environ['R2_BUCKET'],'Key':x.object_key},ExpiresIn=expires)
def serialize(x):
    return {'job_id':x.job_id,'title':x.title,'status':x.status,'kind':x.kind,'thumbnail':x.thumbnail,'url':x.url,'created_at':x.created_at.isoformat() if x.created_at else None,'download_url':media_url(x) if x.status=='completed' else None,'platform':platform(x.url),'error':x.error}
@app.get('/')
def home(): return FileResponse(BASE_DIR/'templates'/'index.html')
@app.get('/manifest.json')
def manifest(): return FileResponse(BASE_DIR/'manifest.json',media_type='application/manifest+json')
@app.get('/sw.js')
def sw(): return FileResponse(BASE_DIR/'sw.js',media_type='application/javascript',headers={'Cache-Control':'no-cache'})
@app.get('/api/health')
def health(): return {'ok':True,'service':'vexdou-web','storage':True}
@app.post('/api/download')
def create(req:Req,vexdou_visitor:str|None=Cookie(None)):
    url=str(req.url).strip(); kind=req.kind.lower().strip()
    if kind not in {'video','audio'}: raise HTTPException(400,'Invalid download type.')
    if not allowed(url): raise HTTPException(400,'Supported: YouTube, TikTok, Instagram, Facebook, Pinterest and X/Twitter.')
    for k in ('R2_ENDPOINT','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET'):
        if not os.getenv(k): raise HTTPException(503,'Storage is not configured on Render.')
    visitor=vexdou_visitor or uuid.uuid4().hex; job=uuid.uuid4().hex
    db=SessionLocal()
    try:
        db.add(Download(job_id=job,visitor_id=visitor,url=url,title='Preparing...',status='queued',kind=kind));db.commit()
    finally:db.close()
    r=JSONResponse({'ok':True,'job_id':job,'platform':platform(url),'kind':kind,'status':'queued'})
    if not vexdou_visitor:r.set_cookie('vexdou_visitor',visitor,max_age=31536000,httponly=True,samesite='lax',secure=True)
    return r
@app.get('/api/download/{job}')
def status(job:str,vexdou_visitor:str|None=Cookie(None)):
    if not vexdou_visitor:raise HTTPException(404,'Download not found.')
    db=SessionLocal()
    try:
        x=db.scalar(select(Download).where(Download.job_id==job,Download.visitor_id==vexdou_visitor))
        if not x:raise HTTPException(404,'Download not found.')
        return serialize(x)
    finally:db.close()
@app.get('/api/history')
def history(vexdou_visitor:str|None=Cookie(None)):
    if not vexdou_visitor:return {'items':[]}
    db=SessionLocal()
    try:
        xs=db.scalars(select(Download).where(Download.visitor_id==vexdou_visitor).order_by(Download.created_at.desc()).limit(50)).all();return {'items':[serialize(x) for x in xs]}
    finally:db.close()
@app.get('/api/file/{job}')
def file(job:str,vexdou_visitor:str|None=Cookie(None)):
    if not vexdou_visitor:raise HTTPException(404,'File not found.')
    db=SessionLocal()
    try:
        x=db.scalar(select(Download).where(Download.job_id==job,Download.visitor_id==vexdou_visitor,Download.status=='completed'))
        if not x:raise HTTPException(404,'File not found.')
        u=media_url(x,900)
        if not u:raise HTTPException(404,'File not found.')
        return RedirectResponse(u,302)
    finally:db.close()
@app.delete('/api/history')
def clear(vexdou_visitor:str|None=Cookie(None)):
    if not vexdou_visitor:return {'ok':True}
    db=SessionLocal()
    try:
        xs=db.scalars(select(Download).where(Download.visitor_id==vexdou_visitor)).all(); client=s3(); bucket=os.environ['R2_BUCKET']
        for x in xs:
            if x.object_key:
                try:client.delete_object(Bucket=bucket,Key=x.object_key)
                except Exception:pass
        db.execute(delete(Download).where(Download.visitor_id==vexdou_visitor));db.commit();return {'ok':True}
    finally:db.close()
