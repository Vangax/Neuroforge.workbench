# Dataset index. In-memory map of NeuroData, write-through to a Store so it
# survives restarts. Attach a store at startup and it rehydrates from disk.
from __future__ import annotations

import logging
from threading import RLock

from .neurodata import NeuroData
from .store import Store

log = logging.getLogger("neuroforge.registry")


class Registry:
    def __init__(self) -> None:
        self._items: dict[str, NeuroData] = {}
        self._lock = RLock()
        self._store: Store | None = None

    def attach(self, store: Store) -> None:
        self._store = store
        for nd in store.load_all():
            self._items[nd.id] = nd
        log.info("registry: rehydrated %d dataset(s) | storage=%s",
                 len(self._items), getattr(store, "backend", "?"))

    @property
    def storage_backend(self) -> str:
        return getattr(self._store, "backend", "none")

    def add(self, nd: NeuroData) -> NeuroData:
        with self._lock:
            self._items[nd.id] = nd
        if self._store is not None:
            self._store.save(nd)
        return nd

    def get(self, dataset_id: str) -> NeuroData:
        nd = self._items.get(dataset_id)
        if nd is None:
            raise KeyError(dataset_id)
        return nd

    def remove(self, dataset_id: str) -> None:
        with self._lock:
            self._items.pop(dataset_id, None)
        if self._store is not None:
            self._store.delete(dataset_id)

    def all(self) -> list[NeuroData]:
        return list(self._items.values())

    def tree(self) -> dict:
        # subject -> session -> [datasets] for the repository panel
        out: dict[str, dict] = {}
        for nd in self._items.values():
            e = nd.entities
            sub = out.setdefault(f"sub-{e.subject}", {"subject": e.subject, "sessions": {}})
            ses_key = f"ses-{e.session}" if e.session else "ses-none"
            ses = sub["sessions"].setdefault(ses_key, {"session": e.session, "datasets": []})
            ses["datasets"].append({
                "id": nd.id, "label": e.label(), "task": e.task, "run": e.run,
                "n_channels": nd.n_channels, "duration": round(nd.duration, 1),
                "sfreq": nd.sfreq, "source_format": nd.source_format,
            })
        return out


registry = Registry()
