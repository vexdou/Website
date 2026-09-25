import os, re, time, uuid, mimetypes, logging, threading, ipaddress, socket, shutil, json, secrets, smtplib, ssl, hashlib, hmac, base64, asyncio
from email.message import EmailMessage
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
from fastapi import FastAPI, HTTPException, Cookie, Request, Header, Depends
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, String, Text, Integer, DateTime, select, update, delete, func
from sqlalchemy.exc import IntegrityError, OperationalError
try:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
except Exception:
    pg_insert = None
try:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
except Exception:
    sqlite_insert = None
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests
except Exception:
    google_id_token = None
    google_requests = None
from contextlib import asynccontextmanager
from telegram_mtproto import configured as telegram_mtproto_configured, encrypt_session as telegram_encrypt_session, decrypt_session as telegram_decrypt_session, send_code as telegram_send_code, sign_in as telegram_sign_in, check_password as telegram_check_password, get_me as telegram_get_me, dialogs as telegram_dialogs, messages as telegram_messages, send_message as telegram_send_message

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

DB_POOL_SIZE = max(1, int(os.getenv("DB_POOL_SIZE", "2")))
DB_MAX_OVERFLOW = max(0, int(os.getenv("DB_MAX_OVERFLOW", "2")))
_engine_kwargs = dict(pool_pre_ping=True, pool_recycle=300, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW)
if DB_URL.startswith("postgresql+"):
    _engine_kwargs["connect_args"] = {"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10"))}
