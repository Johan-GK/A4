"""Sections 12-14 -- Machine Administration, State Machine, Maintenance Workflow."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models, schemas
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..serialize import to_dict, to_list
from ..state_machines import validate_transition, IllegalTransitionError

router = APIRouter(prefix="/v1/machines", tags=["machines"])


@router.get("")
def list_machines(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    machines = db.query(models.Machine).all()
    return {"items": [to_dict(m, {"capabilities": [c.process_step_id for c in m.capabilities]}) for m in machines]}


@router.get("/{machine_id}")
def get_machine(machine_id: str, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    m = db.get(models.Machine, machine_id)
    if not m:
        raise HTTPException(404, "Machine not found.")
    return to_dict(m, {"capabilities": [c.process_step_id for c in m.capabilities]})


@router.post("", status_code=201)
def create_machine(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MACHINES"))):
    m = models.Machine(
        name=body["name"], type=body.get("type"), location=body.get("location"),
        capacity=body.get("capacity", 0), status="AVAILABLE",
        installation_date=body.get("installationDate"), maintenance_schedule=body.get("maintenanceSchedule"),
    )
    db.add(m)
    db.flush()
    for step_id in body.get("capableProcessStepIds", []):
        db.add(models.MachineCapability(machine_id=m.id, process_step_id=step_id))
    write_audit(db, user_id=user.id, action="CREATE_MACHINE", entity_type="MACHINE", entity_id=m.id, new_value=body)
    db.commit()
    return to_dict(m)


@router.patch("/{machine_id}")
def update_machine(machine_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MACHINES"))):
    m = db.get(models.Machine, machine_id)
    if not m:
        raise HTTPException(404, "Machine not found.")
    for field, key in [("name", "name"), ("type", "type"), ("location", "location"),
                        ("capacity", "capacity"), ("maintenanceSchedule", "maintenance_schedule")]:
        if field in body:
            setattr(m, key, body[field])
    if "capableProcessStepIds" in body:
        db.query(models.MachineCapability).filter(models.MachineCapability.machine_id == machine_id).delete()
        for step_id in body["capableProcessStepIds"]:
            db.add(models.MachineCapability(machine_id=machine_id, process_step_id=step_id))
    write_audit(db, user_id=user.id, action="UPDATE_MACHINE", entity_type="MACHINE", entity_id=machine_id, new_value=body)
    db.commit()
    return to_dict(m)


@router.post("/{machine_id}/heartbeat")
def machine_heartbeat(machine_id: str, body: dict = None, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION", "MANAGE_MACHINES"))):
    """Section 35.1/35.2 -- manual data-capture entry point resetting the
    freshness timer for this machine."""
    m = db.get(models.Machine, machine_id)
    if not m:
        raise HTTPException(404, "Machine not found.")
    m.last_heartbeat_at = dt.datetime.utcnow()
    m.is_stale = False
    db.commit()
    return {"ok": True, "lastHeartbeatAt": m.last_heartbeat_at.isoformat()}


@router.post("/{machine_id}/transitions")
def transition_machine(machine_id: str, body: schemas.TransitionRequest, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MACHINES"))):
    m = db.get(models.Machine, machine_id)
    if not m:
        raise HTTPException(404, "Machine not found.")
    try:
        validate_transition("MACHINE", m.status, body.toState)
    except IllegalTransitionError as e:
        raise HTTPException(422, {"code": "ILLEGAL_TRANSITION", "attempted": body.toState, "current": m.status, "message": str(e)})

    # Business-rule guard (Section 13): decommission requires no active/future reservation.
    if body.toState == "DECOMMISSIONED":
        active = db.query(models.ResourceReservation).filter(
            models.ResourceReservation.resource_type == "MACHINE",
            models.ResourceReservation.resource_id == machine_id,
            models.ResourceReservation.status == "ACTIVE",
        ).first()
        if active:
            raise HTTPException(422, {"code": "ACTIVE_RESERVATION_EXISTS", "message": "Cannot decommission a machine with an active/future reservation."})

    old_status = m.status
    m.status = body.toState
    m.version = (m.version or 0) + 1

    if body.toState == "MAINTENANCE":
        db.add(models.MachineMaintenanceRecord(machine_id=machine_id, type="CORRECTIVE", performed_by=user.id, notes=body.reason, status="OPEN"))
        # Impact analysis (Section 14): find active/upcoming runs on this machine.
        impacted_runs = db.query(models.ProductionRun).filter(
            models.ProductionRun.machine_id == machine_id,
            models.ProductionRun.status.in_(["SCHEDULED", "RUNNING", "PAUSED"]),
        ).all()
        for run in impacted_runs:
            db.add(models.Alert(
                type="MACHINE_MAINTENANCE_IMPACT", severity="HIGH", source="MACHINE_TRANSITION",
                affected_run_id=run.id, affected_resource_type="MACHINE", affected_resource_id=machine_id,
                message=f"Machine {m.name} entered MAINTENANCE while Run {run.code} is active.", status="NEW",
                code=f"AL-{machine_id[:6]}-{int(dt.datetime.utcnow().timestamp())%10000}",
            ))

    write_audit(db, user_id=user.id, action="MACHINE_TRANSITION", entity_type="MACHINE", entity_id=machine_id,
                old_value={"status": old_status}, new_value={"status": body.toState}, reason=body.reason)
    db.commit()
    return to_dict(m)


@router.get("/{machine_id}/maintenance-records")
def list_maintenance(machine_id: str, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    recs = db.query(models.MachineMaintenanceRecord).filter(models.MachineMaintenanceRecord.machine_id == machine_id).all()
    return {"items": to_list(recs)}


@router.post("/{machine_id}/maintenance-records/{record_id}/complete")
def complete_maintenance(machine_id: str, record_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MACHINES", "MANAGE_MAINTENANCE"))):
    rec = db.get(models.MachineMaintenanceRecord, record_id)
    if not rec or rec.machine_id != machine_id:
        raise HTTPException(404, "Maintenance record not found.")
    rec.status = "COMPLETED"
    rec.closed_at = dt.datetime.utcnow()
    rec.notes = (rec.notes or "") + "\n" + (body.get("notes") or "")
    db.commit()
    return to_dict(rec)


@router.post("/{machine_id}/maintenance-records/{record_id}/verify")
def verify_maintenance(machine_id: str, record_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MACHINES", "MANAGE_MAINTENANCE"))):
    """Section 14: authorized verification -> Machine = AVAILABLE."""
    rec = db.get(models.MachineMaintenanceRecord, record_id)
    if not rec or rec.machine_id != machine_id:
        raise HTTPException(404, "Maintenance record not found.")
    if rec.performed_by == user.id:
        raise HTTPException(422, {"code": "DUAL_CONTROL_REQUIRED", "message": "The verifying user cannot be the same user who performed the maintenance."})
    m = db.get(models.Machine, machine_id)
    try:
        validate_transition("MACHINE", m.status, "AVAILABLE")
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    rec.status = "VERIFIED"
    rec.verified_by = user.id
    m.status = "AVAILABLE"
    m.version = (m.version or 0) + 1
    m.last_heartbeat_at = dt.datetime.utcnow()
    write_audit(db, user_id=user.id, action="MAINTENANCE_VERIFIED", entity_type="MACHINE", entity_id=machine_id)
    db.commit()
    return to_dict(m)
