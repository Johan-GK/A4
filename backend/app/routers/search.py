"""Section 42 -- Admin Search: a single query fanning out across every
identifiable entity type."""
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..database import get_db
from ..deps import require_permission

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.get("")
def search(q: str, db: OrmSession = Depends(get_db), user=Depends(require_permission("ADMIN_SEARCH"))):
    q = q.strip()
    if not q:
        return {"results": []}
    like = f"%{q}%"
    results = []

    for o in db.query(models.ProductionOrder).filter(or_(models.ProductionOrder.code.ilike(like), models.ProductionOrder.product_name.ilike(like))).limit(10):
        results.append({"type": "PRODUCTION_ORDER", "id": o.id, "label": f"Production Order -> {o.code}", "status": o.status})
    for r in db.query(models.ProductionRun).filter(models.ProductionRun.code.ilike(like)).limit(10):
        results.append({"type": "PRODUCTION_RUN", "id": r.id, "label": f"Production Run -> {r.code}", "status": r.status})
    for b in db.query(models.MaterialBatch).filter(models.MaterialBatch.lot_number.ilike(like)).limit(10):
        results.append({"type": "MATERIAL_BATCH", "id": b.id, "label": f"Material Batch -> {b.lot_number}", "status": b.status})
    for pb in db.query(models.ProductBatch).filter(models.ProductBatch.code.ilike(like)).limit(10):
        results.append({"type": "PRODUCT_BATCH", "id": pb.id, "label": f"Product Batch -> {pb.code}", "status": pb.quality_disposition})
    for m in db.query(models.Machine).filter(models.Machine.name.ilike(like)).limit(10):
        results.append({"type": "MACHINE", "id": m.id, "label": f"Machine -> {m.name}", "status": m.status})
    for i in db.query(models.QualityInspection).filter(models.QualityInspection.code.ilike(like)).limit(10):
        results.append({"type": "QUALITY_INSPECTION", "id": i.id, "label": f"Quality Inspection -> {i.code}", "status": i.result})
    for inc in db.query(models.Incident).filter(models.Incident.code.ilike(like)).limit(10):
        results.append({"type": "INCIDENT", "id": inc.id, "label": f"Incident -> {inc.code}", "status": inc.status})
    for d in db.query(models.Defect).filter(models.Defect.code.ilike(like)).limit(10):
        results.append({"type": "DEFECT", "id": d.id, "label": f"Defect -> {d.code}", "status": d.status})
    for u in db.query(models.User).filter(or_(models.User.name.ilike(like), models.User.username.ilike(like))).limit(10):
        results.append({"type": "USER", "id": u.id, "label": f"User -> {u.name}", "status": u.status})
    for mat in db.query(models.Material).filter(models.Material.name.ilike(like)).limit(10):
        results.append({"type": "MATERIAL", "id": mat.id, "label": f"Material -> {mat.name}"})

    return {"results": results[:40]}
