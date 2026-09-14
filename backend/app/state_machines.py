"""
Explicit state-transition tables -- Sections 13, 17.1, 17.2, 20, 22, 32, 34.

"Any transition not listed is forbidden and must be rejected by the
transition endpoint (Section 45.3), regardless of who requests it."

Each table maps (from_state -> set of legal to_states). A dedicated
`validate_transition()` function is the single place every transition
endpoint in routers/*.py calls through, so the state machines are enforced
in exactly one place, per Section 45.1's requirement.
"""
from dataclasses import dataclass


class IllegalTransitionError(Exception):
    def __init__(self, entity: str, from_state: str, to_state: str):
        self.entity = entity
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Illegal transition for {entity}: {from_state} -> {to_state} is not permitted."
        )


@dataclass
class TransitionResult:
    ok: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Section 13 -- Machine State Machine
# ---------------------------------------------------------------------------
MACHINE_TRANSITIONS = {
    "AVAILABLE":      {"RESERVED", "OFFLINE", "DECOMMISSIONED", "FAULT", "MAINTENANCE"},
    "RESERVED":       {"RUNNING", "AVAILABLE", "FAULT"},
    "RUNNING":        {"PAUSED", "FAULT", "AVAILABLE", "RESERVED"},
    "PAUSED":         {"RUNNING", "FAULT"},
    "FAULT":          {"MAINTENANCE"},
    "MAINTENANCE":    {"AVAILABLE", "DECOMMISSIONED"},
    "OFFLINE":        {"AVAILABLE", "DECOMMISSIONED"},
    "DECOMMISSIONED": set(),   # terminal
}
MACHINE_TERMINAL = {"DECOMMISSIONED"}

# Explicitly forbidden, called out for emphasis in the spec even though the
# tables above already exclude them:
#   MAINTENANCE -> RUNNING directly, FAULT -> RUNNING directly,
#   DECOMMISSIONED -> anything, and any transition into RUNNING that
#   bypasses RESERVED (an AVAILABLE machine cannot jump straight to RUNNING).

# ---------------------------------------------------------------------------
# Section 17.1 -- Material Batch State Machine
# ---------------------------------------------------------------------------
MATERIAL_BATCH_TRANSITIONS = {
    "PENDING_INSPECTION": {"AVAILABLE", "REJECTED"},
    "AVAILABLE":          {"ON_HOLD", "DEPLETED", "EXPIRED"},
    "ON_HOLD":            {"AVAILABLE", "REJECTED"},
    "EXPIRED":            {"ON_HOLD"},
    "REJECTED":           set(),   # terminal
    "DEPLETED":           set(),   # terminal
}
MATERIAL_BATCH_TERMINAL = {"REJECTED", "DEPLETED"}

# ---------------------------------------------------------------------------
# Section 17.2 -- Product Batch quality disposition
# ---------------------------------------------------------------------------
PRODUCT_BATCH_TRANSITIONS = {
    "PENDING_INSPECTION": {"RELEASED", "REWORK_REQUIRED", "ON_HOLD", "SCRAPPED"},
    "REWORK_REQUIRED":    {"PENDING_INSPECTION"},
    "RELEASED":           {"ON_HOLD"},
    "ON_HOLD":            {"RELEASED", "SCRAPPED"},
    "SCRAPPED":           set(),   # terminal
}
PRODUCT_BATCH_TERMINAL = {"SCRAPPED"}

# ---------------------------------------------------------------------------
# Section 20 -- Production Order State Machine
# ---------------------------------------------------------------------------
ORDER_TRANSITIONS = {
    "DRAFT":     {"SUBMITTED", "CANCELLED"},
    "SUBMITTED": {"APPROVED", "DRAFT", "CANCELLED"},
    "APPROVED":  {"READY", "CANCELLED"},
    "READY":     {"RUNNING", "ON_HOLD", "CANCELLED"},
    "RUNNING":   {"ON_HOLD", "DELAYED", "COMPLETED"},
    "DELAYED":   {"RUNNING", "COMPLETED", "ON_HOLD"},
    "ON_HOLD":   {"RUNNING", "CANCELLED"},
    "COMPLETED": set(),   # terminal
    "CANCELLED": set(),   # terminal
}
ORDER_TERMINAL = {"COMPLETED", "CANCELLED"}

