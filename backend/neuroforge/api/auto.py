# Auto-Analysis: one call that answers "what is this recording and is it usable?"
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import autoanalysis
from ..core.registry import registry
from ..core.jobs import jobs

router = APIRouter(prefix="/api/auto", tags=["auto"])


def _get(dataset_id: str):
    try:
        return registry.get(dataset_id)
    except KeyError:
        raise HTTPException(404, f"Dataset {dataset_id} not found")


@router.post("/{dataset_id}/analyze")
def analyze(dataset_id: str):
    """Submit the full battery; poll /api/jobs/{id} for the report."""
    nd = _get(dataset_id)
    job = jobs.submit("auto-analysis", lambda: autoanalysis.analyze(nd))
    return {"job_id": job.id}
