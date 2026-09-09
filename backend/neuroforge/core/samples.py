# Sample-data catalog: one click to a real recording to work with.
#
# Two kinds:
#   synthetic — generated instantly on this machine, no network, always available
#   download  — fetched from PhysioNet via MNE (needs internet, cached afterwards)
from __future__ import annotations

import logging
from pathlib import Path

import mne

from . import synthetic
from .neurodata import NeuroData, BidsEntities
from .loaders import auto_detect_channels
from ..config import settings

log = logging.getLogger("neuroforge.samples")


def catalog() -> list[dict]:
    items = [
        {
            "id": pid, "kind": "synthetic", "label": spec["label"], "blurb": spec["blurb"],
            "duration_s": spec["duration"], "task": spec["task"],
            "needs_network": False,
        }
        for pid, spec in synthetic.PARADIGMS.items()
    ]
    items.append({
        "id": "physionet_mi", "kind": "download",
        "label": "PhysioNet motor imagery (real recording)",
        "blurb": "Subject 1 of the EEG Motor Movement/Imagery database — 64 channels, "
                 "left vs right hand imagery. Downloaded once, then cached.",
        "duration_s": None, "task": "motorimagery", "needs_network": True,
    })
    return items


def _synthetic_sample(sample_id: str, seed: int | None) -> NeuroData:
    spec = synthetic.PARADIGMS[sample_id]
    raw, info = synthetic.generate(paradigm=sample_id, seed=seed)
    ent = BidsEntities(subject="demo", session=None, task=spec["task"])
    nd = NeuroData(raw, entities=ent, source_format="sample (synthetic)")
    nd.extra = {**info, "sample_id": sample_id}
    return nd


def _physionet_mi(subject: int = 1) -> NeuroData:
    """Real motor-imagery runs from PhysioNet (downloads on first use)."""
    from mne.datasets import eegbci

    cache = Path(settings.data_dir) / "mne_data"
    cache.mkdir(parents=True, exist_ok=True)
    paths = eegbci.load_data(subject, [6, 10, 14], path=str(cache),
                             update_path=False, verbose="ERROR")
    raws = [mne.io.read_raw_edf(p, preload=True, verbose="ERROR") for p in paths]
    raw = mne.concatenate_raws(raws, verbose="ERROR")
    try:
        eegbci.standardize(raw)          # strip trailing dots from channel names
    except Exception:
        pass
    detection = auto_detect_channels(raw)
    ent = BidsEntities(subject=f"physionet{subject:02d}", session=None, task="motorimagery")
    nd = NeuroData(raw, entities=ent, source_format="PhysioNet EEGBCI (real)")
    nd.extra = {"sample_id": "physionet_mi", "channel_detection": detection,
                "source": "PhysioNet EEG Motor Movement/Imagery Database",
                "runs": [6, 10, 14], "synthetic": False}
    return nd


def build(sample_id: str, seed: int | None = None) -> NeuroData:
    if sample_id in synthetic.PARADIGMS:
        return _synthetic_sample(sample_id, seed)
    if sample_id == "physionet_mi":
        return _physionet_mi()
    raise ValueError(f"unknown sample '{sample_id}'")
