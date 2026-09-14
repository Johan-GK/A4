"""Section 36 -- Risk Engine read endpoints, and Section 16.4's product-line
traceability opt-in decision."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..serialize import to_dict, to_list

router = APIRouter(prefix="/v1", tags=["risk"])


@router.get("/risk-scores")
def list_risk_scores(entity_type: str = None, entity_id: str = None, db: OrmSession = Depends(get_db), user=Depends(require_permission("VIEW_RISK"))):
    q = db.query(models.RiskScore)
    if entity_type:
        q = q.filter(models.RiskScore.entity_type == entity_type)
    if entity_id:
        q = q.filter(models.RiskScore.entity_id == entity_id)
    items = []
    for r in q.order_by(models.RiskScore.calculated_at.desc()).all():
        d = to_dict(r)
        d["contributingFactors"] = json.loads(r.contributing_factors) if r.contributing_factors else []
        items.append(d)
    return {"items": items}


# --- Section 16.4 -- product-line traceability opt-in -----------------

@router.get("/product-line-traceability-settings")
def list_traceability_settings(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    return {"items": to_list(db.query(models.ProductLineTraceabilitySetting).all())}


@router.put("/product-line-traceability-settings/{product_name}")
def set_traceability_setting(product_name: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("MANAGE_PROCESSES", "MANAGE_SYSTEM_SETTINGS"))):
    row = db.get(models.ProductLineTraceabilitySetting, product_name)
    if not row:
        row = models.ProductLineTraceabilitySetting(product_name=product_name)
        db.add(row)
    row.serialized_tracking_enabled = bool(body.get("serializedTrackingEnabled", False))
    row.decided_by = user.id
    write_audit(db, user_id=user.id, action="SET_PRODUCT_LINE_TRACEABILITY", entity_type="PRODUCT_LINE", entity_id=product_name,
                new_value={"serializedTrackingEnabled": row.serialized_tracking_enabled})
    db.commit()
    return to_dict(row)
