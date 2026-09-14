"""Section 43 -- Notification Center. Notifications are routed by role or by
specific user; the background job (background.py) is what creates most of
them (staleness, escalation, holds); this router lets users read/consume
theirs."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..serialize import to_list

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


@router.get("")
def list_notifications(unread_only: bool = False, db: OrmSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    role_names = user.role_names()
    q = db.query(models.Notification).filter(
        or_(models.Notification.recipient_user_id == user.id, models.Notification.recipient_role.in_(role_names))
    )
    if unread_only:
        q = q.filter(models.Notification.read_at.is_(None))
    items = q.order_by(models.Notification.created_at.desc()).limit(100).all()
    return {"items": to_list(items)}


@router.patch("/{notification_id}")
def mark_read(notification_id: str, db: OrmSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    n = db.get(models.Notification, notification_id)
    if not n:
        raise HTTPException(404, "Notification not found.")
    n.read_at = dt.datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/mark-all-read")
def mark_all_read(db: OrmSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    role_names = user.role_names()
    items = db.query(models.Notification).filter(
        or_(models.Notification.recipient_user_id == user.id, models.Notification.recipient_role.in_(role_names)),
        models.Notification.read_at.is_(None),
    ).all()
    for n in items:
        n.read_at = dt.datetime.utcnow()
    db.commit()
    return {"ok": True, "count": len(items)}
