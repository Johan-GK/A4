"""
Central, configurable settings.

Section 46/2.2 of the specification repeatedly insists that thresholds be
"configurable, not hard-coded" (password policy, lockout thresholds, alert
escalation timers, staleness windows, risk thresholds, retention periods).
This module is the single place those live, with environment-variable
overrides, and DbSetting rows (see models.SystemSetting) let an admin change
a subset of them at runtime from the System Configuration screen without a
redeploy.
"""
import os


class Settings:
    # --- Identity ---
    APP_NAME = "Production Control & Traceability System"
    APP_VERSION = "1.0.0 (spec v3.0 baseline)"

    # --- Auth / Security (Section 44) ---
    JWT_SECRET = os.environ.get("PCTS_JWT_SECRET", "dev-secret-change-me-in-production-1a2b3c")
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_MINUTES = int(os.environ.get("PCTS_ACCESS_TOKEN_MINUTES", "30"))       # 44.3
    REFRESH_TOKEN_HOURS = int(os.environ.get("PCTS_REFRESH_TOKEN_HOURS", "12"))         # 44.3 absolute max
    SESSION_IDLE_MINUTES = 30
    SESSION_ABSOLUTE_HOURS = 12

    PASSWORD_MIN_LENGTH = 10                        # 44.1
    LOCKOUT_MAX_ATTEMPTS = 5                         # 44.4
    LOCKOUT_WINDOW_MINUTES = 15                      # 44.4
    LOCKOUT_BASE_MINUTES = 15                        # base lockout, doubles each repeat (exp backoff)
    MFA_REQUIRED_ROLES = {"SYSTEM_ADMIN", "PRODUCTION_MANAGER"}   # 44.2

    # --- Scheduling / concurrency (Section 25.7) ---
    RETRY_BASE_MS = 50
    RETRY_MAX_MS = 2000
    RETRY_MAX_ATTEMPTS = 6

    # --- Live data freshness (Section 35.2) ---
    MACHINE_STALENESS_MINUTES = 60
    RUN_STALENESS_MINUTES = 480          # one shift boundary, default 8h

    # --- Alert escalation timers (Section 35.3), minutes ---
    ALERT_SLA_MINUTES = {"CRITICAL": 15, "HIGH": 60, "MEDIUM": 240, "LOW": 1440}

    # --- Risk engine (Section 36.1) ---
    RISK_THRESHOLDS = {"LOW": (0, 24), "MEDIUM": (25, 49), "HIGH": (50, 74), "CRITICAL": (75, 100)}

    # --- Audit / retention (Section 46) ---
    AUDIT_RETENTION_YEARS = 3

    # --- Background loop ---
    BACKGROUND_TICK_SECONDS = 20

    CORS_ORIGINS = ["*"]


settings = Settings()
