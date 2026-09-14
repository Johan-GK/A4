"""
FastAPI dependencies: current-session resolution + Section 44.5 server-side
authorization enforcement ("independent of what the client UI shows or
hides -- a hidden button is not a security control").
"""
import datetime as dt

from fastapi import Depends, HTTPException, status, Header
from sqlalchemy.orm import Session as OrmSession

from . import models, security
from .database import get_db
from .permissions import ROLE_PERMISSIONS


def get_current_session(
    authorization: str | None = Header(default=None),
    db: OrmSession = Depends(get_db),
) -> models.Session:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    payload = security.decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")

    sess = db.get(models.Session, payload.get("sid"))
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session not found.")
    if sess.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session has been revoked.")
    now = dt.datetime.utcnow()
    if sess.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired.")
    if (now - sess.last_seen_at).total_seconds() > 30 * 60:
        # idle timeout (Section 44.3), independent of the JWT's own exp
        sess.revoked_at = now
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired due to inactivity.")
    sess.last_seen_at = now
    db.commit()
    return sess


def get_current_user(
    sess: models.Session = Depends(get_current_session),
    db: OrmSession = Depends(get_db),
) -> models.User:
    user = db.get(models.User, sess.user_id)
    if user is None or user.status != "ACTIVE":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not active.")
    return user


def user_permissions(user: models.User) -> set:
    perms = set()
    for role_name in user.role_names():
        perms.update(ROLE_PERMISSIONS.get(role_name, []))
    return perms


def require_permission(*codes: str):
    """Any one of the given permission codes is sufficient."""

    def _dep(user: models.User = Depends(get_current_user)) -> models.User:
        granted = user_permissions(user)
        if not granted.intersection(codes):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Missing required permission (one of: {', '.join(codes)}).",
            )
        return user

    return _dep
