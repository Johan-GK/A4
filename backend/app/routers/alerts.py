"""Sections 33-34 -- Alert Management, Alert State Machine. Section 35.3's
escalation timers are enforced by the background job (background.py); this
router handles the human-driven transitions."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models, schemas
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..serialize import to_dict, to_list
from ..state_machines import validate_transition, IllegalTransitionError

router = APIRouter(prefix="/v1/alerts", tags=["alerts"])


@router.get("")
def list_alerts(status_: str = None, severity: str = None, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Alert)
    if status_:
        q = q.filter(models.Alert.status == status_)
    if severity:
        q = q.filter(models.Alert.severity == severity)
    alerts = q.order_by(models.Alert.created_at.desc()).all()
    return {"items": to_list(alerts)}


@router.post("/{alert_id}/transitions")
def transition_alert(alert_id: str, body: schemas.TransitionRequest, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_ALERTS"))):
    a = db.get(models.Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found.")
    try:
        validate_transition("ALERT", a.status, body.toState)
    except IllegalTransitionError as e:
        raise HTTPException(422, {"code": "ILLEGAL_TRANSITION", "attempted": body.toState, "current": a.status, "message": str(e)})
    if body.toState == "DISMISSED" and not body.reason:
        raise HTTPException(422, "A reason is required to dismiss an alert.")

    old_status = a.status
    a.status = body.toState
    if body.toState == "ACKNOWLEDGED":
        a.acknowledged_at = dt.datetime.utcnow()
        a.assigned_to = user.id
    elif body.toState == "RESOLVED":
        a.resolved_at = dt.datetime.utcnow()
    write_audit(db, user_id=user.id, action="ALERT_TRANSITION", entity_type="ALERT", entity_id=alert_id,
                old_value={"status": old_status}, new_value={"status": body.toState}, reason=body.reason)
    db.commit()
    return to_dict(a)
