"""Sections 28-30 -- Quality Administration, Defect Severity Classification
(29), Quality Gate (30). Plus NCR and Product Batch quality-disposition
transitions (17.2)."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from .. import models, schemas
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..serialize import to_dict, to_list
from ..state_machines import validate_transition, IllegalTransitionError

router = APIRouter(prefix="/v1", tags=["quality"])


# --- Section 29 -- objective severity classification helper -------------

def classify_severity(*, safety_or_regulatory: bool, already_propagated: bool,
                       exceeds_primary_band: bool, affects_fit_form_function: bool,
                       within_secondary_band: bool) -> str:
    """Table 16's objective criteria, any one condition qualifies."""
    if safety_or_regulatory or already_propagated:
        return "CRITICAL"
    if exceeds_primary_band or affects_fit_form_function:
        return "MAJOR"
    if within_secondary_band:
        return "MINOR"
    return "MINOR"


@router.post("/defects/classify-severity")
def classify_severity_endpoint(body: dict, user=Depends(get_current_user)):
    return {"severity": classify_severity(
        safety_or_regulatory=body.get("safetyOrRegulatory", False),
        already_propagated=body.get("alreadyPropagated", False),
        exceeds_primary_band=body.get("exceedsPrimaryBand", False),
        affects_fit_form_function=body.get("affectsFitFormFunction", False),
        within_secondary_band=body.get("withinSecondaryBand", True),
    )}


# --- Inspections (28) ----------------------------------------------------

@router.get("/inspections")
def list_inspections(target_id: str = None, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.QualityInspection)
    if target_id:
        q = q.filter(models.QualityInspection.target_id == target_id)
    return {"items": [to_dict(i, {"inspectorName": i.inspector_id and db.get(models.User, i.inspector_id).name}) for i in q.order_by(models.QualityInspection.timestamp.desc()).all()]}


@router.post("/inspections", status_code=201)
def create_inspection(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("INSPECT_BATCH"))):
    result = body.get("result", "PASS")
    insp = models.QualityInspection(
        code=f"QI-{int(dt.datetime.utcnow().timestamp()) % 100000}",
        target_type=body["targetType"], target_id=body["targetId"], run_id=body.get("runId"),
        inspector_id=user.id, parameter=body.get("parameter"), expected_min=body.get("expectedMin"),
        expected_max=body.get("expectedMax"), actual_value=body.get("actualValue"), result=result,
        remarks=body.get("remarks"),
    )
    db.add(insp)
    db.flush()

    # Quality Gate (Section 30): PASS -> continue; FAIL -> create Defect ->
    # severity routes to Review/Rework (Minor), Hold (Major), Immediate Hold (Critical).
    defect = None
    if result == "FAIL":
        severity = body.get("severity") or classify_severity(
            safety_or_regulatory=body.get("safetyOrRegulatory", False),
            already_propagated=body.get("alreadyPropagated", False),
            exceeds_primary_band=body.get("exceedsPrimaryBand", False),
            affects_fit_form_function=body.get("affectsFitFormFunction", False),
            within_secondary_band=body.get("withinSecondaryBand", True),
        )
        defect = models.Defect(
            code=f"D-{int(dt.datetime.utcnow().timestamp()) % 100000}", inspection_id=insp.id,
            target_type=body["targetType"], target_id=body["targetId"], category=body.get("category", "UNKNOWN"),
            severity=severity, reported_by=user.id, description=body.get("remarks") or "Failed quality inspection.",
            status="OPEN",
        )
        db.add(defect)
        db.flush()
        _apply_quality_gate(db, defect, user)

    write_audit(db, user_id=user.id, action="CREATE_INSPECTION", entity_type="QUALITY_INSPECTION", entity_id=insp.id, new_value=body)
    db.commit()
    return {"inspection": to_dict(insp), "defect": to_dict(defect) if defect else None}


