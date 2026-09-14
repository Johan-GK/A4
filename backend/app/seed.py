"""
Demo data seed -- runs once on first startup (idempotent: skipped if any
User row already exists). Populates enough master data and in-flight
production state that the dashboard, scheduling, quality, traceability, and
alerting screens all have something real to show immediately.
"""
import datetime as dt

from .database import SessionLocal
from . import models, security, risk_engine
from .permissions import ROLES, PERMISSIONS, ROLE_PERMISSIONS
from .audit import write_audit

DEMO_PASSWORD = "Trenser@2026"


def seed_if_empty():
    db = SessionLocal()
    try:
        if db.query(models.User).count() > 0:
            return
        _seed(db)
        db.commit()
        print("[seed] Demo data created.")
    except Exception as e:
        db.rollback()
        print(f"[seed] FAILED: {e}")
        raise
    finally:
        db.close()


def _seed(db):
    now = dt.datetime.utcnow()

    # --- Permissions & Roles (data-driven, Section 11) ------------------
    perm_rows = {}
    for code, desc in PERMISSIONS.items():
        p = models.Permission(code=code, description=desc)
        db.add(p)
        perm_rows[code] = p
    db.flush()

    role_rows = {}
    for name, desc in ROLES.items():
        r = models.Role(name=name, description=desc, is_system=True)
        db.add(r)
        role_rows[name] = r
    db.flush()

    for role_name, codes in ROLE_PERMISSIONS.items():
        for code in codes:
            db.add(models.RolePermission(role_id=role_rows[role_name].id, permission_id=perm_rows[code].id))

    # --- Departments -------------------------------------------------------
    dep_production = models.Department(name="Production")
    dep_quality = models.Department(name="Quality Assurance")
    dep_maintenance = models.Department(name="Maintenance")
    dep_admin = models.Department(name="Administration")
    db.add_all([dep_production, dep_quality, dep_maintenance, dep_admin])
    db.flush()

    # --- Users (one per role) ----------------------------------------------
    def make_user(name, email, username, role, dep, mfa=False):
        u = models.User(
            name=name, email=email, username=username, password_hash=security.hash_password(DEMO_PASSWORD),
            department_id=dep.id, status="ACTIVE", mfa_enabled=mfa,
        )
        db.add(u)
        db.flush()
        db.add(models.UserRole(user_id=u.id, role_id=role_rows[role].id))
        return u

    admin = make_user("Ava Administrator", "admin@pcts.demo", "admin", "SYSTEM_ADMIN", dep_admin)
    pm = make_user("Priya Manager", "pm@pcts.demo", "pmanager", "PRODUCTION_MANAGER", dep_production)
    supervisor = make_user("Sam Supervisor", "supervisor@pcts.demo", "supervisor", "SUPERVISOR", dep_production)
    qa = make_user("Quinn Adler", "qa@pcts.demo", "qaofficer", "QA_QC_OFFICER", dep_quality)
    maint = make_user("Max Turner", "maintenance@pcts.demo", "maintenance", "MAINTENANCE_OFFICER", dep_maintenance)
    op_user1 = make_user("Oscar Reyes", "operator1@pcts.demo", "operator1", "OPERATOR", dep_production)
    op_user2 = make_user("Olivia Chen", "operator2@pcts.demo", "operator2", "OPERATOR", dep_production)
    db.flush()

    # --- Processes / Process Steps ------------------------------------------
    proc_widget = models.Process(name="Widget Fabrication", description="Cutting -> Machining -> Assembly -> Inspection")
    db.add(proc_widget)
    db.flush()

    step_cutting = models.ProcessStep(process_id=proc_widget.id, sequence_number=1, name="Cutting", standard_cycle_time=2.0)
    step_machining = models.ProcessStep(process_id=proc_widget.id, sequence_number=2, name="Machining", standard_cycle_time=3.5)
    step_assembly = models.ProcessStep(process_id=proc_widget.id, sequence_number=3, name="Assembly", standard_cycle_time=1.5)
    step_inspection = models.ProcessStep(process_id=proc_widget.id, sequence_number=4, name="Inspection", standard_cycle_time=1.0)
    db.add_all([step_cutting, step_machining, step_assembly, step_inspection])
    db.flush()

    # Operator skill process (reuse the same process for skill-matching demo)
    proc_general_ops = models.Process(name="General Machine Operation", description="Baseline skill process for machine operation.")
    db.add(proc_general_ops)
    db.flush()
    for step in (step_cutting, step_machining, step_assembly, step_inspection):
        step.required_skill_process_id = proc_general_ops.id

    # --- Suppliers -----------------------------------------------------------
    supplier_a = models.Supplier(name="AlloyWorks Metals", contact_info="sales@alloyworks.example", qualification_status="QUALIFIED")
    supplier_b = models.Supplier(name="Component Partners Inc.", contact_info="orders@componentpartners.example", qualification_status="QUALIFIED")
    db.add_all([supplier_a, supplier_b])
    db.flush()

    # --- Materials & Batches --------------------------------------------------
    mat_steel = models.Material(name="Steel Sheet 2mm", unit_of_measure="KG", category="Raw Material")
    mat_fastener = models.Material(name="M6 Fastener", unit_of_measure="EA", category="Component")
    db.add_all([mat_steel, mat_fastener])
    db.flush()

    batch_mb001 = models.MaterialBatch(material_id=mat_steel.id, supplier_id=supplier_a.id, lot_number="MB-001",
                                        total_quantity=400, status="AVAILABLE", storage_location="Rack A1",
                                        received_date=now - dt.timedelta(days=10), expiry_date=now + dt.timedelta(days=180))
    batch_mb014 = models.MaterialBatch(material_id=mat_steel.id, supplier_id=supplier_a.id, lot_number="MB-014",
                                        total_quantity=150, status="AVAILABLE", storage_location="Rack A2",
                                        received_date=now - dt.timedelta(days=3), expiry_date=now + dt.timedelta(days=200))
    batch_mb021 = models.MaterialBatch(material_id=mat_steel.id, supplier_id=supplier_b.id, lot_number="MB-021",
                                        total_quantity=80, status="ON_HOLD", storage_location="Rack A3",
                                        received_date=now - dt.timedelta(days=1), expiry_date=now + dt.timedelta(days=150))
    batch_mb070 = models.MaterialBatch(material_id=mat_fastener.id, supplier_id=supplier_b.id, lot_number="MB-070",
                                        total_quantity=5000, status="AVAILABLE", storage_location="Bin C4",
                                        received_date=now - dt.timedelta(days=15))
    db.add_all([batch_mb001, batch_mb014, batch_mb021, batch_mb070])
    db.flush()

    # BOM lines: Cutting consumes steel; Assembly consumes fasteners.
    db.add(models.BOMLine(process_step_id=step_cutting.id, material_id=mat_steel.id, quantity_per_unit=0.5))
    db.add(models.BOMLine(process_step_id=step_assembly.id, material_id=mat_fastener.id, quantity_per_unit=4))

    # --- Machines --------------------------------------------------------------
    m03 = models.Machine(name="M-03", type="CNC Mill", location="Bay 1", capacity=120, status="AVAILABLE",
                          installation_date=now - dt.timedelta(days=900), maintenance_schedule="Quarterly")
    m07 = models.Machine(name="M-07", type="CNC Mill", location="Bay 1", capacity=110, status="AVAILABLE",
                          installation_date=now - dt.timedelta(days=700), maintenance_schedule="Quarterly")
    m12 = models.Machine(name="M-12", type="Laser Cutter", location="Bay 2", capacity=200, status="AVAILABLE",
                          installation_date=now - dt.timedelta(days=400), maintenance_schedule="Semiannual")
    m21 = models.Machine(name="M-21", type="Assembly Cell", location="Bay 3", capacity=300, status="FAULT",
                          installation_date=now - dt.timedelta(days=1200), maintenance_schedule="Monthly")
    db.add_all([m03, m07, m12, m21])
    db.flush()

    for m in (m03, m07):
        db.add(models.MachineCapability(machine_id=m.id, process_step_id=step_machining.id))
        db.add(models.MachineCapability(machine_id=m.id, process_step_id=step_cutting.id))
    db.add(models.MachineCapability(machine_id=m12.id, process_step_id=step_cutting.id))
    db.add(models.MachineCapability(machine_id=m21.id, process_step_id=step_assembly.id))

    # --- Operators & skills -------------------------------------------------
    operator1 = models.Operator(user_id=op_user1.id, employee_code="OP-07", shift_pattern="Day")
    operator2 = models.Operator(user_id=op_user2.id, employee_code="OP-12", shift_pattern="Night")
    db.add_all([operator1, operator2])
    db.flush()
    db.add(models.OperatorSkill(operator_id=operator1.id, process_id=proc_general_ops.id, certified_level="EXPERT", certified_date=now - dt.timedelta(days=300)))
    db.add(models.OperatorSkill(operator_id=operator2.id, process_id=proc_general_ops.id, certified_level="QUALIFIED", certified_date=now - dt.timedelta(days=100)))

    # --- Production Orders ---------------------------------------------------
    order_101 = models.ProductionOrder(code="PO-101", product_name="Product-A Widget", quantity_ordered=1000,
                                        process_id=proc_widget.id, due_date=now + dt.timedelta(hours=6), priority=1,
                                        status="APPROVED", created_by=pm.id, created_at=now - dt.timedelta(hours=2))
    order_104 = models.ProductionOrder(code="PO-104", product_name="Product-B Bracket", quantity_ordered=500,
                                        process_id=proc_widget.id, due_date=now + dt.timedelta(hours=2), priority=2,
                                        status="RUNNING", created_by=pm.id, created_at=now - dt.timedelta(hours=5))
    order_105 = models.ProductionOrder(code="PO-105", product_name="Product-A Widget", quantity_ordered=300,
                                        process_id=proc_widget.id, due_date=now + dt.timedelta(days=1), priority=3,
                                        status="DRAFT", created_by=pm.id, created_at=now - dt.timedelta(hours=1))
    db.add_all([order_101, order_104, order_105])
    db.flush()

    # A RUNNING run for PO-104 on M-07 with an active multi-batch material consumption.
    run_201 = models.ProductionRun(code="PR-201", order_id=order_104.id, process_step_id=step_cutting.id,
                                    machine_id=m07.id, operator_id=operator1.id,
                                    scheduled_start=now - dt.timedelta(hours=1), scheduled_end=now + dt.timedelta(hours=1),
                                    actual_start=now - dt.timedelta(hours=1), quantity_planned=500, status="RUNNING",
                                    last_heartbeat_at=now - dt.timedelta(minutes=5))
    db.add(run_201)
    db.flush()
    m07.status = "RUNNING"

    db.add(models.ResourceReservation(run_id=run_201.id, resource_type="MACHINE", resource_id=m07.id,
                                       start_time=run_201.scheduled_start, end_time=run_201.scheduled_end, status="ACTIVE"))
    db.add(models.ResourceReservation(run_id=run_201.id, resource_type="OPERATOR", resource_id=operator1.id,
                                       start_time=run_201.scheduled_start, end_time=run_201.scheduled_end, status="ACTIVE"))
    db.add(models.ResourceReservation(run_id=run_201.id, resource_type="MATERIAL_BATCH", resource_id=batch_mb001.id,
                                       quantity_reserved=200, status="ACTIVE"))
    db.add(models.ResourceReservation(run_id=run_201.id, resource_type="MATERIAL_BATCH", resource_id=batch_mb014.id,
                                       quantity_reserved=50, status="ACTIVE"))
    batch_mb001.reserved_quantity = 200
    batch_mb014.reserved_quantity = 50
    db.add(models.RunMaterialConsumption(run_id=run_201.id, batch_id=batch_mb001.id, material_id=mat_steel.id,
                                          quantity_reserved=200, reserved_at=now - dt.timedelta(hours=1)))
    db.add(models.RunMaterialConsumption(run_id=run_201.id, batch_id=batch_mb014.id, material_id=mat_steel.id,
                                          quantity_reserved=50, reserved_at=now - dt.timedelta(hours=1)))

    # A completed run/order with a released ProductBatch, for traceability demo.
    order_100 = models.ProductionOrder(code="PO-100", product_name="Product-A Widget", quantity_ordered=400,
                                        process_id=proc_widget.id, due_date=now - dt.timedelta(hours=2), priority=2,
                                        status="COMPLETED", created_by=pm.id, created_at=now - dt.timedelta(days=1))
    db.add(order_100)
    db.flush()
    run_101 = models.ProductionRun(code="PR-101", order_id=order_100.id, process_step_id=step_machining.id,
                                    machine_id=m03.id, operator_id=operator1.id,
                                    scheduled_start=now - dt.timedelta(hours=6), scheduled_end=now - dt.timedelta(hours=4),
                                    actual_start=now - dt.timedelta(hours=6), actual_end=now - dt.timedelta(hours=4),
                                    quantity_planned=400, quantity_produced=400, status="COMPLETED")
    db.add(run_101)
    db.flush()
    db.add(models.RunMaterialConsumption(run_id=run_101.id, batch_id=batch_mb001.id, material_id=mat_steel.id,
                                          quantity_reserved=100, quantity_consumed=98, reserved_at=now - dt.timedelta(hours=6),
                                          consumed_at=now - dt.timedelta(hours=4)))
    db.add(models.RunMaterialConsumption(run_id=run_101.id, batch_id=batch_mb070.id, material_id=mat_fastener.id,
                                          quantity_reserved=1600, quantity_consumed=1600, reserved_at=now - dt.timedelta(hours=6),
                                          consumed_at=now - dt.timedelta(hours=4)))
    batch_mb070.consumed_quantity = 1600
    pb_201 = models.ProductBatch(code="PB-201", order_id=order_100.id, run_id=run_101.id, quantity_produced=400,
                                  quality_disposition="RELEASED", created_at=now - dt.timedelta(hours=4))
    db.add(pb_201)
    db.flush()

    insp_501 = models.QualityInspection(code="QI-501", target_type="PRODUCT_BATCH", target_id=pb_201.id, run_id=run_101.id,
                                          inspector_id=qa.id, timestamp=now - dt.timedelta(hours=3, minutes=50),
                                          parameter="Bracket width (mm)", expected_min=24.8, expected_max=25.2,
                                          actual_value=25.0, result="PASS", remarks="Within tolerance.")
    db.add(insp_501)

    # --- Quality hold on MB-021 (feeds the dashboard's Material Holds KPI) ---
    hold_1 = models.QualityHold(target_type="MATERIAL_BATCH", target_id=batch_mb021.id,
                                 reason="Supplier certificate mismatch pending review.", created_by=qa.id, status="OPEN")
    db.add(hold_1)

    # --- Incident + Critical alert for the degraded machine M-21 --------------
    inc_021 = models.Incident(code="INC-021", type="MACHINE_DEGRADATION", severity="CRITICAL", detected_by=maint.id,
                               machine_id=m21.id, description="Assembly Cell M-21 reporting abnormal vibration; faulted out.",
                               status="OPEN", assigned_to=maint.id, detected_at=now - dt.timedelta(hours=1))
    db.add(inc_021)

    alert_1 = models.Alert(code="AL-M21FLT", type="MACHINE_FAULT", severity="CRITICAL", source="MAINTENANCE",
                            affected_resource_type="MACHINE", affected_resource_id=m21.id, status="NEW",
                            message="Machine M-21 degradation detected -- faulted out, awaiting maintenance.",
                            created_at=now - dt.timedelta(hours=1), sla_due_at=now + dt.timedelta(minutes=10))
    alert_2 = models.Alert(code="AL-MB21HLD", type="MATERIAL_HOLD", severity="MEDIUM", source="MATERIAL_HOLD",
                            affected_resource_type="MATERIAL_BATCH", affected_resource_id=batch_mb021.id, status="NEW",
                            message="Material MB-21 on hold pending certificate review.",
                            created_at=now - dt.timedelta(minutes=40), sla_due_at=now + dt.timedelta(hours=3))
    alert_3 = models.Alert(code="AL-PO104RISK", type="RISK_ELEVATED", severity="HIGH", source="RISK_ENGINE",
                            affected_order_id=order_104.id, affected_run_id=run_201.id, status="NEW",
                            message="Order PO-104 deadline risk elevated -- projected completion is close to due date.",
                            created_at=now - dt.timedelta(minutes=20), sla_due_at=now + dt.timedelta(minutes=40))
    db.add_all([alert_1, alert_2, alert_3])

    db.add(models.SchedulingConflictLog(order_id=order_105.id, conflict_type="RESOURCE_CONFLICT",
                                          resource_type="MACHINE", resource_id=m07.id,
                                          message="Machine M-07 -> Double booking attempt for PO-105 against PR-201's window."))
    db.add(models.SchedulingConflictLog(order_id=order_105.id, conflict_type="MATERIAL_SHORTAGE",
                                          resource_type="MATERIAL_BATCH", resource_id=batch_mb021.id,
                                          message="Material MB-15 -> Insufficient quantity for requested allocation."))
    db.add(models.SchedulingConflictLog(conflict_type="RESOURCE_CONFLICT", resource_type="OPERATOR", resource_id=operator2.id,
                                          message="Operator OP-12 -> Schedule conflict with an overlapping assignment."))

    # --- Risk scores -----------------------------------------------------------
    risk_result = risk_engine.combine_factors(["PREDICTED_DEADLINE_MISS", "MACHINE_WARNING"])
    risk_engine.save_risk_score(db, "PRODUCTION_RUN", run_201.id, risk_result)
    risk_result_order = risk_engine.combine_factors(["DEADLINE_CLOSE"])
    risk_engine.save_risk_score(db, "PRODUCTION_ORDER", order_104.id, risk_result_order)

    # --- Notifications -----------------------------------------------------
    db.add(models.Notification(recipient_role="MAINTENANCE_OFFICER", type="MACHINE_FAULT", severity="CRITICAL",
                                message="Machine M-21 faulted -- maintenance action required.",
                                related_entity_type="MACHINE", related_entity_id=m21.id))
    db.add(models.Notification(recipient_role="SUPERVISOR", type="MATERIAL_HOLD", severity="MEDIUM",
                                message="Material MB-21 placed on hold.", related_entity_type="MATERIAL_BATCH",
                                related_entity_id=batch_mb021.id))

    # --- Product-line traceability opt-in demo row (Section 16.4) -----------
    db.add(models.ProductLineTraceabilitySetting(product_name="Product-A Widget", serialized_tracking_enabled=False, decided_by=admin.id))

    write_audit(db, user_id=admin.id, action="SYSTEM_SEED", entity_type="SYSTEM", entity_id="seed",
                reason="Initial demo dataset created on first run.")

    print("\n" + "=" * 72)
    print(" Demo accounts (all use the same password)")
    print("=" * 72)
    for u, role in [(admin, "System Admin"), (pm, "Production Manager"), (supervisor, "Supervisor"),
                    (qa, "QA/QC Officer"), (maint, "Maintenance Officer"), (op_user1, "Operator")]:
        print(f"   {u.username:<12} / {DEMO_PASSWORD}   ({role})")
    print("=" * 72 + "\n")
