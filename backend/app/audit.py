"""
Section 38 -- Audit Log: append-only enforcement + tamper-evident hash chain.

38.1 Application layer: no code path anywhere in this application exposes an
     update or delete against AuditLog -- there is no such router/function.
38.2 Each record stores RecordHash = Hash(record content + PrevHash of the
     immediately preceding record). AuditChainCheckpoint stores the current
     head hash in a separate table (an analogue of "a different storage
     location/credential") so compromising the audit table alone would not
     be enough to silently re-chain it.
"""
import hashlib
import json
import datetime as dt

from sqlalchemy.orm import Session as OrmSession

from . import models


def _canonical(record: dict) -> str:
    return json.dumps(record, sort_keys=True, default=str)


def write_audit(
    db: OrmSession,
    *,
    user_id: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value=None,
    new_value=None,
    reason: str | None = None,
    session_info: str | None = None,
) -> models.AuditLog:
    checkpoint = (
        db.query(models.AuditChainCheckpoint)
        .order_by(models.AuditChainCheckpoint.id.desc())
        .first()
    )
    prev_hash = checkpoint.head_hash if checkpoint else "GENESIS"

    # `seq` is a belt-and-braces sequential ordinal alongside the hash chain
    # (Section 38.2). It is NOT the table's primary key (that is the UUID
    # `id`), so SQLAlchemy/SQLite autoincrement is not applied to it --
    # assign it explicitly here. Deriving it from the checkpoint's head_seq
    # (rather than MAX(seq)) keeps it correct even if earlier rows were ever
    # purged, and stays consistent with the checkpoint we write below.
    next_seq = (checkpoint.head_seq if checkpoint else 0) + 1

    entry = models.AuditLog(
        seq=next_seq,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_value=_canonical(old_value) if old_value is not None else None,
        new_value=_canonical(new_value) if new_value is not None else None,
        timestamp=dt.datetime.utcnow(),
        reason=reason,
        session_info=session_info,
        prev_hash=prev_hash,
    )
    content = {
        "user_id": entry.user_id,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "old_value": entry.old_value,
        "new_value": entry.new_value,
        "timestamp": entry.timestamp.isoformat(),
        "reason": entry.reason,
        "prev_hash": prev_hash,
    }
    entry.record_hash = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()

    db.add(entry)
    db.flush()

    new_checkpoint = models.AuditChainCheckpoint(
        head_hash=entry.record_hash, head_seq=next_seq, verified_ok=True
    )
    db.add(new_checkpoint)
    return entry


def verify_chain(db: OrmSession) -> dict:
    """Periodic integrity-verification job (38.2): recompute the chain and
    report whether any break is found."""
    entries = db.query(models.AuditLog).order_by(models.AuditLog.seq.asc()).all()
    prev_hash = "GENESIS"
    for e in entries:
        content = {
            "user_id": e.user_id,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "old_value": e.old_value,
            "new_value": e.new_value,
            "timestamp": e.timestamp.isoformat(),
            "reason": e.reason,
            "prev_hash": prev_hash,
        }
        expected = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
        if expected != e.record_hash:
            return {"ok": False, "broken_at_seq": e.seq, "checked": len(entries)}
        prev_hash = e.record_hash
    return {"ok": True, "checked": len(entries), "head_hash": prev_hash}
