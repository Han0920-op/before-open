import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import DomainError
from app.models.entities import AnonymousSession
from app.schemas.api import SessionView

Db = Annotated[Session, Depends(get_db, scope="function")]
COOKIE = "before_open_session"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(token: str) -> str:
    return digest(f"csrf:{token}")


def current_session(
    request: Request,
    db: Db,
    session_token: Annotated[str | None, Cookie(alias=COOKIE)] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AnonymousSession:
    token = session_token if session_token is not None else request.cookies.get(COOKIE)
    session = (
        db.scalar(
            select(AnonymousSession).where(AnonymousSession.token_hash == digest(token or ""))
        )
        if token
        else None
    )
    if session is None:
        raise DomainError(401, "SESSION_REQUIRED", "请先建立匿名会话")
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        raise DomainError(401, "SESSION_EXPIRED", "匿名会话已过期")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = csrf_token if csrf_token is not None else request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(digest(csrf), session.csrf_hash):
            raise DomainError(403, "CSRF_INVALID", "请使用当前会话的确认凭据")
    return session


Actor = Annotated[AnonymousSession, Depends(current_session)]


def open_session(request: Request, response: Response, db: Session) -> SessionView:
    token = request.cookies.get(COOKIE)
    if token:
        session = current_session(request, db)
    else:
        token = secrets.token_urlsafe(32)
        session = AnonymousSession(
            token_hash=digest(token),
            csrf_hash=digest(csrf_for(token)),
            expires_at=datetime.now(UTC) + timedelta(days=request.app.state.settings.session_days),
        )
        db.add(session)
        db.flush()
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            secure=request.app.state.settings.cookie_secure,
            samesite="lax",
            path="/",
            max_age=request.app.state.settings.session_days * 86400,
        )
    response.headers["Cache-Control"] = "no-store"
    return SessionView(csrf_token=csrf_for(token), expires_at=session.expires_at)