# ---------------------------------------------------------------------------
# Section 22.1 -- Production Run State Machine
# ---------------------------------------------------------------------------
RUN_TRANSITIONS = {
    "SCHEDULED": {"RUNNING", "CANCELLED"},
    "RUNNING": {
        "PAUSED", "ON_HOLD", "MATERIAL_SUBSTITUTION_PENDING",
        "PARTIALLY_COMPLETED", "SCRAP_REWORK_REVIEW", "COMPLETED",
    },
    "PAUSED": {"RUNNING", "ON_HOLD"},
    "ON_HOLD": {"RUNNING", "CANCELLED"},
    "MATERIAL_SUBSTITUTION_PENDING": {"RUNNING", "ON_HOLD"},
    "PARTIALLY_COMPLETED": {"RUNNING", "COMPLETED"},
    "SCRAP_REWORK_REVIEW": {"RUNNING", "COMPLETED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}
RUN_TERMINAL = {"COMPLETED", "CANCELLED"}

# ---------------------------------------------------------------------------
# Section 32 -- Incident State Machine
# ---------------------------------------------------------------------------
INCIDENT_TRANSITIONS = {
    "OPEN":                {"UNDER_INVESTIGATION", "CLOSED"},
    "UNDER_INVESTIGATION":  {"ACTION_REQUIRED", "CLOSED"},
    "ACTION_REQUIRED":      {"CORRECTIVE_ACTION"},
    "CORRECTIVE_ACTION":    {"VERIFICATION"},
    "VERIFICATION":         {"CLOSED", "UNDER_INVESTIGATION"},
    "CLOSED":               {"REOPENED"},
    "REOPENED":             {"UNDER_INVESTIGATION"},
}
INCIDENT_TERMINAL = set()   # CLOSED is not fully terminal (REOPENED path)

# ---------------------------------------------------------------------------
# Section 34 -- Alert State Machine
# ---------------------------------------------------------------------------
ALERT_TRANSITIONS = {
    "NEW":          {"ACKNOWLEDGED", "DISMISSED"},
    "ACKNOWLEDGED": {"IN_PROGRESS", "DISMISSED"},
    "IN_PROGRESS":  {"RESOLVED", "DISMISSED"},
    "RESOLVED":     set(),
    "DISMISSED":    set(),
}
ALERT_TERMINAL = {"RESOLVED", "DISMISSED"}


REGISTRY = {
    "MACHINE": MACHINE_TRANSITIONS,
    "MATERIAL_BATCH": MATERIAL_BATCH_TRANSITIONS,
    "PRODUCT_BATCH": PRODUCT_BATCH_TRANSITIONS,
    "PRODUCTION_ORDER": ORDER_TRANSITIONS,
    "PRODUCTION_RUN": RUN_TRANSITIONS,
    "INCIDENT": INCIDENT_TRANSITIONS,
    "ALERT": ALERT_TRANSITIONS,
}

TERMINALS = {
    "MACHINE": MACHINE_TERMINAL,
    "MATERIAL_BATCH": MATERIAL_BATCH_TERMINAL,
    "PRODUCT_BATCH": PRODUCT_BATCH_TERMINAL,
    "PRODUCTION_ORDER": ORDER_TERMINAL,
    "PRODUCTION_RUN": RUN_TERMINAL,
    "INCIDENT": INCIDENT_TERMINAL,
    "ALERT": ALERT_TERMINAL,
}


def validate_transition(entity: str, from_state: str, to_state: str) -> None:
    """Raises IllegalTransitionError if the transition is not in the table.
    A terminal state is never overwritten directly (Business Rule, Section
    52): trying to leave a terminal state (other than CLOSED's REOPENED
    path, which is itself listed explicitly above) always fails here."""
    table = REGISTRY.get(entity)
    if table is None:
        raise ValueError(f"Unknown state-machine entity: {entity}")
    legal_targets = table.get(from_state, set())
    if to_state not in legal_targets:
        raise IllegalTransitionError(entity, from_state, to_state)
