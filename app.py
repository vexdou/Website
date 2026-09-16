import os, re, time, uuid, mimetypes, logging, threading, ipaddress, socket, shutil, json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qs
from decimal import Decimal, InvalidOperation
from sqlalchemy import UniqueConstraint, text, Boolean
from sqlalchemy.exc import IntegrityError

import yt_dlp
import requests
try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None
from html import unescape
from fastapi import FastAPI, HTTPException, Cookie, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, String, Text, Integer, DateTime, select, update, delete, func
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

class CreditAccount(Base):
    __tablename__ = "credit_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    free_credits: Mapped[int] = mapped_column(Integer, default=50)
    purchased_credits: Mapped[int] = mapped_column(Integer, default=0)
    month_key: Mapped[str] = mapped_column(String(7), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    unlimited: Mapped[bool] = mapped_column(Boolean, default=False)

class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(128), index=True)
    tx_type: Mapped[str] = mapped_column(String(40))
    credits: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    package_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    paypal_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

class PayPalOrder(Base):
    __tablename__ = "paypal_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    visitor_id: Mapped[str] = mapped_column(String(128), index=True)
    package_id: Mapped[str] = mapped_column(String(40))
    credits: Mapped[int] = mapped_column(Integer)
    amount: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(30), default="created")
    capture_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

Base.metadata.create_all(engine)

def migrate_credit_columns():
    """Backward-compatible schema migration for persistent Render/Postgres DBs.

    Earlier QuickDL builds created the credit tables with fewer columns. SQLAlchemy
    create_all() does not alter existing tables, so upgrades could leave an old
    credit_accounts schema and every download would then fail during credit init.
    This migration explicitly adds every column used by the current credit system.
    """
    try:
        with engine.begin() as conn:
            dialect = conn.dialect.name
            tables = {r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))} if dialect == 'postgresql' else set()

            if dialect == "postgresql":
                # PostgreSQL supports IF NOT EXISTS, making this safe on every deploy.
                stmts = {
                    "credit_accounts": [
                        "ALTER TABLE credit_accounts ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(128)",
                        "ALTER TABLE credit_accounts ADD COLUMN IF NOT EXISTS free_credits INTEGER NOT NULL DEFAULT 50",
                        "ALTER TABLE credit_accounts ADD COLUMN IF NOT EXISTS purchased_credits INTEGER NOT NULL DEFAULT 0",
                        "ALTER TABLE credit_accounts ADD COLUMN IF NOT EXISTS month_key VARCHAR(7) NOT NULL DEFAULT ''",
                        "ALTER TABLE credit_accounts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
                        "ALTER TABLE credit_accounts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
                        "ALTER TABLE credit_accounts ADD COLUMN IF NOT EXISTS unlimited BOOLEAN NOT NULL DEFAULT FALSE",
                    ],
                    "credit_transactions": [
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(128)",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS tx_type VARCHAR(40) DEFAULT 'adjustment'",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS credits INTEGER NOT NULL DEFAULT 0",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS amount VARCHAR(32)",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS currency VARCHAR(8)",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS package_id VARCHAR(40)",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS paypal_order_id VARCHAR(80)",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS paypal_capture_id VARCHAR(80)",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'completed'",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS note TEXT",
                        "ALTER TABLE credit_transactions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
                    ],
                    "paypal_orders": [
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS order_id VARCHAR(80)",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(128)",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS package_id VARCHAR(40)",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS credits INTEGER DEFAULT 0",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS amount VARCHAR(32) DEFAULT '0.00'",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS currency VARCHAR(8) DEFAULT 'USD'",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'created'",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS capture_id VARCHAR(80)",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
                        "ALTER TABLE paypal_orders ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ",
                    ],
                }
                for table, commands in stmts.items():
                    if table in tables:
                        for stmt in commands:
                            conn.execute(text(stmt))

                # Ensure the current visitor identifier remains unique when possible.
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_accounts_visitor_id ON credit_accounts(visitor_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_credit_transactions_visitor_id ON credit_transactions(visitor_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_paypal_orders_visitor_id ON paypal_orders(visitor_id)"))
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_paypal_orders_order_id ON paypal_orders(order_id)"))
            elif dialect == "sqlite":
                def cols(table):
                    return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
                migrations = {
                    "credit_accounts": {
                        "visitor_id":"TEXT", "free_credits":"INTEGER NOT NULL DEFAULT 50",
                        "purchased_credits":"INTEGER NOT NULL DEFAULT 0", "month_key":"TEXT NOT NULL DEFAULT ''",
                        "created_at":"DATETIME", "updated_at":"DATETIME", "unlimited":"INTEGER NOT NULL DEFAULT 0",
                    },
                    "credit_transactions": {
                        "visitor_id":"TEXT", "tx_type":"TEXT DEFAULT 'adjustment'", "credits":"INTEGER NOT NULL DEFAULT 0",
                        "amount":"TEXT", "currency":"TEXT", "package_id":"TEXT", "paypal_order_id":"TEXT",
                        "paypal_capture_id":"TEXT", "status":"TEXT DEFAULT 'completed'", "note":"TEXT", "created_at":"DATETIME",
                    },
                    "paypal_orders": {
                        "order_id":"TEXT", "visitor_id":"TEXT", "package_id":"TEXT", "credits":"INTEGER DEFAULT 0",
                        "amount":"TEXT DEFAULT '0.00'", "currency":"TEXT DEFAULT 'USD'", "status":"TEXT DEFAULT 'created'",
                        "capture_id":"TEXT", "created_at":"DATETIME", "captured_at":"DATETIME",
                    },
                }
                for table, fields in migrations.items():
                    existing=cols(table)
                    for name, typ in fields.items():
                        if name not in existing:
                            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
    except Exception:
        log.exception("database schema migration failed")


migrate_credit_columns()

UA = os.getenv(
    "DOWNLOADER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
)
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "300"))
KEEP_FILE_HOURS = float(os.getenv("KEEP_FILE_HOURS", "6"))
STRICT_PLATFORM_TOGGLES = os.getenv("STRICT_PLATFORM_TOGGLES", "false").lower() in {"1", "true", "yes", "on"}
MONTHLY_FREE_CREDITS = int(os.getenv("MONTHLY_FREE_CREDITS", "50"))
VIDEO_CREDIT_COST = int(os.getenv("VIDEO_CREDIT_COST", "2"))
PAYPAL_MODE = os.getenv("PAYPAL_MODE", "live").strip().lower()
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_CURRENCY = os.getenv("PAYPAL_CURRENCY", "USD").strip().upper()
PAYPAL_DOMAIN = os.getenv("PAYPAL_DOMAIN", "").strip()
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
PAYPAL_TOKEN_CACHE = {"token": None, "expires_at": 0}
WORKER_HEARTBEAT = {"started_at": None, "last_loop": None, "last_job": None}
CREDIT_PACKAGES = {
    "starter": {"name": "Starter", "credits": 100, "price": "1.99", "badge": ""},
    "popular": {"name": "Popular", "credits": 500, "price": "6.99", "badge": "Most popular"},
    "pro": {"name": "Pro", "credits": 1200, "price": "14.99", "badge": "Best value"},
    "business": {"name": "Business", "credits": 3000, "price": "29.99", "badge": ""},
    "mega": {"name": "Mega", "credits": 7500, "price": "59.99", "badge": ""},
}

