# Self-diagnosis: "why isn't this working?" answered by the program itself.
#
# The failure mode this exists to kill: an install where one library is the wrong
# version or one stdlib module is missing, and the user sees a stack trace three
# screens deep in a job result. Every check here knows how to *fix* itself, and
# says so in a sentence a person can act on.
from __future__ import annotations

import os
import platform
import sys
import tempfile
from importlib import import_module
from pathlib import Path

Status = str  # "ok" | "warn" | "fail"


def _check(cid: str, label: str, status: Status, detail: str, fix: str | None = None) -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail, "fix": fix}


def _version(name: str) -> str | None:
    try:
        return getattr(import_module(name), "__version__", "unknown")
    except Exception:
        return None


def _tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in v.split(".")[:3]:
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _python() -> dict:
    v = sys.version_info
    if v < (3, 10):
        return _check("python", "Python version", "fail", f"Python {platform.python_version()}.",
                      "NeuroForge needs Python 3.10 or newer.")
    return _check("python", "Python version", "ok", f"Python {platform.python_version()}.")


def _sqlite() -> dict:
    from . import kvstore
    if kvstore.HAVE_SQLITE:
        return _check("sqlite", "Metadata store", "ok", "SQLite available — datasets persist normally.")
    return _check(
        "sqlite", "Metadata store", "warn",
        "Python's sqlite3 module is missing, so NeuroForge is using its JSON fallback. "
        "Everything works; it is just slower with thousands of datasets.",
        "Repair your Python install (Windows: Settings › Apps › Python › Modify › Repair). "
        "The compiled _sqlite3 extension is usually present and only the pure-Python "
        "wrapper package is missing.")


def _numpy_scipy() -> dict:
    npv, spv = _version("numpy"), _version("scipy")
    if not npv:
        return _check("numpy", "NumPy / SciPy", "fail", "NumPy is not installed.",
                      "pip install -r backend/requirements.txt")
    if not spv:
        return _check("numpy", "NumPy / SciPy", "fail", f"NumPy {npv} present, SciPy missing.",
                      "pip install -r backend/requirements.txt")
    # SciPy pins an upper bound on NumPy; crossing it does not fail at import but
    # produces wrong results or crashes deep inside a transform.
    if _tuple(npv) >= (2, 5):
        return _check("numpy", "NumPy / SciPy", "warn",
                      f"NumPy {npv} is newer than SciPy {spv} supports.",
                      'pip install "numpy<2.5"')
    return _check("numpy", "NumPy / SciPy", "ok", f"NumPy {npv}, SciPy {spv} — compatible.")


def _optional(name: str, label: str, why: str, install: str) -> dict:
    v = _version(name)
    if v:
        return _check(name, label, "ok", f"{label} {v} available.")
    return _check(name, label, "warn", f"Not installed — {why}", install)


def _data_dir(path: str) -> dict:
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=p, delete=True):
            pass
        free = None
        try:
            free = os.statvfs(p).f_bavail * os.statvfs(p).f_frsize  # POSIX
        except AttributeError:
            import shutil
            free = shutil.disk_usage(p).free
        gb = (free or 0) / 1e9
        if gb < 1.0:
            return _check("data_dir", "Data directory", "warn",
                          f"{p} is writable but only {gb:.1f} GB free.",
                          "Free some space — recordings and derivatives are stored here.")
        return _check("data_dir", "Data directory", "ok", f"{p} — writable, {gb:.0f} GB free.")
    except Exception as e:  # noqa: BLE001
        return _check("data_dir", "Data directory", "fail", f"{p} is not writable: {e}",
                      "Set NEUROFORGE_DATA_DIR to a directory you can write to.")


def _ui() -> dict:
    here = Path(__file__).resolve().parent.parent          # .../neuroforge
    for d in (here.parents[1] / "frontend" / "dist", here / "web"):   # same order as main.py
        if (d / "index.html").is_file():
            return _check("ui", "Bundled interface", "ok",
                          f"Built UI is being served from {d}.")
    return _check("ui", "Bundled interface", "warn",
                  "No built interface found, so this server only exposes the API.",
                  "cd frontend && npm install && npm run build")


def run(settings) -> dict:
    checks = [
        _python(),
        _numpy_scipy(),
        _check("mne", "MNE-Python", "ok" if _version("mne") else "fail",
               f"MNE {_version('mne')}." if _version("mne") else "MNE-Python is not installed.",
               None if _version("mne") else "pip install -r backend/requirements.txt"),
        _sqlite(),
        _data_dir(settings.data_dir),
        _optional("sklearn", "scikit-learn", "decoding and microstates are unavailable.",
                  "pip install scikit-learn"),
        _optional("pyxdf", "XDF reader", "Lab Streaming Layer .xdf files cannot be opened.",
                  "pip install pyxdf"),
        _optional("h5py", "HDF5 export", "the .h5 export format is unavailable.",
                  "pip install h5py"),
        _ui(),
    ]
    n_fail = sum(1 for c in checks if c["status"] == "fail")
    n_warn = sum(1 for c in checks if c["status"] == "warn")
    return {
        "status": "fail" if n_fail else "warn" if n_warn else "ok",
        "n_fail": n_fail, "n_warn": n_warn,
        "summary": ("Everything checks out." if not (n_fail or n_warn)
                    else f"{n_fail} problem(s) and {n_warn} advisory(ies)."
                    if n_fail else f"{n_warn} advisory(ies) — nothing is broken."),
        "checks": checks,
    }
