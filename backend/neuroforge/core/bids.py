# BIDS in, BIDS out.
#
# "BIDS-native" has to mean more than storing entities on an object: you should be
# able to point NeuroForge at a study folder and get the whole study, and hand back
# a derivatives tree another lab can read without asking you what you did.
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import mne
import numpy as np

from .neurodata import NeuroData, BidsEntities
from . import loaders

log = logging.getLogger("neuroforge.bids")

#: Entities we parse out of a BIDS filename. Order matters — it is the BIDS order.
_ENTITY_RE = re.compile(
    r"(?:^|_)(sub|ses|task|acq|run)-([A-Za-z0-9]+)", re.IGNORECASE)

#: Directories that never contain source recordings.
_SKIP_DIRS = {"derivatives", "sourcedata", "code", ".git", "__pycache__",
              "node_modules", ".datalad", "stimuli"}


def parse_entities(path: str | Path) -> BidsEntities:
    """Read BIDS entities out of a filename, falling back to the folder above it.

    A file named ``sub-01_ses-02_task-rest_run-03_eeg.edf`` carries its own metadata;
    a loose ``rest.edf`` inside ``sub-05/`` still tells us the subject. Anything we
    cannot infer stays empty rather than being invented.
    """
    p = Path(path)
    found = {k.lower(): v for k, v in _ENTITY_RE.findall(p.name)}

    # Walk up for sub-/ses- when the filename does not carry them (common in
    # exports that only use directory structure).
    for parent in p.parents:
        for key in ("sub", "ses"):
            if key not in found:
                m = re.fullmatch(rf"{key}-([A-Za-z0-9]+)", parent.name, re.IGNORECASE)
                if m:
                    found[key] = m.group(1)

    task = found.get("task")
    if not task:
        # last resort: the stem minus any BIDS suffix, cleaned to a label
        stem = re.sub(r"_(eeg|meg|ieeg|nirs|physio)$", "", p.stem, flags=re.IGNORECASE)
        stem = _ENTITY_RE.sub("", stem).strip("_")
        task = re.sub(r"[^A-Za-z0-9]", "", stem)[:40] or None

    return BidsEntities(
        subject=found.get("sub") or "imported",
        session=found.get("ses"),
        task=task,
        run=found.get("run"),
    )


