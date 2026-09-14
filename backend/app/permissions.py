"""
Sections 5-7 -- User Roles, Permission Matrix, and Permission Scope
Definitions.

Implementation rule from Section 7: "these scopes are permission-code level,
not role-level -- a permission such as VIEW_AUDIT_LOG_LIMITED is a distinct,
assignable permission from VIEW_AUDIT_LOG_ALL, joined to a role through the
Role -> Permission mapping." That mapping is data (RolePermission rows,
seeded from ROLE_PERMISSIONS below) rather than an if/else ladder in code,
per Section 11's "permissions should be data-driven rather than
hard-coded."
"""

# Section 5 -- roles (Table 2)
ROLES = {
    "SYSTEM_ADMIN": "Full system governance; users, roles, permissions, configuration, master data, audit access.",
    "PRODUCTION_MANAGER": "Production planning, orders, resource allocation, scheduling, monitoring, production decisions.",
    "SUPERVISOR": "Day-to-day shop-floor control, alerts, resource assignment, run control, impact decisions.",
    "QA_QC_OFFICER": "Inspections, defects, quality holds, NCRs, traceability investigations, release decisions.",
    "MAINTENANCE_OFFICER": "Machine faults, maintenance records, machine status, maintenance completion and return to service.",
    "OPERATOR": "Assigned production execution, quantity entry, downtime/problem reporting, defect reporting.",
}

# Section 7 -- scope definitions (Table 4), kept here purely as documentation
# for the UI / admin screens; the actual enforcement is the permission-code
# grant below.
SCOPE_DEFINITIONS = {
    "FULL": "Unrestricted access to the function; all records, CRUD + transitions.",
    "VIEW": "Read-only access to all records of the relevant type, system-wide.",
    "LIMITED": "Read-only, restricted to records the user has an explicit relationship to.",
    "OWN": "Read-only, restricted to records the current user authored.",
    "REPORT": "Create-only access to submit a new record; no read of others' submissions.",
    "REQUEST": "Create-only access to submit a record with no operational effect until an authorized role approves it.",
}

# --- Permission catalog -----------------------------------------------------
# code -> description
PERMISSIONS = {
    # Users & roles
    "MANAGE_USERS": "Create/update users, unlock/lock accounts.",
    "MANAGE_ROLES": "Create/update roles and role-permission assignments.",
    # Machines
    "MANAGE_MACHINES": "Full CRUD + transitions on machines.",
    "VIEW_MACHINES": "Read-only, all machines.",
    # Materials
    "MANAGE_MATERIALS": "Full CRUD + transitions on materials/batches.",
    "VIEW_MATERIALS": "Read-only, all materials/batches.",
    # Suppliers
    "MANAGE_SUPPLIERS": "Full CRUD on suppliers.",
    # Processes / BOM
    "MANAGE_PROCESSES": "Full CRUD on processes, process steps, BOM lines.",
    "VIEW_PROCESSES": "Read-only processes/BOM.",
    # Orders / scheduling
    "CREATE_ORDERS": "Create and submit production orders.",
    "APPROVE_ORDERS": "Approve submitted orders (Section 26).",
    "VIEW_ORDERS": "Read-only production orders.",
    "ALLOCATE_RESOURCES": "Run the scheduling algorithm / reserve resources (Sections 23-25).",
    "EXECUTE_PRODUCTION": "Start/pause/resume/hold/complete a production run; post consumption.",
    "VIEW_PRODUCTION": "Read-only runs/orders.",
    # Quality
    "INSPECT_BATCH": "Full quality-inspection authoring/decisions.",
    "VIEW_QUALITY": "Read-only quality records.",
    "REPORT_QUALITY_DEFECT": "Report-only: submit a defect the reporter authored.",
    "CREATE_DEFECT": "Create defect records.",
    "CREATE_HOLD": "Create a quality hold with immediate effect.",
    "REQUEST_HOLD": "Request a quality hold (creates a PENDING suggestion only).",
    "RELEASE_HOLD": "Release/reject a quality hold (Section 26 approval).",
    "CREATE_NCR": "Create/manage NCR records.",
    # Maintenance
    "MANAGE_MAINTENANCE": "Full CRUD on maintenance records + machine return-to-service.",
    "VIEW_MAINTENANCE": "Read-only maintenance records.",
    "REPORT_MAINTENANCE": "Report-only: log a machine problem/downtime event.",
    # Incidents
    "MANAGE_INCIDENTS": "Full incident lifecycle management.",
    "REPORT_INCIDENTS": "Report-only: create incidents the reporter authored.",
    # Alerts / risk
    "MANAGE_ALERTS": "Acknowledge/resolve/dismiss/escalate alerts.",
    "VIEW_RISK": "Read-only risk scores.",
    # Traceability
    "VIEW_TRACEABILITY_ALL": "Full traceability explorer, all batches/runs.",
    "VIEW_TRACEABILITY_LIMITED": "Traceability limited to batches/runs the operator personally executed.",
    # Overrides
    "CREATE_OVERRIDE": "Request a conflict override (Section 27).",
    "APPROVE_OVERRIDE": "Approve a requested override.",
    # Audit log (Section 7 scope-qualified variants)
    "VIEW_AUDIT_LOG_ALL": "Full audit log, all entries.",
    "VIEW_AUDIT_LOG_LIMITED": "Audit entries scoped to the supervisor's assigned area.",
    "VIEW_AUDIT_LOG_OWN": "Audit entries authored by the requesting user only.",
    # System / reports
    "MANAGE_SYSTEM_SETTINGS": "Configure system thresholds and controlled settings.",
    "VIEW_REPORTS": "Run/view reports.",
    "ADMIN_SEARCH": "Use the cross-entity admin search.",
}

