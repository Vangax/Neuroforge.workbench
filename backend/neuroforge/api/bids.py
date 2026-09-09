# Folder import and BIDS export — a study in, a study out.
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import bids
from ..core.registry import registry
from ..core.jobs import jobs
from ..config import settings

router = APIRouter(prefix="/api/bids", tags=["bids"])


class ScanRequest(BaseModel):
    path: str


class ImportRequest(BaseModel):
    path: str
    #: Absolute paths from a previous scan; empty means "everything found".
    files: list[str] = []


class ExportRequest(BaseModel):
    dataset_ids: list[str] = []
    out_dir: str | None = None
    name: str = "NeuroForge export"
    derivative: bool = True


@router.post("/scan")
def scan(req: ScanRequest):
    """List the readable recordings under a folder without loading any of them."""
    try:
        found = bids.scan_folder(req.path)
    except NotADirectoryError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(403, f"cannot read {req.path}: {e}")
    subjects = sorted({c["subject"] for c in found})
    return {
        "root": req.path, "n_found": len(found), "candidates": found,
        "subjects": subjects, "n_subjects": len(subjects),
        "is_bids": _is_bids(req.path),
    }


def _is_bids(path: str) -> bool:
    try:
        return bids.is_bids_root(path)
    except Exception:  # noqa: BLE001 — a probe, never a failure
        return False


@router.post("/import")
def import_folder(req: ImportRequest):
    def task(progress=None):
        out = bids.import_folder(req.path, paths=req.files or None, on_progress=progress)
        loaded = out.pop("loaded")
        for nd in loaded:
            registry.add(nd)
        return {**out, "n_loaded": len(loaded),
                "datasets": [nd.metadata_dict() for nd in loaded]}

    return {"job_id": jobs.submit("bids-import", task).id}


@router.post("/export")
def export(req: ExportRequest):
    if not req.dataset_ids:
        raise HTTPException(400, "no datasets selected")
    datasets = []
    for did in req.dataset_ids:
        try:
            datasets.append(registry.get(did))
        except KeyError:
            raise HTTPException(404, f"Dataset {did} not found")

    out_dir = req.out_dir or str(Path(settings.data_dir) / "bids_export")

    def task(progress=None):
        if progress:
            progress(0, len(datasets), "writing BIDS tree")
        return bids.export_bids(datasets, out_dir, name=req.name,
                                derivative=req.derivative, version=settings.version)

    return {"job_id": jobs.submit("bids-export", task).id, "out_dir": out_dir}
