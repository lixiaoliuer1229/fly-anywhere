"""Database-backed accounts and revocable cookie sessions."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE = "fly_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, _ = encoded.split("$")
        return algorithm == "scrypt" and hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


def check_origin(request: Request):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "不允许跨站请求")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    check_origin(request)
    token = request.cookies.get(COOKIE, "")
    session = db.get(UserSession, hashlib.sha256(token.encode()).hexdigest()) if token else None
    if not session or session.expires_at <= datetime.utcnow():
        raise HTTPException(401, "请先登录")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "请先登录")
    return user


def start_session(user: User, request: Request, response: Response, db: Session):
    old_token = request.cookies.get(COOKIE)
    if old_token:
        db.query(UserSession).filter_by(token_hash=hashlib.sha256(old_token.encode()).hexdigest()).delete()
    db.query(UserSession).filter(UserSession.expires_at <= datetime.utcnow()).delete()
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                       expires_at=datetime.utcnow() + timedelta(seconds=SESSION_SECONDS)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=settings.AUTH_COOKIE_SECURE, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"id": user.id, "username": user.username}


@router.post("/register", status_code=201, dependencies=[Depends(check_origin)])
def register(data: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    user = User(username=data.username, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该账号已存在")
    return start_session(user, request, response, db)


@router.post("/login", dependencies=[Depends(check_origin)])
def login(data: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=data.username).first()
    valid = verify_password(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "账号或密码错误")
    return start_session(user, request, response, db)


@router.get("/me")
def me(response: Response, user: User = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return {"id": user.id, "username": user.username}


@router.post("/logout", dependencies=[Depends(check_origin)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE, "")
    db.query(UserSession).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).delete()
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