def hostname(url):
    return (urlparse(url).hostname or "").lower().rstrip(".")

def current_month_key():
    return datetime.now(timezone.utc).strftime("%Y-%m")

def ensure_credit_account(db, visitor_id):
    if not visitor_id:
        raise ValueError("visitor_id is required")
    month = current_month_key()
    monthly_free = int(setting_get("monthly_free_credits") or MONTHLY_FREE_CREDITS)
    now = datetime.now(timezone.utc)
    account = db.scalar(select(CreditAccount).where(CreditAccount.visitor_id == visitor_id).with_for_update())
    if not account:
        try:
            account = CreditAccount(
                visitor_id=visitor_id,
                free_credits=monthly_free,
                purchased_credits=0,
                month_key=month,
                created_at=now,
                updated_at=now,
                unlimited=False,
            )
            db.add(account)
            db.flush()
        except IntegrityError:
            # Another request may have created the account at the same time.
            db.rollback()
            account = db.scalar(select(CreditAccount).where(CreditAccount.visitor_id == visitor_id).with_for_update())
            if not account:
                raise
    elif account.month_key != month:
        account.free_credits = monthly_free
        account.month_key = month
        account.updated_at = now
        db.flush()
    return account


def credit_balance(account):
    if bool(getattr(account, "unlimited", False)):
        return None
    return max(0, int(account.free_credits or 0)) + max(0, int(account.purchased_credits or 0))

def debit_download_credits(visitor_id, job_id, cost):
    db = Session()
    try:
        account = ensure_credit_account(db, visitor_id)
        if bool(getattr(account, "unlimited", False)):
            db.add(CreditTransaction(visitor_id=visitor_id, tx_type="download", credits=0, status="completed", note=f"Unlimited download {job_id}"))
            db.commit()
            return True, None
        if credit_balance(account) < cost:
            db.rollback()
            return False, credit_balance(account)
        free_used = min(account.free_credits, cost)
        account.free_credits -= free_used
        account.purchased_credits -= (cost - free_used)
        account.updated_at = datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=visitor_id, tx_type="download", credits=-cost, status="completed", note=f"Video download {job_id};free_used={free_used}"))
        db.commit()
        return True, credit_balance(account)
    finally:
        db.close()

def refund_download_credits(visitor_id, job_id, cost):
    db = Session()
    try:
        account = ensure_credit_account(db, visitor_id)
        if bool(getattr(account, "unlimited", False)):
            db.add(CreditTransaction(visitor_id=visitor_id, tx_type="refund", credits=0, status="completed", note=f"Failed unlimited download {job_id}"))
            db.commit()
            return
        tx = db.scalar(select(CreditTransaction).where(CreditTransaction.visitor_id==visitor_id, CreditTransaction.tx_type=="download", CreditTransaction.note.like(f"%{job_id}%")).order_by(CreditTransaction.id.desc()))
        free_used = 0
        if tx and tx.note and "free_used=" in tx.note:
            try: free_used = max(0, min(cost, int(tx.note.rsplit("free_used=",1)[1].split(";",1)[0])))
            except Exception: free_used = 0
        account.free_credits += free_used
        account.purchased_credits += (cost - free_used)
        account.updated_at = datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=visitor_id, tx_type="refund", credits=cost, status="completed", note=f"Failed download refund {job_id}"))
        db.commit()
    finally:
        db.close()

def account_payload(visitor_id):
    db = Session()
    try:
        account = ensure_credit_account(db, visitor_id)
        db.commit()
        return {"free_credits": account.free_credits, "purchased_credits": account.purchased_credits, "credits": credit_balance(account), "unlimited": bool(getattr(account, "unlimited", False)), "monthly_free": int(setting_get("monthly_free_credits") or MONTHLY_FREE_CREDITS), "video_cost": int(setting_get("video_credit_cost") or VIDEO_CREDIT_COST), "month": account.month_key}
    finally:
        db.close()

def paypal_base():
    return "https://api-m.paypal.com" if PAYPAL_MODE == "live" else "https://api-m.sandbox.paypal.com"

