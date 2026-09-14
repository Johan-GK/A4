"""Sections 31-32 -- Incident Management, Incident State Machine."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models, schemas
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..serialize import to_dict, to_list
from ..state_machines import validate_transition, IllegalTransitionError

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])


@router.get("")
def list_incidents(status_: str = None, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.Incident)
    if status_:
        q = q.filter(models.Incident.status == status_)
    return {"items": to_list(q.order_by(models.Incident.detected_at.desc()).all())}


@router.post("", status_code=201)
def create_incident(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_INCIDENTS", "REPORT_INCIDENTS"))):
    inc = models.Incident(
        code=f"INC-{int(dt.datetime.utcnow().timestamp()) % 100000}", type=body.get("type"),
        severity=body.get("severity", "LOW"), detected_by=user.id, order_id=body.get("orderId"),
        run_id=body.get("runId"), machine_id=body.get("machineId"), batch_id=body.get("batchId"),
        operator_id=body.get("operatorId"), description=body.get("description"), status="OPEN",
        assigned_to=body.get("assignedTo"),
    )
    db.add(inc)
    write_audit(db, user_id=user.id, action="CREATE_INCIDENT", entity_type="INCIDENT", entity_id=inc.id, new_value=body)
    db.commit()
    return to_dict(inc)


@router.post("/{incident_id}/transitions")
def transition_incident(incident_id: str, body: schemas.TransitionRequest, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_INCIDENTS"))):
    inc = db.get(models.Incident, incident_id)
    if not inc:
        raise HTTPException(404, "Incident not found.")
    try:
        validate_transition("INCIDENT", inc.status, body.toState)
    except IllegalTransitionError as e:
        raise HTTPException(422, {"code": "ILLEGAL_TRANSITION", "attempted": body.toState, "current": inc.status, "message": str(e)})
    if body.toState == "CLOSED" and not body.reason:
        raise HTTPException(422, "A closure reason is required.")

    old_status = inc.status
    inc.status = body.toState
    if body.toState == "CLOSED":
        inc.closed_by = user.id
        inc.closed_at = dt.datetime.utcnow()
        inc.resolution = body.reason
    write_audit(db, user_id=user.id, action="INCIDENT_TRANSITION", entity_type="INCIDENT", entity_id=incident_id,
                old_value={"status": old_status}, new_value={"status": body.toState}, reason=body.reason)
    db.commit()
    return to_dict(inc)


@router.patch("/{incident_id}")
def update_incident(incident_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_INCIDENTS"))):
    inc = db.get(models.Incident, incident_id)
    if not inc:
        raise HTTPException(404, "Incident not found.")
    for field, key in [("assignedTo", "assigned_to"), ("resolution", "resolution"), ("description", "description")]:
        if field in body:
            setattr(inc, key, body[field])
    db.commit()
    return to_dict(inc)