# --- Role -> permission-code grants (Section 6, Table 3, translated) -------
ROLE_PERMISSIONS = {
    "SYSTEM_ADMIN": list(PERMISSIONS.keys()),   # ✓ across the board
    "PRODUCTION_MANAGER": [
        "MANAGE_MACHINES", "MANAGE_MATERIALS", "MANAGE_SUPPLIERS", "MANAGE_PROCESSES", "VIEW_PROCESSES",
        "CREATE_ORDERS", "APPROVE_ORDERS", "VIEW_ORDERS", "ALLOCATE_RESOURCES", "EXECUTE_PRODUCTION",
        "VIEW_PRODUCTION", "VIEW_QUALITY", "CREATE_HOLD", "RELEASE_HOLD", "VIEW_MAINTENANCE",
        "MANAGE_INCIDENTS", "VIEW_TRACEABILITY_ALL", "CREATE_OVERRIDE", "APPROVE_OVERRIDE",
        "VIEW_AUDIT_LOG_ALL", "VIEW_REPORTS", "ADMIN_SEARCH", "MANAGE_ALERTS", "VIEW_RISK", "VIEW_MACHINES",
        "VIEW_MATERIALS",
    ],
    "SUPERVISOR": [
        "VIEW_MACHINES", "MANAGE_MATERIALS", "VIEW_MATERIALS", "VIEW_PROCESSES", "ALLOCATE_RESOURCES",
        "EXECUTE_PRODUCTION", "VIEW_PRODUCTION", "VIEW_ORDERS", "VIEW_QUALITY", "CREATE_HOLD",
        "VIEW_MAINTENANCE", "MANAGE_INCIDENTS", "VIEW_TRACEABILITY_ALL", "CREATE_OVERRIDE",
        "VIEW_AUDIT_LOG_LIMITED", "MANAGE_ALERTS", "VIEW_RISK", "ADMIN_SEARCH",
    ],
    "QA_QC_OFFICER": [
        "VIEW_MACHINES", "VIEW_MATERIALS", "VIEW_ORDERS", "VIEW_PRODUCTION", "INSPECT_BATCH", "VIEW_QUALITY",
        "CREATE_DEFECT", "CREATE_HOLD", "RELEASE_HOLD", "CREATE_NCR", "MANAGE_INCIDENTS",
        "VIEW_TRACEABILITY_ALL", "VIEW_AUDIT_LOG_LIMITED", "VIEW_RISK", "ADMIN_SEARCH",
    ],
    "MAINTENANCE_OFFICER": [
        "MANAGE_MACHINES", "VIEW_MATERIALS", "MANAGE_MAINTENANCE", "REPORT_MAINTENANCE",
        "REPORT_INCIDENTS", "VIEW_TRACEABILITY_LIMITED", "VIEW_AUDIT_LOG_LIMITED", "VIEW_RISK",
    ],
    "OPERATOR": [
        "VIEW_MACHINES", "VIEW_MATERIALS", "EXECUTE_PRODUCTION", "VIEW_PRODUCTION", "VIEW_ORDERS",
        "REPORT_QUALITY_DEFECT", "REQUEST_HOLD", "REPORT_MAINTENANCE", "REPORT_INCIDENTS",
        "VIEW_TRACEABILITY_LIMITED", "VIEW_AUDIT_LOG_OWN",
    ],
}
