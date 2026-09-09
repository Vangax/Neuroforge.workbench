# FastAPI app: wiring, middleware, RBAC, lifespan. Heavy ops run via the job queue.
from __future__ import annotations

import time
import uuid
import logging
import platform
from pathlib import Path
from contextlib import asynccontextmanager

import numpy as np
import mne
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .core import loaders, doctor
from .core.registry import registry
from .core.store import Store
from .core.jobs import jobs
from .core.security import auth, require
from .api import (
    datasets, signal, spectral, preprocess, erp, analyze,
    mapper, benchmark, bci, edit, report, jobs as jobs_api, scripts as scripts_api,
    auto as auto_api, samples as samples_api, batch as batch_api, bids as bids_api,
)
from .models.schemas import HealthResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("neuroforge")


def _seed() -> None:
    # Three deliberately different recordings so the app has something to show
    # (and Auto-Analysis has something to distinguish). Only runs on a fresh store.
    for s in (
        dict(subject="01", session="01", task="restEC", paradigm="resting_closed", seed=11),
        dict(subject="01", session="02", task="oddball", paradigm="oddball", seed=12),
        dict(subject="02", session="01", task="noisy", paradigm="artifact_heavy", seed=21),
    ):
        registry.add(loaders.make_synthetic(
            subject=s["subject"], session=s["session"], task=s["task"],
            seed=s["seed"], paradigm=s["paradigm"], n_seconds=60.0, sfreq=256.0,
        ))


@asynccontextmanager
async def lifespan(app: FastAPI):
    mne.set_log_level("ERROR")
    registry.attach(Store(settings.db_path, settings.data_dir))
    if settings.seed_synthetic and not registry.all():
        _seed()
    # Say what is wrong at startup, in the terminal, before the user hits it in the
    # middle of an analysis. Advisories are listed once; failures are shouted about.
    diag = doctor.run(settings)
    for c in diag["checks"]:
        if c["status"] == "fail":
            log.error("SETUP | %s: %s%s", c["label"], c["detail"],
                      f"  FIX: {c['fix']}" if c["fix"] else "")
        elif c["status"] == "warn":
            log.warning("setup | %s: %s%s", c["label"], c["detail"],
                        f"  fix: {c['fix']}" if c["fix"] else "")
    log.info("ready | datasets=%d | auth=%s | data=%s | setup=%s",
             len(registry.all()), "on" if auth.enabled else "off", settings.data_dir,
             diag["summary"])
    yield


app = FastAPI(
    title=f"{settings.app_name} API",
    version=settings.version,
    description="Universal brain-data platform — BIDS-native, reproducible.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def access_log(request: Request, call_next):
    rid = uuid.uuid4().hex[:8]
    request.state.rid = rid
    t0 = time.perf_counter()
    response = await call_next(request)
    dt = (time.perf_counter() - t0) * 1000
    response.headers["X-Request-ID"] = rid
    log.info("rid=%s %s %s -> %s %.0fms", rid, request.method, request.url.path,
             response.status_code, dt)
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    rid = getattr(request.state, "rid", "?")
    log.exception("rid=%s unhandled", rid)
    return JSONResponse(
        status_code=500,
        content={"error": {"type": type(exc).__name__, "detail": str(exc), "request_id": rid}},
    )


# RBAC: reads need viewer; compute/edit need analyst. No-op when auth is disabled.
_read = [Depends(require("viewer"))]
_write = [Depends(require("analyst"))]
app.include_router(datasets.router, dependencies=_read)
app.include_router(signal.router, dependencies=_read)
app.include_router(spectral.router, dependencies=_read)
app.include_router(erp.router, dependencies=_read)
app.include_router(analyze.router, dependencies=_read)
app.include_router(mapper.router, dependencies=_read)
app.include_router(report.router, dependencies=_read)
app.include_router(jobs_api.router, dependencies=_read)
app.include_router(auto_api.router, dependencies=_read)      # Auto-Analysis Engine
app.include_router(samples_api.router, dependencies=_read)   # one-click sample data
app.include_router(preprocess.router, dependencies=_write)
app.include_router(batch_api.router, dependencies=_write)     # cohort analyse/clean
app.include_router(bids_api.router, dependencies=_write)      # folder import, BIDS export
app.include_router(benchmark.router, dependencies=_write)
app.include_router(bci.router, dependencies=_write)
app.include_router(edit.router, dependencies=_write)
app.include_router(scripts_api.router, dependencies=_write)   # M11 — runs user code


@app.get("/api/health", response_model=HealthResponse, tags=["meta"])
def health():
    return HealthResponse(
        app=settings.app_name, version=settings.version,
        mne=mne.__version__, numpy=np.__version__, n_datasets=len(registry.all()),
    )


@app.get("/api/system", tags=["meta"])
def system():
    return {
        "app": settings.app_name, "version": settings.version,
        "python": platform.python_version(), "platform": platform.platform(),
        "mne": mne.__version__, "numpy": np.__version__,
        "datasets": len(registry.all()), "data_dir": settings.data_dir,
        "auth_enabled": auth.enabled, "scripts_enabled": settings.scripts_enabled,
        "storage": registry.storage_backend,
        "jobs": jobs.stats(),
    }


@app.get("/api/doctor", tags=["meta"])
def doctor_check():
    """Self-diagnosis — what is wrong with this install and how to fix it."""
    return doctor.run(settings)


@app.get("/api", tags=["meta"])
def api_info():
    return {"app": settings.app_name, "version": settings.version,
            "docs": "/docs", "health": "/api/health"}


# Serve the built UI from the same process/port when it exists, so the whole app
# is one command and one URL. Mounted last so /api/* keeps priority.
#
# Two places to look: `neuroforge/web/` is where the release build lands inside an
# installed wheel; `frontend/dist` is where it sits in a source checkout. Checking
# both means `pip install neuroforge` and `git clone` behave identically.
_HERE = Path(__file__).resolve().parent
_UI_CANDIDATES = [_HERE / "web", _HERE.parents[1] / "frontend" / "dist"]
_UI_DIR = next((p for p in _UI_CANDIDATES if (p / "index.html").is_file()), _UI_CANDIDATES[0])
if _UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
    log.info("serving UI from %s", _UI_DIR)
else:
    @app.get("/", tags=["meta"])
    def root():
        return {"app": settings.app_name, "version": settings.version,
                "docs": "/docs", "health": "/api/health",
                "ui": "not built — run `npm install && npm run build` in frontend/, "
                      "or `npm run dev` for the dev server on :5173"}
