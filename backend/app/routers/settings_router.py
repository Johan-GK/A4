"""System Configuration screen -- the runtime-editable subset of the
"configurable, not hard-coded" thresholds (Sections 29, 35, 36, 44, 46)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..audit import write_audit
from ..config import settings
from ..database import get_db
from ..deps import require_permission

router = APIRouter(prefix="/v1/settings", tags=["settings"])

CONFIGURABLE_DEFAULTS = {
    "MACHINE_STALENESS_MINUTES": settings.MACHINE_STALENESS_MINUTES,
    "RUN_STALENESS_MINUTES": settings.RUN_STALENESS_MINUTES,
    "ALERT_SLA_CRITICAL_MINUTES": settings.ALERT_SLA_MINUTES["CRITICAL"],
    "ALERT_SLA_HIGH_MINUTES": settings.ALERT_SLA_MINUTES["HIGH"],
    "ALERT_SLA_MEDIUM_MINUTES": settings.ALERT_SLA_MINUTES["MEDIUM"],
    "LOCKOUT_MAX_ATTEMPTS": settings.LOCKOUT_MAX_ATTEMPTS,
    "LOCKOUT_WINDOW_MINUTES": settings.LOCKOUT_WINDOW_MINUTES,
    "PASSWORD_MIN_LENGTH": settings.PASSWORD_MIN_LENGTH,
    "AUDIT_RETENTION_YEARS": settings.AUDIT_RETENTION_YEARS,
    "SESSION_IDLE_MINUTES": settings.SESSION_IDLE_MINUTES,
    "SESSION_ABSOLUTE_HOURS": settings.SESSION_ABSOLUTE_HOURS,
}


@router.get("")
def get_settings(db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_SYSTEM_SETTINGS"))):
    rows = {s.key: s.value for s in db.query(models.SystemSetting).all()}
    out = dict(CONFIGURABLE_DEFAULTS)
    out.update(rows)
    return {"settings": out}


@router.patch("")
def update_settings(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_SYSTEM_SETTINGS"))):
    for key, value in body.items():
        if key not in CONFIGURABLE_DEFAULTS:
            continue
        row = db.get(models.SystemSetting, key)
        old_value = row.value if row else str(CONFIGURABLE_DEFAULTS[key])
        if not row:
            row = models.SystemSetting(key=key)
            db.add(row)
        row.value = str(value)
        row.updated_by = user.id
        write_audit(db, user_id=user.id, action="UPDATE_SYSTEM_SETTING", entity_type="SYSTEM_SETTING", entity_id=key,
                    old_value=old_value, new_value=str(value))
    db.commit()
    return {"ok": True}
