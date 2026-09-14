"""Sections 15-18 -- Material Administration, Material Batch State Machine,
Material Hold Workflow. Also Suppliers."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models, schemas
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..serialize import to_dict, to_list
from ..state_machines import validate_transition, IllegalTransitionError

router = APIRouter(prefix="/v1", tags=["materials"])


# --- Materials ---------------------------------------------------------

@router.get("/materials")
def list_materials(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    materials = db.query(models.Material).all()
    out = []
    for m in materials:
        d = to_dict(m)
        d["batchCount"] = len(m.batches)
        d["totalAvailable"] = sum(float(b.available_quantity()) for b in m.batches if b.status == "AVAILABLE")
        out.append(d)
    return {"items": out}


@router.post("/materials", status_code=201)
def create_material(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MATERIALS"))):
    m = models.Material(name=body["name"], unit_of_measure=body["unitOfMeasure"], category=body.get("category"),
                         specification_ref=body.get("specificationRef"))
    db.add(m)
    write_audit(db, user_id=user.id, action="CREATE_MATERIAL", entity_type="MATERIAL", entity_id=m.id, new_value=body)
    db.commit()
    return to_dict(m)


@router.get("/materials/{material_id}/batches")
def list_batches(material_id: str, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    batches = db.query(models.MaterialBatch).filter(models.MaterialBatch.material_id == material_id).all()
    return {"items": [to_dict(b, {"availableQuantity": float(b.available_quantity())}) for b in batches]}


@router.get("/batches")
def list_all_batches(status: str = None, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.MaterialBatch)
    if status:
        q = q.filter(models.MaterialBatch.status == status)
    batches = q.all()
    out = []
    for b in batches:
        d = to_dict(b, {"availableQuantity": float(b.available_quantity()), "materialName": b.material.name if b.material else None,
                          "unitOfMeasure": b.material.unit_of_measure if b.material else None})
        out.append(d)
    return {"items": out}


@router.post("/materials/{material_id}/batches", status_code=201)
def create_batch(material_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MATERIALS"))):
    material = db.get(models.Material, material_id)
    if not material:
        raise HTTPException(404, "Material not found.")
    b = models.MaterialBatch(
        material_id=material_id, supplier_id=body.get("supplierId"), lot_number=body["lotNumber"],
        total_quantity=body.get("totalQuantity", 0), storage_location=body.get("storageLocation"),
        received_date=body.get("receivedDate") or dt.datetime.utcnow(), expiry_date=body.get("expiryDate"),
        status="PENDING_INSPECTION",
    )
    db.add(b)
    write_audit(db, user_id=user.id, action="CREATE_MATERIAL_BATCH", entity_type="MATERIAL_BATCH", entity_id=b.id, new_value=body)
    db.commit()
    return to_dict(b)


@router.post("/batches/{batch_id}/transitions")
def transition_batch(batch_id: str, body: schemas.TransitionRequest, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_MATERIALS", "RELEASE_HOLD"))):
    b = db.get(models.MaterialBatch, batch_id)
    if not b:
        raise HTTPException(404, "Material batch not found.")
    try:
        validate_transition("MATERIAL_BATCH", b.status, body.toState)
    except IllegalTransitionError as e:
        raise HTTPException(422, {"code": "ILLEGAL_TRANSITION", "attempted": body.toState, "current": b.status, "message": str(e)})

    old_status = b.status
    b.status = body.toState
    b.version = (b.version or 0) + 1

    if body.toState == "ON_HOLD":
        _cascade_hold_impact(db, b, user, body.reason)

    write_audit(db, user_id=user.id, action="MATERIAL_BATCH_TRANSITION", entity_type="MATERIAL_BATCH", entity_id=batch_id,
                old_value={"status": old_status}, new_value={"status": body.toState}, reason=body.reason)
    db.commit()
    return to_dict(b)


def _cascade_hold_impact(db, batch: models.MaterialBatch, user, reason):
    """Section 18 Material Hold Workflow: block new reservations (handled by
    the status itself), find existing reservations/runs/orders, generate an
    alert, and -- per Section 22.1's transition table -- automatically move
    any RUNNING run that still needs this batch to ON_HOLD (AT-2)."""
    reservations = db.query(models.ResourceReservation).filter(
        models.ResourceReservation.resource_type == "MATERIAL_BATCH",
        models.ResourceReservation.resource_id == batch.id,
        models.ResourceReservation.status == "ACTIVE",
    ).all()
    affected_run_ids = {r.run_id for r in reservations}
    for run_id in affected_run_ids:
        run = db.get(models.ProductionRun, run_id)
        if not run:
            continue
        fully_consumed = all(
            c.quantity_consumed is not None and float(c.quantity_consumed) >= float(c.quantity_reserved or 0)
            for c in run.consumptions if c.batch_id == batch.id
        )
        if run.status in ("RUNNING", "PAUSED") and not fully_consumed:
            from ..state_machines import validate_transition as vt
            try:
                vt("PRODUCTION_RUN", run.status, "ON_HOLD")
                run.status = "ON_HOLD"
                run.version = (run.version or 0) + 1
                write_audit(db, user_id=user.id if user else None, action="RUN_AUTO_HOLD_MATERIAL", entity_type="PRODUCTION_RUN",
                            entity_id=run.id, reason=f"Required MaterialBatch {batch.id} entered ON_HOLD.")
            except Exception:
                pass
        db.add(models.Alert(
            code=f"AL-{batch.id[:6]}-{int(dt.datetime.utcnow().timestamp())%10000}",
            type="MATERIAL_HOLD_IMPACT", severity="HIGH", source="MATERIAL_HOLD",
            affected_run_id=run.id, affected_order_id=run.order_id,
            affected_resource_type="MATERIAL_BATCH", affected_resource_id=batch.id,
            message=f"Material batch {batch.lot_number} placed ON_HOLD ({reason or 'quality issue'}); affects Run {run.code}.",
            status="NEW", sla_due_at=dt.datetime.utcnow() + dt.timedelta(minutes=60),
        ))
    if not affected_run_ids:
        db.add(models.Alert(
            code=f"AL-{batch.id[:6]}-{int(dt.datetime.utcnow().timestamp())%10000}",
            type="MATERIAL_HOLD", severity="MEDIUM", source="MATERIAL_HOLD",
            affected_resource_type="MATERIAL_BATCH", affected_resource_id=batch.id,
            message=f"Material batch {batch.lot_number} placed ON_HOLD ({reason or 'quality issue'}).", status="NEW",
        ))


# --- Suppliers -----------------------------------------------------------

@router.get("/suppliers")
def list_suppliers(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    return {"items": to_list(db.query(models.Supplier).all())}


@router.post("/suppliers", status_code=201)
def create_supplier(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_SUPPLIERS", "MANAGE_MATERIALS"))):
    s = models.Supplier(name=body["name"], contact_info=body.get("contactInfo"), address=body.get("address"),
                         qualification_status=body.get("qualificationStatus", "QUALIFIED"))
    db.add(s)
    write_audit(db, user_id=user.id, action="CREATE_SUPPLIER", entity_type="SUPPLIER", entity_id=s.id, new_value=body)
    db.commit()
    return to_dict(s)
