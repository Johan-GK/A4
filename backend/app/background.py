"""
Section 35.2 (staleness), 35.3 (alert escalation), 35.4 (automatic hold on
specific CRITICAL risk factors), and 36.2 (risk recalculation).

Runs as an asyncio background task started from main.py's startup event, on
a short tick (default 20s) -- fast enough for a live demo, independent of
the "real" thresholds in config.py which stay realistic (60 minutes
machine staleness, etc).
"""
import asyncio
import datetime as dt
import uuid

from sqlalchemy.orm import Session as OrmSession

from . import models, risk_engine
from .audit import write_audit
from .config import settings
from .database import SessionLocal
from .state_machines import validate_transition, IllegalTransitionError


def _notify(db, *, role=None, user_id=None, type_, severity, message, related_type=None, related_id=None):
    db.add(models.Notification(
        recipient_role=role, recipient_user_id=user_id, type=type_, severity=severity, message=message,
        related_entity_type=related_type, related_entity_id=related_id,
    ))


def check_staleness(db: OrmSession):
    now = dt.datetime.utcnow()
    machine_threshold = dt.timedelta(minutes=settings.MACHINE_STALENESS_MINUTES)
    for m in db.query(models.Machine).filter(models.Machine.status == "RUNNING").all():
        if m.last_heartbeat_at and (now - m.last_heartbeat_at) > machine_threshold and not m.is_stale:
            m.is_stale = True
            _notify(db, role="SUPERVISOR", type_="MACHINE_STALE", severity="MEDIUM",
                    message=f"Machine {m.name} has had no status update in over {settings.MACHINE_STALENESS_MINUTES} minutes -- confirm it is still running as expected.",
                    related_type="MACHINE", related_id=m.id)

    run_threshold = dt.timedelta(minutes=settings.RUN_STALENESS_MINUTES)
    for r in db.query(models.ProductionRun).filter(models.ProductionRun.status.in_(["RUNNING", "PAUSED"])).all():
        if r.last_heartbeat_at and (now - r.last_heartbeat_at) > run_threshold and not r.is_stale:
            r.is_stale = True
            _notify(db, role="SUPERVISOR", type_="RUN_STALE", severity="MEDIUM",
                    message=f"Production Run {r.code} consumption/quality data has not been updated in over {settings.RUN_STALENESS_MINUTES} minutes.",
                    related_type="PRODUCTION_RUN", related_id=r.id)


ESCALATION_CHAIN = {
    "CRITICAL": ["SUPERVISOR", "PRODUCTION_MANAGER"],
    "HIGH": ["SUPERVISOR"],
    "MEDIUM": ["SUPERVISOR"],
    "LOW": [],
}


def check_alert_escalation(db: OrmSession):
    now = dt.datetime.utcnow()
    active = db.query(models.Alert).filter(models.Alert.status == "NEW").all()
    for a in active:
        if not a.sla_due_at:
            a.sla_due_at = a.created_at + dt.timedelta(minutes=settings.ALERT_SLA_MINUTES.get(a.severity, 240))
            continue
        if now > a.sla_due_at and not a.escalated:
            a.escalated = True
            for role in ESCALATION_CHAIN.get(a.severity, []):
                _notify(db, role=role, type_="ALERT_ESCALATED", severity=a.severity,
                        message=f"ESCALATED (missed {a.severity} SLA): {a.message}",
                        related_type="ALERT", related_id=a.id)
            write_audit(db, user_id=None, action="ALERT_ESCALATED", entity_type="ALERT", entity_id=a.id,
                        reason="First-response SLA missed; auto-escalated per Section 35.3 (not a silent re-send).")