def scan_folder(root: str | Path, *, limit: int = 500) -> list[dict]:
    """Every readable recording under a folder, with the entities we can infer.

    Returns candidates rather than loading anything — a study folder can be tens of
    gigabytes, and the caller should get to choose before any of it is read.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a folder")

    out: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS
                       and not d.startswith(".")]
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if loaders.detect_format(str(p)) is None:
                continue
            # BrainVision/EEGLAB write sidecars next to the header; only the header
            # is a dataset, and MNE finds the rest itself.
            if p.suffix.lower() in (".eeg", ".vmrk", ".fdt"):
                continue
            ent = parse_entities(p)
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append({
                "path": str(p),
                "relative": str(p.relative_to(root)),
                "format": loaders.detect_format(str(p)),
                "size_mb": round(size / 1e6, 2),
                "subject": ent.subject, "session": ent.session,
                "task": ent.task, "run": ent.run,
            })
            if len(out) >= limit:
                log.warning("scan_folder hit the %d-file limit at %s", limit, dirpath)
                return out
    return out


def is_bids_root(root: str | Path) -> bool:
    """True when a folder looks like a BIDS dataset root."""
    root = Path(root)
    return (root / "dataset_description.json").is_file() or \
        any(p.is_dir() and p.name.startswith("sub-") for p in root.iterdir())


def import_folder(root: str | Path, *, paths: list[str] | None = None,
                  on_progress=None) -> dict:
    """Load recordings from a folder into NeuroData objects.

    `paths` restricts the import to a subset returned by `scan_folder`. Failures are
    collected and reported rather than aborting the run — one unreadable file in a
    study of 200 should not cost you the other 199.
    """
    root = Path(root)
    wanted = set(paths) if paths else None
    found = scan_folder(root)
    if wanted is not None:
        found = [c for c in found if c["path"] in wanted]

    loaded: list[NeuroData] = []
    failed: list[dict] = []
    for i, cand in enumerate(found):
        if on_progress:
            on_progress(i, len(found), cand["relative"])
        try:
            ent = BidsEntities(subject=cand["subject"], session=cand["session"],
                               task=cand["task"], run=cand["run"])
            nd = loaders.load_file(cand["path"], entities=ent)
            loaded.append(nd)
        except Exception as e:  # noqa: BLE001 — one bad file must not stop the import
            failed.append({"path": cand["relative"], "error": str(e)})
            log.info("import skipped %s: %s", cand["relative"], e)
    return {"loaded": loaded, "failed": failed, "n_found": len(found)}


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def _dataset_description(name: str, *, derivative: bool, version: str) -> dict:
    desc = {
        "Name": name,
        "BIDSVersion": "1.9.0",
        "DatasetType": "derivative" if derivative else "raw",
        "Authors": ["NeuroForge"],
    }
    if derivative:
        desc["GeneratedBy"] = [{
            "Name": "NeuroForge",
            "Version": version,
            "Description": "Preprocessing and analysis derivatives, generated from "
                           "the recorded provenance log.",
        }]
    return desc


def _channels_tsv(raw: mne.io.BaseRaw) -> str:
    rows = ["name\ttype\tunits\tlow_cutoff\thigh_cutoff\tstatus"]
    types = raw.get_channel_types()
    lo = raw.info.get("highpass")
    hi = raw.info.get("lowpass")
    for name, ch_type in zip(raw.ch_names, types):
        units = "uV" if ch_type in ("eeg", "eog", "ecg", "emg") else "n/a"
        status = "bad" if name in raw.info["bads"] else "good"
        rows.append(f"{name}\t{ch_type.upper()}\t{units}\t"
                    f"{'n/a' if lo is None else lo}\t{'n/a' if hi is None else hi}\t{status}")
    return "\n".join(rows) + "\n"


def _events_tsv(raw: mne.io.BaseRaw) -> str | None:
    ann = raw.annotations
    if ann is None or len(ann) == 0:
        return None
    rows = ["onset\tduration\ttrial_type"]
    for onset, dur, desc in zip(ann.onset, ann.duration, ann.description):
        rows.append(f"{onset:.4f}\t{dur:.4f}\t{desc}")
    return "\n".join(rows) + "\n"


def _eeg_json(nd: NeuroData, raw: mne.io.BaseRaw) -> dict:
    types = raw.get_channel_types()
    return {
        "TaskName": nd.entities.task or "unknown",
        "SamplingFrequency": float(raw.info["sfreq"]),
        "EEGChannelCount": int(sum(t == "eeg" for t in types)),
        "EOGChannelCount": int(sum(t == "eog" for t in types)),
        "ECGChannelCount": int(sum(t == "ecg" for t in types)),
        "EMGChannelCount": int(sum(t == "emg" for t in types)),
        "MiscChannelCount": int(sum(t in ("misc", "stim") for t in types)),
        "RecordingDuration": round(float(raw.n_times / raw.info["sfreq"]), 3),
        "RecordingType": "continuous",
        "SoftwareFilters": {
            "HighPass": raw.info.get("highpass"),
            "LowPass": raw.info.get("lowpass"),
        },
        "EEGReference": "n/a",
        "PowerLineFrequency": float(raw.info.get("line_freq") or 50),
    }


def export_bids(datasets: list[NeuroData], out_dir: str | Path, *,
                name: str = "NeuroForge export", derivative: bool = True,
                version: str = "0.2.0") -> dict:
    """Write a BIDS(-derivatives) tree that another tool can read.

    Every run gets its data, a channels.tsv, an events.tsv when there are
    annotations, and a sidecar JSON. The provenance log travels with it, so the
    tree answers "what was done to this" without a conversation.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dataset_description.json").write_text(
        json.dumps(_dataset_description(name, derivative=derivative, version=version),
                   indent=2), encoding="utf-8")

    written: list[dict] = []
    failed: list[dict] = []
    subjects: set[str] = set()

    for nd in datasets:
        e = nd.entities
        try:
            raw = nd.raw
            parts = [f"sub-{_label(e.subject)}"]
            rel = Path(parts[0])
            if e.session:
                parts.append(f"ses-{_label(e.session)}")
                rel = rel / parts[-1]
            rel = rel / (e.datatype or "eeg")
            (out / rel).mkdir(parents=True, exist_ok=True)

            stem = "_".join(parts)
            if e.task:
                stem += f"_task-{_label(e.task)}"
            if e.run:
                stem += f"_run-{_label(e.run)}"
            if derivative:
                stem += "_desc-neuroforge"
            base = out / rel / stem

            raw.save(f"{base}_eeg.fif", overwrite=True, verbose="ERROR")
            (Path(f"{base}_channels.tsv")).write_text(_channels_tsv(raw), encoding="utf-8")
            (Path(f"{base}_eeg.json")).write_text(
                json.dumps(_eeg_json(nd, raw), indent=2), encoding="utf-8")
            ev = _events_tsv(raw)
            if ev:
                (Path(f"{base}_events.tsv")).write_text(ev, encoding="utf-8")
            (Path(f"{base}_provenance.json")).write_text(json.dumps({
                "dataset_id": nd.id,
                "source_format": nd.source_format,
                "source_path": nd.source_path,
                "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "steps": [{"op": s.op, "params": _jsonable(s.params),
                           "software": s.software} for s in nd.provenance],
            }, indent=2), encoding="utf-8")

            subjects.add(parts[0])
            written.append({"dataset_id": nd.id, "path": str(Path(rel) / f"{stem}_eeg.fif")})
        except Exception as exc:  # noqa: BLE001 — report, do not abort the export
            failed.append({"dataset_id": nd.id, "label": e.label(), "error": str(exc)})
            log.info("bids export skipped %s: %s", nd.id, exc)

    if subjects:
        (out / "participants.tsv").write_text(
            "participant_id\n" + "\n".join(sorted(subjects)) + "\n", encoding="utf-8")

    return {"root": str(out), "n_written": len(written), "n_subjects": len(subjects),
            "written": written, "failed": failed}


def _label(value: str | None) -> str:
    """BIDS entity labels are alphanumeric only."""
    return re.sub(r"[^A-Za-z0-9]", "", str(value or ""))[:40] or "x"


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj
