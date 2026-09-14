"""
Sections 23-25 -- Scheduling Algorithm, Resource Conflict Management, and
Concurrency Control.

This module is the executable core of the specification's "single
highest-priority gap": no double-booking, no silent overwrite, and the
higher-priority request actually wins, by construction (Section 25.7) --
not by hoping the database happens to grant its row lock first.

Design, mapped to the spec:
  * `AdmissionController` is the in-process analogue of the durable
    ScheduleRequestQueue + dispatcher described in 25.7: every request
    registers the sorted set of resource keys it needs, and is only allowed
    to proceed once it is the highest-priority *waiting* request for any
    resource key it shares with another waiter. Resource keys are always
    compared in sorted (ResourceType, ResourceID) order (25.7's deterministic
    lock-ordering rule), so two requests that need the same two resources in
    "reversed" order can never form a circular wait -- AT-7.
  * Once admitted, `attempt_schedule()` re-reads current committed state and
    re-runs every check from Section 23.2/24 against it (25.3 steps 2-3),
    exactly like the worked example in 25.4. If a check now fails, the
    transaction is rolled back and the specific failing check is returned,
    never a generic failure (23.2 step 16).
  * Because this reference build is a single process (see README on
    horizontal scaling), the SQLite transaction plus the AdmissionController
    together provide the "exactly one winner per contested resource"
    property that Section 25.8 says is the actual requirement, regardless of
    the specific mechanism used to get there.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy import and_

from . import models, risk_engine
from .audit import write_audit
from .config import settings


class SchedulingConflict(Exception):
    def __init__(self, code: str, message: str, details: list, alternatives: list | None = None):
        self.code = code
        self.message = message
        self.details = details
        self.alternatives = alternatives or []
        super().__init__(message)


# ---------------------------------------------------------------------------
# Section 25.7 -- admission control / deterministic priority + lock ordering
# ---------------------------------------------------------------------------

@dataclass
class _Waiter:
    request_id: str
    keys: frozenset
    priority: int
    due_date: dt.datetime
    created_at: dt.datetime
    ready: threading.Event = field(default_factory=threading.Event)


class AdmissionController:
    """One instance per process (see main.py). Resource keys are strings of
    the form 'TYPE:ID', always compared after sorting -- this is the
    deterministic global lock order of Section 25.7."""

    def __init__(self):
        self._cond = threading.Condition()
        self._waiting: dict[str, _Waiter] = {}
        self._inflight_keys: set[str] = set()

    def _can_dispatch(self, w: _Waiter) -> bool:
        if w.keys & self._inflight_keys:
            return False
        competitors = [
            other for other in self._waiting.values()
            if other.keys & w.keys
        ]
        competitors.sort(key=lambda e: (e.priority, e.due_date or dt.datetime.max, e.created_at))
        return competitors[0].request_id == w.request_id

    def acquire(self, request_id: str, keys: set, priority: int, due_date, created_at, timeout=15.0) -> bool:
        w = _Waiter(request_id, frozenset(sorted(keys)), priority, due_date, created_at)
        with self._cond:
            self._waiting[request_id] = w
            deadline = time.time() + timeout
            while True:
                if self._can_dispatch(w):
                    self._inflight_keys.update(w.keys)
                    del self._waiting[request_id]
                    self._cond.notify_all()
                    return True
                remaining = deadline - time.time()
                if remaining <= 0:
                    del self._waiting[request_id]
                    return False
                self._cond.wait(timeout=min(remaining, 0.05))

    def release(self, keys: set):
        with self._cond:
            self._inflight_keys.difference_update(keys)
            self._cond.notify_all()


admission_controller = AdmissionController()


def resource_key(resource_type: str, resource_id: str) -> str:
    return f"{resource_type}:{resource_id}"


# ---------------------------------------------------------------------------
# Section 24.1 -- time overlap
# ---------------------------------------------------------------------------

def times_overlap(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and end_a > start_b


def _active_reservations(db, resource_type, resource_id, exclude_run_id=None):
    q = db.query(models.ResourceReservation).filter(
        models.ResourceReservation.resource_type == resource_type,
        models.ResourceReservation.resource_id == resource_id,
        models.ResourceReservation.status == "ACTIVE",
    )
    if exclude_run_id:
        q = q.filter(models.ResourceReservation.run_id != exclude_run_id)
    return q.all()


def _check_time_overlap(db, resource_type, resource_id, start, end):
    for r in _active_reservations(db, resource_type, resource_id):
        if r.start_time and r.end_time and times_overlap(start, end, r.start_time, r.end_time):
            return r
    return None


# ---------------------------------------------------------------------------
# Section 16.2 / 24.2 -- multi-batch material allocation & conflict formula
# ---------------------------------------------------------------------------

def _eligible_batches(db, material_id):
    batches = (
        db.query(models.MaterialBatch)
        .filter(models.MaterialBatch.material_id == material_id, models.MaterialBatch.status == "AVAILABLE")
        .all()
    )
    # FEFO where expiry exists, else FIFO by received date
    batches.sort(key=lambda b: (b.expiry_date is None, b.expiry_date or dt.datetime.max, b.received_date or dt.datetime.min))
    return batches


def allocate_material(db, material_id, requested_qty, preferred_batch_id=None):
    """Returns (allocations: [(batch, qty)], shortfall: float|None)."""
    requested_qty = float(requested_qty)
    if preferred_batch_id:
        batch = db.get(models.MaterialBatch, preferred_batch_id)
        if batch is None or batch.material_id != material_id or batch.status != "AVAILABLE":
            return [], requested_qty
        avail = float(batch.available_quantity())
        if avail >= requested_qty:
            return [(batch, requested_qty)], None
        return [], requested_qty - avail   # caller pins a lot; no silent substitution
    allocations = []
    remaining = requested_qty
    for batch in _eligible_batches(db, material_id):
        if remaining <= 0:
            break
        avail = float(batch.available_quantity())
        if avail <= 0:
            continue
        take = min(avail, remaining)
        allocations.append((batch, take))
        remaining -= take
    if remaining > 1e-9:
        return [], remaining
    return allocations, None


# ---------------------------------------------------------------------------
# Alternative-resource suggestions (Section 23.3) -- up to three
# ---------------------------------------------------------------------------

def suggest_alternatives(db, process_step_id, machine_id, start, end, operator_id=None):
    alts = []
    # 1. an equivalent-capability machine with a free slot
    capable_machine_ids = [
        mc.machine_id for mc in db.query(models.MachineCapability)
        .filter(models.MachineCapability.process_step_id == process_step_id).all()
        if mc.machine_id != machine_id
    ]
    for mid in capable_machine_ids:
        m = db.get(models.Machine, mid)
        if not m or m.status not in ("AVAILABLE",):
            continue
        if _check_time_overlap(db, "MACHINE", mid, start, end) is None:
            alts.append({"type": "ALTERNATE_MACHINE", "machineId": mid, "machineName": m.name, "availableFrom": start.isoformat()})
            break
    # 2. next available slot on the same machine
    existing = sorted(_active_reservations(db, "MACHINE", machine_id), key=lambda r: r.end_time or dt.datetime.max)
    if existing:
        next_slot = max(r.end_time for r in existing if r.end_time)
        alts.append({"type": "ALTERNATE_SLOT", "machineId": machine_id, "availableFrom": next_slot.isoformat()})
    # 3. an alternative qualified operator
    if operator_id:
        step = db.get(models.ProcessStep, process_step_id)
        skill_process_id = step.required_skill_process_id if step else None
        candidates = (
            db.query(models.OperatorSkill)
            .filter(models.OperatorSkill.process_id == skill_process_id)
            .all() if skill_process_id else []
        )
        for cand in candidates:
            if cand.operator_id == operator_id:
                continue
            if _check_time_overlap(db, "OPERATOR", cand.operator_id, start, end) is None:
                alts.append({"type": "ALTERNATE_OPERATOR", "operatorId": cand.operator_id})
                break
    return alts[:3]


# ---------------------------------------------------------------------------
# Section 23.2 -- per-request algorithm, run under the admission controller
# ---------------------------------------------------------------------------

def _run_checks(db, order, step, machine_id, operator_id, start, end, material_lines):
    """Re-run every check against current committed state. Raises
    SchedulingConflict naming the exact failing check, or returns the
    resolved material allocation plan on success."""

    if order.status != "APPROVED":
        raise SchedulingConflict(
            "INVALID_ORDER_STATE", f"Order is {order.status}, must be APPROVED to schedule.",
            [{"conflictType": "ORDER_STATUS", "current": order.status}],
        )

    machine = db.get(models.Machine, machine_id)
    if machine is None:
        raise SchedulingConflict("NOT_FOUND", "Machine not found.", [{"conflictType": "MACHINE_NOT_FOUND"}])
    if machine.status not in ("AVAILABLE",):
        raise SchedulingConflict(
            "MACHINE_UNAVAILABLE", f"Machine {machine.name} is {machine.status} and cannot be newly allocated.",
            [{"conflictType": "MACHINE_STATE", "resourceType": "MACHINE", "resourceId": machine_id, "state": machine.status}],
            suggest_alternatives(db, step.id, machine_id, start, end, operator_id),
        )

    capable = db.query(models.MachineCapability).filter_by(machine_id=machine_id, process_step_id=step.id).first()
    if capable is None:
        raise SchedulingConflict(
            "MACHINE_NOT_CAPABLE", f"Machine {machine.name} is not qualified for this process step.",
            [{"conflictType": "MACHINE_CAPABILITY", "resourceId": machine_id}],
            suggest_alternatives(db, step.id, machine_id, start, end, operator_id),
        )

    overlap = _check_time_overlap(db, "MACHINE", machine_id, start, end)
    if overlap:
        raise SchedulingConflict(
            "RESOURCE_CONFLICT", f"Machine {machine.name} is already reserved {overlap.start_time}-{overlap.end_time}.",
            [{"conflictType": "TIME_OVERLAP", "resourceType": "MACHINE", "resourceId": machine_id, "existingRunId": overlap.run_id}],
            suggest_alternatives(db, step.id, machine_id, start, end, operator_id),
        )

    if operator_id:
        operator = db.get(models.Operator, operator_id)
        if operator is None:
            raise SchedulingConflict("NOT_FOUND", "Operator not found.", [{"conflictType": "OPERATOR_NOT_FOUND"}])
        skill_process_id = step.required_skill_process_id
        if skill_process_id:
            has_skill = db.query(models.OperatorSkill).filter_by(operator_id=operator_id, process_id=skill_process_id).first()
            if has_skill is None:
                raise SchedulingConflict(
                    "OPERATOR_NOT_SKILLED", "Operator lacks the required skill for this process step.",
                    [{"conflictType": "OPERATOR_SKILL", "resourceId": operator_id}],
                    suggest_alternatives(db, step.id, machine_id, start, end, operator_id),
                )
        op_overlap = _check_time_overlap(db, "OPERATOR", operator_id, start, end)
        if op_overlap:
            raise SchedulingConflict(
                "RESOURCE_CONFLICT", "Operator is already booked for an overlapping window.",
                [{"conflictType": "TIME_OVERLAP", "resourceType": "OPERATOR", "resourceId": operator_id, "existingRunId": op_overlap.run_id}],
                suggest_alternatives(db, step.id, machine_id, start, end, operator_id),
            )

    resolved_lines = []
    for line in material_lines:
        allocations, shortfall = allocate_material(db, line["materialId"], line["requestedQuantity"], line.get("preferredBatchId"))
        if shortfall is not None:
            raise SchedulingConflict(
                "MATERIAL_SHORTAGE",
                f"Insufficient available quantity for material {line['materialId']}: short by {shortfall:.3f}.",
                [{"conflictType": "MATERIAL_SHORTAGE", "materialId": line["materialId"], "shortfall": shortfall}],
            )
        # quality status re-check (not ON_HOLD / REJECTED / EXPIRED) -- allocate_material
        # already only pulls AVAILABLE batches, so this is guaranteed by construction.
        resolved_lines.append({"materialId": line["materialId"], "requestedQuantity": line["requestedQuantity"],
                                "unit": line.get("unit"), "allocations": allocations})

    return resolved_lines


def schedule_run(
    db: OrmSession,
    *,
    order: models.ProductionOrder,
    step: models.ProcessStep,
    machine_id: str,
    operator_id: str | None,
    start: dt.datetime,
    end: dt.datetime,
    material_lines: list[dict],
    requested_by: str | None,
    request_id: str | None = None,
):
    """Implements Sections 23.2 steps 1-16 end to end, dispatched through the
    Section 25.7 admission controller and committed under a single
    transaction per Section 25.3."""
    request_id = request_id or f"req-{dt.datetime.utcnow().timestamp()}-{random.random()}"

    keys = {resource_key("MACHINE", machine_id)}
    if operator_id:
        keys.add(resource_key("OPERATOR", operator_id))
    for line in material_lines:
        keys.add(resource_key("MATERIAL", line["materialId"]))

    attempts = 0
    base_ms = settings.RETRY_BASE_MS
    while attempts < settings.RETRY_MAX_ATTEMPTS:
        attempts += 1
        admitted = admission_controller.acquire(request_id, keys, order.priority or 5, order.due_date, dt.datetime.utcnow())
        if not admitted:
            raise SchedulingConflict(
                "CONTENDED", "Resource set too contended to resolve within the retry budget.", [], []
            )
        try:
            db.begin_nested() if db.in_transaction() else None
            resolved_lines = _run_checks(db, order, step, machine_id, operator_id, start, end, material_lines)

            # ---- commit reservations (Section 25.3 step 4) ----
            run = models.ProductionRun(
                code=f"PR-{int(time.time()*1000) % 100000}",
                order_id=order.id, process_step_id=step.id, machine_id=machine_id, operator_id=operator_id,
                scheduled_start=start, scheduled_end=end, status="SCHEDULED",
                quantity_planned=order.quantity_ordered,
            )
            db.add(run)
            db.flush()

            db.add(models.ResourceReservation(
                run_id=run.id, resource_type="MACHINE", resource_id=machine_id,
                start_time=start, end_time=end, status="ACTIVE",
            ))
            if operator_id:
                db.add(models.ResourceReservation(
                    run_id=run.id, resource_type="OPERATOR", resource_id=operator_id,
                    start_time=start, end_time=end, status="ACTIVE",
                ))

            response_lines = []
            for line in resolved_lines:
                allocated_batches = []
                for batch, qty in line["allocations"]:
                    batch.reserved_quantity = float(batch.reserved_quantity or 0) + qty
                    db.add(models.ResourceReservation(
                        run_id=run.id, resource_type="MATERIAL_BATCH", resource_id=batch.id,
                        quantity_reserved=qty, status="ACTIVE",
                    ))
                    db.add(models.RunMaterialConsumption(
                        run_id=run.id, batch_id=batch.id, material_id=line["materialId"],
                        quantity_reserved=qty,
                    ))
                    allocated_batches.append({"batchId": batch.id, "lotNumber": batch.lot_number, "quantity": qty})
                response_lines.append({
                    "materialId": line["materialId"], "requestedQuantity": line["requestedQuantity"],
                    "unit": line["unit"], "allocatedBatches": allocated_batches,
                })

            machine = db.get(models.Machine, machine_id)
            machine.status = "RESERVED"
            machine.version = (machine.version or 0) + 1

            if order.status == "APPROVED":
                order.status = "READY"
            order.version = (order.version or 0) + 1

            expected_completion = start + (end - start)

            risk_result = risk_engine.combine_factors([])  # freshly scheduled run starts LOW risk
            risk_engine.save_risk_score(db, "PRODUCTION_RUN", run.id, risk_result)

            write_audit(db, user_id=requested_by, action="SCHEDULE_RUN", entity_type="PRODUCTION_RUN",
                        entity_id=run.id, new_value={"orderId": order.id, "machineId": machine_id,
                                                       "operatorId": operator_id, "start": start.isoformat(), "end": end.isoformat()})
            db.commit()

            return {
                "runId": run.id, "runCode": run.code, "status": "READY",
                "reservations": [{"resourceType": "MACHINE", "resourceId": machine_id}] + (
                    [{"resourceType": "OPERATOR", "resourceId": operator_id}] if operator_id else []
                ),
                "materialAllocations": response_lines,
                "expectedCompletion": expected_completion.isoformat(),
                "riskScore": {"score": risk_result["score"], "classification": risk_result["classification"]},
            }
        except SchedulingConflict:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            admission_controller.release(keys)
        # (loop only re-enters on a transient serialization failure branch, not modelled
        #  distinctly from generic exceptions in this single-process reference build)
    raise SchedulingConflict("CONTENDED", "Exceeded retry budget under contention.", [], [])