def paypal_token():
    """Get a server-side OAuth access token for PayPal REST APIs.

    The browser does NOT need a client token for our v6 checkout because
    PayPal recommends client-id authentication for standard one-time checkout.
    Keeping OAuth here also means the client secret never reaches the browser.
    """
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise HTTPException(503, "PayPal is not configured. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET.")
    if PAYPAL_TOKEN_CACHE.get("token") and time.time() < PAYPAL_TOKEN_CACHE.get("expires_at", 0) - 60:
        return PAYPAL_TOKEN_CACHE["token"]

    try:
        r = requests.post(
            f"{paypal_base()}/v1/oauth2/token",
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            timeout=30,
        )
    except requests.RequestException as exc:
        log.exception("PayPal OAuth network error")
        raise HTTPException(502, "PayPal could not be reached. Try again in a moment.") from exc

    try:
        payload = r.json()
    except ValueError:
        payload = {}

    if r.status_code >= 400:
        name = str(payload.get("name") or "PAYPAL_AUTH_ERROR")
        message = str(payload.get("message") or "PayPal rejected the API credentials.")
        debug_id = str(payload.get("debug_id") or "")
        log.error("PayPal OAuth failed status=%s name=%s message=%s debug_id=%s", r.status_code, name, message, debug_id)
        safe = f"PayPal authentication failed ({name})."
        if debug_id:
            safe += f" Debug ID: {debug_id}"
        raise HTTPException(502, safe)

    token = payload.get("access_token")
    if not token:
        log.error("PayPal OAuth returned no access_token: %s", payload)
        raise HTTPException(502, "PayPal did not return an access token.")

    expires = int(payload.get("expires_in") or 300)
    PAYPAL_TOKEN_CACHE.update({"token": token, "expires_at": time.time() + expires})
    return token

def paypal_json(method, path, payload=None, request_id=None):
    token = paypal_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type":"application/json", "Accept":"application/json"}
    if request_id: headers["PayPal-Request-Id"] = request_id
    r = requests.request(method, paypal_base()+path, headers=headers, json=payload, timeout=45)
    if r.status_code >= 400:
        log.error("PayPal API %s %s: %s", method, path, r.text[:1000])
        try: detail=r.json()
        except Exception: detail={}
        raise HTTPException(502, detail.get("message") or "PayPal payment service error")
    return r.json() if r.content else {}

def platform(url):
    h = hostname(url)
    if "youtube" in h or h == "youtu.be": return "youtube"
    if "tiktok" in h: return "tiktok"
    if "instagram" in h or h == "instagr.am": return "instagram"
    if "facebook" in h or h in {"fb.watch", "fb.me"}: return "facebook"
    if "pinterest" in h or h == "pin.it": return "pinterest"
    if h in {"x.com", "twitter.com"}: return "x"
    if "snapchat.com" in h or h in {"snap.com"}: return "snapchat"
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



def _http_get(url, *, headers=None, timeout=(15, 30), stream=False):
    """Use curl_cffi browser impersonation when installed, otherwise requests."""
    headers = headers or {}
    if curl_requests is not None:
        try:
            return curl_requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                stream=stream,
                impersonate="chrome",
            )
        except Exception as exc:
            log.debug("curl_cffi request failed for %s: %s; using requests", url, exc)
    return requests.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
        stream=stream,
    )