def _active_factors_for_run(db, run: models.ProductionRun) -> list:
    factors = []
    if run.machine and run.machine.status == "FAULT":
        factors.append("MACHINE_FAULT")
    open_machine_warning = db.query(models.Alert).filter(
        models.Alert.affected_resource_type == "MACHINE", models.Alert.affected_resource_id == run.machine_id,
        models.Alert.type == "MACHINE_WARNING", models.Alert.status.in_(["NEW", "ACKNOWLEDGED", "IN_PROGRESS"]),
    ).first()
    if open_machine_warning:
        factors.append("MACHINE_WARNING")
    if run.status == "MATERIAL_SUBSTITUTION_PENDING":
        factors.append("MATERIAL_SHORTAGE")
    quality_hold_active = any(
        c.batch and c.batch.status == "ON_HOLD" for c in run.consumptions
    ) or any(pb.quality_disposition == "ON_HOLD" for pb in run.product_batches)
    if quality_hold_active:
        factors.append("QUALITY_HOLD")
    recent_defects = db.query(models.Defect).join(
        models.ProductBatch, models.Defect.target_id == models.ProductBatch.id
    ).filter(models.ProductBatch.run_id == run.id, models.Defect.status == "OPEN").count() if run.product_batches else 0
    if recent_defects >= 2:
        factors.append("HIGH_DEFECT_RATE")

    if run.order and run.order.due_date and run.status in ("SCHEDULED", "RUNNING", "PAUSED"):
        now = dt.datetime.utcnow()
        remaining = (run.order.due_date - now).total_seconds()
        planned_duration = (run.scheduled_end - run.scheduled_start).total_seconds() if run.scheduled_start and run.scheduled_end else 0
        if remaining < 0 or (run.scheduled_end and run.scheduled_end > run.order.due_date):
            factors.append("PREDICTED_DEADLINE_MISS")
        elif remaining < max(planned_duration, 3600) * 1.2:
            factors.append("DEADLINE_CLOSE")
    return factors


def recalc_risk_and_autohold(db: OrmSession):
    active_runs = db.query(models.ProductionRun).filter(models.ProductionRun.status.in_(
        ["SCHEDULED", "RUNNING", "PAUSED", "MATERIAL_SUBSTITUTION_PENDING", "SCRAP_REWORK_REVIEW"]
    )).all()
    for run in active_runs:
        factors = _active_factors_for_run(db, run)
        result = risk_engine.combine_factors(factors)
        risk_engine.save_risk_score(db, "PRODUCTION_RUN", run.id, result)

        if result["classification"] in ("HIGH", "CRITICAL"):
            existing = db.query(models.Alert).filter(
                models.Alert.affected_run_id == run.id, models.Alert.type == "RISK_ELEVATED",
                models.Alert.status.in_(["NEW", "ACKNOWLEDGED", "IN_PROGRESS"]),
            ).first()
            if not existing:
                db.add(models.Alert(
                    code=f"AL-RISK-{uuid.uuid4().hex[:6]}", type="RISK_ELEVATED", severity=result["classification"],
                    source="RISK_ENGINE", affected_run_id=run.id, affected_order_id=run.order_id, status="NEW",
                    message=f"Run {run.code} risk is {result['classification']} (score {result['score']}): "
                            f"{', '.join(f['factorCode'] for f in result['contributing_factors'])}.",
                    sla_due_at=dt.datetime.utcnow() + dt.timedelta(minutes=settings.ALERT_SLA_MINUTES[result["classification"]]),
                ))

        # Section 35.4 -- automatic line hold for the specific safety-relevant factors
        if result["classification"] == "CRITICAL" and result["auto_hold_trigger"] and run.status in ("RUNNING", "PAUSED"):
            try:
                validate_transition("PRODUCTION_RUN", run.status, "ON_HOLD")
                run.status = "ON_HOLD"
                run.version = (run.version or 0) + 1
                write_audit(db, user_id=None, action="RUN_AUTO_HOLD_RISK", entity_type="PRODUCTION_RUN", entity_id=run.id,
                            reason=f"Automatic safety hold: CRITICAL risk driven by {result['auto_hold_trigger']} (Section 35.4).")
            except IllegalTransitionError:
                pass

        # Order-level DELAYED reclassification (system-derived, Section 20)
        order = run.order
        if order and order.status == "RUNNING" and "PREDICTED_DEADLINE_MISS" in factors:
            try:
                validate_transition("PRODUCTION_ORDER", order.status, "DELAYED")
                order.status = "DELAYED"
            except IllegalTransitionError:
                pass
        elif order and order.status == "DELAYED" and "PREDICTED_DEADLINE_MISS" not in factors:
            try:
                validate_transition("PRODUCTION_ORDER", order.status, "RUNNING")
                order.status = "RUNNING"
            except IllegalTransitionError:
                pass


def run_tick():
    db = SessionLocal()
    try:
        check_staleness(db)
        check_alert_escalation(db)
        recalc_risk_and_autohold(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def background_loop():
    while True:
        try:
            run_tick()
        except Exception as e:  # never let the loop die
            print(f"[background] tick failed: {e}")
        await asyncio.sleep(settings.BACKGROUND_TICK_SECONDS)
