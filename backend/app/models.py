"""
Data model -- Section 8 (Entity Dictionary) of the specification.

Every entity named in the narrative sections is implemented here with its
key, its fields, and each field's type, matching Section 8.2-8.5. Types are
mapped from the document's logical types (Text, Integer, Decimal(p,s),
Boolean, Timestamp, Enum, UUID) onto SQLAlchemy columns. A relational store
(SQLite by default, see database.py) is used for the foreign-key
relationships shown in the ERD (Section 8.1).

Enums are implemented as plain string columns (rather than DB-native ENUM
types) so the same model file works unmodified against SQLite, Postgres, or
MySQL -- consistent with the document's stated stack-agnostic scope
(Section 2.2). Legality of values is enforced in the state-machine layer
(state_machines.py), not at the column level, exactly as Section 45.3
requires ("state changes are never a raw PATCH ... they go through a
dedicated transition operation").
"""
import uuid
import datetime as dt

from sqlalchemy import (
    Column, String, Text, Integer, Numeric, Boolean, DateTime, ForeignKey,
    UniqueConstraint, ForeignKeyConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now() -> dt.datetime:
    return dt.datetime.utcnow()


def Dec(precision=12, scale=3):
    return Numeric(precision, scale)


# ---------------------------------------------------------------------------
# 8.2 Identity & Access
# ---------------------------------------------------------------------------

class Department(Base):
    __tablename__ = "departments"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False, unique=True)

    users = relationship("User", back_populates="department")


class Role(Base):
    __tablename__ = "roles"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False, unique=True)          # e.g. SYSTEM_ADMIN
    description = Column(Text)
    is_system = Column(Boolean, default=False)                # seeded baseline role, protected from deletion

    permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")
    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")


class Permission(Base):
    __tablename__ = "permissions"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, nullable=False, unique=True)           # e.g. VIEW_AUDIT_LOG_LIMITED
    description = Column(Text)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id = Column(String, ForeignKey("roles.id"), primary_key=True)
    permission_id = Column(String, ForeignKey("permissions.id"), primary_key=True)

    role = relationship("Role", back_populates="permissions")
    permission = relationship("Permission")


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False)
    email = Column(Text, nullable=False, unique=True)
    phone = Column(Text)
    username = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    department_id = Column(String, ForeignKey("departments.id"), nullable=True)
    status = Column(String, nullable=False, default="ACTIVE")   # ACTIVE/INACTIVE/LOCKED/SUSPENDED
    mfa_enabled = Column(Boolean, default=False)
    mfa_secret = Column(Text, nullable=True)
    failed_login_count = Column(Integer, default=0)
    failed_login_window_start = Column(DateTime, nullable=True)
    lockout_until = Column(DateTime, nullable=True)
    lockout_count = Column(Integer, default=0)                  # for exponential backoff
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    department = relationship("Department", back_populates="users")
    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    operator_profile = relationship("Operator", back_populates="user", uselist=False)

    def role_names(self):
        return [ur.role.name for ur in self.roles]


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    role_id = Column(String, ForeignKey("roles.id"), primary_key=True)

    user = relationship("User", back_populates="roles")
    role = relationship("Role", back_populates="user_roles")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(Text, nullable=False)
    created_at = Column(DateTime, default=now)
    expires_at = Column(DateTime, nullable=False)
    ip_address = Column(Text)
    user_agent = Column(Text)
    revoked_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, default=now)


class Operator(Base):
    __tablename__ = "operators"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    employee_code = Column(Text, unique=True)
    shift_pattern = Column(Text)

    user = relationship("User", back_populates="operator_profile")
    skills = relationship("OperatorSkill", back_populates="operator", cascade="all, delete-orphan")


