"""Section 9 -- Admin Dashboard. Gives a system-wide overview without
bypassing controlled workflows (every widget here is read-only)."""
import datetime as dt
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..serialize import to_list

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(db: OrmSession = Depends(get_db), user: models.User = Depends(get_current_user)):
    orders = db.query(models.ProductionOrder).all()
    machines = db.query(models.Machine).all()
    material_holds = db.query(models.MaterialBatch).filter(models.MaterialBatch.status == "ON_HOLD").count()
    quality_holds = db.query(models.QualityHold).filter(models.QualityHold.status.in_(["OPEN", "PENDING"])).count()
    critical_alerts = db.query(models.Alert).filter(models.Alert.severity == "CRITICAL", models.Alert.status.in_(["NEW", "ACKNOWLEDGED", "IN_PROGRESS"])).all()
    delayed_orders = [o for o in orders if o.status == "DELAYED"]
    open_incidents = db.query(models.Incident).filter(models.Incident.status.notin_(["CLOSED"])).count()

    status_counts = Counter(o.status for o in orders)
    machine_counts = Counter(m.status for m in machines)

    recent_conflicts = db.query(models.SchedulingConflictLog).order_by(models.SchedulingConflictLog.created_at.desc()).limit(8).all()

    stale_machines = [m for m in machines if m.is_stale]
    stale_runs = db.query(models.ProductionRun).filter(models.ProductionRun.is_stale == True).all()  # noqa: E712

    return {
        "kpis": {
            "activeOrders": len([o for o in orders if o.status in ("APPROVED", "READY", "RUNNING", "DELAYED")]),
            "runningMachines": machine_counts.get("RUNNING", 0),
            "availableMachines": machine_counts.get("AVAILABLE", 0),
            "materialHolds": material_holds,
            "qualityHolds": quality_holds,
            "criticalAlerts": len(critical_alerts),
            "delayedOrders": len(delayed_orders),
            "openIncidents": open_incidents,
        },
        "productionStatus": dict(status_counts),
        "machineStatus": dict(machine_counts),
        "criticalAlertsList": to_list(critical_alerts),
        "resourceConflicts": to_list(recent_conflicts),
        "staleness": {
            "machines": [{"id": m.id, "name": m.name, "lastHeartbeatAt": m.last_heartbeat_at.isoformat() if m.last_heartbeat_at else None} for m in stale_machines],
            "runs": [{"id": r.id, "code": r.code, "lastHeartbeatAt": r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None} for r in stale_runs],
        },
        "generatedAt": dt.datetime.utcnow().isoformat(),
    }
