"""Section 38 -- Audit Log (REVISED), enforcing the Section 7 scope
definitions: VIEW_AUDIT_LOG_ALL / _LIMITED / _OWN. No update/delete
endpoint exists here or anywhere else in the application (38.1)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..audit import verify_chain
from ..database import get_db
from ..deps import get_current_user, user_permissions
from ..serialize import to_list

router = APIRouter(prefix="/v1/audit-logs", tags=["audit"])

# Section 7, Table 4: Supervisor + Audit Logs "Limited" boundary --
# approximated here as production-floor entity types rather than
# user/role/system-configuration administration entries.
_LIMITED_ENTITY_TYPES = ["PRODUCTION_ORDER", "PRODUCTION_RUN", "MACHINE", "MATERIAL_BATCH", "QUALITY_HOLD", "INCIDENT", "ALERT", "DEFECT"]


@router.get("")
def list_audit_logs(entity_type: str = None, entity_id: str = None, limit: int = 200,
                     db: OrmSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    perms = user_permissions(user)
    q = db.query(models.AuditLog)

    if "VIEW_AUDIT_LOG_ALL" in perms:
        pass
    elif "VIEW_AUDIT_LOG_LIMITED" in perms:
        q = q.filter(models.AuditLog.entity_type.in_(_LIMITED_ENTITY_TYPES))
    elif "VIEW_AUDIT_LOG_OWN" in perms:
        q = q.filter(models.AuditLog.user_id == user.id)
    else:
        raise HTTPException(403, "No audit-log viewing permission granted.")

    if entity_type:
        q = q.filter(models.AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(models.AuditLog.entity_id == entity_id)

    entries = q.order_by(models.AuditLog.seq.desc()).limit(min(limit, 1000)).all()
    out = []
    for e in entries:
        d = to_list([e])[0]
        d["username"] = e.user_id and db.get(models.User, e.user_id) and db.get(models.User, e.user_id).username
        out.append(d)
    return {"items": out}


@router.get("/verify-chain")
def verify_chain_endpoint(db: OrmSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    perms = user_permissions(user)
    if "VIEW_AUDIT_LOG_ALL" not in perms:
        raise HTTPException(403, "Only full audit-log access can run chain verification.")
    return verify_chain(db)
