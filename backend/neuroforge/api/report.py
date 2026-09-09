"""Module 10 — reporting & export."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from ..core import report, repro
from ..core.registry import registry

router = APIRouter(prefix="/api/report", tags=["report"])


def _get(dataset_id: str):
    try:
        return registry.get(dataset_id)
    except KeyError:
        raise HTTPException(404, f"Dataset {dataset_id} not found")


@router.get("/formats")
def formats():
    return {"export_formats": [
        {"fmt": "fif", "label": "MNE-Python (.fif)"},
        {"fmt": "csv", "label": "CSV (channels × time)"},
        {"fmt": "npy", "label": "NumPy array (.npy)"},
        {"fmt": "hdf5", "label": "HDF5 (.h5)"},
        {"fmt": "edf", "label": "EDF (if backend available)"},
    ]}


@router.get("/{dataset_id}/html", response_class=HTMLResponse)
def html(dataset_id: str):
    return HTMLResponse(report.build_report(_get(dataset_id)))


@router.get("/{dataset_id}/script")
def script(dataset_id: str, download: bool = Query(False)):
    """The dataset's provenance rendered as a runnable MNE script."""
    nd = _get(dataset_id)
    name = f"reproduce_{nd.entities.label().replace('/', '_')}.py"
    code = repro.build_script(nd, filename=name)
    if not download:
        return {"filename": name, "code": code}
    return Response(content=code.encode("utf-8"), media_type="text/x-python",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/{dataset_id}/environment")
def environment(dataset_id: str):
    return {"environment": report.environment(), "repro_hash": report.repro_hash(_get(dataset_id))}


@router.get("/{dataset_id}/export")
def export(dataset_id: str, fmt: str = Query("fif")):
    nd = _get(dataset_id)
    try:
        data, filename, media = report.export_dataset(nd, fmt)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Export failed: {e}")
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