class OperatorSkill(Base):
    __tablename__ = "operator_skills"
    operator_id = Column(String, ForeignKey("operators.id"), primary_key=True)
    process_id = Column(String, ForeignKey("processes.id"), primary_key=True)
    certified_level = Column(String, default="BASIC")   # BASIC/QUALIFIED/EXPERT
    certified_date = Column(DateTime, nullable=True)
    expiry_date = Column(DateTime, nullable=True)

    operator = relationship("Operator", back_populates="skills")
    process = relationship("Process")


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False)
    contact_info = Column(Text)
    address = Column(Text)
    qualification_status = Column(String, default="QUALIFIED")  # QUALIFIED/PROBATIONARY/DISQUALIFIED
    created_at = Column(DateTime, default=now)


# ---------------------------------------------------------------------------
# 8.3 Resources
# ---------------------------------------------------------------------------

class Machine(Base):
    __tablename__ = "machines"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False)
    type = Column(Text)
    location = Column(Text)
    capacity = Column(Dec(10, 2))              # units/hour
    status = Column(String, nullable=False, default="AVAILABLE")  # Section 13
    installation_date = Column(DateTime, nullable=True)
    maintenance_schedule = Column(Text)
    version = Column(Integer, default=0)        # optimistic concurrency counter
    last_heartbeat_at = Column(DateTime, default=now)   # Section 35.2 freshness
    is_stale = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)

    capabilities = relationship("MachineCapability", back_populates="machine", cascade="all, delete-orphan")
    maintenance_records = relationship("MachineMaintenanceRecord", back_populates="machine", cascade="all, delete-orphan")


class MachineCapability(Base):
    __tablename__ = "machine_capabilities"
    machine_id = Column(String, ForeignKey("machines.id"), primary_key=True)
    process_step_id = Column(String, ForeignKey("process_steps.id"), primary_key=True)

    machine = relationship("Machine", back_populates="capabilities")
    process_step = relationship("ProcessStep")


class MachineMaintenanceRecord(Base):
    __tablename__ = "machine_maintenance_records"
    id = Column(String, primary_key=True, default=gen_uuid)
    machine_id = Column(String, ForeignKey("machines.id"), nullable=False)
    type = Column(String, default="PREVENTIVE")   # PREVENTIVE/CORRECTIVE
    opened_at = Column(DateTime, default=now)
    closed_at = Column(DateTime, nullable=True)
    performed_by = Column(String, ForeignKey("users.id"), nullable=True)
    verified_by = Column(String, ForeignKey("users.id"), nullable=True)
    notes = Column(Text)
    status = Column(String, default="OPEN")      # OPEN/COMPLETED/VERIFIED

    machine = relationship("Machine", back_populates="maintenance_records")


class Material(Base):
    __tablename__ = "materials"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False)
    unit_of_measure = Column(String, nullable=False)  # KG/L/EA/M/...
    category = Column(Text)
    specification_ref = Column(Text)

    batches = relationship("MaterialBatch", back_populates="material", cascade="all, delete-orphan")


class MaterialBatch(Base):
    __tablename__ = "material_batches"
    id = Column(String, primary_key=True, default=gen_uuid)
    material_id = Column(String, ForeignKey("materials.id"), nullable=False)
    supplier_id = Column(String, ForeignKey("suppliers.id"), nullable=True)
    lot_number = Column(Text, nullable=False)
    total_quantity = Column(Dec(12, 3), nullable=False, default=0)
    reserved_quantity = Column(Dec(12, 3), nullable=False, default=0)
    consumed_quantity = Column(Dec(12, 3), nullable=False, default=0)
    status = Column(String, nullable=False, default="PENDING_INSPECTION")  # Section 17.1
    storage_location = Column(Text)
    received_date = Column(DateTime, default=now)
    expiry_date = Column(DateTime, nullable=True)
    version = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    material = relationship("Material", back_populates="batches")
    supplier = relationship("Supplier")

    def available_quantity(self):
        return (self.total_quantity or 0) - (self.reserved_quantity or 0) - (self.consumed_quantity or 0)


