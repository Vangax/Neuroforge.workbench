# Durable storage: metadata rows via kvstore (SQLite, or JSON when SQLite is
# unavailable), raw data as FIF on disk. Datasets and their derivatives survive
# restarts. The registry writes through to this.
from __future__ import annotations

import os
import hashlib
import logging
from dataclasses import asdict
from pathlib import Path

from .neurodata import NeuroData, BidsEntities, ProvenanceStep
from . import kvstore

log = logging.getLogger("neuroforge.store")


class Store:
    def __init__(self, db_path: str, data_dir: str):
        self.db_path = db_path
        self.raw_dir = Path(data_dir) / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._table = kvstore.open_table(db_path, "datasets")
        self.backend = kvstore.backend_name()

    def save(self, nd: NeuroData) -> None:
        # Write the FIF once (path is stable per id), then upsert the row.
        fif = self.raw_dir / f"{nd.id}_raw.fif"
        if nd.fif_path != str(fif):
            nd.raw.save(str(fif), overwrite=True, verbose="ERROR")
            nd._fif_path = str(fif)

        e = nd.entities
        self._table.put(nd.id, {
            "id": nd.id,
            "label": e.label(),
            "subject": e.subject, "session": e.session, "task": e.task,
            "run": e.run, "datatype": e.datatype,
            "source_format": nd.source_format, "source_path": nd.source_path,
            "fif_path": nd.fif_path, "parent_id": nd.extra.get("parent"),
            "summary": nd._scalars(),
            "extra": nd.extra,
            "provenance": [asdict(p) for p in nd.provenance],
            "checksum": hashlib.sha256(nd.raw.get_data().tobytes()).hexdigest()[:16],
            "created_at": nd.created_at,
        })
        nd._raw = None  # data is safe on disk now; free RAM, reload lazily when needed

    def load_all(self) -> list[NeuroData]:
        out: list[NeuroData] = []
        for r in self._table.all():
            fif_path = r.get("fif_path")
            if not fif_path or not os.path.exists(fif_path):
                log.warning("dropping %s: FIF missing at %s", r.get("id"), fif_path)
                continue
            ent = BidsEntities(
                subject=r.get("subject") or "01", session=r.get("session"),
                task=r.get("task"), run=r.get("run"), datatype=r.get("datatype") or "eeg",
            )
            prov = [ProvenanceStep(**p) for p in (r.get("provenance") or [])]
            out.append(NeuroData(
                None, entities=ent, source_format=r.get("source_format") or "unknown",
                source_path=r.get("source_path"), extra=r.get("extra") or {},
                dataset_id=r["id"], fif_path=fif_path, summary=r.get("summary"),
                provenance=prov, created_at=r.get("created_at"),
            ))
        return out

    def delete(self, dataset_id: str) -> None:
        row = self._table.get(dataset_id)
        fif_path = (row or {}).get("fif_path")
        if fif_path and os.path.exists(fif_path):
            try:
                os.unlink(fif_path)
            except OSError:
                pass
        self._table.delete(dataset_id)

    def count(self) -> int:
        return self._table.count()