def _extract_meta(html, prop):
    """Read an HTML meta property regardless of attribute order/quoting."""
    patterns = [
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            return unescape(m.group(1)).replace("&amp;", "&").strip()
    return None


def _instagram_embed_url(url):
    """Build the public embed endpoint for common Instagram post/reel URLs."""
    m = re.search(r"/(?:p|reel|tv)/([^/?#]+)/?", url, re.I)
    if not m:
        return None
    return f"https://www.instagram.com/{'reel' if '/reel/' in url.lower() else 'p'}/{m.group(1)}/embed/captioned/"


def instagram_public_fallback(job, url, kind):
    """Public-only Instagram fallback.

    It never supplies credentials and never attempts to bypass a private/login wall.
    It first tries the normal public page, then Instagram's public embed page.
    """
    if kind != "video":
        return None

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    urls = [url]
    embed = _instagram_embed_url(url)
    if embed and embed not in urls:
        urls.append(embed)

    html = None
    final_url = url
    last_error = None

    for page_url in urls:
        for attempt in range(3):
            try:
                if attempt:
                    time.sleep(min(2 ** attempt, 5))
                r = _http_get(page_url, headers=headers, timeout=(15, 35))
                if r.status_code == 429:
                    last_error = RuntimeError("Instagram HTTP 429 rate limit")
                    continue
                r.raise_for_status()
                html = r.text
                final_url = str(getattr(r, "url", page_url))
                break
            except Exception as exc:
                last_error = exc
        if html:
            break

    if not html:
        log.info("job=%s: Instagram public fallback unavailable: %s", job, last_error)
        return None

    # Instagram may expose the video under og:video, og:video:secure_url,
    # or an embed page may contain the same URL in a slightly different form.
    media_url = (
        _extract_meta(html, "og:video:secure_url")
        or _extract_meta(html, "og:video")
        or _extract_meta(html, "twitter:player:stream")
    )

    # Last public-only attempt: locate an obvious video URL in the HTML.
    if not media_url:
        candidates = re.findall(
            r'https?://[^"\'\s<>]+?\.(?:mp4|m3u8)(?:\?[^"\'\s<>]*)?',
            html,
            re.I,
        )
        if candidates:
            media_url = unescape(candidates[0]).replace("\\/", "/").replace("&amp;", "&")

    if not media_url or not media_url.startswith(("http://", "https://")):
        log.info("job=%s: Instagram page did not expose a public video URL", job)
        return None

    out = WORK / f"{job}.mp4"
    max_bytes = int(setting_get("max_file_mb") or MAX_FILE_MB) * 1024 * 1024

    try:
        for attempt in range(3):
            if attempt:
                time.sleep(min(2 ** attempt, 5))
            try:
                with _http_get(
                    media_url,
                    headers={"User-Agent": UA, "Referer": final_url},
                    timeout=(15, 90),
                    stream=True,
                ) as mr:
                    if getattr(mr, "status_code", 200) == 429:
                        continue
                    mr.raise_for_status()
                    total = 0
                    with open(out, "wb") as fh:
                        for chunk in mr.iter_content(chunk_size=1024 * 256):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > max_bytes:
                                raise RuntimeError("Instagram media exceeds the configured file size limit")
                            fh.write(chunk)
                if total > 0:
                    break
            except Exception as exc:
                last_error = exc
                try:
                    out.unlink()
                except OSError:
                    pass
        else:
            log.info("job=%s: Instagram media request failed: %s", job, last_error)
            return None

        if not out.exists() or out.stat().st_size < 1:
            out.unlink(missing_ok=True)
            return None

        title = _extract_meta(html, "og:title") or "Instagram Media"
        thumbnail = _extract_meta(html, "og:image")
        return {
            "title": title[:180],
            "thumbnail": thumbnail,
            "webpage_url": url,
        }
    except Exception as exc:
        out.unlink(missing_ok=True)
        log.info("job=%s: Instagram public media fallback failed: %s", job, exc)
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
    return text[:700] or "Download failed. Please try another media URL."

def ytdlp_options(job, kind, youtube_embedded=False, youtube_client=None):
    out = str(WORK / f"{job}.%(ext)s")
    opts = {
        "outtmpl": out,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 6,
        "fragment_retries": 6,
        "file_access_retries": 4,
        "socket_timeout": 45,
        "concurrent_fragment_downloads": 1,
        "skip_unavailable_fragments": True,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "http_headers": {
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
        },
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" if kind == "video" else "ba/b",
        "merge_output_format": "mp4" if kind == "video" else None,
        "max_filesize": int(setting_get("max_file_mb") or MAX_FILE_MB) * 1024 * 1024,
        "js_runtimes": {"node": {}} if shutil.which("node") else None,
        "sleep_interval_requests": 1,
        "sleep_interval": 1,
        "max_sleep_interval": 4,
        "overwrites": True,
    }

    # Current yt-dlp YouTube extraction works best when EJS/Node is enabled.
    # We try several public clients rather than assuming one client works forever.
    if youtube_embedded:
        client = youtube_client or "web_embedded"
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
    elif youtube_client:
        opts["extractor_args"] = {"youtube": {"player_client": [youtube_client]}}

    if kind == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    return {k: v for k, v in opts.items() if v is not None}

def youtube_needs_fallback(exc):
    text = str(exc).lower()
    markers = (
        "sign in to confirm", "requires sign-in", "requires sign in",
        "login required", "authentication required", "confirm you're not a bot",
        "this content isn't available", "http error 403", "forbidden",
        "po token", "challenge", "player responses are not available",
        "video unavailable", "bot detection", "http error 429", "too many requests"
    )
    return any(marker in text for marker in markers)

def cleanup_job(job):
    for f in WORK.glob(f"{job}.*"):
        try: f.unlink()
        except OSError: pass

def mark_failed(job, error):
    db = Session()
    visitor = None
    already_failed = False
    try:
        row = db.scalar(select(Download).where(Download.job_id == job))
        if not row: return
        visitor = row.visitor_id
        already_failed = row.status == "failed"
        db.execute(update(Download).where(Download.job_id == job).values(status="failed", error=human_error(error)))
        db.commit()
    finally:
        db.close()
    if visitor and not already_failed:
        try: refund_download_credits(visitor, job, VIDEO_CREDIT_COST)
        except Exception: log.exception("Could not refund credits for failed job %s", job)

def process(job, kind):
    cleanup_job(job)
    db = Session()
    try:
        row = db.scalar(select(Download).where(Download.job_id == job))
        if not row:
            return
        url = row.url
    finally:
        db.close()

    p = platform(url)

    try:
        # YouTube: use several public extractor clients. Shorts and normal videos
        # both go through the same YouTube extractor and therefore share these fallbacks.
        if p == "youtube":
            # Shorts are normal YouTube URLs to yt-dlp; these public clients give
            # the extractor a few independent ways to resolve Shorts/Reels-style URLs.
            attempts = [
                ytdlp_options(job, kind),
                ytdlp_options(job, kind, youtube_embedded=True, youtube_client="web_embedded"),
                ytdlp_options(job, kind, youtube_embedded=True, youtube_client="web_safari"),
                ytdlp_options(job, kind, youtube_embedded=True, youtube_client="android"),
            ]
        elif p in {"facebook", "instagram", "pinterest", "tiktok", "x", "snapchat", "web"}:
            # Give every supported public source a second clean extractor pass after
            # a transient HTTP/rate-limit failure. This does not bypass private/login walls.
            attempts = [ytdlp_options(job, kind), ytdlp_options(job, kind)]
        else:
            attempts = [ytdlp_options(job, kind)]

        last_exc = None
        info = None

        for attempt_no, opts in enumerate(attempts):
            try:
                cleanup_job(job)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                if info:
                    break
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "job=%s platform=%s extraction attempt %s/%s failed: %s",
                    job, p, attempt_no + 1, len(attempts), exc
                )

                # Public Instagram fallback after yt-dlp fails/rate-limits.
                if p == "instagram":
                    cleanup_job(job)
                    fallback_info = instagram_public_fallback(job, url, kind)
                    if fallback_info:
                        info = fallback_info
                        log.info("job=%s: Instagram public fallback succeeded", job)
                        break

                # Stop trying redundant YouTube clients when the error is clearly
                # an access-controlled/private media condition.
                if p == "youtube" and not youtube_needs_fallback(exc):
                    # Still give the public embedded client one chance if this was
                    # the first normal extraction attempt.
                    if attempt_no == 0:
                        continue
                    raise

                if attempt_no < len(attempts) - 1:
                    time.sleep(min(2 * (attempt_no + 1), 6))

        if info is None:
            # One final Instagram fallback if all extractor attempts failed.
            if p == "instagram":
                cleanup_job(job)
                fallback_info = instagram_public_fallback(job, url, kind)
                if fallback_info:
                    info = fallback_info
            if info is None:
                raise last_exc or RuntimeError("No media information was returned")

        files = [
            f for f in WORK.glob(f"{job}.*")
            if f.is_file() and f.suffix not in {".part", ".ytdl"}
        ]
        if not files:
            raise RuntimeError("No media file was created")

        media = max(files, key=lambda f: f.stat().st_size)
        if media.stat().st_size < 1:
            raise RuntimeError("Downloaded file is empty")

        ctype = (
            mimetypes.guess_type(media.name)[0]
            or ("audio/mpeg" if kind == "audio" else "video/mp4")
        )
        title = re.sub(r"\s+", " ", info.get("title") or "Media").strip()[:180]

        db = Session()
        try:
            db.execute(
                update(Download)
                .where(Download.job_id == job)
                .values(
                    title=title,
                    thumbnail=info.get("thumbnail"),
                    filename=media.name,
                    content_type=ctype,
                    status="completed",
                    error=None,
                )
            )
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
    WORKER_HEARTBEAT["started_at"] = datetime.now(timezone.utc).isoformat()
    recover_stuck()
    last = 0
    while True:
        try:
            if time.time() - last > 600:
                cleanup_old(); last = time.time()
            WORKER_HEARTBEAT["last_loop"] = datetime.now(timezone.utc).isoformat()
            item = claim_one()
            if item:
                WORKER_HEARTBEAT["last_job"] = item[0]
                process(*item)
            else: time.sleep(float(os.getenv("WORKER_POLL_SECONDS", "0.7")))
        except Exception:
            log.exception("worker error"); time.sleep(2)

