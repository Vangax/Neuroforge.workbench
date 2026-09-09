# Module 11: user scripting. Save/run custom Python against a dataset. Execution
# is delegated to _script_runner in a separate process with a parent-side timeout.
from __future__ import annotations

import os
import sys
import json
import time
import uuid
import tempfile
import subprocess
from pathlib import Path

from .neurodata import NeuroData
from . import kvstore
from ..config import settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # dir containing the `neuroforge` package


class ScriptStore:
    def __init__(self, db_path: str):
        self._table = kvstore.open_table(db_path, "scripts")

    def save(self, name: str, description: str, code: str, author: str = "local",
             script_id: str | None = None) -> dict:
        sid = script_id or uuid.uuid4().hex[:12]
        existing = self._table.get(sid)
        created = existing["created_at"] if existing else time.time()
        self._table.put(sid, {"id": sid, "name": name, "description": description,
                              "code": code, "author": author, "created_at": created})
        return self.get(sid)

    def get(self, script_id: str) -> dict | None:
        return self._table.get(script_id)

    def list(self) -> list[dict]:
        rows = sorted(self._table.all(), key=lambda r: r.get("created_at") or 0.0, reverse=True)
        return [{k: r.get(k) for k in ("id", "name", "description", "author", "created_at")}
                for r in rows]

    def delete(self, script_id: str) -> None:
        self._table.delete(script_id)


def _spawn(job: dict) -> dict:
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    out.close()
    job["out"] = out.name
    job["mem_mb"] = settings.script_mem_mb
    t0 = time.perf_counter()
    try:
        # -E -s: ignore env vars + user site (mild hygiene) but keep cwd on sys.path
        # so `-m neuroforge...` resolves. Real isolation = the separate process,
        # the timeout, and the POSIX memory cap in the runner.
        proc = subprocess.run(
            [sys.executable, "-E", "-s", "-m", "neuroforge.core._script_runner"],
            input=json.dumps(job).encode(),
            capture_output=True, timeout=settings.script_timeout_s, cwd=str(_BACKEND_ROOT),
        )
        stdout = proc.stdout.decode("utf-8", "replace")[-8000:]
        with open(out.name, encoding="utf-8") as f:
            payload = json.load(f)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_type": "user",
                "error": f"script exceeded the {settings.script_timeout_s}s limit",
                "stdout": "", "duration": float(settings.script_timeout_s)}
    except Exception as e:  # noqa: BLE001 — spawn/parse failure is our problem
        return {"ok": False, "error_type": "system", "error": str(e),
                "stdout": "", "duration": round(time.perf_counter() - t0, 2)}
    finally:
        try:
            os.unlink(out.name)
        except OSError:
            pass
    payload["stdout"] = stdout
    payload["duration"] = round(time.perf_counter() - t0, 2)
    return payload


def _disabled() -> dict:
    return {"ok": False, "error_type": "system", "error": "scripting is disabled (NEUROFORGE_SCRIPTS=0)"}


def run_script(nd: NeuroData, code: str, params: dict | None = None) -> dict:
    if not settings.scripts_enabled:
        return _disabled()
    if not nd.fif_path:
        return {"ok": False, "error_type": "system", "error": "dataset is not persisted"}
    return _spawn({"fif": nd.fif_path, "id": nd.id, "label": nd.entities.label(),
                   "params": params or {}, "code": code})


def run_group(nds: list[NeuroData], code: str, params: dict | None = None) -> dict:
    # one process sees every selected dataset at once: `raws`, `datasets`
    if not settings.scripts_enabled:
        return _disabled()
    fifs = [{"fif": nd.fif_path, "id": nd.id, "label": nd.entities.label()} for nd in nds if nd.fif_path]
    if not fifs:
        return {"ok": False, "error_type": "system", "error": "no persisted datasets selected"}
    return _spawn({"fifs": fifs, "params": params or {}, "code": code})


def run_batch(nds: list[NeuroData], code: str, params: dict | None = None) -> dict:
    # run the same code once per dataset, each in its own subprocess (memory freed
    # between datasets). Good for "run this on everyone".
    runs = []
    for nd in nds:
        p = run_script(nd, code, params)
        runs.append({"dataset_id": nd.id, "label": nd.entities.label(),
                     "ok": p.get("ok"), "error_type": p.get("error_type"), "error": p.get("error"),
                     "result": p.get("result"), "figures": p.get("figures"), "duration": p.get("duration")})
    return {"mode": "each", "runs": runs, "n": len(runs),
            "ok": bool(runs) and all(r["ok"] for r in runs)}


EXAMPLES = [
    {
        "name": "Band power per channel",
        "code": (
            "# `raw` is an MNE Raw; set `result` (JSON-serialisable) or define run(raw, params).\n"
            "psd = raw.compute_psd(method='welch', fmin=1, fmax=40, verbose='ERROR')\n"
            "p, f = psd.get_data(return_freqs=True)\n"
            "import numpy as np\n"
            "alpha = p[:, (f>=8)&(f<=13)].mean(axis=1)\n"
            "result = {'channels': raw.ch_names, 'alpha_power': alpha.tolist()}\n"
        ),
    },
    {
        "name": "Custom band-pass + RMS",
        "code": (
            "lo = params.get('l_freq', 4)\n"
            "hi = params.get('h_freq', 8)\n"
            "flt = raw.copy().filter(lo, hi, verbose='ERROR')\n"
            "import numpy as np\n"
            "rms = np.sqrt((flt.get_data()**2).mean(axis=1)) * 1e6\n"
            "result = {'band': [lo, hi], 'rms_uv': dict(zip(raw.ch_names, rms.round(2).tolist()))}\n"
        ),
    },
    {
        "name": "Plot a channel spectrum (figure is captured)",
        "code": (
            "ch = params.get('channel', raw.ch_names[0])\n"
            "psd = raw.compute_psd(method='welch', fmin=1, fmax=45, picks=[ch], verbose='ERROR')\n"
            "fig = psd.plot(show=False)\n"
            "result = {'channel': ch, 'note': 'figure returned below'}\n"
        ),
    },
]
