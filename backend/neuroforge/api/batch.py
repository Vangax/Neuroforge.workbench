# Cohort endpoints — analyse or clean many recordings in one job.
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..core import batch
from ..core.registry import registry
from ..core.jobs import jobs

router = APIRouter(prefix="/api/batch", tags=["batch"])


class BatchRequest(BaseModel):
    dataset_ids: list[str] = []
    #: None -> every recording gets its own recommended cleanup.
    steps: list[dict] | None = None


def _resolve(ids: list[str]):
    if not ids:
        raise HTTPException(400, "no datasets selected")
    out = []
    for did in ids:
        try:
            out.append(registry.get(did))
        except KeyError:
            raise HTTPException(404, f"Dataset {did} not found")
    return out


@router.get("/columns")
def columns():
    return {"columns": batch.COLUMNS}


@router.post("/analyze")
def analyze(req: BatchRequest):
    datasets = _resolve(req.dataset_ids)

    def task(progress=None):
        return batch.analyze_many(datasets, on_progress=progress)

    return {"job_id": jobs.submit("batch-analyze", task).id, "n": len(datasets)}


@router.post("/clean")
def clean(req: BatchRequest):
    datasets = _resolve(req.dataset_ids)

    def task(progress=None):
        out = batch.clean_many(datasets, req.steps, on_progress=progress)
        for nd in out.pop("derived"):        # persist derivatives, keep them out of JSON
            registry.add(nd)
        return out

    return {"job_id": jobs.submit("batch-clean", task).id, "n": len(datasets)}


class CsvRequest(BaseModel):
    rows: list[dict] = []


@router.post("/csv")
def csv(req: CsvRequest):
    """Turn a cohort table into CSV. Takes the rows back so what you export is
    exactly what you were looking at — filters, sorting and all."""
    return Response(
        content=batch.to_csv(req.rows).encode("utf-8"), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="neuroforge_cohort.csv"'},
    )