def _apply_quality_gate(db, defect: models.Defect, user):
    """Section 30: Minor -> Review/Rework; Major -> Hold; Critical ->
    Immediate Hold + Incident, run enters SCRAP_REWORK_REVIEW."""
    target_run = None
    if defect.target_type == "PRODUCT_BATCH":
        pb = db.get(models.ProductBatch, defect.target_id)
        if pb:
            target_run = db.get(models.ProductionRun, pb.run_id)
            if defect.severity == "MINOR":
                try:
                    validate_transition("PRODUCT_BATCH", pb.quality_disposition, "REWORK_REQUIRED")
                    pb.quality_disposition = "REWORK_REQUIRED"
                except IllegalTransitionError:
                    pass
            elif defect.severity in ("MAJOR", "CRITICAL"):
                try:
                    validate_transition("PRODUCT_BATCH", pb.quality_disposition, "ON_HOLD")
                    pb.quality_disposition = "ON_HOLD"
                except IllegalTransitionError:
                    pass
            if defect.severity in ("MAJOR", "CRITICAL") and target_run and target_run.status in ("RUNNING", "PAUSED"):
                try:
                    validate_transition("PRODUCTION_RUN", target_run.status, "SCRAP_REWORK_REVIEW")
                    target_run.status = "SCRAP_REWORK_REVIEW"
                    target_run.version = (target_run.version or 0) + 1
                except IllegalTransitionError:
                    pass
    elif defect.target_type == "MATERIAL_BATCH":
        mb = db.get(models.MaterialBatch, defect.target_id)
        if mb and defect.severity in ("MAJOR", "CRITICAL"):
            try:
                validate_transition("MATERIAL_BATCH", mb.status, "ON_HOLD")
                mb.status = "ON_HOLD"
            except IllegalTransitionError:
                pass
            from .materials import _cascade_hold_impact
            _cascade_hold_impact(db, mb, user, f"Defect {defect.code} ({defect.severity})")

    severity_alert_map = {"MINOR": "LOW", "MAJOR": "HIGH", "CRITICAL": "CRITICAL"}
    db.add(models.Alert(
        code=f"AL-DEF-{defect.code}", type="QUALITY_DEFECT", severity=severity_alert_map[defect.severity],
        source="QUALITY_GATE", affected_run_id=target_run.id if target_run else None,
        affected_resource_type=defect.target_type, affected_resource_id=defect.target_id,
        message=f"{defect.severity} defect {defect.code} detected on {defect.target_type} {defect.target_id}.",
        status="NEW", sla_due_at=dt.datetime.utcnow() + dt.timedelta(minutes={"MINOR": 240, "MAJOR": 60, "CRITICAL": 15}[defect.severity]),
    ))

    if defect.severity == "CRITICAL":
        db.add(models.Incident(
            code=f"INC-{int(dt.datetime.utcnow().timestamp()) % 100000}", type="CRITICAL_QUALITY_FAILURE",
            severity="CRITICAL", detected_by=user.id, run_id=target_run.id if target_run else None,
            description=f"Critical defect {defect.code}: {defect.description}", status="OPEN",
        ))


# --- Defects ---------------------------------------------------------------

@router.get("/defects")
def list_defects(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    return {"items": to_list(db.query(models.Defect).order_by(models.Defect.detected_at.desc()).all())}


@router.post("/defects", status_code=201)
def create_defect(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("CREATE_DEFECT", "REPORT_QUALITY_DEFECT"))):
    severity = body.get("severity") or classify_severity(
        safety_or_regulatory=body.get("safetyOrRegulatory", False), already_propagated=body.get("alreadyPropagated", False),
        exceeds_primary_band=body.get("exceedsPrimaryBand", False), affects_fit_form_function=body.get("affectsFitFormFunction", False),
        within_secondary_band=body.get("withinSecondaryBand", True),
    )
    d = models.Defect(
        code=f"D-{int(dt.datetime.utcnow().timestamp()) % 100000}", target_type=body["targetType"], target_id=body["targetId"],
        category=body.get("category", "UNKNOWN"), severity=severity, reported_by=user.id, description=body.get("description"), status="OPEN",
    )
    db.add(d)
    db.flush()
    _apply_quality_gate(db, d, user)
    write_audit(db, user_id=user.id, action="CREATE_DEFECT", entity_type="DEFECT", entity_id=d.id, new_value=body)
    db.commit()
    return to_dict(d)


@router.patch("/defects/{defect_id}")
def update_defect(defect_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("CREATE_DEFECT", "INSPECT_BATCH"))):
    d = db.get(models.Defect, defect_id)
    if not d:
        raise HTTPException(404, "Defect not found.")
    if "status" in body:
        d.status = body["status"]
    db.commit()
    return to_dict(d)


# --- Quality Holds (18, 17.1, 17.2) --------------------------------------