class Process(Base):
    __tablename__ = "processes"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False)
    description = Column(Text)

    steps = relationship("ProcessStep", back_populates="process", cascade="all, delete-orphan",
                          order_by="ProcessStep.sequence_number", foreign_keys="ProcessStep.process_id")


class ProcessStep(Base):
    __tablename__ = "process_steps"
    id = Column(String, primary_key=True, default=gen_uuid)
    process_id = Column(String, ForeignKey("processes.id"), nullable=False)
    sequence_number = Column(Integer, nullable=False, default=1)
    name = Column(Text, nullable=False)
    required_skill_process_id = Column(String, ForeignKey("processes.id"), nullable=True)
    standard_cycle_time = Column(Dec(10, 2), default=1)  # minutes/unit

    process = relationship("Process", back_populates="steps", foreign_keys=[process_id])
    bom_lines = relationship("BOMLine", back_populates="process_step", cascade="all, delete-orphan")


class BOMLine(Base):
    __tablename__ = "bom_lines"
    id = Column(String, primary_key=True, default=gen_uuid)
    process_step_id = Column(String, ForeignKey("process_steps.id"), nullable=False)
    material_id = Column(String, ForeignKey("materials.id"), nullable=False)
    quantity_per_unit = Column(Dec(12, 4), nullable=False)

    process_step = relationship("ProcessStep", back_populates="bom_lines")
    material = relationship("Material")


class ResourceReservation(Base):
    """Section 8.3 -- the single table backing every conflict check (23-25)."""
    __tablename__ = "resource_reservations"
    id = Column(String, primary_key=True, default=gen_uuid)
    run_id = Column(String, ForeignKey("production_runs.id"), nullable=False)
    resource_type = Column(String, nullable=False)   # MACHINE/OPERATOR/MATERIAL_BATCH
    resource_id = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    quantity_reserved = Column(Dec(12, 3), nullable=True)
    status = Column(String, default="ACTIVE")   # ACTIVE/RELEASED/CONSUMED
    version = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    run = relationship("ProductionRun", back_populates="reservations")


# ---------------------------------------------------------------------------
# 8.4 Production
# ---------------------------------------------------------------------------

class ProductionOrder(Base):
    __tablename__ = "production_orders"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, unique=True)            # human-friendly PO-101 style code
    product_name = Column(Text, nullable=False)
    quantity_ordered = Column(Dec(12, 3), nullable=False)
    process_id = Column(String, ForeignKey("processes.id"), nullable=False)
    due_date = Column(DateTime, nullable=False)
    priority = Column(Integer, default=5)        # 1 = highest
    status = Column(String, nullable=False, default="DRAFT")   # Section 20
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)
    version = Column(Integer, default=0)

    process = relationship("Process")
    runs = relationship("ProductionRun", back_populates="order", cascade="all, delete-orphan")


class ProductionRun(Base):
    __tablename__ = "production_runs"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, unique=True)             # PR-201 style code
    order_id = Column(String, ForeignKey("production_orders.id"), nullable=False)
    process_step_id = Column(String, ForeignKey("process_steps.id"), nullable=False)
    machine_id = Column(String, ForeignKey("machines.id"), nullable=True)
    operator_id = Column(String, ForeignKey("operators.id"), nullable=True)
    scheduled_start = Column(DateTime, nullable=True)
    scheduled_end = Column(DateTime, nullable=True)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    quantity_planned = Column(Dec(12, 3), default=0)
    quantity_produced = Column(Dec(12, 3), default=0)
    status = Column(String, nullable=False, default="SCHEDULED")  # Section 22.1
    last_heartbeat_at = Column(DateTime, default=now)
    is_stale = Column(Boolean, default=False)
    version = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    order = relationship("ProductionOrder", back_populates="runs")
    process_step = relationship("ProcessStep")
    machine = relationship("Machine")
    operator = relationship("Operator")
    reservations = relationship("ResourceReservation", back_populates="run", cascade="all, delete-orphan")
    consumptions = relationship("RunMaterialConsumption", back_populates="run", cascade="all, delete-orphan")
    product_batches = relationship("ProductBatch", back_populates="run", cascade="all, delete-orphan")


