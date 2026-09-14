"""Section 37 -- Traceability Administration (REVISED for multi-batch
genealogy, Section 16). Supports the Traceability Explorer searches by
Order/Run/ProductBatch/MaterialBatch/Machine/Operator/Defect/Incident ID,
and the forward-recall query pattern of Acceptance Test AT-4."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..database import get_db
from ..deps import require_permission
from ..serialize import to_dict, to_list

router = APIRouter(prefix="/v1/traceability", tags=["traceability"])


def _run_node(db, run: models.ProductionRun):
    return {
        "runId": run.id, "runCode": run.code, "status": run.status,
        "orderId": run.order_id, "orderCode": run.order.code if run.order else None,
        "machineId": run.machine_id, "machineName": run.machine.name if run.machine else None,
        "operatorId": run.operator_id, "operatorName": run.operator.user.name if run.operator and run.operator.user else None,
        "processStepId": run.process_step_id, "processStepName": run.process_step.name if run.process_step else None,
        "materialBatches": [
            {"batchId": c.batch_id, "lotNumber": c.batch.lot_number if c.batch else None,
             "materialName": c.material.name if c.material else None, "role": c.role,
             "quantityReserved": float(c.quantity_reserved or 0), "quantityConsumed": float(c.quantity_consumed) if c.quantity_consumed is not None else None}
            for c in run.consumptions
        ],
        "productBatches": [{"productBatchId": pb.id, "code": pb.code, "quantityProduced": float(pb.quantity_produced or 0),
                             "qualityDisposition": pb.quality_disposition} for pb in run.product_batches],
        "inspections": to_list(db.query(models.QualityInspection).filter(models.QualityInspection.run_id == run.id).all()),
    }


@router.get("/lookup")
def lookup(
    q: str = "",
    db: OrmSession = Depends(get_db),
    user=Depends(require_permission("VIEW_TRACEABILITY_ALL", "VIEW_TRACEABILITY_LIMITED")),
):
    """Find traceable records by the reference people see in the UI.

    The former Explorer required an opaque database UUID and a separately
    selected entity type.  This endpoint deliberately returns only entity
    kinds handled by ``trace`` below, so every result can be opened directly
    in the Explorer.
    """
    query = q.strip()
    if len(query) < 2:
        return {"items": []}

    like = f"%{query}%"
    items = []

    def add(entity_type, entity_id, reference, description, status):
        items.append({
            "entityType": entity_type,
            "id": entity_id,
            "reference": reference,
            "description": description,
            "status": status,
        })

    for order in db.query(models.ProductionOrder).filter(
        or_(models.ProductionOrder.code.ilike(like), models.ProductionOrder.product_name.ilike(like))
    ).order_by(models.ProductionOrder.code).limit(8):
        add("PRODUCTION_ORDER", order.id, order.code, order.product_name, order.status)

    for run in db.query(models.ProductionRun).filter(
        models.ProductionRun.code.ilike(like)
    ).order_by(models.ProductionRun.code).limit(8):
        add("PRODUCTION_RUN", run.id, run.code, run.order.code if run.order else "Production run", run.status)

    for batch in db.query(models.ProductBatch).filter(
        models.ProductBatch.code.ilike(like)
    ).order_by(models.ProductBatch.code).limit(8):
        add("PRODUCT_BATCH", batch.id, batch.code, batch.order.product_name if batch.order else "Product batch", batch.quality_disposition)

    for batch in db.query(models.MaterialBatch).filter(
        models.MaterialBatch.lot_number.ilike(like)
    ).order_by(models.MaterialBatch.lot_number).limit(8):
        add("MATERIAL_BATCH", batch.id, batch.lot_number, batch.material.name if batch.material else "Material batch", batch.status)

    for machine in db.query(models.Machine).filter(
        models.Machine.name.ilike(like)
    ).order_by(models.Machine.name).limit(8):
        add("MACHINE", machine.id, machine.name, machine.type or "Machine", machine.status)

    for operator in db.query(models.Operator).join(models.User).filter(
        or_(models.Operator.employee_code.ilike(like), models.User.name.ilike(like))
    ).order_by(models.Operator.employee_code).limit(8):
        add("OPERATOR", operator.id, operator.employee_code or operator.user.name, operator.user.name if operator.user else "Operator", None)

    for defect in db.query(models.Defect).filter(
        models.Defect.code.ilike(like)
    ).order_by(models.Defect.code).limit(8):
        add("DEFECT", defect.id, defect.code, defect.category or "Defect", defect.status)

    for incident in db.query(models.Incident).filter(
        or_(models.Incident.code.ilike(like), models.Incident.description.ilike(like))
    ).order_by(models.Incident.code).limit(8):
        add("INCIDENT", incident.id, incident.code, incident.type or "Incident", incident.status)

    return {"items": items[:25]}


@router.get("/{entity_type}/{entity_id}")
def trace(entity_type: str, entity_id: str, db: OrmSession = Depends(get_db), user=Depends(require_permission("VIEW_TRACEABILITY_ALL", "VIEW_TRACEABILITY_LIMITED"))):
    entity_type = entity_type.upper()

    if entity_type == "PRODUCT_BATCH":
        pb = db.get(models.ProductBatch, entity_id)
        if not pb:
            raise HTTPException(404, "Product batch not found.")
        run = db.get(models.ProductionRun, pb.run_id)
        return {"entityType": "PRODUCT_BATCH", "productBatch": to_dict(pb), "run": _run_node(db, run) if run else None,
                "defects": to_list(db.query(models.Defect).filter(models.Defect.target_id == pb.id, models.Defect.target_type == "PRODUCT_BATCH").all())}

    if entity_type == "MATERIAL_BATCH":
        mb = db.get(models.MaterialBatch, entity_id)
        if not mb:
            raise HTTPException(404, "Material batch not found.")
        consumptions = db.query(models.RunMaterialConsumption).filter(models.RunMaterialConsumption.batch_id == mb.id).all()
        runs = []
        seen_run_ids = set()
        product_batches = []
        for c in consumptions:
            if c.run_id in seen_run_ids:
                continue
            seen_run_ids.add(c.run_id)
            run = db.get(models.ProductionRun, c.run_id)
            if run:
                runs.append(_run_node(db, run))
                product_batches.extend(pb.id for pb in run.product_batches)
        return {
            "entityType": "MATERIAL_BATCH", "materialBatch": to_dict(mb, {"availableQuantity": float(mb.available_quantity())}),
            "forwardRecall": {"affectedRuns": runs, "affectedProductBatchIds": product_batches, "affectedOrderIds": list({r["orderId"] for r in runs})},
        }

    if entity_type in ("RUN", "PRODUCTION_RUN"):
        run = db.get(models.ProductionRun, entity_id)
        if not run:
            raise HTTPException(404, "Run not found.")
        return {"entityType": "PRODUCTION_RUN", "run": _run_node(db, run)}

    if entity_type in ("ORDER", "PRODUCTION_ORDER"):
        order = db.get(models.ProductionOrder, entity_id)
        if not order:
            raise HTTPException(404, "Order not found.")
        return {"entityType": "PRODUCTION_ORDER", "order": to_dict(order), "runs": [_run_node(db, r) for r in order.runs]}

    if entity_type == "MACHINE":
        machine = db.get(models.Machine, entity_id)
        if not machine:
            raise HTTPException(404, "Machine not found.")
        runs = db.query(models.ProductionRun).filter(models.ProductionRun.machine_id == entity_id).all()
        return {"entityType": "MACHINE", "machine": to_dict(machine), "runs": [_run_node(db, r) for r in runs],
                "maintenanceHistory": to_list(machine.maintenance_records)}

    if entity_type == "OPERATOR":
        operator = db.get(models.Operator, entity_id)
        if not operator:
            raise HTTPException(404, "Operator not found.")
        runs = db.query(models.ProductionRun).filter(models.ProductionRun.operator_id == entity_id).all()
        return {"entityType": "OPERATOR", "operator": to_dict(operator), "runs": [_run_node(db, r) for r in runs]}

    if entity_type == "DEFECT":
        defect = db.get(models.Defect, entity_id)
        if not defect:
            raise HTTPException(404, "Defect not found.")
        node = {"entityType": "DEFECT", "defect": to_dict(defect)}
        if defect.target_type == "PRODUCT_BATCH":
            pb = db.get(models.ProductBatch, defect.target_id)
            if pb:
                run = db.get(models.ProductionRun, pb.run_id)
                node["productBatch"] = to_dict(pb)
                node["run"] = _run_node(db, run) if run else None
        return node

    if entity_type == "INCIDENT":
        inc = db.get(models.Incident, entity_id)
        if not inc:
            raise HTTPException(404, "Incident not found.")
        node = {"entityType": "INCIDENT", "incident": to_dict(inc)}
        if inc.run_id:
            run = db.get(models.ProductionRun, inc.run_id)
            node["run"] = _run_node(db, run) if run else None
        return node

    raise HTTPException(400, f"Unsupported traceability entity type: {entity_type}")