@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=worker_loop, daemon=True, name="quickdl-worker").start()
    yield

app = FastAPI(title="QuickDL", version="17.0.0", lifespan=lifespan)

@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    log.exception("Unhandled request error %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"ok": False, "error": "internal_error", "message": "Server error. Check the admin Error Center / Render logs."})

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
    return {"announcement_enabled":setting_bool("announcement_enabled"),"announcement":setting_get("announcement"),"maintenance":setting_bool("maintenance"),"credits_enabled":True,"monthly_free":int(setting_get("monthly_free_credits") or MONTHLY_FREE_CREDITS),"video_cost":int(setting_get("video_credit_cost") or VIDEO_CREDIT_COST),"paypal_enabled":bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET),"paypal_mode":PAYPAL_MODE,"paypal_client_id":PAYPAL_CLIENT_ID,"currency":PAYPAL_CURRENCY}

@app.get("/api/health")
def health():
    db = Session()
    try:
        db.execute(select(Download.id).limit(1))
        return {"ok": True, "service": "quickdl", "storage": "local-ephemeral", "version": "17.0.0", "worker": WORKER_HEARTBEAT}
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
    # Platform switches are optional. By default QuickDL attempts all supported
    # public sources; set STRICT_PLATFORM_TOGGLES=true if the admin switches should
    # actively block a platform. This prevents stale DB flags from making every link
    # look "temporarily unavailable" after a deployment.
    if STRICT_PLATFORM_TOGGLES and not setting_bool(f"{p}_enabled"):
        raise HTTPException(503, f"{p.title()} downloads are temporarily unavailable.")
    if kind not in {"video", "audio"}: raise HTTPException(400, "Invalid download type")
    if not allowed(url): raise HTTPException(400, "Please enter a valid public HTTP/HTTPS URL")
    visitor, job = vexdou_visitor or uuid.uuid4().hex, uuid.uuid4().hex
    cost = int(setting_get("video_credit_cost") or VIDEO_CREDIT_COST)
    try:
        ok, remaining = debit_download_credits(visitor, job, cost)
    except Exception as exc:
        diagnostic_id = uuid.uuid4().hex[:12]
        log.exception("credit check failed id=%s visitor=%s", diagnostic_id, visitor)
        raise HTTPException(500, f"Could not initialize your credit account. Diagnostic ID: {diagnostic_id}") from exc
    if not ok:
        raise HTTPException(402, detail={"code":"OUT_OF_CREDITS","message":"You are out of credits. Please buy more credits to continue.","credits":remaining or 0,"cost":cost})
    db = Session()
    try:
        db.add(Download(job_id=job, visitor_id=visitor, url=url, title="Preparing...", status="queued", kind=kind))
        db.commit()
    except Exception:
        db.rollback()
        try: refund_download_credits(visitor, job, cost)
        except Exception: log.exception("Could not refund credits after queue insert failure")
        raise
    finally: db.close()
    out = JSONResponse({"ok":True, "job_id":job, "status":"queued", "platform":platform(url), "kind":kind})
    if not vexdou_visitor:
        # Secure cookies are required on HTTPS, but disabling Secure here keeps
        # local HTTP testing functional. Production should always use HTTPS.
        out.set_cookie(
            "vexdou_visitor",
            visitor,
            max_age=31536000,
            httponly=True,
            samesite="lax",
            secure=bool(os.getenv("COOKIE_SECURE", "true").lower() in {"1","true","yes","on"}),
        )
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
        seen = set()
        for r in rows:
            s = serialize(r)
            if s["status"] != "completed":
                continue
            # Prevent the same media request from appearing twice in History.
            # Keep the newest completed record when duplicate jobs exist.
            key = (str(r.url).strip().rstrip("/"), r.kind)
            if key in seen:
                continue
            seen.add(key)
            items.append(s)
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

@app.get("/api/preview/{job}")
def preview(job: str, vexdou_visitor: str | None = Cookie(default=None)):
    """Inline media response for the HTML5 video/audio player."""
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
                            headers={"Accept-Ranges":"bytes", "Cache-Control":"private,max-age=3600"})
    finally:
        db.close()

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