engine = create_engine(DB_URL, **_engine_kwargs)
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
    user_code: Mapped[str | None] = mapped_column(String(10), unique=True, nullable=True, index=True)
    free_credits: Mapped[int] = mapped_column(Integer, default=50)
    purchased_credits: Mapped[int] = mapped_column(Integer, default=0)
    month_key: Mapped[str] = mapped_column(String(7), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    unlimited: Mapped[bool] = mapped_column(Boolean, default=False)
    google_sub: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    google_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    google_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    google_picture: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    google_welcome_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    welcome_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_auth_date: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_broadcast_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_last_broadcast_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_session_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_pending_session_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_pending_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    telegram_pending_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_admin_chat_access: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_admin_chat_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    auth_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_code_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reset_code_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reset_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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

class AppError(Base):
    __tablename__ = "app_errors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(32), index=True)
    method: Mapped[str] = mapped_column(String(12), default="GET")
    path: Mapped[str] = mapped_column(Text)
    status: Mapped[int] = mapped_column(Integer, default=500)
    error_type: Mapped[str] = mapped_column(String(160), default="Exception")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

Base.metadata.create_all(engine)

def migrate_credit_columns():
    """Best-effort, restart-safe schema migration for existing Render databases.

    Each ALTER is committed independently so one old/odd index cannot roll back the
    whole migration. Existing users also receive a stable 10-digit public user code.
    """
    try:
        dialect = engine.dialect.name
        if dialect == "postgresql":
            additions = [
                ("credit_accounts", "visitor_id", "VARCHAR(128)"),
                ("credit_accounts", "user_code", "VARCHAR(10)"),
                ("credit_accounts", "free_credits", "INTEGER NOT NULL DEFAULT 50"),
                ("credit_accounts", "purchased_credits", "INTEGER NOT NULL DEFAULT 0"),
                ("credit_accounts", "month_key", "VARCHAR(7) NOT NULL DEFAULT ''"),
                ("credit_accounts", "created_at", "TIMESTAMPTZ DEFAULT NOW()"),
                ("credit_accounts", "updated_at", "TIMESTAMPTZ DEFAULT NOW()"),
                ("credit_accounts", "unlimited", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("credit_accounts", "google_sub", "VARCHAR(128)"),
                ("credit_accounts", "google_email", "VARCHAR(320)"),
                ("credit_accounts", "google_name", "VARCHAR(200)"),
                ("credit_accounts", "google_picture", "TEXT"),
                ("credit_accounts", "google_linked_at", "TIMESTAMPTZ"),
                ("credit_accounts", "google_welcome_sent_at", "TIMESTAMPTZ"),
                ("credit_accounts", "welcome_email_sent_at", "TIMESTAMPTZ"),
                ("credit_accounts", "telegram_id", "VARCHAR(32)"),
                ("credit_accounts", "telegram_username", "VARCHAR(255)"),
                ("credit_accounts", "telegram_first_name", "VARCHAR(255)"),
                ("credit_accounts", "telegram_last_name", "VARCHAR(255)"),
                ("credit_accounts", "telegram_photo_url", "TEXT"),
                ("credit_accounts", "telegram_auth_date", "BIGINT"),
                ("credit_accounts", "telegram_linked_at", "TIMESTAMPTZ"),
                ("credit_accounts", "telegram_broadcast_opt_in", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("credit_accounts", "telegram_consent_at", "TIMESTAMPTZ"),
                ("credit_accounts", "telegram_last_broadcast_at", "TIMESTAMPTZ"),
                ("credit_accounts", "telegram_session_encrypted", "TEXT"),
                ("credit_accounts", "telegram_pending_session_encrypted", "TEXT"),
                ("credit_accounts", "telegram_pending_phone", "VARCHAR(40)"),
                ("credit_accounts", "telegram_pending_code_hash", "VARCHAR(255)"),
                ("credit_accounts", "telegram_admin_chat_access", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("credit_accounts", "telegram_admin_chat_access_at", "TIMESTAMPTZ"),
                ("credit_accounts", "telegram_last_active_at", "TIMESTAMPTZ"),
                ("credit_accounts", "email", "VARCHAR(320)"),
                ("credit_accounts", "auth_name", "VARCHAR(200)"),
                ("credit_accounts", "password_hash", "TEXT"),
                ("credit_accounts", "email_verified", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("credit_accounts", "email_code_hash", "VARCHAR(128)"),
                ("credit_accounts", "email_code_expires_at", "TIMESTAMPTZ"),
                ("credit_accounts", "reset_code_hash", "VARCHAR(128)"),
                ("credit_accounts", "reset_code_expires_at", "TIMESTAMPTZ"),
                ("credit_transactions", "visitor_id", "VARCHAR(128)"),
                ("credit_transactions", "tx_type", "VARCHAR(40) DEFAULT 'adjustment'"),
                ("credit_transactions", "credits", "INTEGER NOT NULL DEFAULT 0"),
                ("credit_transactions", "amount", "VARCHAR(32)"),
                ("credit_transactions", "currency", "VARCHAR(8)"),
                ("credit_transactions", "package_id", "VARCHAR(40)"),
                ("credit_transactions", "paypal_order_id", "VARCHAR(80)"),
                ("credit_transactions", "paypal_capture_id", "VARCHAR(80)"),
                ("credit_transactions", "status", "VARCHAR(30) DEFAULT 'completed'"),
                ("credit_transactions", "note", "TEXT"),
                ("credit_transactions", "created_at", "TIMESTAMPTZ DEFAULT NOW()"),
                ("paypal_orders", "order_id", "VARCHAR(80)"),
                ("paypal_orders", "visitor_id", "VARCHAR(128)"),
                ("paypal_orders", "package_id", "VARCHAR(40)"),
                ("paypal_orders", "credits", "INTEGER DEFAULT 0"),
                ("paypal_orders", "amount", "VARCHAR(32) DEFAULT '0.00'"),
                ("paypal_orders", "currency", "VARCHAR(8) DEFAULT 'USD'"),
                ("paypal_orders", "status", "VARCHAR(30) DEFAULT 'created'"),
                ("paypal_orders", "capture_id", "VARCHAR(80)"),
                ("paypal_orders", "created_at", "TIMESTAMPTZ DEFAULT NOW()"),
                ("paypal_orders", "captured_at", "TIMESTAMPTZ"),
            ]
            for table, col, typ in additions:
                try:
                    with engine.begin() as conn:
                        exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar()
                        if exists:
                            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}'))
                except Exception:
                    log.exception("schema migration column failed: %s.%s", table, col)
            # Indexes are intentionally independent from column migration.
            for stmt in [
                "CREATE INDEX IF NOT EXISTS ix_credit_accounts_user_code ON credit_accounts(user_code)",
                "CREATE INDEX IF NOT EXISTS ix_credit_transactions_visitor_id ON credit_transactions(visitor_id)",
                "CREATE INDEX IF NOT EXISTS ix_paypal_orders_visitor_id ON paypal_orders(visitor_id)",
                "CREATE INDEX IF NOT EXISTS ix_credit_accounts_email ON credit_accounts(email)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_accounts_visitor_id ON credit_accounts(visitor_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_accounts_telegram_id ON credit_accounts(telegram_id) WHERE telegram_id IS NOT NULL",
            ]:
                try:
                    with engine.begin() as conn: conn.execute(text(stmt))
                except Exception: log.exception("schema migration index failed: %s", stmt)
        elif dialect == "sqlite":
            with engine.begin() as conn:
                for table, fields in {
                    "credit_accounts": {"visitor_id":"TEXT", "user_code":"TEXT", "free_credits":"INTEGER NOT NULL DEFAULT 50", "purchased_credits":"INTEGER NOT NULL DEFAULT 0", "month_key":"TEXT NOT NULL DEFAULT ''", "created_at":"DATETIME", "updated_at":"DATETIME", "unlimited":"INTEGER NOT NULL DEFAULT 0", "google_sub":"TEXT", "google_email":"TEXT", "google_name":"TEXT", "google_picture":"TEXT", "google_linked_at":"DATETIME", "google_welcome_sent_at":"DATETIME", "welcome_email_sent_at":"DATETIME", "telegram_id":"TEXT", "telegram_username":"TEXT", "telegram_first_name":"TEXT", "telegram_last_name":"TEXT", "telegram_photo_url":"TEXT", "telegram_auth_date":"INTEGER", "telegram_linked_at":"DATETIME", "telegram_broadcast_opt_in":"INTEGER NOT NULL DEFAULT 0", "telegram_consent_at":"DATETIME", "telegram_last_broadcast_at":"DATETIME", "telegram_session_encrypted":"TEXT", "telegram_pending_session_encrypted":"TEXT", "telegram_pending_phone":"TEXT", "telegram_pending_code_hash":"TEXT", "telegram_admin_chat_access":"INTEGER NOT NULL DEFAULT 0", "telegram_admin_chat_access_at":"DATETIME", "telegram_last_active_at":"DATETIME", "email":"TEXT", "auth_name":"TEXT", "password_hash":"TEXT", "email_verified":"INTEGER NOT NULL DEFAULT 0", "email_code_hash":"TEXT", "email_code_expires_at":"DATETIME", "reset_code_hash":"TEXT", "reset_code_expires_at":"DATETIME"},
                    "credit_transactions": {"visitor_id":"TEXT", "tx_type":"TEXT DEFAULT 'adjustment'", "credits":"INTEGER NOT NULL DEFAULT 0", "amount":"TEXT", "currency":"TEXT", "package_id":"TEXT", "paypal_order_id":"TEXT", "paypal_capture_id":"TEXT", "status":"TEXT DEFAULT 'completed'", "note":"TEXT", "created_at":"DATETIME"},
                    "paypal_orders": {"order_id":"TEXT", "visitor_id":"TEXT", "package_id":"TEXT", "credits":"INTEGER DEFAULT 0", "amount":"TEXT DEFAULT '0.00'", "currency":"TEXT DEFAULT 'USD'", "status":"TEXT DEFAULT 'created'", "capture_id":"TEXT", "created_at":"DATETIME", "captured_at":"DATETIME"},
                }.items():
                    existing={r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
                    for col, typ in fields.items():
                        if col not in existing: conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
    except Exception:
        log.exception("database schema migration failed")


def make_user_code(db):
    for _ in range(30):
        code = str(secrets.randbelow(9_000_000_000) + 1_000_000_000)
        if not db.scalar(select(CreditAccount).where(CreditAccount.user_code == code)):
            return code
    raise RuntimeError("Could not allocate a unique 10-digit user ID")

def backfill_user_codes():
    db = Session()
    try:
        rows = db.scalars(select(CreditAccount).where((CreditAccount.user_code == None) | (CreditAccount.user_code == ""))).all()
        for account in rows: account.user_code = make_user_code(db)
        if rows: db.commit()
    except Exception:
        db.rollback(); log.exception("user code backfill failed")
    finally: db.close()

migrate_credit_columns()

# Existing accounts from older QuickDL versions receive a stable 10-digit ID.
backfill_user_codes()
try:
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_accounts_user_code ON credit_accounts(user_code)"))
        elif conn.dialect.name == "sqlite":
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_accounts_user_code ON credit_accounts(user_code)"))
except Exception:
    log.exception("user code unique index could not be created")

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
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_AUTH_MAX_AGE = max(60, int(os.getenv("TELEGRAM_AUTH_MAX_AGE", "600")))
TELEGRAM_BOT_USERNAME = "Antartickgaaf_bot"
TELEGRAM_ADMIN_PASSWORD = os.getenv("TELEGRAM_ADMIN_PASSWORD", "").strip()
TELEGRAM_BROADCAST_DELAY = max(0.05, float(os.getenv("TELEGRAM_BROADCAST_DELAY", "0.12")))
telegram_admin_security = HTTPBasic()
SMTP_HOST = os.getenv("SMTP_HOST", "mail.spacemail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", os.getenv("SPACEMAIL_USER", "support@quickdl.site")).strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", os.getenv("SPACEMAIL_PASSWORD", "")).strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", "QuickDL <support@quickdl.site>").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM", EMAIL_FROM).strip()
RESEND_REPLY_TO = os.getenv("RESEND_REPLY_TO", "").strip()
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "auto").strip().lower()
# If no email provider is configured, QuickDL can still create email/password accounts.
# Verification remains enabled automatically whenever Resend/SMTP is configured.
EMAIL_AUTH_REQUIRE_VERIFICATION = os.getenv("EMAIL_AUTH_REQUIRE_VERIFICATION", "false").lower() in {"1","true","yes","on"}
AUTH_CODE_MINUTES = max(5, int(os.getenv("AUTH_CODE_MINUTES", "10")))
PAYPAL_TOKEN_CACHE = {"token": None, "expires_at": 0}
WORKER_HEARTBEAT = {"started_at": None, "last_loop": None, "last_job": None, "last_error": None, "jobs_completed": 0, "jobs_failed": 0}
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
    """Get/create a credit account without relying on a fragile user_code insert.

    The legacy database may already exist with older indexes.  The safest path is:
    1) serialize this visitor with a PostgreSQL advisory transaction lock;
    2) read the existing account;
    3) insert with user_code=NULL so a random user-code collision cannot abort creation;
    4) re-read the row;
    5) assign the public user_code in a separate savepoint.

    PostgreSQL ON CONFLICT DO NOTHING without an explicit target is deliberately used
    here because it can tolerate any existing unique constraint/index in an older
    schema. The advisory lock prevents two QuickDL workers from creating the same
    visitor concurrently even if the old database is missing the expected index.
    """
    if not visitor_id or not re.fullmatch(r"[a-f0-9]{32}", str(visitor_id)):
        raise ValueError("invalid visitor_id")

    month = current_month_key()
    try:
        monthly_free = max(0, int(setting_get("monthly_free_credits", db) or MONTHLY_FREE_CREDITS))
    except Exception:
        log.exception("monthly credit setting read failed; using default")
        monthly_free = max(0, MONTHLY_FREE_CREDITS)
    now = datetime.now(timezone.utc)
    dialect = db.bind.dialect.name if db.bind is not None else ""

    if dialect == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:visitor_id))"), {"visitor_id": str(visitor_id)})

    account = db.scalar(
        select(CreditAccount).where(CreditAccount.visitor_id == visitor_id).limit(1).with_for_update()
    )

    if account is None:
        values = dict(
            visitor_id=visitor_id,
            user_code=None,
            free_credits=monthly_free,
            purchased_credits=0,
            month_key=month,
            created_at=now,
            updated_at=now,
            unlimited=False,
        )
        last_error = None
        for attempt in range(3):
            try:
                with db.begin_nested():
                    if dialect == "postgresql" and pg_insert is not None:
                        db.execute(pg_insert(CreditAccount).values(**values).on_conflict_do_nothing())
                    elif dialect == "sqlite" and sqlite_insert is not None:
                        db.execute(sqlite_insert(CreditAccount).values(**values).on_conflict_do_nothing())
                    else:
                        db.add(CreditAccount(**values))
                        db.flush()
                account = db.scalar(
                    select(CreditAccount).where(CreditAccount.visitor_id == visitor_id).limit(1).with_for_update()
                )
                if account is not None:
                    break
            except IntegrityError as exc:
                last_error = exc
                # The savepoint is rolled back automatically; re-read in case another
                # worker/process already created the row.
                try:
                    account = db.scalar(
                        select(CreditAccount).where(CreditAccount.visitor_id == visitor_id).limit(1).with_for_update()
                    )
                except Exception:
                    account = None
                if account is not None:
                    break
                time.sleep(0.05 * (attempt + 1))
            except Exception as exc:
                # Do not hide the real database error in logs. The browser still gets
                # a safe message, while the server log contains the exact exception.
                log.exception("credit account insert failed visitor=%s attempt=%s", visitor_id, attempt + 1)
                raise

        if account is None:
            if last_error:
                log.exception("credit account creation failed after savepoint retries: %s", last_error)
            raise RuntimeError("credit account could not be created; database schema/index mismatch")

    if not account.user_code:
        assigned = False
        for _ in range(50):
            code = str(secrets.randbelow(9_000_000_000) + 1_000_000_000)
            try:
                with db.begin_nested():
                    account.user_code = code
                    db.flush()
                assigned = True
                break
            except IntegrityError:
                try:
                    db.refresh(account)
                except Exception:
                    pass
                if account.user_code:
                    assigned = True
                    break
        if not assigned or not account.user_code:
            raise RuntimeError("credit account user ID could not be assigned")

    if not free_mode_enabled() and account.month_key != month:
        account.month_key = month
        account.free_credits = monthly_free
        account.updated_at = now
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

def repair_database_schema():
    """Best-effort runtime repair for older Render databases.

    Deployments can survive across schema generations; if a request hits an
    older database before the startup migration completed, repair the schema
    and retry the request instead of leaving Account/Credits/Download unusable.
    """
    try:
        Base.metadata.create_all(engine)
    except Exception:
        log.exception("runtime create_all failed")
    try:
        migrate_credit_columns()
    except Exception:
        log.exception("runtime credit migration failed")
    try:
        backfill_user_codes()
    except Exception:
        log.exception("runtime user-code backfill failed")


def account_payload(visitor_id):
    last_exc = None
    for attempt in range(2):
        db = Session()
        try:
            account = ensure_credit_account(db, visitor_id)
            try:
                monthly_free = max(0, int(setting_get("monthly_free_credits", db) or MONTHLY_FREE_CREDITS))
            except Exception:
                log.exception("account monthly setting read failed; using default")
                monthly_free = max(0, MONTHLY_FREE_CREDITS)
            try:
                video_cost = max(0, int(setting_get("video_credit_cost", db) or VIDEO_CREDIT_COST))
            except Exception:
                log.exception("account video-cost setting read failed; using default")
                video_cost = max(0, VIDEO_CREDIT_COST)
            db.commit()
            telegram_authenticated = bool(getattr(account, "telegram_id", None))
            authenticated = bool(account.google_sub or account.email_verified or telegram_authenticated)
            display_name = (account.telegram_first_name or account.telegram_username or account.google_name or account.auth_name or account.google_email or account.email)
            return {"visitor_id": visitor_id, "user_code": account.user_code, "free_credits": int(account.free_credits or 0), "purchased_credits": int(account.purchased_credits or 0), "credits": credit_balance(account), "unlimited": bool(getattr(account, "unlimited", False)), "monthly_free": monthly_free, "video_cost": video_cost, "month": account.month_key, "google": bool(account.google_sub), "google_email": account.google_email, "google_name": account.google_name, "google_picture": account.google_picture, "telegram": telegram_authenticated, "telegram_id": account.telegram_id, "telegram_username": account.telegram_username, "telegram_first_name": account.telegram_first_name, "telegram_last_name": account.telegram_last_name, "telegram_photo_url": account.telegram_photo_url, "telegram_broadcast_opt_in": bool(getattr(account, "telegram_broadcast_opt_in", False)), "telegram_consent_at": account.telegram_consent_at.isoformat() if getattr(account, "telegram_consent_at", None) else None, "telegram_admin_chat_access": bool(getattr(account, "telegram_admin_chat_access", False)), "telegram_admin_chat_access_at": account.telegram_admin_chat_access_at.isoformat() if getattr(account, "telegram_admin_chat_access_at", None) else None, "telegram_last_active_at": account.telegram_last_active_at.isoformat() if getattr(account, "telegram_last_active_at", None) else None, "email": account.email, "email_verified": bool(getattr(account, "email_verified", False)), "auth_name": account.auth_name, "authenticated": authenticated, "display_name": display_name, "welcome_email_sent": bool(getattr(account, "welcome_email_sent_at", None) or getattr(account, "google_welcome_sent_at", None))}
        except Exception as exc:
            last_exc = exc
            try: db.rollback()
            except Exception: pass
            if attempt == 0:
                log.exception("account payload failed; attempting schema repair")
                repair_database_schema()
                continue
            raise
        finally:
            db.close()
    raise last_exc or RuntimeError("account initialization failed")
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
    text = re.sub(r"\s+", " ", str(exc)).strip().lower()
    if any(x in text for x in ("private", "drm", "login required", "authentication", "sign in")):
        return "This media could not be downloaded."
    if any(x in text for x in ("429", "too many requests", "rate-limit", "timeout", "timed out")):
        return "The download could not be completed right now. Please try again."
    if any(x in text for x in ("unsupported url", "no suitable extractor")):
        return "This link could not be processed."
    return "The download could not be completed. Please try another link."

def public_og_video_fallback(job, url, kind, source_name):
    """Public-only fallback for pages exposing a direct og:video URL.

    This is deliberately limited to public page metadata. It does not submit
    credentials or bypass private/login/DRM/CAPTCHA protections.
    """
    if kind != "video":
        return None
    headers={
        "User-Agent":UA,
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"en-US,en;q=0.9",
        "Cache-Control":"no-cache",
    }
    last=None
    html=None
    final_url=url
    for attempt in range(3):
        try:
            if attempt: time.sleep(min(2**attempt,5))
            r=_http_get(url,headers=headers,timeout=(15,35))
            if r.status_code in (401,403,429):
                last=RuntimeError(f"{source_name} returned HTTP {r.status_code}")
                continue
            r.raise_for_status()
            html=r.text
            final_url=str(getattr(r,"url",url))
            break
        except Exception as exc:
            last=exc
    if not html:
        log.info("job=%s: %s public page fallback unavailable: %s",job,source_name,last)
        return None
    media_url=(
        _extract_meta(html,"og:video:secure_url")
        or _extract_meta(html,"og:video:url")
        or _extract_meta(html,"og:video")
        or _extract_meta(html,"twitter:player:stream")
    )
    if not media_url:
        candidates=re.findall(r'https?://[^"\'<>\s]+?\.(?:mp4)(?:\?[^"\'<>\s]*)?',html,re.I)
        if candidates: media_url=unescape(candidates[0]).replace("\\/","/").replace("&amp;","&")
    if not media_url or not media_url.startswith(("http://","https://")):
        return None
    out=WORK/f"{job}.mp4"
    max_bytes=int(setting_get("max_file_mb") or MAX_FILE_MB)*1024*1024
    try:
        with _http_get(media_url,headers={"User-Agent":UA,"Referer":final_url},timeout=(15,120),stream=True) as mr:
            mr.raise_for_status()
            total=0
            with open(out,"wb") as fh:
                for chunk in mr.iter_content(chunk_size=1024*256):
                    if not chunk: continue
                    total+=len(chunk)
                    if total>max_bytes: raise RuntimeError("Media exceeds the configured file size limit")
                    fh.write(chunk)
        if not out.exists() or out.stat().st_size<1024:
            out.unlink(missing_ok=True); return None
        return {
            "title":(_extract_meta(html,"og:title") or f"{source_name} Media")[:180],
            "thumbnail":_extract_meta(html,"og:image"),
            "webpage_url":url,
        }
    except Exception as exc:
        out.unlink(missing_ok=True)
        log.info("job=%s: %s public metadata fallback failed: %s",job,source_name,exc)
        return None

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
        "js_runtimes": ({"deno": {}} if shutil.which("deno") else ({"node": {}} if shutil.which("node") else None)),
        "impersonate": "chrome" if curl_requests is not None else None,
        "sleep_interval_requests": 1,
        "sleep_interval": 1,
        "max_sleep_interval": 4,
        "overwrites": True,
        "remote_components": "ejs:npm" if shutil.which("deno") else None,
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
    job_kind = "video"
    try:
        row = db.scalar(select(Download).where(Download.job_id == job))
        if not row: return
        visitor = row.visitor_id
        job_kind = row.kind or "video"
        already_failed = row.status == "failed"
        db.execute(update(Download).where(Download.job_id == job).values(status="failed", error=human_error(error)))
        db.commit()
    finally:
        db.close()
    if visitor and not already_failed:
        WORKER_HEARTBEAT["jobs_failed"] += 1
        if job_kind == "video":
            try: refund_download_credits(visitor, job, int(setting_get("video_credit_cost") or VIDEO_CREDIT_COST))
            except Exception: log.exception("Could not refund credits for failed job %s", job)
        queue_user_email(visitor, "QuickDL download update", "Your download could not be completed", "The download did not finish successfully. The video credits reserved for this job were returned to your account.", "DOWNLOAD UPDATE", "#f05b75")

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
            attempts = [ytdlp_options(job, kind), ytdlp_options(job, kind), ytdlp_options(job, kind)]
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

                # Public metadata fallbacks after yt-dlp fails/rate-limits.
                # Instagram keeps its specialized embed fallback; the generic
                # OG fallback covers public pages that expose a direct MP4 URL.
                if p == "instagram":
                    cleanup_job(job)
                    fallback_info = instagram_public_fallback(job, url, kind)
                    if fallback_info:
                        info = fallback_info
                        log.info("job=%s: Instagram public fallback succeeded", job)
                        break
                if p in {"facebook","tiktok","pinterest","x","snapchat"}:
                    cleanup_job(job)
                    fallback_info = public_og_video_fallback(job,url,kind,p.title())
                    if fallback_info:
                        info=fallback_info
                        log.info("job=%s: %s public OG fallback succeeded",job,p)
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
            # Final public-only fallback if all extractor attempts failed.
            if p == "instagram":
                cleanup_job(job)
                fallback_info = instagram_public_fallback(job, url, kind)
                if fallback_info: info = fallback_info
            elif p in {"facebook","tiktok","pinterest","x","snapchat"}:
                cleanup_job(job)
                fallback_info = public_og_video_fallback(job,url,kind,p.title())
                if fallback_info: info = fallback_info
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
                WORKER_HEARTBEAT["jobs_completed"] += 1
            else: time.sleep(float(os.getenv("WORKER_POLL_SECONDS", "0.7")))
        except Exception as exc:
            WORKER_HEARTBEAT["last_error"] = f"{type(exc).__name__}: {exc}"[:500]
            log.exception("worker error"); time.sleep(2)

@asynccontextmanager
async def lifespan(app):
    # Repair/migrate legacy PostgreSQL schemas before accepting API traffic.
    try:
        repair_database_schema()
        log.info("database schema check completed")
    except Exception:
        log.exception("database startup repair failed")
    threading.Thread(target=worker_loop, daemon=True, name="quickdl-worker").start()
    yield

app = FastAPI(title="QuickDL", version="36.0.0", lifespan=lifespan)

def record_app_error(ref, request, exc, status=500):
    try:
        db = Session()
        try:
            db.add(AppError(reference=ref, method=request.method[:12], path=str(request.url.path)[:2000], status=status, error_type=type(exc).__name__[:160], message=str(exc)[:4000]))
            db.commit()
        finally:
            db.close()
    except Exception:
        log.exception("Could not persist application error ref=%s", ref)

@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    # Never expose framework, database, provider, or hosting details to users.
    # The full exception remains available to the admin Error Center/server logs.
    ref = uuid.uuid4().hex[:12]
    log.exception("Unhandled request error ref=%s %s %s", ref, request.method, request.url.path)
    record_app_error(ref, request, exc, 500)
    return JSONResponse(status_code=500, content={"ok": False, "error": "internal_error", "message": "Something went wrong. Please try again.", "reference": ref})

def _cookie_secure():
    return os.getenv("COOKIE_SECURE", "true").lower() in {"1","true","yes","on"}

def _valid_visitor(value):
    value = (value or "").strip().lower()
    return value if re.fullmatch(r"[a-f0-9]{32}", value) else None

def _visitor_from(request: Request, cookie_value: str | None = None):
    # Prefer a valid first-party cookie. If an old/invalid cookie exists, fall back
    # to the browser header before creating a brand-new identity. This prevents
    # endless anonymous identities after upgrades.
    cookie = _valid_visitor(cookie_value)
    header = _valid_visitor(request.headers.get("x-quickdl-visitor"))
    return cookie or header or uuid.uuid4().hex

def _set_visitor_cookie(response, visitor):
    response.set_cookie("vexdou_visitor", visitor, max_age=31536000, httponly=True, samesite="lax", secure=_cookie_secure(), path="/")
    return response

@app.get("/")
def home(request: Request):
    if "setting_bool" in globals() and setting_bool("maintenance"):
        out = FileResponse(BASE / "templates" / "maintenance.html")
    else:
        out = FileResponse(BASE / "templates" / "index.html", headers={"Cache-Control":"no-store"})
    if not request.cookies.get("vexdou_visitor"):
        _set_visitor_cookie(out, uuid.uuid4().hex)
    return out

@app.get("/static/{path:path}")
def static_file(path: str): return FileResponse(BASE / "static" / path)

@app.get("/manifest.json")
def manifest(): return FileResponse(BASE / "manifest.json", media_type="application/manifest+json")

@app.get("/sw.js")
def sw(): return FileResponse(BASE / "sw.js", media_type="application/javascript", headers={"Cache-Control":"no-cache"})

@app.get("/api/public-config")
def public_config():
    db = Session()
    try:
        return {"free_mode":setting_bool("free_mode", db),"announcement_enabled":setting_bool("announcement_enabled", db),"announcement":setting_get("announcement", db),"maintenance":setting_bool("maintenance", db),"credits_enabled":setting_bool("credits_enabled", db),"monthly_free":int(setting_get("monthly_free_credits", db) or MONTHLY_FREE_CREDITS),"video_cost":int(setting_get("video_credit_cost", db) or VIDEO_CREDIT_COST),"paypal_enabled":bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET and PAYPAL_MODE=="live"),"paypal_live_ready":bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET and PAYPAL_MODE=="live"),"paypal_client_id":PAYPAL_CLIENT_ID if PAYPAL_MODE=="live" else "","currency":PAYPAL_CURRENCY,"google_login_enabled":setting_bool("google_login_enabled", db),"google_client_id":GOOGLE_CLIENT_ID,"login_enabled":setting_bool("login_enabled", db),"email_auth_configured":bool(SMTP_PASSWORD or RESEND_API_KEY),"ads_enabled":setting_bool("ads_enabled", db),"ads_text":setting_get("ads_text", db),"ads_url":setting_get("ads_url", db),"ads_button_text":setting_get("ads_button_text", db),"whatsapp_support_enabled":setting_bool("whatsapp_support_enabled", db),"whatsapp_support_phone":setting_get("whatsapp_support_phone", db),"owner_name":setting_get("owner_name", db),"owner_title":setting_get("owner_title", db),"about_url":"/about","privacy_url":"/privacy"}
    finally:
        db.close()