class RunMaterialConsumption(Base):
    """Section 8.4 -- one row per (run, batch) pair; the mechanism that removes
    the one-material-per-run limitation and the record finalized by
    consumption posting (Section 22.3)."""
    __tablename__ = "run_material_consumptions"
    id = Column(String, primary_key=True, default=gen_uuid)
    run_id = Column(String, ForeignKey("production_runs.id"), nullable=False)
    batch_id = Column(String, ForeignKey("material_batches.id"), nullable=False)
    material_id = Column(String, ForeignKey("materials.id"), nullable=False)
    role = Column(String, default="PRIMARY")     # PRIMARY / SECONDARY_COMPONENT / SUBSTITUTE
    quantity_reserved = Column(Dec(12, 3), nullable=False, default=0)
    quantity_consumed = Column(Dec(12, 3), nullable=True)
    reserved_at = Column(DateTime, default=now)
    consumed_at = Column(DateTime, nullable=True)

    run = relationship("ProductionRun", back_populates="consumptions")
    batch = relationship("MaterialBatch")
    material = relationship("Material")


class ProductBatch(Base):
    __tablename__ = "product_batches"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, unique=True)              # PB-201 style code
    order_id = Column(String, ForeignKey("production_orders.id"), nullable=False)
    run_id = Column(String, ForeignKey("production_runs.id"), nullable=False)
    quantity_produced = Column(Dec(12, 3), default=0)
    scrapped_quantity = Column(Dec(12, 3), default=0)
    quality_disposition = Column(String, default="PENDING_INSPECTION")  # Section 17.2
    created_at = Column(DateTime, default=now)

    order = relationship("ProductionOrder")
    run = relationship("ProductionRun", back_populates="product_batches")
    serialized_units = relationship("SerializedUnit", back_populates="product_batch", cascade="all, delete-orphan")


class SerializedUnit(Base):
    """Opt-in extension, Section 16.4/8.4 -- unit-level traceability."""
    __tablename__ = "serialized_units"
    id = Column(String, primary_key=True, default=gen_uuid)
    product_batch_id = Column(String, ForeignKey("product_batches.id"), nullable=False)
    serial_number = Column(Text, nullable=False)
    status = Column(String, default="IN_STOCK")   # IN_STOCK/SHIPPED/RETURNED/SCRAPPED
    __table_args__ = (UniqueConstraint("product_batch_id", "serial_number", name="uq_serial_per_batch"),)

    product_batch = relationship("ProductBatch", back_populates="serialized_units")


class ProductLineTraceabilitySetting(Base):
    """Per-product-line opt-in decision for serial/unit-level traceability
    (Section 16.4) -- explicit and never assumed silently in either
    direction."""
    __tablename__ = "product_line_traceability_settings"
    product_name = Column(Text, primary_key=True)
    serialized_tracking_enabled = Column(Boolean, default=False)
    decided_by = Column(String, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, default=now)


# ---------------------------------------------------------------------------
# 8.5 Quality, Risk & Governance
# ---------------------------------------------------------------------------

class QualityInspection(Base):
    __tablename__ = "quality_inspections"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, unique=True)             # QI-501
    target_type = Column(String, nullable=False)  # MATERIAL_BATCH/PRODUCT_BATCH/SERIALIZED_UNIT
    target_id = Column(String, nullable=False)
    run_id = Column(String, ForeignKey("production_runs.id"), nullable=True)
    inspector_id = Column(String, ForeignKey("users.id"), nullable=True)
    timestamp = Column(DateTime, default=now)
    parameter = Column(Text)
    expected_min = Column(Dec(14, 4), nullable=True)
    expected_max = Column(Dec(14, 4), nullable=True)
    actual_value = Column(Dec(14, 4), nullable=True)
    result = Column(String, nullable=False, default="PASS")   # PASS/FAIL
    remarks = Column(Text)