# --- Credits + PayPal ---
class PackageRequest(BaseModel):
    package_id: str

@app.get("/api/account")
def api_account(vexdou_visitor: str | None = Cookie(default=None)):
    visitor = vexdou_visitor or uuid.uuid4().hex
    data = account_payload(visitor)
    out = JSONResponse({"ok":True, **data})
    if not vexdou_visitor:
        out.set_cookie("vexdou_visitor", visitor, max_age=31536000, httponly=True, samesite="lax", secure=True, path="/")
    return out

@app.get("/api/credits/packages")
def credit_packages():
    return {"currency":PAYPAL_CURRENCY,"video_cost":VIDEO_CREDIT_COST,"monthly_free":MONTHLY_FREE_CREDITS,"packages":[{"id":k,**v} for k,v in CREDIT_PACKAGES.items()]}

@app.get("/api/credits/transactions")
def credit_transactions(vexdou_visitor: str | None = Cookie(default=None), limit: int = 50):
    if not vexdou_visitor: return {"items":[]}
    db=Session()
    try:
        rows=db.scalars(select(CreditTransaction).where(CreditTransaction.visitor_id==vexdou_visitor).order_by(CreditTransaction.created_at.desc()).limit(max(1,min(limit,100)))).all()
        return {"items":[{"type":r.tx_type,"credits":r.credits,"amount":r.amount,"currency":r.currency,"package_id":r.package_id,"status":r.status,"note":r.note,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

@app.get("/api/credits/health")
def credits_health(vexdou_visitor: str | None = Cookie(default=None)):
    """Safe diagnostic endpoint for the credit initialization path."""
    visitor = vexdou_visitor or uuid.uuid4().hex
    db = Session()
    try:
        account = ensure_credit_account(db, visitor)
        payload = {
            "ok": True,
            "has_cookie": bool(vexdou_visitor),
            "visitor_id_length": len(visitor),
            "credits": credit_balance(account),
            "unlimited": bool(getattr(account, "unlimited", False)),
            "month": account.month_key,
            "db": engine.dialect.name,
        }
        db.commit()
        out = JSONResponse(payload)
        if not vexdou_visitor:
            out.set_cookie("vexdou_visitor", visitor, max_age=31536000, httponly=True, samesite="lax", secure=True, path="/")
        return out
    except Exception as exc:
        db.rollback()
        log.exception("credit health failed visitor=%s", visitor)
        return JSONResponse(status_code=500, content={
            "ok": False,
            "error": "credit_account_initialization_failed",
            "message": str(exc)[:500],
            "db": engine.dialect.name,
        })
    finally:
        db.close()

@app.get("/paypal-api/health")
def paypal_health():
    """Non-secret PayPal connectivity check for deployment diagnostics."""
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        return {"ok": False, "configured": False, "mode": PAYPAL_MODE, "message": "Missing PayPal credentials."}
    try:
        token = paypal_token()
        return {"ok": bool(token), "configured": True, "mode": PAYPAL_MODE, "client_id_suffix": PAYPAL_CLIENT_ID[-8:], "base_url": paypal_base()}
    except HTTPException as exc:
        detail = str(exc.detail)
        return {"ok": False, "configured": True, "mode": PAYPAL_MODE, "client_id_suffix": PAYPAL_CLIENT_ID[-8:], "base_url": paypal_base(), "status_code": exc.status_code, "message": detail}

@app.post("/paypal-api/checkout/orders/create")
def paypal_create_order(data: PackageRequest, vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(401,"Your QuickDL session is missing. Refresh and try again.")
    package = CREDIT_PACKAGES.get(data.package_id)
    if not package: raise HTTPException(400,"Invalid credit package.")
    amount = Decimal(package["price"])
    payload = {"intent":"CAPTURE","purchase_units":[{"reference_id":data.package_id,"custom_id":data.package_id,"description":f"QuickDL {package['credits']} Credits","amount":{"currency_code":PAYPAL_CURRENCY,"value":f"{amount:.2f}"}}]}
    order = paypal_json("POST","/v2/checkout/orders",payload,request_id=uuid.uuid4().hex)
    order_id = order.get("id")
    if not order_id: raise HTTPException(502,"PayPal did not return an order ID.")
    db=Session()
    try:
        db.add(PayPalOrder(order_id=order_id,visitor_id=vexdou_visitor,package_id=data.package_id,credits=package["credits"],amount=f"{amount:.2f}",currency=PAYPAL_CURRENCY,status="created"))
        db.commit()
    finally: db.close()
    return {"id":order_id}

@app.post("/paypal-api/checkout/orders/{order_id}/capture")
def paypal_capture_order(order_id: str, vexdou_visitor: str | None = Cookie(default=None)):
    if not vexdou_visitor: raise HTTPException(401,"QuickDL session missing.")
    db=Session()
    try:
        po=db.scalar(select(PayPalOrder).where(PayPalOrder.order_id==order_id,PayPalOrder.visitor_id==vexdou_visitor).with_for_update())
        if not po: raise HTTPException(404,"Payment order not found.")
        if po.status=="captured": return {"ok":True,"already_credited":True,"credits":account_payload(vexdou_visitor)["credits"]}
        package=CREDIT_PACKAGES.get(po.package_id)
        if not package: raise HTTPException(400,"Credit package no longer exists.")
    finally: db.close()
    capture=paypal_json("POST",f"/v2/checkout/orders/{order_id}/capture",{})
    status=capture.get("status")
    if status != "COMPLETED": raise HTTPException(402,"PayPal payment was not completed.")
    captures=(capture.get("purchase_units") or [{}])[0].get("payments",{}).get("captures",[]) or []
    cap=captures[0] if captures else {}
    capture_id=cap.get("id")
    db=Session()
    try:
        po=db.scalar(select(PayPalOrder).where(PayPalOrder.order_id==order_id,PayPalOrder.visitor_id==vexdou_visitor).with_for_update())
        if not po: raise HTTPException(404,"Payment order not found.")
        if po.status != "captured":
            account=ensure_credit_account(db,vexdou_visitor)
            account.purchased_credits += po.credits
            account.updated_at=datetime.now(timezone.utc)
            po.status="captured"; po.capture_id=capture_id; po.captured_at=datetime.now(timezone.utc)
            db.add(CreditTransaction(visitor_id=vexdou_visitor,tx_type="purchase",credits=po.credits,amount=po.amount,currency=po.currency,package_id=po.package_id,paypal_order_id=order_id,paypal_capture_id=capture_id,status="completed",note=f"PayPal purchase: {package['name']}"))
            db.commit()
        balance=account_payload(vexdou_visitor)
        return {"ok":True,"credits_added":po.credits,"balance":balance["credits"],"order_id":order_id,"capture_id":capture_id}
    finally: db.close()

@app.post("/paypal-api/webhook")
@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    if not PAYPAL_WEBHOOK_ID:
        return {"ok":True,"ignored":True}
    raw = await request.body()
    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400,"Invalid webhook payload")
    headers = {k.lower():v for k,v in request.headers.items()}
    required = ["paypal-auth-algo","paypal-cert-url","paypal-transmission-id","paypal-transmission-sig","paypal-transmission-time"]
    if any(not headers.get(k) for k in required):
        raise HTTPException(400,"Missing PayPal webhook signature headers")
    verify_payload = {
        "auth_algo": headers["paypal-auth-algo"],
        "cert_url": headers["paypal-cert-url"],
        "transmission_id": headers["paypal-transmission-id"],
        "transmission_sig": headers["paypal-transmission-sig"],
        "transmission_time": headers["paypal-transmission-time"],
        "webhook_id": PAYPAL_WEBHOOK_ID,
        "webhook_event": event,
    }
    token = paypal_token()
    vr = requests.post(paypal_base()+"/v1/notifications/verify-webhook-signature",headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},json=verify_payload,timeout=30)
    if vr.status_code >= 400 or vr.json().get("verification_status") != "SUCCESS":
        raise HTTPException(401,"Invalid PayPal webhook signature")
    if event.get("event_type") != "PAYMENT.CAPTURE.COMPLETED":
        return {"ok":True,"ignored":True}
    resource = event.get("resource") or {}
    related = ((resource.get("supplementary_data") or {}).get("related_ids") or {})
    order_id = related.get("order_id")
    capture_id = resource.get("id")
    if not order_id:
        return {"ok":True,"ignored":True}
    db=Session()
    try:
        po=db.scalar(select(PayPalOrder).where(PayPalOrder.order_id==order_id).with_for_update())
        if not po or po.status=="captured": return {"ok":True,"already_processed":True}
        account=ensure_credit_account(db,po.visitor_id)
        account.purchased_credits += po.credits
        account.updated_at=datetime.now(timezone.utc)
        po.status="captured"; po.capture_id=capture_id; po.captured_at=datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=po.visitor_id,tx_type="purchase",credits=po.credits,amount=po.amount,currency=po.currency,package_id=po.package_id,paypal_order_id=order_id,paypal_capture_id=capture_id,status="completed",note="PayPal webhook purchase"))
        db.commit()
        return {"ok":True,"credited":po.credits}
    finally: db.close()

