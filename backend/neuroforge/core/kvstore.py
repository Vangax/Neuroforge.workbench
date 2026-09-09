# Tiny id -> row store. Uses SQLite when the stdlib module is importable and
# transparently falls back to a JSON file when it isn't.
#
# Why: some Python builds ship without the `sqlite3` package (minimal installs,
# trimmed distributions, a deleted Lib/sqlite3). NeuroForge must still start —
# losing persistence is acceptable, failing to launch is not.
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

try:
    import sqlite3
except Exception:                       # pragma: no cover - depends on the interpreter
    sqlite3 = None

HAVE_SQLITE = sqlite3 is not None


class Table:
    def put(self, row_id: str, row: dict) -> None:
        raise NotImplementedError

    def get(self, row_id: str) -> dict | None:
        raise NotImplementedError

    def all(self) -> list[dict]:
        raise NotImplementedError

    def delete(self, row_id: str) -> None:
        raise NotImplementedError

    def count(self) -> int:
        return len(self.all())


class _SqliteTable(Table):
    def __init__(self, db_path: str, name: str):
        self._name = name
        self._lock = threading.RLock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute(
            f"CREATE TABLE IF NOT EXISTS {name} "
            "(id TEXT PRIMARY KEY, created_at REAL, body TEXT)"
        )
        self._db.commit()

    def put(self, row_id: str, row: dict) -> None:
        with self._lock:
            self._db.execute(
                f"INSERT OR REPLACE INTO {self._name} VALUES (?,?,?)",
                (row_id, float(row.get("created_at") or 0.0), json.dumps(row)),
            )
            self._db.commit()

    def get(self, row_id: str) -> dict | None:
        r = self._db.execute(f"SELECT body FROM {self._name} WHERE id=?", (row_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def all(self) -> list[dict]:
        cur = self._db.execute(f"SELECT body FROM {self._name} ORDER BY created_at")
        return [json.loads(b) for (b,) in cur]

    def delete(self, row_id: str) -> None:
        with self._lock:
            self._db.execute(f"DELETE FROM {self._name} WHERE id=?", (row_id,))
            self._db.commit()


class _JsonTable(Table):
    def __init__(self, db_path: str, name: str):
        self._path = Path(f"{db_path}.{name}.json")
        self._lock = threading.RLock()
        self._rows: dict[str, dict] = {}
        if self._path.exists():
            try:
                self._rows = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._rows = {}          # corrupt file: start clean rather than crash

    def _flush(self) -> None:
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(self._rows), encoding="utf-8")
        os.replace(tmp, self._path)      # atomic on Windows and POSIX

    def put(self, row_id: str, row: dict) -> None:
        with self._lock:
            self._rows[row_id] = row
            self._flush()

    def get(self, row_id: str) -> dict | None:
        return self._rows.get(row_id)

    def all(self) -> list[dict]:
        return sorted(self._rows.values(), key=lambda r: r.get("created_at") or 0.0)

    def delete(self, row_id: str) -> None:
        with self._lock:
            self._rows.pop(row_id, None)
            self._flush()


def open_table(db_path: str, name: str) -> Table:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return _SqliteTable(db_path, name) if HAVE_SQLITE else _JsonTable(db_path, name)


def backend_name() -> str:
    return "sqlite" if HAVE_SQLITE else "json-fallback"
