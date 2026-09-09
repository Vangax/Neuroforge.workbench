# Sample data: one click from "empty app" to a real recording to analyze.
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import samples
from ..core.registry import registry
from ..core.jobs import jobs

router = APIRouter(prefix="/api/samples", tags=["samples"])


@router.get("")
def list_samples():
    return {"samples": samples.catalog()}


@router.post("/{sample_id}/load")
def load_sample(sample_id: str):
    """Synthetic samples load immediately; downloads run as a job."""
    known = {s["id"]: s for s in samples.catalog()}
    if sample_id not in known:
        raise HTTPException(404, f"unknown sample '{sample_id}'")

    if known[sample_id]["kind"] == "download":
        def task():
            nd = samples.build(sample_id)
            registry.add(nd)
            return nd.metadata_dict()
        return {"job_id": jobs.submit("sample-download", task).id}

    try:
        nd = samples.build(sample_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"could not build sample: {e}")
    registry.add(nd)
    return {"dataset": nd.metadata_dict()}