# --- Admin18 control center ---
import hashlib, hmac, base64

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
    "max_concurrent_jobs": os.getenv("MAX_CONCURRENT_JOBS", "2"),
    "monthly_free_credits": str(MONTHLY_FREE_CREDITS),
    "video_credit_cost": str(VIDEO_CREDIT_COST),
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

@app.get("/api/admin/system")
def admin_system(request: Request):
    require_admin(request)
    db=Session()
    try:
        counts={}
        for st in ("queued","downloading","completed","failed"):
            counts[st]=db.scalar(select(func.count()).select_from(Download).where(Download.status==st)) or 0
        return {
            "version":"17.0.0",
            "python":os.sys.version.split()[0],
            "yt_dlp":getattr(yt_dlp,"version",{}).get("version") if isinstance(getattr(yt_dlp,"version",None),dict) else str(getattr(yt_dlp,"version","unknown")),
            "ffmpeg":shutil.which("ffmpeg") or "missing",
            "node":shutil.which("node") or "missing",
            "work_dir":str(WORK),
            "work_exists":WORK.exists(),
            "worker":WORKER_HEARTBEAT,
            "downloads":counts,
            "paypal_mode":PAYPAL_MODE,
            "paypal_configured":bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET),
            "paypal_base":paypal_base(),
            "settings":settings_all(),
        }
    finally: db.close()

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
    out.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=43200,
        httponly=True,
        secure=False,
        samesite="strict",
        path="/",
    )
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

class AdminCreditAction(BaseModel):
    visitor_id: str
    credits: int = 0
    unlimited: bool | None = None
    note: str = "Admin adjustment"

@app.get("/api/admin/credit-users")
def admin_credit_users(request: Request, q: str = "", limit: int = 100):
    require_admin(request); limit=max(1,min(limit,500)); db=Session()
    try:
        accounts=db.scalars(select(CreditAccount).order_by(CreditAccount.updated_at.desc()).limit(1000)).all()
        downloads=db.scalars(select(Download).order_by(Download.created_at.desc()).limit(5000)).all()
        counts={}
        for r in downloads:
            x=counts.setdefault(r.visitor_id,{"downloads":0,"completed":0,"failed":0,"last_seen":r.created_at})
            x["downloads"]+=1; x["completed"]+=int(r.status=="completed"); x["failed"]+=int(r.status=="failed")
            if r.created_at and (not x.get("last_seen") or r.created_at>x["last_seen"]): x["last_seen"]=r.created_at
        q=(q or "").strip().lower(); items=[]
        for a in accounts:
            if q and q not in a.visitor_id.lower(): continue
            c=counts.get(a.visitor_id,{})
            items.append({"visitor_id":a.visitor_id,"credits":credit_balance(a),"free_credits":a.free_credits,"purchased_credits":a.purchased_credits,"unlimited":bool(getattr(a,"unlimited",False)),"last_seen":c.get("last_seen").isoformat() if c.get("last_seen") else None,"downloads":c.get("downloads",0),"completed":c.get("completed",0),"failed":c.get("failed",0),"updated_at":a.updated_at.isoformat() if a.updated_at else None,"last_seen":c.get("last_seen").isoformat() if c.get("last_seen") else None})
        return {"items":items[:limit]}
    finally: db.close()