@router.get("/holds")
def list_holds(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    return {"items": to_list(db.query(models.QualityHold).order_by(models.QualityHold.created_at.desc()).all())}


@router.post("/holds", status_code=201)
def create_hold(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("CREATE_HOLD", "REQUEST_HOLD"))):
    from ..permissions import ROLE_PERMISSIONS
    granted = set()
    for r in user.role_names():
        granted.update(ROLE_PERMISSIONS.get(r, []))
    is_request_only = "CREATE_HOLD" not in granted

    hold = models.QualityHold(target_type=body["targetType"], target_id=body["targetId"], reason=body["reason"],
                               created_by=user.id, status="PENDING" if is_request_only else "OPEN")
    db.add(hold)
    db.flush()

    if not is_request_only:
        if body["targetType"] == "MATERIAL_BATCH":
            batch = db.get(models.MaterialBatch, body["targetId"])
            if batch:
                try:
                    validate_transition("MATERIAL_BATCH", batch.status, "ON_HOLD")
                    batch.status = "ON_HOLD"
                    from .materials import _cascade_hold_impact
                    _cascade_hold_impact(db, batch, user, body["reason"])
                except IllegalTransitionError as e:
                    raise HTTPException(422, str(e))
        elif body["targetType"] == "PRODUCT_BATCH":
            pb = db.get(models.ProductBatch, body["targetId"])
            if pb:
                try:
                    validate_transition("PRODUCT_BATCH", pb.quality_disposition, "ON_HOLD")
                    pb.quality_disposition = "ON_HOLD"
                except IllegalTransitionError as e:
                    raise HTTPException(422, str(e))

    write_audit(db, user_id=user.id, action="CREATE_QUALITY_HOLD", entity_type="QUALITY_HOLD", entity_id=hold.id, new_value=body)
    db.commit()
    return to_dict(hold)


@router.post("/holds/{hold_id}/transitions")
def transition_hold(hold_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("RELEASE_HOLD"))):
    hold = db.get(models.QualityHold, hold_id)
    if not hold:
        raise HTTPException(404, "Hold not found.")
    action = body.get("action")   # APPROVE / RELEASE / REJECT
    if action in ("APPROVE", "RELEASE"):
        hold.status = "RELEASED"
        hold.released_by = user.id
        hold.released_at = dt.datetime.utcnow()
        if hold.target_type == "MATERIAL_BATCH":
            batch = db.get(models.MaterialBatch, hold.target_id)
            if batch:
                validate_transition("MATERIAL_BATCH", batch.status, "AVAILABLE")
                batch.status = "AVAILABLE"
        elif hold.target_type == "PRODUCT_BATCH":
            pb = db.get(models.ProductBatch, hold.target_id)
            if pb:
                validate_transition("PRODUCT_BATCH", pb.quality_disposition, "RELEASED")
                pb.quality_disposition = "RELEASED"
    elif action == "REJECT":
        hold.status = "REJECTED"
        hold.released_by = user.id
        hold.released_at = dt.datetime.utcnow()
        if hold.target_type == "MATERIAL_BATCH":
            batch = db.get(models.MaterialBatch, hold.target_id)
            if batch:
                validate_transition("MATERIAL_BATCH", batch.status, "REJECTED")
                batch.status = "REJECTED"
        elif hold.target_type == "PRODUCT_BATCH":
            pb = db.get(models.ProductBatch, hold.target_id)
            if pb:
                validate_transition("PRODUCT_BATCH", pb.quality_disposition, "SCRAPPED")
                pb.quality_disposition = "SCRAPPED"
    else:
        raise HTTPException(400, "action must be APPROVE, RELEASE, or REJECT.")
    write_audit(db, user_id=user.id, action=f"HOLD_{action}", entity_type="QUALITY_HOLD", entity_id=hold_id, reason=body.get("reason"))
    db.commit()
    return to_dict(hold)


# --- NCR ------------------------------------------------------------------

@router.get("/ncrs")
def list_ncrs(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    return {"items": to_list(db.query(models.NCR).order_by(models.NCR.created_at.desc()).all())}


@router.post("/ncrs", status_code=201)
def create_ncr(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("CREATE_NCR"))):
    ncr = models.NCR(code=f"NCR-{int(dt.datetime.utcnow().timestamp()) % 100000}", defect_id=body["defectId"],
                      raised_by=user.id, description=body.get("description"), status="OPEN")
    db.add(ncr)
    write_audit(db, user_id=user.id, action="CREATE_NCR", entity_type="NCR", entity_id=ncr.id, new_value=body)
    db.commit()
    return to_dict(ncr)


@router.patch("/ncrs/{ncr_id}")
def update_ncr(ncr_id: str, body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("CREATE_NCR"))):
    ncr = db.get(models.NCR, ncr_id)
    if not ncr:
        raise HTTPException(404, "NCR not found.")
    for field, key in [("rootCause", "root_cause"), ("correctiveAction", "corrective_action"), ("status", "status")]:
        if field in body:
            setattr(ncr, key, body[field])
    if body.get("status") == "CLOSED":
        ncr.closed_at = dt.datetime.utcnow()
    db.commit()
    return to_dict(ncr)


@router.get("/product-batches")
def list_product_batches(db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    items = db.query(models.ProductBatch).order_by(models.ProductBatch.created_at.desc()).all()
    return {"items": [to_dict(pb, {"orderCode": pb.order.code if pb.order else None, "runCode": pb.run.code if pb.run else None}) for pb in items]}
