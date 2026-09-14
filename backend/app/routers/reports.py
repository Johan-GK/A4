"""Section 41 -- Reports (Table 21 groups: Production, Resources, Quality,
Traceability)."""
import datetime as dt
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..database import get_db
from ..deps import require_permission

router = APIRouter(prefix="/v1/reports", tags=["reports"])


@router.get("/production")
def production_report(db: OrmSession = Depends(get_db), user=Depends(require_permission("VIEW_REPORTS"))):
    orders = db.query(models.ProductionOrder).all()
    by_status = Counter(o.status for o in orders)
    runs = db.query(models.ProductionRun).all()
    planned_vs_actual = [
        {"runCode": r.code, "orderCode": r.order.code if r.order else None, "planned": float(r.quantity_planned or 0),
         "actual": float(r.quantity_produced or 0), "status": r.status}
        for r in runs if r.status in ("COMPLETED", "PARTIALLY_COMPLETED")
    ]
    delayed = [{"orderCode": o.code, "dueDate": o.due_date.isoformat() if o.due_date else None} for o in orders if o.status == "DELAYED"]
    return {
        "ordersByStatus": dict(by_status),
        "plannedVsActual": planned_vs_actual,
        "delayedOrders": delayed,
        "totalOrders": len(orders),
        "totalRuns": len(runs),
    }


@router.get("/resources")
def resources_report(db: OrmSession = Depends(get_db), user=Depends(require_permission("VIEW_REPORTS"))):
    machines = db.query(models.Machine).all()
    machine_util = Counter(m.status for m in machines)
    materials = db.query(models.Material).all()
    shortages = []
    for m in materials:
        avail = sum(float(b.available_quantity()) for b in m.batches if b.status == "AVAILABLE")
        if avail <= 0:
            shortages.append({"materialId": m.id, "materialName": m.name})
    return {
        "machinesByStatus": dict(machine_util),
        "materialShortages": shortages,
        "operatorCount": db.query(models.Operator).count(),
    }


@router.get("/quality")
def quality_report(db: OrmSession = Depends(get_db), user=Depends(require_permission("VIEW_REPORTS"))):
    defects = db.query(models.Defect).all()
    by_severity = Counter(d.severity for d in defects)
    by_category = Counter(d.category for d in defects)
    holds = db.query(models.QualityHold).all()
    ncrs = db.query(models.NCR).all()
    total_batches = db.query(models.MaterialBatch).count()
    rejected = db.query(models.MaterialBatch).filter(models.MaterialBatch.status == "REJECTED").count()
    return {
        "defectsBySeverity": dict(by_severity),
        "defectsByCategory": dict(by_category),
        "openHolds": len([h for h in holds if h.status in ("OPEN", "PENDING")]),
        "ncrsByStatus": dict(Counter(n.status for n in ncrs)),
        "rejectedBatchRate": (rejected / total_batches) if total_batches else 0,
    }


@router.get("/traceability")
def traceability_report(db: OrmSession = Depends(get_db), user=Depends(require_permission("VIEW_REPORTS"))):
    product_batches = db.query(models.ProductBatch).all()
    scrap_total = sum(float(pb.scrapped_quantity or 0) for pb in product_batches)
    produced_total = sum(float(pb.quantity_produced or 0) for pb in product_batches)
    scrap_rate = (scrap_total / produced_total) if produced_total else 0
    return {
        "productBatchCount": len(product_batches),
        "scrapRate": scrap_rate,
        "materialBatchCount": db.query(models.MaterialBatch).count(),
        "incidentCount": db.query(models.Incident).count(),
    }
