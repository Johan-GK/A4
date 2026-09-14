# PCTS — Production Control and Traceability System

A complete, working reference implementation of the Production Control and
Traceability System Development Specification (v3): production order
scheduling with conflict-free resource admission control, multi-batch
FEFO/FIFO material traceability, RBAC, a risk engine, an append-only
hash-chained audit log, alert escalation, and more.

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, SQLite (file-based, zero
  setup — no external database server required).
- **Frontend**: Plain HTML/CSS/JavaScript single-page app, no build step,
  served directly by the backend at `http://127.0.0.1:8000`.

## Quick start

### Option A — one command

**macOS / Linux**
```bash
./start.sh
```

**Windows**
```bat
start.bat
```

This creates a virtual environment, installs dependencies, seeds a demo
dataset on first run, and starts the server at `http://127.0.0.1:8000`.
Open that URL in your browser.

### Option B — Visual Studio Code (recommended for exploring/debugging the code)

1. Open this folder (`pcts/`) in VS Code — **File → Open Folder…**
2. Install the recommended extensions when prompted (Python + Python
   Debugger), or install them manually from the Extensions panel.
3. Open a terminal in VS Code (`` Ctrl+` ``) and create the virtual
   environment once:
   ```bash
   cd backend
   python -m venv .venv
   # Windows: .venv\Scripts\activate
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. Press **F5** (or go to Run & Debug → "PCTS: Run Backend (FastAPI/Uvicorn)"
   → Start). This is preconfigured in `.vscode/launch.json` and lets you set
   breakpoints anywhere in `backend/app/`.
5. Open `http://127.0.0.1:8000` in your browser.

### Option C — manual

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Demo accounts

A demo dataset (orders, machines, materials, batches, an incident, alerts,
etc.) is seeded automatically the first time the server starts, as long as
`backend/data/pcts.db` does not already exist. All accounts share the same
password.

| Username      | Role                | Password       |
|---------------|---------------------|----------------|
| `admin`       | System Admin        | `Trenser@2026` |
| `pmanager`    | Production Manager  | `Trenser@2026` |
| `supervisor`  | Supervisor          | `Trenser@2026` |
| `qaofficer`   | QA / QC Officer     | `Trenser@2026` |
| `maintenance` | Maintenance Officer | `Trenser@2026` |
| `operator1`   | Operator            | `Trenser@2026` |
| `operator2`   | Operator            | `Trenser@2026` |

`admin` and `pmanager` are configured to require MFA per the spec's
sensitive-role policy. On first login for those accounts, the login screen
will walk you through TOTP setup (scan the QR code with any authenticator
app, e.g. Google Authenticator).

To reset all demo data, stop the server and delete `backend/data/pcts.db`
(plus the `-wal`/`-shm` files if present) — it will reseed on next start.

## What's implemented

The backend implements the specification's core logical design end to end,
not just a UI mockup:

- **Entities & state machines** — every lifecycle-bearing entity (machines,
  material batches, product batches, production orders, production runs,
  incidents, alerts) moves only through explicit, validated
  from→to transitions — never a raw status edit.
- **Conflict-free scheduling** — a priority-ordered admission controller
  with deterministic resource-lock ordering prevents double-booking a
  machine, operator, or material batch, and returns alternative
  machines/slots on conflict.
- **Multi-batch material allocation** — FEFO/FIFO allocation can split a
  single requirement across several batches automatically.
- **RBAC** — 6 roles mapped to ~35 granular permissions, enforced on every
  API endpoint.
- **Risk engine** — configurable per-category risk scoring with automatic
  run hold on critical machine-fault/quality/deadline-miss combinations.
- **Traceability** — full forward/backward genealogy across runs, batches,
  and orders for recall scenarios.
- **Audit log** — append-only, SHA-256 hash-chained, with an integrity
  verification endpoint (no update/delete code path exists anywhere for it).
- **Alert escalation & live-data staleness** — background jobs enforce
  per-severity SLA escalation and flag stale machine/run heartbeats.

## Project layout

```
pcts/
├── start.sh / start.bat      One-command launchers
├── .vscode/                  VS Code run/debug configuration
├── backend/
│   ├── app/
│   │   ├── main.py           App wiring, static frontend mount
│   │   ├── models.py         SQLAlchemy entities (Section 8)
│   │   ├── state_machines.py Transition tables & validation
│   │   ├── scheduling.py     Admission control & material allocation
│   │   ├── risk_engine.py    Risk scoring (Section 36)
│   │   ├── audit.py          Hash-chained audit log (Section 38)
│   │   ├── permissions.py    RBAC roles & permission matrix
│   │   ├── background.py     Staleness / escalation / risk background loop
│   │   ├── seed.py           Demo data seeding
│   │   └── routers/          One router per functional area
│   ├── data/                 SQLite database (created on first run)
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── css/style.css
    └── js/                   api.js, utils.js, app.js, views_*.js
```

## Notes

- The database is SQLite by default (zero configuration). To point at a
  different database (e.g. PostgreSQL) for a non-demo deployment, set the
  `PCTS_DATABASE_URL` environment variable before starting — see
  `backend/.env.example`.
- This is a hackathon/demo-grade reference implementation of the spec's
  logic, built for demonstration and evaluation rather than hardened for
  production traffic (e.g., the scheduler's admission control is
  in-process and single-instance).