class Defect(Base):
    __tablename__ = "defects"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, unique=True)             # D-104
    inspection_id = Column(String, ForeignKey("quality_inspections.id"), nullable=True)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    category = Column(String, default="UNKNOWN")   # MATERIAL/MACHINE/PROCESS/OPERATOR/MEASUREMENT/UNKNOWN
    severity = Column(String, nullable=False)       # MINOR/MAJOR/CRITICAL -- Section 29
    detected_at = Column(DateTime, default=now)
    reported_by = Column(String, ForeignKey("users.id"), nullable=True)
    description = Column(Text)
    status = Column(String, default="OPEN")         # OPEN/REVIEWED/CLOSED


class QualityHold(Base):
    __tablename__ = "quality_holds"
    id = Column(String, primary_key=True, default=gen_uuid)
    target_type = Column(String, nullable=False)   # MATERIAL_BATCH/PRODUCT_BATCH
    target_id = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now)
    status = Column(String, default="OPEN")        # OPEN / RELEASED / REJECTED
    released_by = Column(String, ForeignKey("users.id"), nullable=True)
    released_at = Column(DateTime, nullable=True)


class NCR(Base):
    __tablename__ = "ncrs"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, unique=True)
    defect_id = Column(String, ForeignKey("defects.id"), nullable=False)
    raised_by = Column(String, ForeignKey("users.id"), nullable=True)
    description = Column(Text)
    root_cause = Column(Text, nullable=True)
    corrective_action = Column(Text, nullable=True)
    status = Column(String, default="OPEN")   # OPEN/IN_PROGRESS/CLOSED
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, unique=True)             # INC-021
    type = Column(Text)
    severity = Column(String, default="LOW")      # LOW/MEDIUM/HIGH/CRITICAL
    detected_at = Column(DateTime, default=now)
    detected_by = Column(String, ForeignKey("users.id"), nullable=True)
    order_id = Column(String, ForeignKey("production_orders.id"), nullable=True)
    run_id = Column(String, ForeignKey("production_runs.id"), nullable=True)
    machine_id = Column(String, ForeignKey("machines.id"), nullable=True)
    batch_id = Column(String, ForeignKey("material_batches.id"), nullable=True)
    operator_id = Column(String, ForeignKey("operators.id"), nullable=True)
    description = Column(Text)
    status = Column(String, default="OPEN")       # Section 32
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)
    resolution = Column(Text, nullable=True)
    closed_by = Column(String, ForeignKey("users.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(Text, unique=True)              # AL-xxx
    type = Column(Text)
    severity = Column(String, default="LOW")       # LOW/MEDIUM/HIGH/CRITICAL
    source = Column(Text)
    created_at = Column(DateTime, default=now)
    affected_order_id = Column(String, ForeignKey("production_orders.id"), nullable=True)
    affected_run_id = Column(String, ForeignKey("production_runs.id"), nullable=True)
    affected_resource_type = Column(String, nullable=True)
    affected_resource_id = Column(String, nullable=True)
    status = Column(String, default="NEW")         # Section 34
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    sla_due_at = Column(DateTime, nullable=True)
    escalated = Column(Boolean, default=False)
    message = Column(Text)


class RiskScore(Base):
    __tablename__ = "risk_scores"
    id = Column(String, primary_key=True, default=gen_uuid)
    entity_type = Column(String, nullable=False)   # ORDER/RUN/MACHINE/MATERIAL_BATCH
    entity_id = Column(String, nullable=False)
    score = Column(Integer, default=0)
    classification = Column(String, default="LOW")
    calculated_at = Column(DateTime, default=now)
    contributing_factors = Column(Text)  # JSON list of {category, factorCode, score}


class Override(Base):
    __tablename__ = "overrides"
    id = Column(String, primary_key=True, default=gen_uuid)
    conflict_type = Column(Text)
    requested_by = Column(String, ForeignKey("users.id"), nullable=True)
    approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    reason = Column(Text)
    justification = Column(Text)
    timestamp = Column(DateTime, default=now)
    entity_type = Column(String)
    entity_id = Column(String)
    status = Column(String, default="PENDING")   # PENDING/APPROVED/REJECTED
    linked_audit_id = Column(String, ForeignKey("audit_logs.id"), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(String, primary_key=True, default=gen_uuid)
    recipient_role = Column(String, nullable=True)
    recipient_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    type = Column(Text)
    severity = Column(String, default="LOW")
    message = Column(Text)
    related_entity_type = Column(String, nullable=True)
    related_entity_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)
    read_at = Column(DateTime, nullable=True)


class AuditLog(Base):
    """Append-only, hash-chained. Section 38. No update/delete code path is
    ever exposed against this table anywhere in the application (38.1)."""
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=gen_uuid)
    seq = Column(Integer, autoincrement=True, unique=True)     # sequential ordinal, belt-and-braces with hash chain
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    action = Column(Text, nullable=False)
    entity_type = Column(Text)
    entity_id = Column(Text)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=now)
    reason = Column(Text, nullable=True)
    session_info = Column(Text, nullable=True)
    prev_hash = Column(Text, nullable=True)
    record_hash = Column(Text, nullable=True)


