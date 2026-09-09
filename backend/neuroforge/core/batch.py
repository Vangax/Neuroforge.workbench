# Cohort operations — the same thing, to all of them, at once.
#
# Nobody works with one recording. Everything else in NeuroForge acts on a single
# dataset; this is where a study gets treated as a study: analyse forty runs, clean
# them with one pipeline, and get one table you can sort, compare and export.
from __future__ import annotations

import logging
from typing import Callable

import numpy as np

from . import autoanalysis, pipeline
from .neurodata import NeuroData

log = logging.getLogger("neuroforge.batch")

Progress = Callable[[int, int, str], None] | None


def _safe(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except Exception as e:  # noqa: BLE001 — one bad run must not lose the other 39
        return None, str(e)


def _row(nd: NeuroData, report: dict) -> dict:
    """One line of the cohort table — the numbers you actually compare across runs."""
    checks = {c["id"]: c for c in report["health"]["checks"]}

    def val(cid):
        v = checks.get(cid, {}).get("value")
        return v if isinstance(v, (int, float)) else None

    ev = report["dataset"]
    findings = report.get("findings", [])
    alpha = next((f for f in findings if "alpha" in f["title"].lower()
                  and "fade" not in f["title"].lower()), None)
    p300 = next((f for f in findings if "P300" in f["title"]), None)

    return {
        "dataset_id": nd.id,
        "label": nd.entities.label(),
        "subject": nd.entities.subject,
        "session": nd.entities.session,
        "task": nd.entities.task,
        "run": nd.entities.run,
        "recording_type": report["recording_type"]["label"],
        "type_code": report["recording_type"]["code"],
        "type_confidence": report["recording_type"]["confidence"],
        "health": report["health"]["score"],
        "grade": report["health"]["grade"],
        "n_fail": report["health"].get("n_fail", 0),
        "n_warn": report["health"].get("n_warn", 0),
        "n_channels": ev["n_channels"],
        "duration_s": ev["duration_s"],
        "sfreq": ev["sfreq"],
        "n_events": ev["n_events"],
        "bad_channels": val("bad_channels"),
        "line_noise_db": val("line_noise"),
        "drift_uv": val("drift"),
        "muscle_pct": val("muscle"),
        "blinks_per_min": val("blinks"),
        "alpha_peak_hz": report["recording_type"].get("alpha_peak_hz"),
        "alpha_finding": alpha["title"] if alpha else None,
        "p300_finding": p300["title"] if p300 else None,
    }


def analyze_many(datasets: list[NeuroData], on_progress: Progress = None) -> dict:
    """Run the full auto-analysis on every dataset and build a comparable table."""
    rows: list[dict] = []
    failed: list[dict] = []
    for i, nd in enumerate(datasets):
        if on_progress:
            on_progress(i, len(datasets), nd.entities.label())
        report, err = _safe(autoanalysis.analyze, nd)
        if err or not report or report.get("error"):
            failed.append({"dataset_id": nd.id, "label": nd.entities.label(),
                           "error": err or report.get("error", "unknown")})
            continue
        rows.append(_row(nd, report))
    return {"rows": rows, "failed": failed, "summary": summarize(rows),
            "columns": COLUMNS}


def clean_many(datasets: list[NeuroData], steps: list[dict] | None,
               on_progress: Progress = None) -> dict:
    """Apply one pipeline to a whole cohort, then re-score every recording.

    With `steps=None` each recording gets *its own* recommended cleanup — which is
    usually what you want, because a study is rarely broken in the same way twice.
    The uniform pipeline is there for when a reviewer will ask you to prove every
    subject was treated identically.
    """
    results: list[dict] = []
    failed: list[dict] = []
    derived: list[NeuroData] = []

    for i, nd in enumerate(datasets):
        if on_progress:
            on_progress(i, len(datasets), nd.entities.label())
        before, err = _safe(autoanalysis.analyze, nd)
        if err or not before or before.get("error"):
            failed.append({"dataset_id": nd.id, "label": nd.entities.label(),
                           "error": err or before.get("error", "could not analyse")})
            continue

        use = steps if steps is not None else [
            {"op": s["op"], "params": s["params"]} for s in before["cleanup"]["steps"]]
        if not use:
            results.append({"dataset_id": nd.id, "new_id": None,
                            "label": nd.entities.label(), "skipped": "already clean",
                            "before": before["health"]["score"],
                            "after": before["health"]["score"], "delta": 0})
            continue

        out, err = _safe(pipeline.run_pipeline, nd, use)
        if err or out is None:
            failed.append({"dataset_id": nd.id, "label": nd.entities.label(), "error": err})
            continue
        new, qc = out

        after, err = _safe(autoanalysis.analyze, new)
        if err or not after or after.get("error"):
            failed.append({"dataset_id": nd.id, "label": nd.entities.label(),
                           "error": f"cleaned, but re-analysis failed: {err}"})
            continue

        derived.append(new)
        results.append({
            "dataset_id": nd.id, "new_id": new.id, "label": nd.entities.label(),
            "before": before["health"]["score"], "after": after["health"]["score"],
            "delta": after["health"]["score"] - before["health"]["score"],
            "grade_before": before["health"]["grade"], "grade_after": after["health"]["grade"],
            "steps": [s["op"] for s in use],
            "detected_bads": qc.get("detected_bads", []),
            "ica_excluded": qc.get("ica_excluded", []),
            "row": _row(new, after),
        })

    deltas = [r["delta"] for r in results if r.get("new_id")]
    return {
        "results": results, "failed": failed, "derived": derived,
        "n_improved": sum(1 for d in deltas if d > 0),
        "n_unchanged": sum(1 for d in deltas if d == 0),
        "n_worse": sum(1 for d in deltas if d < 0),
        "mean_delta": round(float(np.mean(deltas)), 1) if deltas else 0.0,
    }


#: Columns the cohort table offers, in the order a person reads them.
COLUMNS = [
    {"key": "label", "label": "Recording", "kind": "text"},
    {"key": "subject", "label": "Subject", "kind": "text"},
    {"key": "session", "label": "Session", "kind": "text"},
    {"key": "task", "label": "Task", "kind": "text"},
    {"key": "recording_type", "label": "Detected as", "kind": "text"},
    {"key": "health", "label": "Health", "kind": "score"},
    {"key": "grade", "label": "Grade", "kind": "grade"},
    {"key": "n_channels", "label": "Ch", "kind": "int"},
    {"key": "duration_s", "label": "Duration s", "kind": "num"},
    {"key": "sfreq", "label": "Hz", "kind": "num"},
    {"key": "n_events", "label": "Events", "kind": "int"},
    {"key": "bad_channels", "label": "Bad ch", "kind": "int"},
    {"key": "line_noise_db", "label": "Mains dB", "kind": "num"},
    {"key": "drift_uv", "label": "Drift µV", "kind": "num"},
    {"key": "muscle_pct", "label": "Muscle %", "kind": "num"},
    {"key": "blinks_per_min", "label": "Blinks/min", "kind": "num"},
    {"key": "alpha_peak_hz", "label": "Alpha Hz", "kind": "num"},
]

_OUTLIER_KEYS = ("health", "line_noise_db", "drift_uv", "muscle_pct",
                 "blinks_per_min", "alpha_peak_hz", "duration_s")

#: Fewer runs than this and "outlier" is not a meaningful word.
MIN_COHORT_FOR_OUTLIERS = 5


def summarize(rows: list[dict]) -> dict:
    """Cohort-level facts, plus the runs that do not look like the others.

    The outlier list is the point of this whole screen: in a study of forty, the
    useful question is never "what is the average" but "which three should I look
    at before I trust any of it".
    """
    if not rows:
        return {"n": 0, "stats": {}, "outliers": [], "types": {}, "grades": {}}

    stats: dict[str, dict] = {}
    for key in _OUTLIER_KEYS:
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        if len(vals) < 2:
            continue
        arr = np.asarray(vals, dtype=float)
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med)))
        stats[key] = {"median": round(med, 2), "mad": round(mad, 2),
                      "min": round(float(arr.min()), 2), "max": round(float(arr.max()), 2)}

    outliers: list[dict] = []
    # Below five runs the MAD is too unstable to call anything an outlier — with
    # n=3 any spread at all makes one of them "significant".
    if len(rows) >= MIN_COHORT_FOR_OUTLIERS:
        for r in rows:
            reasons = []
            for key, s in stats.items():
                v = r.get(key)
                if not isinstance(v, (int, float)) or s["mad"] <= 0:
                    continue
                z = 0.6745 * (v - s["median"]) / s["mad"]
                # Robust z alone is not enough: in a tight cohort the MAD collapses and
                # a 1 Hz difference in alpha peak scores z=6 while meaning nothing. The
                # deviation also has to be large relative to the value itself.
                relative = abs(v - s["median"]) / (abs(s["median"]) + 1e-9)
                if abs(z) >= 3.5 and relative >= 0.15:
                    col = next((c["label"] for c in COLUMNS if c["key"] == key), key)
                    reasons.append(f"{col} {v} vs cohort median {s['median']}")
            if reasons:
                outliers.append({"dataset_id": r["dataset_id"], "label": r["label"],
                                 "reasons": reasons})

    types: dict[str, int] = {}
    grades: dict[str, int] = {}
    for r in rows:
        types[r["recording_type"]] = types.get(r["recording_type"], 0) + 1
        grades[r["grade"]] = grades.get(r["grade"], 0) + 1

    healths = [r["health"] for r in rows if isinstance(r.get("health"), (int, float))]
    return {
        "n": len(rows),
        "stats": stats,
        "outliers": outliers,
        "types": types,
        "grades": grades,
        "mean_health": round(float(np.mean(healths)), 1) if healths else None,
        "n_usable": sum(1 for r in rows if r.get("grade") in ("excellent", "good")),
        "consistent": len(types) == 1,
    }


def to_csv(rows: list[dict]) -> str:
    """The table as CSV — because the next step is always a spreadsheet or R."""
    keys = [c["key"] for c in COLUMNS]
    lines = [",".join(c["label"] for c in COLUMNS)]
    for r in rows:
        cells = []
        for k in keys:
            v = r.get(k)
            v = "" if v is None else str(v)
            cells.append(f'"{v}"' if ("," in v or '"' in v) else v)
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"
