"""
Production Control and Traceability System -- FastAPI application entry
point.

Implements the Administration & Management Module described in the
specification (v3.0): Sections 1-53. See README.md at the repository root
for how each section maps to a module in this codebase.
"""
import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
from .background import background_loop
from .routers import (
    auth, users, machines, materials, processes, orders, runs, quality,
    incidents, alerts, overrides, traceability, audit_logs, reports,
    notifications, search, dashboard, settings_router, risk,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

for router in (
    auth.router, users.router, machines.router, materials.router, processes.router,
    orders.router, runs.router, quality.router, incidents.router, alerts.router,
    overrides.router, traceability.router, audit_logs.router, reports.router,
    notifications.router, search.router, dashboard.router, settings_router.router,
    risk.router,
):
    app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.on_event("startup")
async def on_startup():
    from .seed import seed_if_empty
    seed_if_empty()
    asyncio.create_task(background_loop())


# --- Serve the frontend SPA -------------------------------------------------
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend")

if os.path.isdir(FRONTEND_DIR):
    # Mounted at "/" so the frontend's relative asset paths (css/style.css,
    # js/app.js) resolve correctly; registered last so it only catches
    # requests that don't match an API route registered above.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