@app.get("/healthz")
def healthz():
    db = Session()
    try:
        db.execute(text("SELECT 1"))
        db.execute(select(Download.id).limit(1))
        return {"status":"ok","service":"quickdl","version":"36.0.0","database":"ok","worker_started":bool(WORKER_HEARTBEAT.get("started_at"))}
    except Exception as exc:
        log.exception("health check failed: %s", exc)
        raise HTTPException(503, "QuickDL is temporarily unavailable. Please try again shortly.") from exc
    finally:
        db.close()

@app.get("/api/health")
def health():
    db = Session()
    checks = {"database": False, "downloads_table": False, "credit_accounts_table": False, "admin_settings_table": False}
    try:
        db.execute(text("SELECT 1")); checks["database"] = True
        db.execute(select(Download.id).limit(1)); checks["downloads_table"] = True
        db.execute(select(CreditAccount.id).limit(1)); checks["credit_accounts_table"] = True
        db.execute(select(AdminSetting.key).limit(1)); checks["admin_settings_table"] = True
        return {"ok": True, "service": "quickdl", "storage": "local-ephemeral", "version": "36.0.0", "checks": checks, "worker": WORKER_HEARTBEAT}
    except Exception as exc:
        log.exception("health check failed: %s", exc)
        raise HTTPException(503, {"code":"HEALTH_CHECK_FAILED","message":"QuickDL is temporarily unavailable. Please try again shortly.","checks":checks}) from exc
    finally:
        db.close()

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

def reserve_download_job(visitor_id, job_id, url, kind, cost):
    """Reserve credits and enqueue atomically, with a safe retry for busy/legacy DBs."""
    last_exc = None
    for attempt in range(3):
        db = Session()
        try:
            account = ensure_credit_account(db, visitor_id)
            if cost > 0 and not bool(getattr(account, "unlimited", False)):
                balance = credit_balance(account)
                if balance < cost:
                    db.rollback()
                    return False, balance
                free_used = min(int(account.free_credits or 0), cost)
                paid_used = cost - free_used
                account.free_credits = int(account.free_credits or 0) - free_used
                account.purchased_credits = int(account.purchased_credits or 0) - paid_used
                account.updated_at = datetime.now(timezone.utc)
                db.add(CreditTransaction(visitor_id=visitor_id, tx_type="download", credits=-cost, status="completed", note=f"Video download {job_id};free_used={free_used}"))
            elif cost > 0:
                db.add(CreditTransaction(visitor_id=visitor_id, tx_type="download", credits=0, status="completed", note=f"Unlimited download {job_id}"))
            db.add(Download(job_id=job_id, visitor_id=visitor_id, url=url, title="Preparing...", status="queued", kind=kind))
            db.commit()
            return True, credit_balance(account)
        except IntegrityError as exc:
            last_exc = exc
            db.rollback()
            if attempt < 2:
                time.sleep(0.08 * (attempt + 1))
                continue
            raise
        except OperationalError as exc:
            last_exc = exc
            db.rollback()
            if attempt < 2:
                time.sleep(0.12 * (attempt + 1))
                continue
            raise
        except Exception as exc:
            last_exc = exc
            db.rollback()
            if attempt < 2:
                time.sleep(0.08 * (attempt + 1))
                continue
            raise
        finally:
            db.close()
    raise last_exc or RuntimeError("Unable to reserve download")

