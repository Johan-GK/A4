"""Section 44 -- Login & Security."""
import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from .. import models, security, schemas
from ..audit import write_audit
from ..config import settings
from ..database import get_db
from ..deps import get_current_user, get_current_session
from ..serialize import to_dict
from ..permissions import ROLE_PERMISSIONS

router = APIRouter(prefix="/v1/auth", tags=["auth"])

# In-memory pending-MFA tickets (short-lived; not worth a DB table for a
# reference build). ticket -> {user_id, expires}
_pending_mfa: dict[str, dict] = {}


def _lockout_alert_check(db: OrmSession):
    """Section 44.4: a pattern of lockouts across many distinct accounts in a
    short window is itself an Alert (credential-stuffing signal)."""
    window_start = dt.datetime.utcnow() - dt.timedelta(minutes=15)
    count = db.query(models.User).filter(models.User.lockout_until != None, models.User.updated_at >= window_start).count()  # noqa: E711
    if count >= 3:
        existing = db.query(models.Alert).filter(models.Alert.type == "CREDENTIAL_STUFFING_SUSPECTED", models.Alert.status.in_(["NEW", "ACKNOWLEDGED", "IN_PROGRESS"])).first()
        if not existing:
            db.add(models.Alert(
                code=f"AL-{uuid.uuid4().hex[:6]}", type="CREDENTIAL_STUFFING_SUSPECTED", severity="HIGH",
                source="LOGIN_MONITOR", status="NEW",
                message=f"{count} accounts locked out within a 15-minute window -- possible credential-stuffing attack.",
                sla_due_at=dt.datetime.utcnow() + dt.timedelta(minutes=settings.ALERT_SLA_MINUTES["HIGH"]),
            ))


@router.post("/login")
def login(body: schemas.LoginRequest, request: Request, db: OrmSession = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == body.username).first()
    generic_error = "Invalid username or password."

    if user and user.lockout_until and user.lockout_until > dt.datetime.utcnow():
        write_audit(db, user_id=user.id, action="LOGIN_FAILED_LOCKED", entity_type="USER", entity_id=user.id)
        db.commit()
        raise HTTPException(status.HTTP_423_LOCKED, f"Account locked until {user.lockout_until.isoformat()}.")

    if not user or not security.verify_password(body.password, user.password_hash):
        if user:
            window_start = user.failed_login_window_start
            now = dt.datetime.utcnow()
            if not window_start or (now - window_start).total_seconds() > settings.LOCKOUT_WINDOW_MINUTES * 60:
                user.failed_login_count = 0
                user.failed_login_window_start = now
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.LOCKOUT_MAX_ATTEMPTS:
                user.lockout_count = (user.lockout_count or 0) + 1
                minutes = settings.LOCKOUT_BASE_MINUTES * (2 ** (user.lockout_count - 1))
                user.lockout_until = now + dt.timedelta(minutes=minutes)
                user.status = "LOCKED" if user.status == "ACTIVE" else user.status
                write_audit(db, user_id=user.id, action="ACCOUNT_LOCKED", entity_type="USER", entity_id=user.id,
                            reason=f"{user.failed_login_count} failed attempts within lockout window.")
                _lockout_alert_check(db)
            write_audit(db, user_id=user.id, action="LOGIN_FAILED", entity_type="USER", entity_id=user.id)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, generic_error)

    if user.status != "ACTIVE" and user.status != "LOCKED":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.status}.")
    if user.status == "LOCKED" and (not user.lockout_until or user.lockout_until <= dt.datetime.utcnow()):
        user.status = "ACTIVE"   # lockout window elapsed

    # success -- reset failure counters
    user.failed_login_count = 0
    user.failed_login_window_start = None

    roles = user.role_names()
    mfa_required = user.mfa_enabled or bool(set(roles) & settings.MFA_REQUIRED_ROLES and user.mfa_enabled)

    if user.mfa_enabled:
        ticket = uuid.uuid4().hex
        _pending_mfa[ticket] = {"user_id": user.id, "expires": dt.datetime.utcnow() + dt.timedelta(minutes=5)}
        write_audit(db, user_id=user.id, action="LOGIN_MFA_CHALLENGE", entity_type="USER", entity_id=user.id)
        db.commit()
        return {"mfaRequired": True, "loginTicket": ticket}

    return _issue_session(db, user, request)


def _issue_session(db: OrmSession, user: models.User, request: Request):
    now = dt.datetime.utcnow()
    sess = models.Session(
        user_id=user.id,
        token_hash="pending",
        expires_at=now + dt.timedelta(hours=settings.SESSION_ABSOLUTE_HOURS),
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        last_seen_at=now,
    )
    db.add(sess)
    db.flush()

    access = security.create_access_token(user.id, sess.id, user.role_names())
    refresh = security.create_refresh_token(user.id, sess.id)
    sess.token_hash = security.hash_token(access)

    write_audit(db, user_id=user.id, action="LOGIN_SUCCESS", entity_type="USER", entity_id=user.id,
                session_info=sess.id)
    db.commit()

    granted = set()
    for r in user.role_names():
        granted.update(ROLE_PERMISSIONS.get(r, []))

    return {
        "accessToken": access,
        "refreshToken": refresh,
        "expiresInMinutes": settings.ACCESS_TOKEN_MINUTES,
        "user": {**to_dict(user, {"roles": user.role_names(), "permissions": sorted(granted)})},
    }


@router.post("/mfa/verify")
def verify_mfa(body: schemas.MfaVerifyRequest, request: Request, db: OrmSession = Depends(get_db)):
    ticket = _pending_mfa.get(body.loginTicket)
    if not ticket or ticket["expires"] < dt.datetime.utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA ticket expired or invalid; log in again.")
    user = db.get(models.User, ticket["user_id"])
    if not user or not security.verify_totp(user.mfa_secret, body.code):
        write_audit(db, user_id=user.id if user else None, action="LOGIN_MFA_FAILED", entity_type="USER", entity_id=ticket["user_id"])
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA code.")
    del _pending_mfa[body.loginTicket]
    write_audit(db, user_id=user.id, action="LOGIN_MFA_SUCCESS", entity_type="USER", entity_id=user.id)
    return _issue_session(db, user, request)


@router.post("/refresh")
def refresh(body: schemas.RefreshRequest, db: OrmSession = Depends(get_db)):
    payload = security.decode_token(body.refreshToken)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token.")
    sess = db.get(models.Session, payload.get("sid"))
    if not sess or sess.revoked_at or sess.expires_at < dt.datetime.utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session no longer valid.")
    user = db.get(models.User, sess.user_id)
    access = security.create_access_token(user.id, sess.id, user.role_names())
    sess.token_hash = security.hash_token(access)
    sess.last_seen_at = dt.datetime.utcnow()
    db.commit()
    return {"accessToken": access, "expiresInMinutes": settings.ACCESS_TOKEN_MINUTES}


@router.post("/logout")
def logout(sess: models.Session = Depends(get_current_session), user: models.User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    sess.revoked_at = dt.datetime.utcnow()
    write_audit(db, user_id=user.id, action="LOGOUT", entity_type="USER", entity_id=user.id, session_info=sess.id)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    granted = set()
    for r in user.role_names():
        granted.update(ROLE_PERMISSIONS.get(r, []))
    return {**to_dict(user, {"roles": user.role_names(), "permissions": sorted(granted)})}
