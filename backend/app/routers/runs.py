"""Section 22 -- Production Run State Machine, material substitution (22.2),
partial completion & final consumption posting (22.3), scrap/rework
disposition (22.4). This is the module the Q4 review specifically asked for:
a Run has states an Order does not, and this file is where they live."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models, risk_engine
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..scheduling import allocate_material
from ..serialize import to_dict, to_list
from ..state_machines import validate_transition, IllegalTransitionError

router = APIRouter(prefix="/v1/runs", tags=["runs"])


@router.get("")
def list_runs(status_: str = None, machine_id: str = None, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.ProductionRun)
    if status_:
        q = q.filter(models.ProductionRun.status == status_)
    if machine_id:
        q = q.filter(models.ProductionRun.machine_id == machine_id)
    runs = q.order_by(models.ProductionRun.scheduled_start.asc()).all()
    out = []
    for r in runs:
        out.append(to_dict(r, {
            "orderCode": r.order.code if r.order else None, "machineName": r.machine.name if r.machine else None,
            "operatorName": r.operator.user.name if r.operator and r.operator.user else None,
            "processStepName": r.process_step.name if r.process_step else None,
        }))
    return {"items": out}


@router.get("/{run_id}")
def get_run(run_id: str, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    r = db.get(models.ProductionRun, run_id)
    if not r:
        raise HTTPException(404, "Run not found.")
    d = to_dict(r, {"orderCode": r.order.code if r.order else None, "machineName": r.machine.name if r.machine else None})
    d["consumptions"] = [to_dict(c, {"lotNumber": c.batch.lot_number if c.batch else None, "materialName": c.material.name if c.material else None}) for c in r.consumptions]
    d["reservations"] = to_list(r.reservations)
    d["productBatches"] = to_list(r.product_batches)
    return d


def _apply_run_transition(db, run, to_state, reason=None):
    validate_transition("PRODUCTION_RUN", run.status, to_state)
    run.status = to_state
    run.version = (run.version or 0) + 1
    run.last_heartbeat_at = dt.datetime.utcnow()
    run.is_stale = False


def _release_run_resources(db, run, release_material_reservations=True):
    for res in run.reservations:
        if res.status != "ACTIVE":
            continue
        if res.resource_type in ("MACHINE", "OPERATOR"):
            res.status = "RELEASED"
        elif res.resource_type == "MATERIAL_BATCH" and release_material_reservations:
            batch = db.get(models.MaterialBatch, res.resource_id)
            if batch and res.quantity_reserved:
                batch.reserved_quantity = max(0, float(batch.reserved_quantity or 0) - float(res.quantity_reserved))
            res.status = "RELEASED"


@router.post("/{run_id}/start")
def start_run(run_id: str, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        _apply_run_transition(db, run, "RUNNING")
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    run.actual_start = dt.datetime.utcnow()
    if run.machine:
        try:
            validate_transition("MACHINE", run.machine.status, "RUNNING")
            run.machine.status = "RUNNING"
            run.machine.version = (run.machine.version or 0) + 1
        except IllegalTransitionError:
            pass
    if run.order and run.order.status == "READY":
        run.order.status = "RUNNING"
    write_audit(db, user_id=user.id, action="RUN_START", entity_type="PRODUCTION_RUN", entity_id=run_id)
    db.commit()
    return to_dict(run)


@router.post("/{run_id}/pause")
def pause_run(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        _apply_run_transition(db, run, "PAUSED", body.get("reason"))
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    if run.machine:
        run.machine.status = "PAUSED"
    write_audit(db, user_id=user.id, action="RUN_PAUSE", entity_type="PRODUCTION_RUN", entity_id=run_id, reason=body.get("reason"))
    db.commit()
    return to_dict(run)


@router.post("/{run_id}/resume")
def resume_run(run_id: str, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        _apply_run_transition(db, run, "RUNNING")
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    if run.machine:
        run.machine.status = "RUNNING"
    write_audit(db, user_id=user.id, action="RUN_RESUME", entity_type="PRODUCTION_RUN", entity_id=run_id)
    db.commit()
    return to_dict(run)


@router.post("/{run_id}/hold")
def hold_run(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION", "MANAGE_INCIDENTS"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        _apply_run_transition(db, run, "ON_HOLD", body.get("reason"))
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    write_audit(db, user_id=user.id, action="RUN_HOLD", entity_type="PRODUCTION_RUN", entity_id=run_id, reason=body.get("reason"))
    db.commit()
    return to_dict(run)


@router.post("/{run_id}/release-hold")
def release_hold(run_id: str, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION", "APPROVE_ORDERS"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        _apply_run_transition(db, run, "RUNNING")
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    if run.machine:
        run.machine.status = "RUNNING"
    write_audit(db, user_id=user.id, action="RUN_RELEASE_HOLD", entity_type="PRODUCTION_RUN", entity_id=run_id)
    db.commit()
    return to_dict(run)


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION", "APPROVE_ORDERS"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        _apply_run_transition(db, run, "CANCELLED", body.get("reason"))
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    _release_run_resources(db, run)
    if run.machine and run.machine.status in ("RESERVED", "RUNNING", "PAUSED"):
        run.machine.status = "AVAILABLE"
    write_audit(db, user_id=user.id, action="RUN_CANCEL", entity_type="PRODUCTION_RUN", entity_id=run_id, reason=body.get("reason"))
    db.commit()
    return to_dict(run)


# --- Section 22.2 -- material substitution mid-run --------------------

@router.post("/{run_id}/material-substitution/request")
def request_substitution(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION"))):
    """The allocated batch became unusable mid-run; try automatic
    reallocation first (16.2), otherwise enter MATERIAL_SUBSTITUTION_PENDING
    for a Supervisor/Production Manager to approve."""
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    material_id = body["materialId"]
    remaining_qty = float(body["remainingQuantity"])

    allocations, shortfall = allocate_material(db, material_id, remaining_qty)
    if shortfall is None:
        for batch, qty in allocations:
            batch.reserved_quantity = float(batch.reserved_quantity or 0) + qty
            db.add(models.ResourceReservation(run_id=run.id, resource_type="MATERIAL_BATCH", resource_id=batch.id, quantity_reserved=qty, status="ACTIVE"))
            db.add(models.RunMaterialConsumption(run_id=run.id, batch_id=batch.id, material_id=material_id, quantity_reserved=qty, role="SUBSTITUTE"))
        write_audit(db, user_id=user.id, action="AUTO_MATERIAL_SUBSTITUTION", entity_type="PRODUCTION_RUN", entity_id=run_id,
                    new_value={"materialId": material_id, "allocations": [{"batchId": b.id, "qty": q} for b, q in allocations]})
        db.commit()
        return {"automatic": True, "allocations": [{"batchId": b.id, "lotNumber": b.lot_number, "quantity": q} for b, q in allocations]}

    try:
        _apply_run_transition(db, run, "MATERIAL_SUBSTITUTION_PENDING", "No automatic substitute available within policy.")
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    db.add(models.Alert(
        code=f"AL-SUB-{int(dt.datetime.utcnow().timestamp())%100000}", type="MATERIAL_SUBSTITUTION_NEEDED", severity="HIGH",
        source="RUN_SUBSTITUTION", affected_run_id=run.id, affected_order_id=run.order_id, status="NEW",
        message=f"Run {run.code} needs approval for a material substitute (short by {shortfall:.3f}).",
        sla_due_at=dt.datetime.utcnow() + dt.timedelta(minutes=60),
    ))
    write_audit(db, user_id=user.id, action="MATERIAL_SUBSTITUTION_PENDING", entity_type="PRODUCTION_RUN", entity_id=run_id,
                reason=f"Shortfall {shortfall:.3f} for material {material_id}")
    db.commit()
    return {"automatic": False, "status": "MATERIAL_SUBSTITUTION_PENDING", "shortfall": shortfall}


@router.post("/{run_id}/material-substitution/approve")
def approve_substitution(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("APPROVE_ORDERS", "MANAGE_INCIDENTS"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    if run.status != "MATERIAL_SUBSTITUTION_PENDING":
        raise HTTPException(422, "Run is not awaiting a material substitution decision.")
    batch = db.get(models.MaterialBatch, body["substituteBatchId"])
    if not batch or batch.status != "AVAILABLE":
        raise HTTPException(422, "Substitute batch is not AVAILABLE.")
    qty = float(body["quantity"])
    if float(batch.available_quantity()) < qty:
        raise HTTPException(409, {"code": "MATERIAL_SHORTAGE", "message": "Substitute batch does not have enough available quantity."})

    batch.reserved_quantity = float(batch.reserved_quantity or 0) + qty
    db.add(models.ResourceReservation(run_id=run.id, resource_type="MATERIAL_BATCH", resource_id=batch.id, quantity_reserved=qty, status="ACTIVE"))
    db.add(models.RunMaterialConsumption(run_id=run.id, batch_id=batch.id, material_id=batch.material_id, quantity_reserved=qty, role="SUBSTITUTE"))
    _apply_run_transition(db, run, "RUNNING")
    write_audit(db, user_id=user.id, action="MATERIAL_SUBSTITUTION_APPROVED", entity_type="PRODUCTION_RUN", entity_id=run_id,
                new_value={"batchId": batch.id, "quantity": qty})
    db.commit()
    return to_dict(run)


# --- Section 22.3 -- partial completion & final consumption posting ----

def _post_consumption(db, run, postings: list, user):
    """Mandatory step: confirm actual QuantityConsumed per allocated batch,
    release unused reserved quantity, and finalize genealogy."""
    posting_map = {p["consumptionId"]: p["quantityConsumed"] for p in postings}
    for c in run.consumptions:
        if c.consumed_at is not None:
            continue
        qty = posting_map.get(c.id, float(c.quantity_reserved))   # defaults to reserved if unchanged
        c.quantity_consumed = qty
        c.consumed_at = dt.datetime.utcnow()
        batch = c.batch
        if batch:
            batch.consumed_quantity = float(batch.consumed_quantity or 0) + qty
            unused = float(c.quantity_reserved or 0) - qty
            if unused > 0:
                batch.reserved_quantity = max(0, float(batch.reserved_quantity or 0) - unused)
            else:
                batch.reserved_quantity = max(0, float(batch.reserved_quantity or 0) - float(c.quantity_reserved or 0))
            if float(batch.available_quantity()) <= 0 and batch.status == "AVAILABLE":
                batch.status = "DEPLETED"
            for res in run.reservations:
                if res.resource_type == "MATERIAL_BATCH" and res.resource_id == batch.id and res.status == "ACTIVE":
                    res.status = "CONSUMED"


@router.post("/{run_id}/complete")
def complete_run(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        validate_transition("PRODUCTION_RUN", run.status, "COMPLETED")
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))

    unposted = [c for c in run.consumptions if c.consumed_at is None]
    postings = body.get("postings", [])
    if unposted and not postings and any(p.get("consumptionId") not in [c.id for c in unposted] for p in postings):
        pass  # allow default-to-reserved path below
    _post_consumption(db, run, postings, user)

    quantity_produced = float(body.get("quantityProduced", run.quantity_planned or 0))
    run.quantity_produced = quantity_produced
    run.actual_end = dt.datetime.utcnow()
    run.status = "COMPLETED"
    run.version = (run.version or 0) + 1

    pb = models.ProductBatch(
        code=f"PB-{int(dt.datetime.utcnow().timestamp()) % 100000}", order_id=run.order_id, run_id=run.id,
        quantity_produced=quantity_produced, quality_disposition="PENDING_INSPECTION",
    )
    db.add(pb)

    if run.machine:
        next_queued = db.query(models.ResourceReservation).filter(
            models.ResourceReservation.resource_type == "MACHINE", models.ResourceReservation.resource_id == run.machine_id,
            models.ResourceReservation.status == "ACTIVE", models.ResourceReservation.run_id != run.id,
        ).first()
        run.machine.status = "RESERVED" if next_queued else "AVAILABLE"

    for res in run.reservations:
        if res.resource_type in ("MACHINE", "OPERATOR") and res.status == "ACTIVE":
            res.status = "RELEASED"

    remaining_runs = [r for r in run.order.runs if r.status not in ("COMPLETED", "CANCELLED")]
    if run.order and not remaining_runs:
        try:
            validate_transition("PRODUCTION_ORDER", run.order.status, "COMPLETED")
            run.order.status = "COMPLETED"
        except IllegalTransitionError:
            pass

    write_audit(db, user_id=user.id, action="RUN_COMPLETE", entity_type="PRODUCTION_RUN", entity_id=run_id,
                new_value={"quantityProduced": quantity_produced, "productBatchId": pb.id})
    db.commit()
    return {"run": to_dict(run), "productBatch": to_dict(pb)}


@router.post("/{run_id}/partial-complete")
def partial_complete_run(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        validate_transition("PRODUCTION_RUN", run.status, "PARTIALLY_COMPLETED")
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))

    postings = body.get("postings", [])
    _post_consumption(db, run, postings, user)

    quantity_produced = float(body.get("quantityProduced", 0))
    run.quantity_produced = quantity_produced
    run.status = "PARTIALLY_COMPLETED"
    run.version = (run.version or 0) + 1

    pb = models.ProductBatch(
        code=f"PB-{int(dt.datetime.utcnow().timestamp()) % 100000}", order_id=run.order_id, run_id=run.id,
        quantity_produced=quantity_produced, quality_disposition="PENDING_INSPECTION",
    )
    db.add(pb)
    write_audit(db, user_id=user.id, action="RUN_PARTIAL_COMPLETE", entity_type="PRODUCTION_RUN", entity_id=run_id,
                new_value={"quantityProduced": quantity_produced})
    db.commit()
    return {"run": to_dict(run), "productBatch": to_dict(pb)}


@router.post("/{run_id}/resume-partial")
def resume_partial(run_id: str, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        _apply_run_transition(db, run, "RUNNING")
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    write_audit(db, user_id=user.id, action="RUN_RESUME_PARTIAL", entity_type="PRODUCTION_RUN", entity_id=run_id)
    db.commit()
    return to_dict(run)


@router.post("/{run_id}/waive-remaining")
def waive_remaining(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("APPROVE_ORDERS"))):
    """PARTIALLY_COMPLETED -> COMPLETED: remaining quantity formally waived
    (Section 22.1, requires authorization per Section 26)."""
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    try:
        _apply_run_transition(db, run, "COMPLETED", body.get("reason"))
    except IllegalTransitionError as e:
        raise HTTPException(422, str(e))
    run.actual_end = dt.datetime.utcnow()
    _release_run_resources(db, run)
    if run.machine and run.machine.status != "AVAILABLE":
        run.machine.status = "AVAILABLE"
    write_audit(db, user_id=user.id, action="RUN_WAIVE_REMAINING", entity_type="PRODUCTION_RUN", entity_id=run_id, reason=body.get("reason"))
    db.commit()
    return to_dict(run)


# --- Section 22.4 -- scrap/rework disposition ---------------------------

@router.post("/{run_id}/scrap-rework/dispose")
def scrap_rework_dispose(run_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("RELEASE_HOLD", "APPROVE_ORDERS"))):
    """disposition: 'REWORK' (run resumes) or 'SCRAP' (scrapped qty recorded,
    never deleted)."""
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    if run.status != "SCRAP_REWORK_REVIEW":
        raise HTTPException(422, "Run is not in SCRAP_REWORK_REVIEW.")
    disposition = body.get("disposition")
    scrapped_qty = float(body.get("scrappedQuantity", 0))

    pb = run.product_batches[-1] if run.product_batches else None
    if pb:
        pb.scrapped_quantity = float(pb.scrapped_quantity or 0) + scrapped_qty
        pb.quality_disposition = "SCRAPPED" if disposition == "SCRAP" else pb.quality_disposition

    if disposition == "REWORK":
        _apply_run_transition(db, run, "RUNNING", body.get("reason"))
    else:
        _apply_run_transition(db, run, "COMPLETED", body.get("reason"))
        run.actual_end = dt.datetime.utcnow()
        _release_run_resources(db, run)
        if run.machine:
            run.machine.status = "AVAILABLE"

    write_audit(db, user_id=user.id, action="SCRAP_REWORK_DISPOSITION", entity_type="PRODUCTION_RUN", entity_id=run_id,
                new_value={"disposition": disposition, "scrappedQuantity": scrapped_qty})
    db.commit()
    return to_dict(run)


@router.post("/{run_id}/heartbeat")
def run_heartbeat(run_id: str, db: OrmSession = Depends(get_db), user=Depends(require_permission("EXECUTE_PRODUCTION"))):
    run = db.get(models.ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found.")
    run.last_heartbeat_at = dt.datetime.utcnow()
    run.is_stale = False
    db.commit()
    return {"ok": True}
