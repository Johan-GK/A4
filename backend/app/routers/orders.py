"""Sections 19-21, 26 -- Production Order Administration, State Machine,
Planning, Approval Workflow. Section 45.2's scheduling endpoint also lives
here since it operates on /production-orders/{id}/schedule."""
import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session as OrmSession

from .. import models, schemas
from ..audit import write_audit
from ..database import get_db
from ..deps import require_permission, get_current_user
from ..scheduling import schedule_run, SchedulingConflict
from ..serialize import to_dict, to_list
from ..state_machines import validate_transition, IllegalTransitionError

router = APIRouter(prefix="/v1/production-orders", tags=["orders"])


def _next_code(db, prefix, model, code_field="code"):
    count = db.query(model).count()
    return f"{prefix}-{100 + count + 1}"


@router.get("")
def list_orders(status_: str = None, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(models.ProductionOrder)
    if status_:
        q = q.filter(models.ProductionOrder.status == status_)
    orders = q.order_by(models.ProductionOrder.priority.asc(), models.ProductionOrder.due_date.asc()).all()
    return {"items": [to_dict(o, {"processName": o.process.name if o.process else None, "runCount": len(o.runs)}) for o in orders]}


@router.get("/{order_id}")
def get_order(order_id: str, db: OrmSession = Depends(get_db), user=Depends(get_current_user)):
    o = db.get(models.ProductionOrder, order_id)
    if not o:
        raise HTTPException(404, "Order not found.")
    d = to_dict(o, {"processName": o.process.name if o.process else None})
    d["runs"] = to_list(o.runs)
    return d


@router.post("", status_code=201)
def create_order(body: dict, db: OrmSession = Depends(get_db), user=Depends(require_permission("CREATE_ORDERS"))):
    process = db.get(models.Process, body["processId"])
    if not process:
        raise HTTPException(400, "processId must reference an existing process.")
    o = models.ProductionOrder(
        code=_next_code(db, "PO", models.ProductionOrder), product_name=body["productName"],
        quantity_ordered=body["quantityOrdered"], process_id=body["processId"],
        due_date=body["dueDate"], priority=body.get("priority", 5), status="DRAFT", created_by=user.id,
    )
    db.add(o)
    db.flush()
    write_audit(db, user_id=user.id, action="CREATE_ORDER", entity_type="PRODUCTION_ORDER", entity_id=o.id, new_value=body)
    db.commit()
    return to_dict(o)


@router.post("/{order_id}/transitions")
def transition_order(order_id: str, body: schemas.TransitionRequest, db: OrmSession = Depends(get_db), user=Depends(require_permission("CREATE_ORDERS", "APPROVE_ORDERS"))):
    o = db.get(models.ProductionOrder, order_id)
    if not o:
        raise HTTPException(404, "Order not found.")
    try:
        validate_transition("PRODUCTION_ORDER", o.status, body.toState)
    except IllegalTransitionError as e:
        raise HTTPException(422, {"code": "ILLEGAL_TRANSITION", "attempted": body.toState, "current": o.status, "message": str(e)})

    if body.toState == "APPROVED" and "APPROVE_ORDERS" not in _perms(user):
        raise HTTPException(403, "Approving an order requires the APPROVE_ORDERS permission (Section 26).")

    old_status = o.status
    o.status = body.toState
    o.version = (o.version or 0) + 1
    write_audit(db, user_id=user.id, action="ORDER_TRANSITION", entity_type="PRODUCTION_ORDER", entity_id=order_id,
                old_value={"status": old_status}, new_value={"status": body.toState}, reason=body.reason)
    db.commit()
    return to_dict(o)


def _perms(user):
    from ..permissions import ROLE_PERMISSIONS
    s = set()
    for r in user.role_names():
        s.update(ROLE_PERMISSIONS.get(r, []))
    return s


@router.post("/{order_id}/schedule")
def schedule_order(
    order_id: str, body: schemas.ScheduleRequest, db: OrmSession = Depends(get_db),
    user=Depends(require_permission("ALLOCATE_RESOURCES")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Section 45.2's representative scheduling endpoint -- the highest-risk
    endpoint in the system. See scheduling.py for the full check-and-reserve
    implementation (Sections 23-25)."""
    if idempotency_key:
        existing = db.get(models.IdempotencyRecord, idempotency_key)
        if existing:
            return json.loads(existing.response_body)

    order = db.get(models.ProductionOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found.")
    step = db.get(models.ProcessStep, body.processStepId)
    if not step:
        raise HTTPException(400, "processStepId not found.")

    material_lines = [line.model_dump() for line in body.materialAllocations]

    try:
        result = schedule_run(
            db, order=order, step=step, machine_id=body.machineId, operator_id=body.operatorId,
            start=body.requestedStart.replace(tzinfo=None), end=body.requestedEnd.replace(tzinfo=None),
            material_lines=material_lines, requested_by=user.id,
        )
    except SchedulingConflict as e:
        payload = {"code": e.code, "message": e.message, "details": e.details, "alternatives": e.alternatives}
        detail0 = e.details[0] if e.details else {}
        db.add(models.SchedulingConflictLog(
            order_id=order_id, conflict_type=e.code,
            resource_type=detail0.get("resourceType"), resource_id=detail0.get("resourceId"),
            message=e.message,
        ))
        db.commit()
        raise HTTPException(409 if e.code != "CONTENDED" else 503, payload)

    if idempotency_key:
        db.add(models.IdempotencyRecord(key=idempotency_key, endpoint=f"/v1/production-orders/{order_id}/schedule",
                                          user_id=user.id, status_code=200, response_body=json.dumps(result)))
        db.commit()
    return result