@app.get("/api/admin/user/{visitor_id}")
def admin_user_detail(visitor_id: str, request: Request):
    require_admin(request)
    db=Session()
    try:
        a=ensure_credit_account(db,visitor_id); db.commit()
        rows=db.scalars(select(CreditTransaction).where(CreditTransaction.visitor_id==visitor_id).order_by(CreditTransaction.created_at.desc()).limit(100)).all()
        downloads=db.scalars(select(Download).where(Download.visitor_id==visitor_id).order_by(Download.created_at.desc()).limit(100)).all()
        return {
            "account": account_payload(visitor_id),
            "transactions":[{"type":r.tx_type,"credits":r.credits,"amount":r.amount,"currency":r.currency,"package_id":r.package_id,"status":r.status,"note":r.note,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows],
            "downloads":[{"job_id":r.job_id,"url":r.url,"title":r.title,"platform":platform(r.url),"status":r.status,"error":r.error,"created_at":r.created_at.isoformat() if r.created_at else None} for r in downloads],
        }
    finally: db.close()

@app.post("/api/admin/credits/grant")
def admin_grant_credits(data: AdminCreditAction, request: Request):
    require_admin(request)
    if len(data.visitor_id)>128 or data.credits<0: raise HTTPException(400,"Invalid credit adjustment")
    db=Session()
    try:
        a=ensure_credit_account(db,data.visitor_id)
        if data.credits:
            a.purchased_credits += data.credits
            db.add(CreditTransaction(visitor_id=data.visitor_id,tx_type="admin_grant",credits=data.credits,status="completed",note=data.note[:1000]))
        if data.unlimited is not None:
            a.unlimited=bool(data.unlimited)
            db.add(CreditTransaction(visitor_id=data.visitor_id,tx_type="admin_unlimited",credits=0,status="completed",note=("Unlimited enabled" if a.unlimited else "Unlimited disabled")+" · "+data.note[:900]))
        a.updated_at=datetime.now(timezone.utc); db.commit(); audit("admin_credit_adjustment",f"{data.visitor_id}: +{data.credits}, unlimited={data.unlimited}")
        return {"ok":True,**account_payload(data.visitor_id)}
    finally: db.close()

@app.post("/api/admin/credits/revoke")
def admin_revoke_credits(data: AdminCreditAction, request: Request):
    require_admin(request)
    if data.credits<0: raise HTTPException(400,"Invalid amount")
    db=Session()
    try:
        a=ensure_credit_account(db,data.visitor_id); amount=min(data.credits,max(0,int(a.purchased_credits or 0))); a.purchased_credits-=amount; a.updated_at=datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=data.visitor_id,tx_type="admin_revoke",credits=-amount,status="completed",note=data.note[:1000])); db.commit(); audit("admin_credit_revoke",f"{data.visitor_id}: -{amount}")
        return {"ok":True,**account_payload(data.visitor_id)}
    finally: db.close()

@app.post("/api/admin/credits/reset")
def admin_reset_credits(data: AdminCreditAction, request: Request):
    require_admin(request); db=Session()
    try:
        a=ensure_credit_account(db,data.visitor_id); old=credit_balance(a) or 0; a.free_credits=MONTHLY_FREE_CREDITS; a.purchased_credits=0; a.unlimited=False; a.updated_at=datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=data.visitor_id,tx_type="admin_reset",credits=-int(old),status="completed",note=data.note[:1000])); db.commit(); audit("admin_credit_reset",data.visitor_id)
        return {"ok":True,**account_payload(data.visitor_id)}
    finally: db.close()

@app.get("/api/admin/revenue")
def admin_revenue(request: Request):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(CreditTransaction).where(CreditTransaction.tx_type=="purchase",CreditTransaction.status=="completed").order_by(CreditTransaction.created_at.desc()).limit(5000)).all()
        total=sum(float(r.amount or 0) for r in rows); credits=sum(int(r.credits or 0) for r in rows)
        return {"total_revenue":round(total,2),"purchased_credits":credits,"transactions":len(rows),"items":[{"visitor_id":r.visitor_id,"amount":r.amount,"currency":r.currency,"credits":r.credits,"package_id":r.package_id,"order_id":r.paypal_order_id,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows[:100]]}
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

@app.post("/api/admin/download/retry")
def admin_retry_download(data: AdminAction, request: Request):
    require_admin(request); db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==data.value))
        if not row: raise HTTPException(404,"Download not found")
        if row.status=="downloading": raise HTTPException(409,"Download is already running")
        row.status="queued"; row.error=None; row.filename=None; row.content_type=None; db.commit(); audit("admin_retry_download",data.value); return {"ok":True}
    finally: db.close()

@app.post("/api/admin/download/delete")
def admin_delete_download(data: AdminAction, request: Request):
    require_admin(request); db=Session()
    try:
        row=db.scalar(select(Download).where(Download.job_id==data.value))
        if not row: raise HTTPException(404,"Download not found")
        cleanup_job(row.job_id); db.delete(row); db.commit(); audit("admin_delete_download",data.value); return {"ok":True}
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