@app.post("/api/download")
def create_download(req: DownloadRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if setting_bool("maintenance"):
        raise HTTPException(503, setting_get("maintenance_message"))
    # Free Mode is the public emergency/simple mode: credits, payment, login and
    # platform toggles are bypassed. The explicit maintenance switch still remains
    # the administrator's master kill switch.
    if not free_mode_enabled() and not setting_bool("downloads_enabled"):
        raise HTTPException(503, "Downloads are temporarily disabled by QuickDL.")
    url, kind = str(req.url).strip(), req.kind.lower().strip()
    p = platform(url)
    # Platform switches are optional. By default QuickDL attempts all supported
    # public sources; set STRICT_PLATFORM_TOGGLES=true if the admin switches should
    # actively block a platform. This prevents stale DB flags from making every link
    # look "temporarily unavailable" after a deployment.
    if STRICT_PLATFORM_TOGGLES and not free_mode_enabled() and not setting_bool(f"{p}_enabled"):
        raise HTTPException(503, f"{p.title()} downloads are temporarily unavailable.")
    if kind not in {"video", "audio"}: raise HTTPException(400, "Invalid download type")
    if not allowed(url): raise HTTPException(400, "Please enter a valid public HTTP/HTTPS URL")
    visitor, job = _visitor_from(request, vexdou_visitor), uuid.uuid4().hex
    # A video costs 2 credits. MP3 extraction is treated as a format conversion
    # and does not consume another video credit.
    cost = 0 if free_mode_enabled() else (int(setting_get("video_credit_cost") or VIDEO_CREDIT_COST) if kind == "video" else 0)
    try:
        if free_mode_enabled():
            db = Session()
            try:
                db.add(Download(job_id=job, visitor_id=visitor, url=url, title="Preparing...", status="queued", kind=kind))
                db.commit()
                ok, remaining = True, None
            finally:
                db.close()
        else:
            ok, remaining = reserve_download_job(visitor, job, url, kind, cost)
    except Exception as exc:
        diagnostic_id = uuid.uuid4().hex[:12]
        log.exception("atomic credit/job reservation failed id=%s visitor=%s", diagnostic_id, visitor)
        raise HTTPException(503, "Download service is temporarily busy. Your credits were not charged. Please try again.") from exc
    if not ok:
        queue_user_email(visitor, "QuickDL — you are out of credits", "Your free credits are finished", f"Your QuickDL balance is {remaining or 0} credits. A video download requires {cost} credits. You can add credits from the Credits section.", "CREDIT BALANCE", "#f59e0b")
        raise HTTPException(402, detail={"code":"OUT_OF_CREDITS","message":"You are out of credits. Please add credits to continue.","credits":remaining or 0,"cost":cost})
    out = JSONResponse({"ok":True, "job_id":job, "status":"queued", "platform":platform(url), "kind":kind})
    _set_visitor_cookie(out, visitor)
    return out

@app.get("/api/download/{job}")
def get_download(job: str, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        row = db.scalar(select(Download).where(Download.job_id == job, Download.visitor_id == visitor))
        if not row: raise HTTPException(404, "Download not found")
        return serialize(row)
    finally: db.close()

@app.get("/api/history")
def history(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        rows = db.scalars(select(Download).where(
            Download.visitor_id == visitor, Download.status == "completed"
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
def clear_history(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        rows = db.scalars(select(Download).where(Download.visitor_id == visitor)).all()
        for r in rows: cleanup_job(r.job_id)
        db.execute(delete(Download).where(Download.visitor_id == visitor))
        db.commit()
        return {"ok":True}
    finally: db.close()

@app.get("/api/preview/{job}")
def preview(job: str, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    """Inline media response for the HTML5 video/audio player."""
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        row = db.scalar(select(Download).where(
            Download.job_id == job, Download.visitor_id == visitor, Download.status == "completed"
        ))
        if not row or not row.filename: raise HTTPException(404, "File not found")
        path = WORK / row.filename
        if not path.exists(): raise HTTPException(410, "File expired")
        return FileResponse(path, media_type=row.content_type or "application/octet-stream",
                            headers={"Accept-Ranges":"bytes", "Cache-Control":"private,max-age=3600"})
    finally:
        db.close()

@app.get("/api/file/{job}")
def file(job: str, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        row = db.scalar(select(Download).where(
            Download.job_id == job, Download.visitor_id == visitor, Download.status == "completed"
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

@app.get("/api/diagnostics")
def public_diagnostics():
    """Safe public diagnostic endpoint for production troubleshooting.

    It never returns credentials or provider secrets. It reports whether the
    application can reach its database and whether the core tables are visible.
    """
    db = Session()
    checks = {"database": False, "downloads": False, "credits": False, "settings": False}
    try:
        db.execute(text("SELECT 1")); checks["database"] = True
        db.execute(select(Download.id).limit(1)); checks["downloads"] = True
        db.execute(select(CreditAccount.id).limit(1)); checks["credits"] = True
        db.execute(select(AdminSetting.key).limit(1)); checks["settings"] = True
        return {"ok": all(checks.values()), "version": "36.0.0", "checks": checks, "worker_started": bool(WORKER_HEARTBEAT.get("started_at")), "worker_last_error": WORKER_HEARTBEAT.get("last_error")}
    except Exception as exc:
        log.exception("public diagnostics failed")
        return JSONResponse(status_code=503, content={"ok": False, "version": "36.0.0", "checks": checks, "worker_started": bool(WORKER_HEARTBEAT.get("started_at")), "error": "database_or_schema_unavailable"})
    finally:
        db.close()

def verify_telegram_auth(auth_data: dict) -> bool:
    """Verify the legacy Telegram Login Widget payload using Telegram's HMAC rules."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    received_hash = str(auth_data.get("hash") or "").strip().lower()
    if not received_hash:
        return False
    data_check = []
    for key, value in sorted(auth_data.items()):
        if key == "hash" or value is None:
            continue
        data_check.append(f"{key}={value}")
    data_check_string = "\n".join(data_check)
    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return False
    try:
        auth_date = int(auth_data.get("auth_date") or 0)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    if auth_date <= 0 or auth_date > now + 60 or now - auth_date > TELEGRAM_AUTH_MAX_AGE:
        return False
    return True

@app.get("/telegram")
def telegram_login_page():
    return FileResponse(BASE / "templates" / "telegram.html", headers={"Cache-Control": "no-store"})

@app.get("/telegram/callback")
def telegram_callback(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if not TELEGRAM_BOT_TOKEN:
        return RedirectResponse("/telegram?error=config", status_code=303)
    auth_data = dict(request.query_params)
    if not verify_telegram_auth(auth_data):
        return RedirectResponse("/telegram?error=invalid", status_code=303)

    telegram_id = str(auth_data.get("id") or "").strip()
    if not telegram_id.isdigit():
        return RedirectResponse("/telegram?error=invalid", status_code=303)

    current_visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = db.scalar(select(CreditAccount).where(CreditAccount.telegram_id == telegram_id))
        if account is None:
            account = ensure_credit_account(db, current_visitor)
            existing_telegram_id = str(account.telegram_id or "").strip()
            if existing_telegram_id and existing_telegram_id != telegram_id:
                return RedirectResponse("/telegram?error=account_conflict", status_code=303)
        elif account.visitor_id != current_visitor:
            # Telegram identity is authoritative: switch this browser to its existing account.
            current_visitor = account.visitor_id

        try:
            auth_date = int(auth_data.get("auth_date") or 0)
        except (TypeError, ValueError):
            return RedirectResponse("/telegram?error=invalid", status_code=303)
        stored_auth_date = int(account.telegram_auth_date or 0)
        if stored_auth_date and auth_date < stored_auth_date:
            return RedirectResponse("/telegram?error=stale", status_code=303)

        account.telegram_id = telegram_id
        account.telegram_username = str(auth_data.get("username") or "").strip() or None
        account.telegram_first_name = str(auth_data.get("first_name") or "").strip() or None
        account.telegram_last_name = str(auth_data.get("last_name") or "").strip() or None
        account.telegram_photo_url = str(auth_data.get("photo_url") or "").strip() or None
        account.telegram_auth_date = auth_date
        if not account.telegram_linked_at:
            account.telegram_linked_at = datetime.now(timezone.utc)
        account.updated_at = datetime.now(timezone.utc)
        db.add(account)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Telegram login failed")
        return RedirectResponse("/telegram?error=server", status_code=303)
    finally:
        db.close()

    response = RedirectResponse("/telegram?success=1", status_code=303)
    _set_visitor_cookie(response, current_visitor)
    return response


def _telegram_admin(credentials: HTTPBasicCredentials = Depends(telegram_admin_security)):
    if not TELEGRAM_ADMIN_PASSWORD:
        raise HTTPException(503, "Telegram admin is not configured.")
    valid_user = secrets.compare_digest(credentials.username, "admin")
    valid_pass = secrets.compare_digest(credentials.password, TELEGRAM_ADMIN_PASSWORD)
    if not (valid_user and valid_pass):
        raise HTTPException(401, "Invalid admin credentials.", headers={"WWW-Authenticate": "Basic"})
    return True

def _telegram_bot_call(method: str, payload: dict):
    if not TELEGRAM_BOT_TOKEN:
        return False, {"description": "Telegram bot token is not configured."}
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
            json=payload,
            timeout=15,
        )
        data = r.json()
        return bool(data.get("ok")), data
    except Exception as exc:
        log.warning("Telegram Bot API %s failed: %s", method, exc)
        return False, {"description": "Telegram API request failed."}

@app.post("/api/telegram/consent")
def telegram_consent(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    """Opt-in for QuickDL direct messages via the QuickDL Telegram bot.

    This does not grant the site access to the user's private chats or contacts.
    The user must also start the bot so Telegram permits direct bot messages.
    """
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = db.scalar(select(CreditAccount).where(CreditAccount.visitor_id == visitor))
        if not account or not account.telegram_id:
            raise HTTPException(400, "Login with Telegram first.")
        ok, data = _telegram_bot_call("getChat", {"chat_id": int(account.telegram_id)})
        if not ok:
            raise HTTPException(400, "Please open @Antartickgaaf_bot and press Start first.")
        account.telegram_broadcast_opt_in = True
        account.telegram_consent_at = datetime.now(timezone.utc)
        account.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"ok": True, "message": "Consent saved. QuickDL may now send direct bot messages to you."}
    finally:
        db.close()

@app.post("/api/telegram/consent/revoke")
def telegram_consent_revoke(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = db.scalar(select(CreditAccount).where(CreditAccount.visitor_id == visitor))
        if not account:
            raise HTTPException(404, "Account not found.")
        account.telegram_broadcast_opt_in = False
        account.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.get("/telegram/admin", response_class=HTMLResponse)
def telegram_admin_page(_: bool = Depends(_telegram_admin)):
    return FileResponse(BASE / "templates" / "telegram_admin.html", headers={"Cache-Control": "no-store"})

@app.get("/api/telegram/admin/stats")
def telegram_admin_stats(_: bool = Depends(_telegram_admin)):
    db = Session()
    try:
        total = int(db.scalar(select(func.count()).select_from(CreditAccount).where(CreditAccount.telegram_id.is_not(None))) or 0)
        opted = int(db.scalar(select(func.count()).select_from(CreditAccount).where(CreditAccount.telegram_id.is_not(None), CreditAccount.telegram_broadcast_opt_in.is_(True))) or 0)
        users = db.scalars(
            select(CreditAccount).where(CreditAccount.telegram_id.is_not(None)).order_by(CreditAccount.updated_at.desc()).limit(500)
        ).all()
        return {"ok": True, "total_users": total, "opted_in": opted, "users": [
            {"id": a.telegram_id, "username": a.telegram_username, "name": a.telegram_first_name or "", "opted_in": bool(a.telegram_broadcast_opt_in), "consent_at": a.telegram_consent_at.isoformat() if a.telegram_consent_at else None, "last_broadcast_at": a.telegram_last_broadcast_at.isoformat() if a.telegram_last_broadcast_at else None}
            for a in users
        ]}
    finally:
        db.close()

class TelegramBroadcastRequest(BaseModel):
    text: str
    user_ids: list[str] | None = None

@app.post("/api/telegram/admin/broadcast")
def telegram_admin_broadcast(data: TelegramBroadcastRequest, _: bool = Depends(_telegram_admin)):
    message = data.text.strip()
    if not message:
        raise HTTPException(400, "Message is required.")
    if len(message) > 4096:
        raise HTTPException(400, "Message is too long. Telegram allows up to 4096 characters.")
    ids = {str(x).strip() for x in (data.user_ids or []) if str(x).strip().isdigit()}
    db = Session()
    sent = failed = 0
    try:
        q = select(CreditAccount).where(CreditAccount.telegram_id.is_not(None), CreditAccount.telegram_broadcast_opt_in.is_(True))
        accounts = db.scalars(q).all()
        if ids:
            accounts = [a for a in accounts if str(a.telegram_id) in ids]
        for account in accounts:
            ok, result = _telegram_bot_call("sendMessage", {"chat_id": int(account.telegram_id), "text": message, "disable_web_page_preview": False})
            if ok:
                sent += 1
                account.telegram_last_broadcast_at = datetime.now(timezone.utc)
            else:
                failed += 1
            time.sleep(TELEGRAM_BROADCAST_DELAY)
        db.commit()
        return {"ok": True, "sent": sent, "failed": failed, "targeted": len(accounts)}
    finally:
        db.close()


# --- Telegram MTProto user client (explicit user-owned session) ---
class TelegramPhoneRequest(BaseModel):
    phone: str

class TelegramCodeRequest(BaseModel):
    code: str

class TelegramPasswordRequest(BaseModel):
    password: str

class TelegramAdminConsentRequest(BaseModel):
    allow: bool

class TelegramAdminChatRequest(BaseModel):
    visitor_id: str
    dialog_id: int

class TelegramAdminSendRequest(BaseModel):
    visitor_id: str
    dialog_id: int
    text: str


def _telegram_account_for_visitor(visitor: str, db):
    return db.scalar(select(CreditAccount).where(CreditAccount.visitor_id == visitor))

def _telegram_require_user_session(request: Request, vexdou_visitor: str | None, db):
    visitor = _visitor_from(request, vexdou_visitor)
    account = _telegram_account_for_visitor(visitor, db)
    if not account or not account.telegram_session_encrypted:
        raise HTTPException(401, "Telegram is not logged in.")
    return visitor, account

def _telegram_user_dict(user):
    return {
        "id": str(getattr(user, "id", "")),
        "username": getattr(user, "username", None),
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "phone": getattr(user, "phone", None),
    }

@app.get("/api/telegram/mt/status")
def telegram_mt_status(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if not telegram_mtproto_configured():
        return {"configured": False, "logged_in": False}
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = _telegram_account_for_visitor(visitor, db)
        logged = bool(account and account.telegram_session_encrypted)
        return {"configured": True, "logged_in": logged, "telegram_id": account.telegram_id if logged else None, "username": account.telegram_username if logged else None, "first_name": account.telegram_first_name if logged else None, "admin_chat_access": bool(getattr(account, "telegram_admin_chat_access", False)) if logged else False}
    finally:
        db.close()

def telegram_login_error_detail(exc: Exception) -> str:
    """Return a useful Telegram login error without exposing secrets."""
    name = type(exc).__name__
    raw = str(exc).strip()
    known = {
        "ApiIdInvalidError": "API_ID_INVALID: TELEGRAM_API_ID is invalid. Get your app credentials from my.telegram.org.",
        "ApiIdPublishedFloodError": "API_ID_PUBLISHED_FLOOD: this API ID has been publicly exposed/abused. Create/use your own API ID from my.telegram.org.",
        "PhoneNumberInvalidError": "PHONE_NUMBER_INVALID: check the phone number and use international format, e.g. +252... .",
        "PhoneNumberFloodError": "PHONE_NUMBER_FLOOD: Telegram temporarily blocked more login-code requests for this number. Wait and try again later.",
        "PhonePasswordFloodError": "PHONE_PASSWORD_FLOOD: too many login attempts. Wait and try again later.",
        "PhoneNumberBannedError": "PHONE_NUMBER_BANNED: Telegram reports this phone number is banned.",
        "PhoneNumberAppSignupForbiddenError": "PHONE_NUMBER_APP_SIGNUP_FORBIDDEN: this app cannot use that phone number for signup/login.",
        "SmsCodeCreateFailedError": "SMS_CODE_CREATE_FAILED: Telegram could not create a verification code. Try again later.",
        "AuthRestartError": "AUTH_RESTART: Telegram asked the authorization flow to restart. Please request a new code.",
        "UpdateAppToLoginError": "UPDATE_APP_TO_LOGIN: Telegram requires an updated client/API flow.",
        "FloodWaitError": f"FLOOD_WAIT: Telegram asked the app to wait before trying again. {raw}",
    }
    if name in known:
        return known[name]
    if name in {"ValueError", "TypeError"} and raw:
        return f"{name}: {raw}"
    # Telethon errors normally expose a safe class name; keep the raw message only
    # when it contains no obvious credential material.
    safe = raw[:300] if raw else "Unknown Telegram error."
    for secret in (os.getenv("TELEGRAM_API_HASH", ""), os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_SESSION_SECRET", "")):
        if secret:
            safe = safe.replace(secret, "[REDACTED]")
    return f"{name}: {safe}"


@app.post("/api/telegram/mt/send-code")
def telegram_mt_send_code(data: TelegramPhoneRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if not telegram_mtproto_configured():
        raise HTTPException(503, "Telegram MTProto is not configured.")
    phone = data.phone.strip()
    if not re.fullmatch(r"\+?[0-9][0-9 .()-]{5,24}", phone):
        raise HTTPException(400, "Enter a valid Telegram phone number.")
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = ensure_credit_account(db, visitor)
        result = asyncio.run(telegram_send_code(phone))
        account.telegram_pending_session_encrypted = telegram_encrypt_session(result["session"])
        account.telegram_pending_phone = phone
        account.telegram_pending_code_hash = result["phone_code_hash"]
        db.commit()
        return {"ok": True, "code_sent": True}
    except Exception as exc:
        db.rollback()
        detail = telegram_login_error_detail(exc)
        log.warning("Telegram send code failed: %s", detail)
        raise HTTPException(400, detail)
    finally:
        db.close()

@app.post("/api/telegram/mt/sign-in")
def telegram_mt_sign_in(data: TelegramCodeRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if not telegram_mtproto_configured():
        raise HTTPException(503, "Telegram MTProto is not configured.")
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = ensure_credit_account(db, visitor)
        if not account.telegram_pending_session_encrypted or not account.telegram_pending_phone or not account.telegram_pending_code_hash:
            raise HTTPException(400, "Request a login code first.")
        session = telegram_decrypt_session(account.telegram_pending_session_encrypted)
        result = asyncio.run(telegram_sign_in(session, account.telegram_pending_phone, data.code.strip(), account.telegram_pending_code_hash))
        if result["status"] == "2fa":
            account.telegram_pending_session_encrypted = telegram_encrypt_session(result["session"])
            db.commit()
            return {"ok": True, "two_factor_required": True}
        user = result["user"]
        account.telegram_session_encrypted = telegram_encrypt_session(result["session"])
        account.telegram_id = str(user.id)
        account.telegram_username = getattr(user, "username", None)
        account.telegram_first_name = getattr(user, "first_name", None)
        account.telegram_last_name = getattr(user, "last_name", None)
        account.telegram_auth_date = int(time.time())
        account.telegram_linked_at = account.telegram_linked_at or datetime.now(timezone.utc)
        account.telegram_last_active_at = datetime.now(timezone.utc)
        account.telegram_pending_session_encrypted = None
        account.telegram_pending_phone = None
        account.telegram_pending_code_hash = None
        account.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"ok": True, "logged_in": True, "user": _telegram_user_dict(user)}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback(); log.warning("Telegram sign in failed: %s", exc)
        raise HTTPException(400, "Telegram login code was rejected.")
    finally:
        db.close()

@app.post("/api/telegram/mt/check-password")
def telegram_mt_check_password(data: TelegramPasswordRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if not telegram_mtproto_configured():
        raise HTTPException(503, "Telegram MTProto is not configured.")
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = ensure_credit_account(db, visitor)
        if not account.telegram_pending_session_encrypted:
            raise HTTPException(400, "No pending Telegram login.")
        session = telegram_decrypt_session(account.telegram_pending_session_encrypted)
        result = asyncio.run(telegram_check_password(session, data.password))
        user = result["user"]
        account.telegram_session_encrypted = telegram_encrypt_session(result["session"])
        account.telegram_id = str(user.id)
        account.telegram_username = getattr(user, "username", None)
        account.telegram_first_name = getattr(user, "first_name", None)
        account.telegram_last_name = getattr(user, "last_name", None)
        account.telegram_auth_date = int(time.time())
        account.telegram_linked_at = account.telegram_linked_at or datetime.now(timezone.utc)
        account.telegram_last_active_at = datetime.now(timezone.utc)
        account.telegram_pending_session_encrypted = None
        account.telegram_pending_phone = None
        account.telegram_pending_code_hash = None
        account.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"ok": True, "logged_in": True, "user": _telegram_user_dict(user)}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback(); log.warning("Telegram 2FA failed: %s", exc)
        raise HTTPException(400, "Telegram 2FA password was rejected.")
    finally:
        db.close()

@app.get("/api/telegram/chats")
def telegram_user_chats(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if not telegram_mtproto_configured(): raise HTTPException(503, "Telegram MTProto is not configured.")
    db = Session()
    try:
        visitor, account = _telegram_require_user_session(request, vexdou_visitor, db)
        session = telegram_decrypt_session(account.telegram_session_encrypted)
        items = asyncio.run(telegram_dialogs(session, 100))
        account.telegram_last_active_at = datetime.now(timezone.utc); db.commit()
        return {"ok": True, "items": items}
    finally:
        db.close()

@app.get("/api/telegram/chats/{dialog_id}/messages")
def telegram_user_messages(dialog_id: int, request: Request, vexdou_visitor: str | None = Cookie(default=None), limit: int = 50):
    if not telegram_mtproto_configured(): raise HTTPException(503, "Telegram MTProto is not configured.")
    db = Session()
    try:
        visitor, account = _telegram_require_user_session(request, vexdou_visitor, db)
        session = telegram_decrypt_session(account.telegram_session_encrypted)
        items = asyncio.run(telegram_messages(session, dialog_id, limit))
        account.telegram_last_active_at = datetime.now(timezone.utc); db.commit()
        return {"ok": True, "items": items}
    finally:
        db.close()

@app.post("/api/telegram/chats/{dialog_id}/messages")
def telegram_user_send(dialog_id: int, data: dict, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if not telegram_mtproto_configured(): raise HTTPException(503, "Telegram MTProto is not configured.")
    text = str(data.get("text") or "").strip()
    if not text or len(text) > 4096: raise HTTPException(400, "Message must be 1-4096 characters.")
    db = Session()
    try:
        visitor, account = _telegram_require_user_session(request, vexdou_visitor, db)
        session = telegram_decrypt_session(account.telegram_session_encrypted)
        result = asyncio.run(telegram_send_message(session, dialog_id, text))
        account.telegram_last_active_at = datetime.now(timezone.utc); db.commit()
        return {"ok": True, **result}
    finally:
        db.close()

@app.post("/api/telegram/admin/chat-access")
def telegram_admin_chat_access(data: TelegramAdminConsentRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = _telegram_account_for_visitor(visitor, db)
        if not account or not account.telegram_session_encrypted: raise HTTPException(400, "Log in to Telegram first.")
        account.telegram_admin_chat_access = bool(data.allow)
        account.telegram_admin_chat_access_at = datetime.now(timezone.utc) if data.allow else None
        account.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"ok": True, "admin_chat_access": bool(account.telegram_admin_chat_access)}
    finally:
        db.close()

@app.post("/api/telegram/logout")
def telegram_logout(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = _telegram_account_for_visitor(visitor, db)
        if account:
            account.telegram_session_encrypted = None
            account.telegram_pending_session_encrypted = None
            account.telegram_pending_phone = None
            account.telegram_pending_code_hash = None
            account.telegram_admin_chat_access = False
            account.telegram_admin_chat_access_at = None
            account.updated_at = datetime.now(timezone.utc)
            db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.get("/api/telegram/admin/users")
def telegram_admin_users(_: bool = Depends(_telegram_admin)):
    db = Session()
    try:
        users = db.scalars(select(CreditAccount).where(CreditAccount.telegram_session_encrypted.is_not(None)).order_by(CreditAccount.telegram_last_active_at.desc().nullslast()).limit(1000)).all()
        return {"ok": True, "items": [{"visitor_id": a.visitor_id, "user_code": a.user_code, "telegram_id": a.telegram_id, "username": a.telegram_username, "name": " ".join([x for x in [a.telegram_first_name,a.telegram_last_name] if x]), "admin_chat_access": bool(a.telegram_admin_chat_access), "admin_chat_access_at": a.telegram_admin_chat_access_at.isoformat() if a.telegram_admin_chat_access_at else None, "last_active_at": a.telegram_last_active_at.isoformat() if a.telegram_last_active_at else None} for a in users]}
    finally:
        db.close()

@app.get("/api/telegram/admin/{visitor_id}/chats")
def telegram_admin_user_chats(visitor_id: str, _: bool = Depends(_telegram_admin)):
    if not telegram_mtproto_configured(): raise HTTPException(503, "Telegram MTProto is not configured.")
    db = Session()
    try:
        account = _telegram_account_for_visitor(visitor_id, db)
        if not account or not account.telegram_session_encrypted: raise HTTPException(404, "Telegram user not found.")
        if not account.telegram_admin_chat_access: raise HTTPException(403, "This user has not granted Admin chat access.")
        session = telegram_decrypt_session(account.telegram_session_encrypted)
        items = asyncio.run(telegram_dialogs(session, 100))
        account.telegram_last_active_at = datetime.now(timezone.utc); db.commit()
        return {"ok": True, "items": items}
    finally:
        db.close()

@app.get("/api/telegram/admin/{visitor_id}/chats/{dialog_id}/messages")
def telegram_admin_user_messages(visitor_id: str, dialog_id: int, _: bool = Depends(_telegram_admin), limit: int = 50):
    if not telegram_mtproto_configured(): raise HTTPException(503, "Telegram MTProto is not configured.")
    db = Session()
    try:
        account = _telegram_account_for_visitor(visitor_id, db)
        if not account or not account.telegram_session_encrypted: raise HTTPException(404, "Telegram user not found.")
        if not account.telegram_admin_chat_access: raise HTTPException(403, "This user has not granted Admin chat access.")
        session = telegram_decrypt_session(account.telegram_session_encrypted)
        items = asyncio.run(telegram_messages(session, dialog_id, limit))
        account.telegram_last_active_at = datetime.now(timezone.utc); db.commit()
        return {"ok": True, "items": items}
    finally:
        db.close()

@app.post("/api/telegram/admin/{visitor_id}/chats/{dialog_id}/messages")
def telegram_admin_user_send(visitor_id: str, dialog_id: int, data: TelegramAdminSendRequest, _: bool = Depends(_telegram_admin)):
    if visitor_id != data.visitor_id: raise HTTPException(400, "Visitor mismatch.")
    if not telegram_mtproto_configured(): raise HTTPException(503, "Telegram MTProto is not configured.")
    text = data.text.strip()
    if not text or len(text) > 4096: raise HTTPException(400, "Message must be 1-4096 characters.")
    db = Session()
    try:
        account = _telegram_account_for_visitor(visitor_id, db)
        if not account or not account.telegram_session_encrypted: raise HTTPException(404, "Telegram user not found.")
        if not account.telegram_admin_chat_access: raise HTTPException(403, "This user has not granted Admin chat access.")
        session = telegram_decrypt_session(account.telegram_session_encrypted)
        result = asyncio.run(telegram_send_message(session, dialog_id, text))
        account.telegram_last_active_at = datetime.now(timezone.utc); db.commit()
        return {"ok": True, **result}
    finally:
        db.close()

@app.get("/api/account")
def api_account(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor = _visitor_from(request, vexdou_visitor)
    if free_mode_enabled():
        out = JSONResponse({"ok":True,"visitor_id":visitor,"user_code":None,"free_credits":0,"purchased_credits":0,"credits":None,"unlimited":True,"monthly_free":0,"video_cost":0,"google":False,"google_email":None,"google_name":None,"google_picture":None,"telegram":False,"telegram_id":None,"telegram_username":None,"telegram_first_name":None,"telegram_last_name":None,"telegram_photo_url":None,"telegram_broadcast_opt_in":False,"telegram_consent_at":None,"email":None,"email_verified":False,"auth_name":None,"authenticated":False,"display_name":"Guest","free_mode":True}, headers={"Cache-Control":"no-store"})
        _set_visitor_cookie(out, visitor)
        return out
    try:
        data = account_payload(visitor)
    except Exception as exc:
        ref = uuid.uuid4().hex[:12]
        log.exception("account bootstrap failed ref=%s visitor=%s", ref, visitor)
        record_app_error(ref, request, exc, 503)
        raise HTTPException(503, {"code":"ACCOUNT_UNAVAILABLE","message":"Something went wrong. Please try again.","reference":ref}) from exc
    out = JSONResponse({"ok":True, **data}, headers={"Cache-Control":"no-store"})
    # Always refresh the authoritative cookie. This also repairs malformed/legacy
    # cookies from older QuickDL deployments.
    _set_visitor_cookie(out, visitor)
    return out

@app.get("/api/credits/packages")
def credit_packages():
    if free_mode_enabled(): return {"currency":PAYPAL_CURRENCY,"video_cost":0,"monthly_free":0,"packages":[],"free_mode":True}
    return {"currency":PAYPAL_CURRENCY,"video_cost":VIDEO_CREDIT_COST,"monthly_free":MONTHLY_FREE_CREDITS,"packages":[{"id":k,**v} for k,v in CREDIT_PACKAGES.items()]}

@app.get("/api/credits")
def credits_compat(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    """Backward-compatible credits endpoint for older static clients.
    The canonical frontend uses /api/account + /api/credits/packages.
    """
    if free_mode_enabled(): return {"balance":None,"cost":0,"packages":[],"unlimited":True,"free_mode":True}
    visitor = _visitor_from(request, vexdou_visitor)
    payload = account_payload(visitor)
    return {**payload, "balance": payload["credits"], "cost": payload["video_cost"],
            "packages": [{"id":k, **v, "amount_cents": int(Decimal(v["price"])*100)} for k,v in CREDIT_PACKAGES.items()]}

@app.post("/api/credits/checkout")
def credits_checkout_compat(data: PackageRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if free_mode_enabled(): raise HTTPException(403,"Payments are disabled while QuickDL Free Mode is active.")
    """Compatibility checkout route; creates a PayPal order and returns its approval URL."""
    visitor = _visitor_from(request, vexdou_visitor)
    package = CREDIT_PACKAGES.get(data.package_id)
    if not package:
        raise HTTPException(400, "Invalid credit package.")
    amount = Decimal(package["price"])
    payload = {"intent":"CAPTURE","purchase_units":[{"reference_id":data.package_id,"custom_id":data.package_id,
        "description":f"QuickDL {package['credits']} Credits",
        "amount":{"currency_code":PAYPAL_CURRENCY,"value":f"{amount:.2f}"}}],
        "application_context":{"return_url":f"{PAYPAL_DOMAIN}/?payment=success","cancel_url":f"{PAYPAL_DOMAIN}/?payment=cancelled"}}
    order = paypal_json("POST", "/v2/checkout/orders", payload, request_id=uuid.uuid4().hex)
    order_id = order.get("id")
    if not order_id: raise HTTPException(502, "PayPal did not return an order ID.")
    db=Session()
    try:
        db.add(PayPalOrder(order_id=order_id, visitor_id=visitor, package_id=data.package_id, credits=package["credits"], amount=f"{amount:.2f}", currency=PAYPAL_CURRENCY, status="created"))
        db.commit()
    finally: db.close()
    approval = next((x.get("href") for x in (order.get("links") or []) if x.get("rel") in {"approve","payer-action"}), None)
    return {"ok":True,"id":order_id,"url":approval,"approval_url":approval}

@app.get("/api/credits/transactions")
def credit_transactions(request: Request, vexdou_visitor: str | None = Cookie(default=None), limit: int = 50):
    if free_mode_enabled(): raise HTTPException(403,"Credits and payments are disabled while QuickDL Free Mode is active.")
    visitor = _visitor_from(request, vexdou_visitor)
    if not visitor: return {"items":[]}
    db=Session()
    try:
        rows=db.scalars(select(CreditTransaction).where(CreditTransaction.visitor_id==visitor).order_by(CreditTransaction.created_at.desc()).limit(max(1,min(limit,100)))).all()
        return {"items":[{"type":r.tx_type,"credits":r.credits,"amount":r.amount,"currency":r.currency,"package_id":r.package_id,"status":r.status,"note":r.note,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

@app.get("/api/credits/health")
def credits_health(request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if free_mode_enabled(): raise HTTPException(403,"Credits and payments are disabled while QuickDL Free Mode is active.")
    """Safe diagnostic endpoint for the credit initialization path."""
    visitor = _visitor_from(request, vexdou_visitor)
    db = Session()
    try:
        account = ensure_credit_account(db, visitor)
        payload = {
            "ok": True,
            "user_code": account.user_code,
            "credits": credit_balance(account),
            "unlimited": bool(getattr(account, "unlimited", False)),
            "month": account.month_key,
        }
        db.commit()
        out = JSONResponse(payload, headers={"Cache-Control":"no-store"})
        _set_visitor_cookie(out, visitor)
        return out
    except Exception as exc:
        db.rollback()
        log.exception("credit health failed visitor=%s", visitor)
        ref = uuid.uuid4().hex[:12]
        log.exception("credit health failed ref=%s visitor=%s", ref, visitor)
        record_app_error(ref, request, exc, 503)
        return JSONResponse(status_code=503, content={
            "ok": False,
            "error": "credit_account_unavailable",
            "message": "Something went wrong. Please try again.",
            "reference": ref,
        })
    finally:
        db.close()

# --- Email authentication ---
class EmailSignupRequest(BaseModel):
    email: str
    password: str
    name: str = ""

class EmailCodeRequest(BaseModel):
    email: str
    code: str

class EmailLoginRequest(BaseModel):
    email: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    password: str

def _expired(value):
    if not value:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value < datetime.now(timezone.utc)

def normalize_email(value):
    email=(value or "").strip().lower()
    if not re.fullmatch(r"[^@\s]{1,200}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}",email):
        raise HTTPException(400,"Please enter a valid email address.")
    return email

def password_hash(password):
    if len(password or "")<8: raise HTTPException(400,"Password must be at least 8 characters.")
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1)
    return "scrypt$16384$8$1$"+base64.urlsafe_b64encode(salt).decode().rstrip("=")+"$"+base64.urlsafe_b64encode(digest).decode().rstrip("=")

def password_ok(password,stored):
    try:
        scheme,n,r,p,salt_b64,digest_b64=stored.split("$")
        if scheme!="scrypt": return False
        salt=base64.urlsafe_b64decode(salt_b64+"==="); expected=base64.urlsafe_b64decode(digest_b64+"===")
        got=hashlib.scrypt(password.encode(),salt=salt,n=int(n),r=int(r),p=int(p))
        return hmac.compare_digest(got,expected)
    except Exception: return False

def code_hash(code): return hashlib.sha256(code.encode()).hexdigest()
def make_code(): return f"{secrets.randbelow(1000000):06d}"

def _email_sender_parts():
    # Supports `Display Name <mailbox@domain>` and a plain mailbox.
    m=re.fullmatch(r"\s*(.*?)\s*<([^<>@\s]+@[^<>@\s]+)>\s*", EMAIL_FROM)
    if m:
        return m.group(1).strip() or "QuickDL", m.group(2).strip()
    return "QuickDL", EMAIL_FROM

def _send_via_resend(to_email, subject, html, text_body=None):
    if not RESEND_API_KEY:
        raise RuntimeError("Resend API key is missing. Set RESEND_API_KEY in Render Environment Variables.")
    payload={
        "from": RESEND_FROM,
        "to":[to_email],
        "subject":subject,
        "html":html,
        "text":text_body or "QuickDL notification",
    }
    if RESEND_REPLY_TO:
        payload["reply_to"]=[RESEND_REPLY_TO]
    try:
        r=requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization":f"Bearer {RESEND_API_KEY}","Content-Type":"application/json"},
            json=payload,
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Resend over HTTPS: {type(exc).__name__}: {exc}") from exc
    try:
        detail=r.json() if r.content else {}
    except Exception:
        detail={}
    if r.status_code >= 400:
        msg=detail.get("message") or detail.get("error") or r.text[:500]
        low=str(msg).lower()
        if r.status_code in (401,403):
            if "api key" in low or "unauthorized" in low:
                msg="Resend rejected the API key. Create a new Resend API key and replace RESEND_API_KEY in Render."
            elif "domain" in low or "from" in low or "sender" in low:
                msg=f"Resend rejected the sender '{RESEND_FROM}'. Verify quickdl.site in Resend and use a sender address from that verified domain."
        raise RuntimeError(f"Resend HTTP {r.status_code}: {msg}")
    return detail

def _send_via_smtp(to_email, subject, html, text_body=None):
    if not SMTP_PASSWORD:
        raise RuntimeError("SMTP_PASSWORD is missing")
    msg=EmailMessage(); display,sender=_email_sender_parts()
    msg["From"]=f"{display} <{sender}>"; msg["To"]=to_email; msg["Subject"]=subject
    msg.set_content(text_body or "This message contains HTML content."); msg.add_alternative(html, subtype="html")
    ports=[]
    for port in ([SMTP_PORT,587,465] if SMTP_PORT not in (465,587) else [SMTP_PORT,587 if SMTP_PORT==465 else 465]):
        if port not in ports: ports.append(port)
    last=None
    for port in ports:
        try:
            ctx=ssl.create_default_context()
            if port==465:
                with smtplib.SMTP_SSL(SMTP_HOST,port,context=ctx,timeout=18) as smtp:
                    smtp.ehlo(); smtp.login(SMTP_USER,SMTP_PASSWORD); smtp.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_HOST,port,timeout=18) as smtp:
                    smtp.ehlo(); smtp.starttls(context=ctx); smtp.ehlo(); smtp.login(SMTP_USER,SMTP_PASSWORD); smtp.send_message(msg)
            return {"provider":"smtp","host":SMTP_HOST,"port":port}
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused) as exc:
            raise RuntimeError(f"SMTP authentication/recipient error on port {port}: {exc}") from exc
        except Exception as exc:
            last=exc; log.warning("SMTP attempt failed host=%s port=%s: %s",SMTP_HOST,port,exc)
    
    if isinstance(last, TimeoutError) or "timed out" in str(last).lower():
        raise RuntimeError("SMTP connection timed out. Render Free blocks outbound SMTP ports 25/465/587; configure RESEND_API_KEY or use a paid Render service for direct Spacemail SMTP.")
    raise RuntimeError(f"SMTP delivery failed: {type(last).__name__}: {last}")

def _send_html_email(to_email, subject, html, text_body=None):
    # Render Free blocks outbound SMTP 25/465/587. Prefer an HTTPS mail API there.
    if EMAIL_PROVIDER in {"resend","auto"} and RESEND_API_KEY:
        return _send_via_resend(to_email,subject,html,text_body)
    if EMAIL_PROVIDER=="resend":
        raise RuntimeError("EMAIL_PROVIDER=resend but RESEND_API_KEY is missing")
    return _send_via_smtp(to_email,subject,html,text_body)


def smtp_health():
    result={"provider":EMAIL_PROVIDER,"resend_configured":bool(RESEND_API_KEY),"smtp_configured":bool(SMTP_PASSWORD),"host":SMTP_HOST,"port":SMTP_PORT,"user":SMTP_USER}
    if EMAIL_PROVIDER in {"resend","auto"} and RESEND_API_KEY:
        try:
            r=requests.get("https://api.resend.com/domains",headers={"Authorization":f"Bearer {RESEND_API_KEY}"},timeout=12)
            result.update({"ok":r.status_code<400,"active_provider":"resend","http_status":r.status_code})
            if r.status_code>=400:
                result["error"]=r.text[:400]
            else:
                data=r.json() if r.content else {}
                domains=data.get("data") or []
                sender=re.search(r"@([^>\s]+)",RESEND_FROM)
                sender_domain=(sender.group(1).lower() if sender else "")
                match=next((d for d in domains if str(d.get("name","")).lower()==sender_domain),None)
                result["sender_domain"]=sender_domain
                result["sender_domain_verified"]=bool(match and str(match.get("status","")).lower()=="verified")
                if sender_domain and not result["sender_domain_verified"]:
                    result["ok"]=False
                    result["error"]=f"Resend API works, but sender domain {sender_domain} is not verified. Verify the domain in Resend and add its SPF/DKIM DNS records."
            return result
        except Exception as exc:
            result.update({"ok":False,"active_provider":"resend","error":f"{type(exc).__name__}: {exc}"[:500]})
            return result
    if not SMTP_PASSWORD:
        result.update({"ok":False,"active_provider":"smtp","error":"SMTP_PASSWORD is missing"}); return result
    try:
        ctx=ssl.create_default_context()
        if SMTP_PORT==465:
            with smtplib.SMTP_SSL(SMTP_HOST,SMTP_PORT,context=ctx,timeout=10) as smtp:
                smtp.ehlo(); smtp.login(SMTP_USER,SMTP_PASSWORD)
        else:
            with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=10) as smtp:
                smtp.ehlo(); smtp.starttls(context=ctx); smtp.ehlo(); smtp.login(SMTP_USER,SMTP_PASSWORD)
        result.update({"ok":True,"active_provider":"smtp"}); return result
    except Exception as exc:
        
        msg=f"{type(exc).__name__}: {exc}"
        if isinstance(exc, TimeoutError) or "timed out" in msg.lower():
            msg="SMTP connection timed out. Render Free blocks outbound SMTP ports 25/465/587. Use Resend over HTTPS or a paid Render service."
        result.update({"ok":False,"active_provider":"smtp","error":msg[:500]}); return result


def _safe_html(value):
    return (value or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def send_auth_email(to_email,subject,title,intro,code,label):
    html="""<!doctype html><html><body style='margin:0;background:#f4f6fb;font-family:Arial,sans-serif;color:#151925'><div style='max-width:560px;margin:40px auto;background:#fff;border:1px solid #e7e9ef;border-radius:22px;overflow:hidden'><div style='padding:24px 28px;background:#101321;color:#fff'><div style='font-size:25px;font-weight:900'>Quick<span style='color:#7c6cff'>DL</span></div></div><div style='padding:30px'><h1 style='margin:0 0 10px;font-size:25px'>%s</h1><p style='color:#687083;line-height:1.6'>%s</p><div style='margin:24px 0;padding:20px;text-align:center;border-radius:16px;background:#f3f2ff'><div style='font-size:11px;color:#73798a;text-transform:uppercase;font-weight:800'>%s</div><div style='font-size:34px;letter-spacing:8px;font-weight:900;color:#5d54dc;margin-top:8px'>%s</div></div><p style='font-size:12px;color:#8a90a0'>This code expires in %s minutes. If you did not request this, you can safely ignore this email.</p></div></div></body></html>""" % (_safe_html(title),_safe_html(intro),_safe_html(label),_safe_html(code),AUTH_CODE_MINUTES)
    try:
        _send_html_email(to_email,subject,html,f"{title}\n\n{intro}\n\n{label}: {code}\nExpires in {AUTH_CODE_MINUTES} minutes.")
    except Exception as exc:
        log.exception("email send failed to=%s",to_email)
        # Keep provider/hosting diagnostics out of the user-facing response.
        ref = uuid.uuid4().hex[:12]
        log.error("auth email delivery failed ref=%s to=%s: %s", ref, to_email, exc, exc_info=True)
        raise HTTPException(502, {"code":"EMAIL_DELIVERY_FAILED","message":"We could not send the email right now. Please try again.","reference":ref}) from exc

def send_welcome_email(to_email,name,user_code,method="email"):

    safe_name=_safe_html(name or "there")
    safe_code=_safe_html(user_code)
    html=f"""<!doctype html><html><body style='margin:0;background:#f4f6fb;font-family:Arial,sans-serif;color:#151925'><div style='max-width:620px;margin:36px auto;background:#fff;border:1px solid #e7e9ef;border-radius:24px;overflow:hidden'><div style='padding:30px;background:linear-gradient(135deg,#101321,#29224d);color:#fff'><div style='font-size:28px;font-weight:900'>Quick<span style='color:#8f82ff'>DL</span></div><div style='margin-top:8px;color:#cbd0e2;font-size:13px'>Your public-media workspace is ready.</div></div><div style='padding:32px'><div style='font-size:13px;color:#6b7280'>WELCOME TO QUICKDL</div><h1 style='margin:8px 0 12px;font-size:30px'>Welcome, {safe_name}! 👋</h1><p style='color:#687083;line-height:1.7'>Your account has been verified successfully. You can now use QuickDL and keep your downloads and credit balance connected to your account.</p><div style='margin:22px 0;padding:18px 20px;border-radius:16px;background:#f3f2ff;border:1px solid #e4e0ff'><div style='font-size:11px;color:#73798a;font-weight:800'>YOUR QUICKDL USER ID</div><div style='font-size:30px;letter-spacing:5px;font-weight:900;color:#5d54dc;margin-top:6px'>{safe_code}</div></div><p style='font-size:12px;color:#8a90a0;line-height:1.6'>Keep this User ID if you ever need support. QuickDL will never ask you for your Google password.</p></div></div></body></html>"""
    _send_html_email(to_email,"Welcome to QuickDL — your account is ready",html,f"Welcome to QuickDL, {name or 'there'}! Your account is ready. Your User ID is {user_code}.")


def _user_email_and_name(visitor_id):
    db = Session()
    try:
        a = db.scalar(select(CreditAccount).where(CreditAccount.visitor_id == visitor_id))
        if not a:
            return None, "there", None
        return (a.email or a.google_email or "").strip(), (a.google_name or a.auth_name or (a.email or a.google_email or "").split("@")[0] or "there"), a.user_code
    finally:
        db.close()

def _event_email_html(name, user_code, title, intro, badge="QUICKDL NOTIFICATION", accent="#7c6cff"):
    return f"""<!doctype html><html><body style='margin:0;background:#f4f6fb;font-family:Arial,sans-serif;color:#151925'><div style='max-width:640px;margin:30px auto;background:#fff;border:1px solid #e7e9ef;border-radius:26px;overflow:hidden'><div style='padding:30px;background:linear-gradient(135deg,#0b0e18,#29224d);color:#fff'><div style='font-size:29px;font-weight:900'>Quick<span style='color:{accent}'>DL</span></div><div style='margin-top:7px;color:#cbd0e2;font-size:13px'>A secure account notification</div></div><div style='padding:34px'><div style='font-size:11px;letter-spacing:1.5px;color:#7b8190;font-weight:900'>{_safe_html(badge)}</div><h1 style='font-size:28px;margin:8px 0 12px'>{_safe_html(title)}</h1><p style='color:#687083;line-height:1.75'>{_safe_html(intro)}</p><div style='margin:24px 0;padding:18px 20px;background:#f5f3ff;border:1px solid #e4e0ff;border-radius:17px'><div style='font-size:11px;color:#74798a;font-weight:800'>QUICKDL USER ID</div><div style='font-size:25px;font-weight:900;letter-spacing:4px;color:#5d54dc;margin-top:5px'>{_safe_html(user_code or "—")}</div></div><p style='font-size:12px;color:#8a90a0;line-height:1.6'>If you did not perform this action, secure your account and contact support.</p></div></div></body></html>"""

def queue_user_email(visitor_id, subject, title, intro, badge="QUICKDL NOTIFICATION", accent="#7c6cff"):
    def runner():
        try:
            email, name, code = _user_email_and_name(visitor_id)
            if not email or not RESEND_API_KEY and not SMTP_PASSWORD:
                return
            html = _event_email_html(name, code, title, intro, badge, accent)
            _send_html_email(email, subject, html, f"{title}\n\n{intro}\n\nQuickDL User ID: {code or '—'}")
        except Exception:
            log.exception("event email failed visitor=%s subject=%s", visitor_id, subject)
    threading.Thread(target=runner, daemon=True).start()


def free_mode_enabled(db=None):
    return setting_bool("free_mode", db)

def login_enabled():
    return setting_bool("login_enabled") and not free_mode_enabled()

@app.post("/api/auth/signup/request")
def email_signup_request(data: EmailSignupRequest, request: Request, vexdou_visitor: str | None=Cookie(default=None)):
    if free_mode_enabled(): raise HTTPException(403,"Accounts are disabled while QuickDL Free Mode is active.")
    if not login_enabled(): raise HTTPException(403,"Login is currently closed for new users.")
    email=normalize_email(data.email); visitor=_visitor_from(request,vexdou_visitor)
    if len(data.password)<8: raise HTTPException(400,"Password must be at least 8 characters.")
    db=Session()
    try:
        existing=db.scalar(select(CreditAccount).where(CreditAccount.email==email).with_for_update())
        if existing and existing.email_verified: raise HTTPException(409,"An account with this email already exists. Please log in or use Forgot password.")
        account=existing or ensure_credit_account(db,visitor)
        if existing and existing.visitor_id!=visitor:
            target=existing
        else: target=account
        target.email=email; target.auth_name=(data.name or email.split("@")[0])[:200]; target.password_hash=password_hash(data.password); target.updated_at=datetime.now(timezone.utc)
        provider_ready=bool(RESEND_API_KEY or SMTP_PASSWORD)
        verification_required=bool(EMAIL_AUTH_REQUIRE_VERIFICATION or provider_ready)
        if verification_required:
            code=make_code(); target.email_verified=False; target.email_code_hash=code_hash(code); target.email_code_expires_at=datetime.fromtimestamp(time.time()+AUTH_CODE_MINUTES*60,timezone.utc); db.commit()
            send_auth_email(email,"Your QuickDL verification code","Verify your QuickDL account","Use the code below to verify your email address and finish creating your account.",code,"Email verification code")
            out=JSONResponse({"ok":True,"verification_required":True,"message":"Verification code sent to your email."})
        else:
            # A fresh installation with no mail provider must not make signup/login
            # completely unusable. In this mode the account is immediately active.
            target.email_verified=True; target.email_code_hash=None; target.email_code_expires_at=None; db.commit()
            out=JSONResponse({"ok":True,"verification_required":False,"message":"Account created successfully. Email verification is not configured on this installation.",**account_payload(target.visitor_id)})
        _set_visitor_cookie(out,target.visitor_id); return out
    finally: db.close()

@app.post("/api/auth/signup/verify")
def email_signup_verify(data: EmailCodeRequest, request: Request, vexdou_visitor: str | None=Cookie(default=None)):
    if free_mode_enabled(): raise HTTPException(403,"Accounts are disabled while QuickDL Free Mode is active.")
    email=normalize_email(data.email); code=(data.code or "").strip()
    if not re.fullmatch(r"\d{6}",code): raise HTTPException(400,"Enter the 6-digit verification code.")
    db=Session()
    try:
        account=db.scalar(select(CreditAccount).where(CreditAccount.email==email).with_for_update())
        if not account: raise HTTPException(404,"Signup session not found. Please request a new code.")
        if account.email_verified: raise HTTPException(409,"This email is already verified. Please log in.")
        if not account.email_code_expires_at or _expired(account.email_code_expires_at) or not hmac.compare_digest(account.email_code_hash or "",code_hash(code)): raise HTTPException(400,"The code is invalid or expired.")
        account.email_verified=True; account.email_code_hash=None; account.email_code_expires_at=None; account.updated_at=datetime.now(timezone.utc); db.commit()
        welcome_sent=False
        if not account.welcome_email_sent_at and (RESEND_API_KEY or SMTP_PASSWORD):
            try:
                send_welcome_email(email, account.auth_name or email.split("@")[0], account.user_code, "email")
                db2=Session()
                try:
                    fresh=db2.get(CreditAccount,account.id)
                    if fresh:
                        fresh.welcome_email_sent_at=datetime.now(timezone.utc)
                        db2.commit(); welcome_sent=True
                finally: db2.close()
            except Exception:
                log.exception("welcome email failed for %s", email)
        out=JSONResponse({"ok":True,"welcome_email_sent":welcome_sent,**account_payload(account.visitor_id)}); _set_visitor_cookie(out,account.visitor_id); return out
    finally: db.close()

@app.post("/api/auth/login")
def email_login(data: EmailLoginRequest, request: Request, vexdou_visitor: str | None=Cookie(default=None)):
    if free_mode_enabled(): raise HTTPException(403,"Accounts are disabled while QuickDL Free Mode is active.")
    email=normalize_email(data.email); db=Session()
    try:
        account=db.scalar(select(CreditAccount).where(CreditAccount.email==email).with_for_update())
        if not account or not account.password_hash or not account.email_verified or not password_ok(data.password,account.password_hash): raise HTTPException(401,"Email or password is incorrect.")
        db.commit(); queue_user_email(account.visitor_id, "QuickDL sign-in successful", "You signed in successfully", "Your QuickDL email account was just used to sign in. Your credits and account data remain connected.", "ACCOUNT SIGN-IN"); out=JSONResponse({"ok":True,**account_payload(account.visitor_id)}); _set_visitor_cookie(out,account.visitor_id); return out
    finally: db.close()

@app.post("/api/auth/logout")
def auth_logout(request: Request):
    """End the browser identity session. The account remains safely stored in DB."""
    out = JSONResponse({"ok": True, "signed_out": True})
    out.delete_cookie("vexdou_visitor", path="/")
    # Also expire common variants created by older deployments.
    out.delete_cookie("vexdou_visitor", path="/", secure=True)
    out.delete_cookie("vexdou_visitor", path="/", secure=False)
    return out

@app.post("/api/auth/forgot")
def forgot_password(data: ForgotPasswordRequest):
    if free_mode_enabled(): raise HTTPException(403,"Accounts are disabled while QuickDL Free Mode is active.")
    email=normalize_email(data.email); db=Session()
    try:
        account=db.scalar(select(CreditAccount).where(CreditAccount.email==email).with_for_update())
        if account and account.email_verified:
            code=make_code(); account.reset_code_hash=code_hash(code); account.reset_code_expires_at=datetime.fromtimestamp(time.time()+AUTH_CODE_MINUTES*60,timezone.utc); db.commit(); send_auth_email(email,"Reset your QuickDL password","Password reset code","Use this code to choose a new QuickDL password.",code,"Password reset code")
        else: db.commit()
        return {"ok":True,"message":"If that email has a QuickDL account, a reset code has been sent."}
    finally: db.close()

@app.post("/api/auth/reset")
def reset_password(data: ResetPasswordRequest, request: Request):
    if free_mode_enabled(): raise HTTPException(403,"Accounts are disabled while QuickDL Free Mode is active.")
    email=normalize_email(data.email); code=(data.code or "").strip()
    if not re.fullmatch(r"\d{6}",code): raise HTTPException(400,"Enter the 6-digit reset code.")
    new_hash=password_hash(data.password); db=Session()
    try:
        account=db.scalar(select(CreditAccount).where(CreditAccount.email==email).with_for_update())
        if not account or not account.reset_code_expires_at or _expired(account.reset_code_expires_at) or not hmac.compare_digest(account.reset_code_hash or "",code_hash(code)): raise HTTPException(400,"The reset code is invalid or expired.")
        account.password_hash=new_hash; account.reset_code_hash=None; account.reset_code_expires_at=None; account.updated_at=datetime.now(timezone.utc); db.commit(); out=JSONResponse({"ok":True,**account_payload(account.visitor_id)}); _set_visitor_cookie(out,account.visitor_id); return out
    finally: db.close()

class GoogleLoginRequest(BaseModel):
    credential: str

@app.post("/api/auth/google")
def google_login(data: GoogleLoginRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if free_mode_enabled(): raise HTTPException(403,"Accounts are disabled while QuickDL Free Mode is active.")
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google Login is not configured.")
    visitor = _visitor_from(request, vexdou_visitor)
    try:
        credential = (data.credential or "").strip()
        if not credential or len(credential) > 12000:
            raise ValueError("Missing or invalid Google credential")
        info = None
        if google_id_token is not None and google_requests is not None:
            info = google_id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
        else:
            r = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": credential}, timeout=15)
            if r.status_code >= 400:
                raise ValueError("Google rejected the sign-in token")
            info = r.json()
        if str(info.get("aud") or "") != GOOGLE_CLIENT_ID:
            raise ValueError("Google token audience does not match this site")
        if str(info.get("iss") or "") not in {"accounts.google.com", "https://accounts.google.com"}:
            raise ValueError("Invalid Google token issuer")
        if str(info.get("email_verified", "")).lower() != "true":
            raise ValueError("Google email is not verified")
        sub = str(info.get("sub") or "").strip()
        email = str(info.get("email") or "").strip().lower()
        name = str(info.get("name") or email.split("@")[0] or "Google User")[:200]
        picture = str(info.get("picture") or "")[:2000]
        if not sub or not email or "@" not in email:
            raise ValueError("Google did not return a valid account")
    except Exception as exc:
        log.warning("Google sign-in verification failed: %s", exc)
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.")

    db = Session()
    try:
        current = ensure_credit_account(db, visitor)
        existing = db.scalar(select(CreditAccount).where((CreditAccount.google_sub == sub) | (CreditAccount.google_email == email) | (CreditAccount.email == email)).with_for_update())
        login_open = setting_bool("google_login_enabled")
        if existing and existing.visitor_id != current.visitor_id:
            target = existing
            # Never silently merge anonymous monthly free credits into an existing
            # Google account; this prevents free-credit farming across browsers.
            if current.purchased_credits:
                target.purchased_credits += current.purchased_credits
                current.purchased_credits = 0
            first_google_login = not bool(target.google_sub)
            target.google_sub=sub; target.google_email=email; target.google_name=name; target.google_picture=picture; target.google_linked_at=datetime.now(timezone.utc)
            db.commit()
            queue_user_email(target.visitor_id, "QuickDL — Google sign-in", "Google sign-in confirmed", "Your Google account was used to sign in to QuickDL successfully.", "GOOGLE SIGN-IN")
            if first_google_login and not target.google_welcome_sent_at and (RESEND_API_KEY or SMTP_PASSWORD):
                try:
                    send_welcome_email(email,name,target.user_code, "google")
                    db2=Session()
                    try:
                        fresh=db2.get(CreditAccount,target.id)
                        if fresh:
                            fresh.google_welcome_sent_at=datetime.now(timezone.utc); fresh.welcome_email_sent_at=datetime.now(timezone.utc); db2.commit()
                    finally:
                        db2.close()
                except Exception:
                    log.exception("Google welcome email failed for %s", email)
            payload=account_payload(target.visitor_id)
            out=JSONResponse({"ok":True,"linked":True,"message":"Google account connected.","welcome_email_sent":bool(target.google_welcome_sent_at),**payload})
            _set_visitor_cookie(out,target.visitor_id)
            return out
        if not login_open and not current.google_sub:
            raise HTTPException(403, "Google Login is currently closed for new users.")
        first_google_login = not bool(current.google_sub)
        current.google_sub=sub; current.google_email=email; current.google_name=name; current.google_picture=picture; current.google_linked_at=datetime.now(timezone.utc); current.updated_at=datetime.now(timezone.utc)
        db.commit()
        queue_user_email(current.visitor_id, "QuickDL — Google sign-in", "Google sign-in confirmed", "Your Google account was used to sign in to QuickDL successfully.", "GOOGLE SIGN-IN")
        if first_google_login and not current.google_welcome_sent_at and (RESEND_API_KEY or SMTP_PASSWORD):
            try:
                send_welcome_email(email,name,current.user_code, "google")
                db2=Session()
                try:
                    fresh=db2.get(CreditAccount,current.id)
                    if fresh:
                        fresh.google_welcome_sent_at=datetime.now(timezone.utc)
                        fresh.welcome_email_sent_at=datetime.now(timezone.utc)
                        db2.commit()
                finally:
                    db2.close()
            except Exception:
                # Login must never fail just because an optional welcome email failed.
                log.exception("Google welcome email failed for %s", email)
        payload=account_payload(current.visitor_id)
        out=JSONResponse({"ok":True,"linked":True,"message":"Google account connected.","welcome_email_sent":bool(current.google_welcome_sent_at),**payload})
        _set_visitor_cookie(out,current.visitor_id)
        return out
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
def paypal_create_order(data: PackageRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if free_mode_enabled(): raise HTTPException(403,"Payments are disabled while QuickDL Free Mode is active.")
    vexdou_visitor = _visitor_from(request, vexdou_visitor)
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
def paypal_capture_order(order_id: str, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    if free_mode_enabled(): raise HTTPException(403,"Payments are disabled while QuickDL Free Mode is active.")
    vexdou_visitor = _visitor_from(request, vexdou_visitor)
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
            queue_user_email(vexdou_visitor, "QuickDL credit purchase confirmed", "Your credits were added", f"Your PayPal purchase of {po.credits:,} credits has been confirmed and added to your QuickDL account.", "PAYMENT CONFIRMED", "#20b486")
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

class ContactRequest(BaseModel):
    name: str = ""
    email: str = ""
    message: str

@app.get("/about", response_class=HTMLResponse)
def about_page():
    return FileResponse(BASE / "templates" / "owner.html")

@app.get("/privacy", response_class=HTMLResponse)
def privacy_page():
    return FileResponse(BASE / "templates" / "privacy.html")

@app.get("/contact", response_class=HTMLResponse)
def contact_page():
    return FileResponse(BASE / "templates" / "contact.html")

@app.post("/api/contact")
def contact_submit(data: ContactRequest, request: Request, vexdou_visitor: str | None = Cookie(default=None)):
    visitor=_visitor_from(request,vexdou_visitor)
    message=(data.message or "").strip()
    if len(message)<3: raise HTTPException(400,"Please enter your message.")
    if len(message)>5000: raise HTTPException(400,"Message is too long.")
    db=Session()
    try:
        account=ensure_credit_account(db,visitor)
        row=ContactMessage(visitor_id=visitor,user_code=account.user_code,name=(data.name or "").strip()[:160] or None,email=(data.email or "").strip()[:320] or None,message=message)
        db.add(row); db.commit(); audit("contact_message",f"user={account.user_code}")
        return {"ok":True,"message":"Your message has been sent to QuickDL support."}
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

class ContactMessage(Base):
    __tablename__ = "contact_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    user_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
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
    "credits_enabled": "true",
    "google_login_enabled": "true",
    "login_enabled": "true",
    "ads_enabled": "false",
    "ads_text": "",
    "ads_url": "",
    "ads_button_text": "Learn more",
    "free_mode": "true",
    "whatsapp_support_enabled": "true",
    "whatsapp_support_phone": "+252907868526",
    "owner_name": "Mohamet Abdirahman Osman Ahmet",
    "owner_title": "CEO & Owner of QuickDL",
}

def setting_get(key, db=None):
    """Read one admin setting, reusing a caller session when provided."""
    own = db is None
    db = db or Session()
    try:
        row = db.get(AdminSetting, key)
        return row.value if row else DEFAULT_SETTINGS.get(key, "")
    finally:
        if own:
            db.close()

def settings_all():
    db = Session()
    try:
        vals = dict(DEFAULT_SETTINGS)
        for row in db.scalars(select(AdminSetting)).all(): vals[row.key] = row.value
        return vals
    finally: db.close()

def setting_bool(key, db=None):
    return setting_get(key, db).lower() in {"1", "true", "yes", "on"}

def bootstrap_access_settings():
    """Migrate the old closed-by-default access flags once on v28.

    After this one-time migration, admin changes are respected normally.
    """
    db = Session()
    try:
        marker = db.get(AdminSetting, "v28_access_settings_migrated")
        if marker is None:
            for key in ("login_enabled", "google_login_enabled"):
                row = db.get(AdminSetting, key)
                if row is None:
                    db.add(AdminSetting(key=key, value="true"))
                elif str(row.value).strip().lower() in {"false", "0", "no", "off", ""}:
                    row.value = "true"
                    row.updated_at = datetime.now(timezone.utc)
            db.add(AdminSetting(key="v28_access_settings_migrated", value="true"))
            db.commit()
    except Exception:
        db.rollback()
        log.exception("access settings bootstrap failed")
    finally:
        db.close()

bootstrap_access_settings()

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
            "version":"36.0.0",
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
            "google_login_configured":bool(GOOGLE_CLIENT_ID),
            "email_auth_configured":bool(SMTP_PASSWORD or RESEND_API_KEY),"email_provider":EMAIL_PROVIDER,
            "settings":settings_all(),
        }
    finally: db.close()

@app.get("/api/admin/email/health")
def admin_email_health(request: Request):
    require_admin(request)
    return smtp_health()

@app.get("/api/email/health")
def public_email_health():
    """Public health check without provider, hosting, or configuration details."""
    try:
        h=smtp_health()
        return {"ok": bool(h.get("ok")), "message": "Email service is ready." if h.get("ok") else "Email service is temporarily unavailable."}
    except Exception:
        return {"ok":False,"message":"Email service is temporarily unavailable."}

@app.get("/admin", response_class=HTMLResponse)
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
        return {"version":"36.0.0-admin", "users":users, "downloads":len(rows), "today":len(today), "week":len(week), "completed":status.get("completed",0), "failed":status.get("failed",0), "queued":status.get("queued",0), "downloading":status.get("downloading",0), "platforms":plats, "settings":settings_all(), "worker":"running"}
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
    require_admin(request); db=Session(); limit=max(1,min(limit,300))
    try:
        items=[]
        for r in db.scalars(select(AppError).order_by(AppError.created_at.desc()).limit(limit)).all():
            items.append({"reference":r.reference,"type":"application","method":r.method,"path":r.path,"status":r.status,"error":r.message,"error_type":r.error_type,"created_at":r.created_at.isoformat() if r.created_at else None})
        for r in db.scalars(select(Download).where(Download.status=="failed").order_by(Download.created_at.desc()).limit(limit)).all():
            items.append({"reference":r.job_id,"type":"download","method":"WORKER","path":r.url,"status":500,"error":r.error or "Download failed","error_type":"DownloadError","created_at":r.created_at.isoformat() if r.created_at else None})
        items.sort(key=lambda x:x.get("created_at") or "", reverse=True)
        return {"items":items[:limit]}
    finally: db.close()

@app.get("/api/admin/audit")
def admin_audit(request: Request, limit: int = 100):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(max(1,min(limit,300)))).all(); return {"items":[{"action":r.action,"detail":r.detail,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

class AdminCreditAction(BaseModel):
    visitor_id: str = ""
    user_code: str = ""
    credits: int = 0
    unlimited: bool | None = None
    note: str = "Admin adjustment"

def resolve_admin_visitor(db, data: AdminCreditAction):
    code=(data.user_code or "").strip()
    visitor=(data.visitor_id or "").strip()
    if code:
        if not re.fullmatch(r"\d{10}", code): raise HTTPException(400, "User ID must be exactly 10 digits")
        account=db.scalar(select(CreditAccount).where(CreditAccount.user_code==code))
        if not account: raise HTTPException(404, "User ID not found")
        return account.visitor_id
    if not visitor or len(visitor)>128: raise HTTPException(400, "Enter a valid user ID")
    return visitor

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
            if q and q not in a.visitor_id.lower() and q not in str(a.user_code or "").lower() and q not in str(a.google_email or "").lower() and q not in str(a.google_name or "").lower(): continue
            c=counts.get(a.visitor_id,{})
            items.append({"visitor_id":a.visitor_id,"user_code":a.user_code,"credits":credit_balance(a),"free_credits":a.free_credits,"purchased_credits":a.purchased_credits,"unlimited":bool(getattr(a,"unlimited",False)),"last_seen":c.get("last_seen").isoformat() if c.get("last_seen") else None,"downloads":c.get("downloads",0),"completed":c.get("completed",0),"failed":c.get("failed",0),"updated_at":a.updated_at.isoformat() if a.updated_at else None,"google":bool(a.google_sub),"google_email":a.google_email,"google_name":a.google_name,"google_picture":a.google_picture,"email":a.email,"email_verified":bool(getattr(a,"email_verified",False)),"auth_name":a.auth_name,"last_seen":c.get("last_seen").isoformat() if c.get("last_seen") else None})
        return {"items":items[:limit]}
    finally: db.close()

@app.get("/api/admin/user-code/{user_code}")
def admin_user_by_code(user_code: str, request: Request):
    require_admin(request)
    if not re.fullmatch(r"\d{10}", user_code): raise HTTPException(400, "User ID must be exactly 10 digits")
    db=Session()
    try:
        a=db.scalar(select(CreditAccount).where(CreditAccount.user_code==user_code))
        if not a: raise HTTPException(404, "User not found")
        return admin_user_detail(a.visitor_id, request)
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
            "user_code": a.user_code,
            "visitor_id": visitor_id,
            "google": {"connected": bool(a.google_sub), "email": a.google_email, "name": a.google_name, "picture": a.google_picture},
            "transactions":[{"type":r.tx_type,"credits":r.credits,"amount":r.amount,"currency":r.currency,"package_id":r.package_id,"status":r.status,"note":r.note,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows],
            "downloads":[{"job_id":r.job_id,"url":r.url,"title":r.title,"platform":platform(r.url),"status":r.status,"error":r.error,"created_at":r.created_at.isoformat() if r.created_at else None} for r in downloads],
        }
    finally: db.close()

@app.post("/api/admin/credits/grant")
def admin_grant_credits(data: AdminCreditAction, request: Request):
    require_admin(request)
    if data.credits<0: raise HTTPException(400,"Invalid credit adjustment")
    db=Session()
    try:
        target=resolve_admin_visitor(db,data); a=ensure_credit_account(db,target)
        if data.credits:
            a.purchased_credits += data.credits
            db.add(CreditTransaction(visitor_id=target,tx_type="admin_grant",credits=data.credits,status="completed",note=data.note[:1000]))
        if data.unlimited is not None:
            a.unlimited=bool(data.unlimited)
            db.add(CreditTransaction(visitor_id=target,tx_type="admin_unlimited",credits=0,status="completed",note=("Unlimited enabled" if a.unlimited else "Unlimited disabled")+" · "+data.note[:900]))
        a.updated_at=datetime.now(timezone.utc); db.commit(); audit("admin_credit_adjustment",f"{target}: +{data.credits}, unlimited={data.unlimited}")
        if data.credits or data.unlimited is not None:
            queue_user_email(target, "QuickDL account credit update", "Your account was updated", f"An administrator updated your QuickDL account. Credits added: {data.credits:,}." + (" Unlimited access was enabled." if data.unlimited else ""), "ADMIN ACCOUNT UPDATE")
        return {"ok":True,**account_payload(target)}
    finally: db.close()

@app.post("/api/admin/credits/adjust")
def admin_adjust_compat(data: dict, request: Request):
    """Compatibility wrapper for the previous admin credit UI."""
    visitor_id = str(data.get("visitor_id") or "").strip()
    amount = int(data.get("amount") or 0)
    reason = str(data.get("description") or "Admin adjustment")[:1000]
    if not visitor_id or not re.fullmatch(r"[a-f0-9]{32}", visitor_id):
        raise HTTPException(400, "Invalid visitor ID.")
    require_admin(request)
    db=Session()
    try:
        a=ensure_credit_account(db, visitor_id)
        if amount >= 0:
            a.purchased_credits += amount
            tx=CreditTransaction(visitor_id=visitor_id, tx_type="admin_grant", credits=amount, status="completed", note=reason)
        else:
            remove=min(-amount, max(0,int(a.purchased_credits or 0)))
            a.purchased_credits-=remove
            tx=CreditTransaction(visitor_id=visitor_id, tx_type="admin_revoke", credits=-remove, status="completed", note=reason)
        a.updated_at=datetime.now(timezone.utc); db.add(tx); db.commit(); audit("admin_credit_adjustment_compat", f"{visitor_id}: {amount}")
        return {"ok":True,"balance":credit_balance(a),**account_payload(visitor_id)}
    finally: db.close()

@app.post("/api/admin/credits/revoke")
def admin_revoke_credits(data: AdminCreditAction, request: Request):
    require_admin(request)
    if data.credits<0: raise HTTPException(400,"Invalid amount")
    db=Session()
    try:
        target=resolve_admin_visitor(db,data); a=ensure_credit_account(db,target); amount=min(data.credits,max(0,int(a.purchased_credits or 0))); a.purchased_credits-=amount; a.updated_at=datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=target,tx_type="admin_revoke",credits=-amount,status="completed",note=data.note[:1000])); db.commit(); audit("admin_credit_revoke",f"{target}: -{amount}")
        if amount: queue_user_email(target, "QuickDL credit update", "Credits were removed", f"An administrator removed {amount:,} purchased credits from your account.", "ACCOUNT UPDATE", "#f05b75")
        return {"ok":True,**account_payload(target)}
    finally: db.close()

@app.post("/api/admin/credits/reset")
def admin_reset_credits(data: AdminCreditAction, request: Request):
    require_admin(request); db=Session()
    try:
        target=resolve_admin_visitor(db,data); a=ensure_credit_account(db,target); old=credit_balance(a) or 0; a.free_credits=MONTHLY_FREE_CREDITS; a.purchased_credits=0; a.unlimited=False; a.updated_at=datetime.now(timezone.utc)
        db.add(CreditTransaction(visitor_id=target,tx_type="admin_reset",credits=-int(old),status="completed",note=data.note[:1000])); db.commit(); audit("admin_credit_reset",target)
        queue_user_email(target, "QuickDL account credits reset", "Your credits were reset", "An administrator reset your QuickDL credit balance. Your monthly allowance remains available according to the current billing month.", "ACCOUNT UPDATE", "#f05b75")
        return {"ok":True,**account_payload(target)}
    finally: db.close()

@app.get("/api/admin/revenue")
def admin_revenue(request: Request):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(CreditTransaction).where(CreditTransaction.tx_type=="purchase",CreditTransaction.status=="completed").order_by(CreditTransaction.created_at.desc()).limit(5000)).all()
        total=sum(float(r.amount or 0) for r in rows); credits=sum(int(r.credits or 0) for r in rows)
        return {"total_revenue":round(total,2),"purchased_credits":credits,"transactions":len(rows),"items":[{"visitor_id":r.visitor_id,"amount":r.amount,"currency":r.currency,"credits":r.credits,"package_id":r.package_id,"order_id":r.paypal_order_id,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows[:100]]}
    finally: db.close()

@app.get("/api/admin/messages")
def admin_messages(request: Request, limit: int = 200):
    require_admin(request); db=Session()
    try:
        rows=db.scalars(select(ContactMessage).order_by(ContactMessage.created_at.desc()).limit(max(1,min(limit,500)))).all()
        return {"items":[{"id":r.id,"user_code":r.user_code,"name":r.name,"email":r.email,"message":r.message,"status":r.status,"created_at":r.created_at.isoformat() if r.created_at else None} for r in rows]}
    finally: db.close()

class AdminMessageAction(BaseModel):
    id: int
    status: str = "closed"

@app.post("/api/admin/messages/status")
def admin_message_status(data: AdminMessageAction, request: Request):
    require_admin(request); db=Session()
    try:
        row=db.get(ContactMessage,data.id)
        if not row: raise HTTPException(404,"Message not found")
        row.status=data.status if data.status in {"open","closed"} else "open"; db.commit(); audit("message_status",f"{data.id}: {row.status}")
        return {"ok":True}
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
            if key in {"login_enabled", "google_login_enabled"} and db.get(AdminSetting, "v28_access_settings_migrated") is None:
                db.add(AdminSetting(key="v28_access_settings_migrated", value="true"))
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

