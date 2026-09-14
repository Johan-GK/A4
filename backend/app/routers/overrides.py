"""Section 27 -- Override System. Every override creates an Override record
linked to its own AuditLog entry -- never merely a bypassed check."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models, schemas
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..serialize import to_dict, to_list

router = APIRouter(prefix="/v1/overrides", tags=["overrides"])


@router.get("")
def list_overrides(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    return {"items": to_list(db.query(models.Override).order_by(models.Override.timestamp.desc()).all())}


@router.post("", status_code=201)
def request_override(body: schemas.OverrideCreateRequest, db: OrmSession = Depends(get_db), user=Depends(require_permission("CREATE_OVERRIDE"))):
    entry = write_audit(db, user_id=user.id, action="OVERRIDE_REQUESTED", entity_type=body.entityType, entity_id=body.entityId,
                         reason=body.reason)
    db.flush()
    ov = models.Override(
        conflict_type=body.conflictType, requested_by=user.id, reason=body.reason, justification=body.justification,
        entity_type=body.entityType, entity_id=body.entityId, status="PENDING", linked_audit_id=entry.id,
    )
    db.add(ov)
    db.commit()
    return to_dict(ov)


@router.get("/{override_id}")
def get_override(override_id: str, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    ov = db.get(models.Override, override_id)
    if not ov:
        raise HTTPException(404, "Override not found.")
    return to_dict(ov)


@router.post("/{override_id}/approve")
def approve_override(override_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("APPROVE_OVERRIDE"))):
    ov = db.get(models.Override, override_id)
    if not ov:
        raise HTTPException(404, "Override not found.")
    if ov.status != "PENDING":
        raise HTTPException(422, f"Override is already {ov.status}.")
    ov.status = "APPROVED"
    ov.approved_by = user.id
    write_audit(db, user_id=user.id, action="OVERRIDE_APPROVED", entity_type=ov.entity_type, entity_id=ov.entity_id,
                reason=body.get("reason"))
    db.commit()
    return to_dict(ov)


@router.post("/{override_id}/reject")
def reject_override(override_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("APPROVE_OVERRIDE"))):
    ov = db.get(models.Override, override_id)
    if not ov:
        raise HTTPException(404, "Override not found.")
    ov.status = "REJECTED"
    ov.approved_by = user.id
    write_audit(db, user_id=user.id, action="OVERRIDE_REJECTED", entity_type=ov.entity_type, entity_id=ov.entity_id,
                reason=body.get("reason"))
    db.commit()
    return to_dict(ov)
