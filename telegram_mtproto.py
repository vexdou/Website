import asyncio, base64, hashlib, os
from datetime import datetime, timezone
from cryptography.fernet import Fernet

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError
except Exception:
    TelegramClient = None
    StringSession = None
    SessionPasswordNeededError = Exception

API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or 0)
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
SESSION_SECRET = os.getenv("TELEGRAM_SESSION_SECRET", "").strip()

def configured():
    return bool(TelegramClient and API_ID and API_HASH and SESSION_SECRET)

def _fernet():
    if not SESSION_SECRET:
        raise RuntimeError("TELEGRAM_SESSION_SECRET is not configured")
    key = base64.urlsafe_b64encode(hashlib.sha256(SESSION_SECRET.encode()).digest())
    return Fernet(key)

def encrypt_session(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def decrypt_session(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()

def run(coro):
    return asyncio.run(coro)

async def send_code(phone: str):
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        return {"session": client.session.save(), "phone_code_hash": sent.phone_code_hash}
    finally:
        await client.disconnect()

async def sign_in(session: str, phone: str, code: str, phone_code_hash: str):
    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            user = await client.get_me()
            return {"status": "ok", "session": client.session.save(), "user": user}
        except SessionPasswordNeededError:
            return {"status": "2fa", "session": client.session.save()}
    finally:
        await client.disconnect()

async def check_password(session: str, password: str):
    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(password=password)
        user = await client.get_me()
        return {"status": "ok", "session": client.session.save(), "user": user}
    finally:
        await client.disconnect()

async def get_me(session: str):
    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        return await client.get_me()
    finally:
        await client.disconnect()

async def dialogs(session: str, limit: int = 100):
    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        out = []
        async for d in client.iter_dialogs(limit=limit):
            e = d.entity
            out.append({
                "id": int(d.id),
                "name": d.name or "",
                "username": getattr(e, "username", None),
                "unread_count": int(getattr(d, "unread_count", 0) or 0),
                "is_user": bool(getattr(d, "is_user", False)),
                "is_group": bool(getattr(d, "is_group", False)),
                "is_channel": bool(getattr(d, "is_channel", False)),
            })
        return out
    finally:
        await client.disconnect()

async def messages(session: str, dialog_id: int, limit: int = 50):
    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        entity = None
        async for d in client.iter_dialogs(limit=200):
            if int(d.id) == int(dialog_id):
                entity = d.entity
                break
        if entity is None:
            raise ValueError("Chat not found in this account's dialogs")
        out = []
        async for m in client.iter_messages(entity, limit=max(1, min(limit, 100))):
            sender = await m.get_sender() if m.sender_id else None
            out.append({
                "id": int(m.id),
                "text": m.message or "",
                "date": m.date.isoformat() if m.date else None,
                "out": bool(m.out),
                "sender_id": int(m.sender_id) if m.sender_id else None,
                "sender_name": ((getattr(sender, "first_name", "") or "") + " " + (getattr(sender, "last_name", "") or "")).strip() if sender else None,
                "media": bool(m.media),
            })
        return out
    finally:
        await client.disconnect()

async def send_message(session: str, dialog_id: int, text: str):
    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        entity = None
        async for d in client.iter_dialogs(limit=200):
            if int(d.id) == int(dialog_id):
                entity = d.entity
                break
        if entity is None:
            raise ValueError("Chat not found in this account's dialogs")
        m = await client.send_message(entity, text)
        return {"id": int(m.id), "date": m.date.isoformat() if m.date else None}
    finally:
        await client.disconnect()
