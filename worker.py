import os,time,uuid,mimetypes,logging,re
from pathlib import Path
from datetime import datetime,timezone
import boto3,yt_dlp
from botocore.client import Config
from sqlalchemy import create_engine,select,update
from sqlalchemy.orm import sessionmaker
from app import Download
logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s'); log=logging.getLogger('vexdou-worker')
DB=os.environ['DATABASE_URL'];DB=DB.replace('postgres://','postgresql+psycopg2://',1).replace('postgresql://','postgresql+psycopg2://',1) if DB.startswith(('postgres://','postgresql://')) else DB
engine=create_engine(DB,pool_pre_ping=True,pool_recycle=300);Session=sessionmaker(bind=engine,autoflush=False,autocommit=False)
WORK=Path('/tmp/vexdou');WORK.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'
def host(url):
 from urllib.parse import urlparse
 return (urlparse(url).hostname or '').lower()
def plat(url):
 h=host(url)
 if 'youtube' in h or 'youtu.be' in h:return 'youtube'
 if 'tiktok' in h:return 'tiktok'
 if 'instagram' in h:return 'instagram'
 if 'facebook' in h or 'fb.watch' in h:return 'facebook'
 if 'pinterest' in h or 'pin.it' in h:return 'pinterest'
 return 'x'
def opts(job,kind,p):
 o={'outtmpl':str(WORK/f'{job}.%(ext)s'),'noplaylist':True,'quiet':True,'no_warnings':True,'retries':5,'fragment_retries':5,'file_access_retries':5,'socket_timeout':45,'skip_unavailable_fragments':True,'restrictfilenames':True,'windowsfilenames':True,'impersonate':'chrome','http_headers':{'User-Agent':UA,'Referer':{'youtube':'https://www.youtube.com/','tiktok':'https://www.tiktok.com/','instagram':'https://www.instagram.com/','facebook':'https://www.facebook.com/','pinterest':'https://www.pinterest.com/','x':'https://x.com/'}.get(p,'')},'format':'best[ext=mp4]/best'}
 if p=='youtube':o['extractor_args']={'youtube':{'player_client':['web','android']}}
 if kind=='audio':o.update(format='bestaudio/best',postprocessors=[{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'192'}])
 return o
def s3():return boto3.client('s3',endpoint_url=os.environ['R2_ENDPOINT'],aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],region_name=os.getenv('R2_REGION','auto'),config=Config(signature_version='s3v4'))
def cleanup(job):
 for p in WORK.glob(f'{job}.*'):
  try:p.unlink()
  except OSError:pass
def claim():
 db=Session()
 try:
  x=db.scalar(select(Download).where(Download.status=='queued').order_by(Download.id).limit(1))
  if not x:return None
  r=db.execute(update(Download).where(Download.id==x.id,Download.status=='queued').values(status='downloading',error=None))
  if r.rowcount!=1:db.rollback();return None
  db.commit();return x
 finally:db.close()
def fail(job,msg):
 db=Session();db.execute(update(Download).where(Download.job_id==job).values(status='failed',error=str(msg)[:1000]));db.commit();db.close()
def process(x):
 job=x.job_id;cleanup(job)
 try:
  p=plat(x.url);log.info('Downloading %s %s',job,p)
  with yt_dlp.YoutubeDL(opts(job,x.kind,p)) as y:info=y.extract_info(x.url,download=True)
  files=[p for p in WORK.glob(f'{job}.*') if p.is_file() and p.suffix not in {'.part','.ytdl'}]
  if not files:raise RuntimeError('No media file was created.')
  media=max(files,key=lambda p:p.stat().st_size)
  if media.stat().st_size<=0:raise RuntimeError('Media file is empty.')
  key=f"media/{datetime.now(timezone.utc):%Y/%m/%d}/{uuid.uuid4().hex}{media.suffix.lower()}";ctype=mimetypes.guess_type(media.name)[0] or ('audio/mpeg' if x.kind=='audio' else 'video/mp4')
  s3().upload_file(str(media),os.environ['R2_BUCKET'],key,ExtraArgs={'ContentType':ctype,'CacheControl':'public,max-age=3600'})
  db=Session();db.execute(update(Download).where(Download.job_id==job).values(title=re.sub(r'\s+',' ',info.get('title') or 'Media')[:160],thumbnail=info.get('thumbnail'),filename=media.name,object_key=key,content_type=ctype,status='completed',error=None));db.commit();db.close();log.info('Completed %s',job)
 except Exception as e:log.exception('Failed %s',job);fail(job,e)
 finally:cleanup(job)
def main():
 while True:
  x=claim()
  if x:process(x)
  else:time.sleep(float(os.getenv('WORKER_POLL_SECONDS','1')))
if __name__=='__main__':main()