class AuditChainCheckpoint(Base):
    """Section 38.2 -- the current chain head hash stored outside the primary
    audit table, so compromising the audit table alone is not sufficient to
    re-chain it undetected."""
    __tablename__ = "audit_chain_checkpoints"
    id = Column(Integer, primary_key=True, autoincrement=True)
    head_hash = Column(Text, nullable=False)
    head_seq = Column(Integer, nullable=False)
    recorded_at = Column(DateTime, default=now)
    verified_ok = Column(Boolean, default=True)


class SystemSetting(Base):
    """Runtime-configurable thresholds (System Configuration screen)."""
    __tablename__ = "system_settings"
    key = Column(String, primary_key=True)
    value = Column(Text)
    description = Column(Text)
    updated_at = Column(DateTime, default=now)
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)


class IdempotencyRecord(Base):
    """Section 25.5 -- Idempotency-Key support for create-with-side-effect
    operations (order submission, schedule request, reservation, override
    approval)."""
    __tablename__ = "idempotency_records"
    key = Column(String, primary_key=True)
    endpoint = Column(Text, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    status_code = Column(Integer)
    response_body = Column(Text)
    created_at = Column(DateTime, default=now)


class SchedulingConflictLog(Base):
    """Feeds the Dashboard's 'Resource Conflicts' panel (Section 9) -- a
    rolling log of rejected scheduling attempts, distinct from the Alert
    table because a rejected request is not itself an actionable alert,
    just dashboard-visible signal."""
    __tablename__ = "scheduling_conflict_log"
    id = Column(String, primary_key=True, default=gen_uuid)
    order_id = Column(String, ForeignKey("production_orders.id"), nullable=True)
    conflict_type = Column(String)
    resource_type = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)
    message = Column(Text)
    created_at = Column(DateTime, default=now)


class ScheduleRequestQueue(Base):
    """Section 25.7 -- durable admission-control queue. Every scheduling
    request is written here before any lock is attempted, so priority
    ordering is enforced by construction rather than by database lock-grant
    timing."""
    __tablename__ = "schedule_request_queue"
    id = Column(String, primary_key=True, default=gen_uuid)
    resource_key_set = Column(Text, nullable=False)   # JSON sorted list of "TYPE:ID"
    order_id = Column(String, ForeignKey("production_orders.id"), nullable=True)
    priority = Column(Integer, default=5)
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now)
    status = Column(String, default="PENDING")   # PENDING/DISPATCHED/DONE/FAILED
    attempts = Column(Integer, default=0)
    result_code = Column(Text, nullable=True)
