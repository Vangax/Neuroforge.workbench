# Preprocessing pipeline. A pipeline is an ordered list of {op, params}.
# run_pipeline applies them to a copy, logs provenance per step, and returns a new
# derivative plus QC (before/after PSD, detected bad channels, removed ICA comps).
from __future__ import annotations

import logging
import warnings

import numpy as np
import mne

from .neurodata import NeuroData, ProvenanceStep
from . import dsp

log = logging.getLogger("neuroforge.pipeline")


# Catalog advertised to the UI's pipeline builder.
STEP_CATALOG = [
    {"op": "reference", "label": "Re-reference", "params": {"mode": "average"}},
    {"op": "filter", "label": "Band-pass filter", "params": {"l_freq": 1.0, "h_freq": 40.0}},
    {"op": "notch", "label": "Notch (line noise)", "params": {"freq": 50}},
    {"op": "resample", "label": "Resample", "params": {"sfreq": 128}},
    {"op": "detect_bads", "label": "Detect bad channels", "params": {"z": 4.0, "corr": 0.15}},
    {"op": "interpolate", "label": "Interpolate bads", "params": {}},
    {"op": "ica", "label": "ICA artifact removal", "params": {"n_components": 15, "method": "fastica", "eog_ch": "Fp1"}},
]


def _robust_z(x: np.ndarray) -> np.ndarray:
    """Median/MAD z-score. With mean/std a couple of dead channels inflate the
    spread enough to hide themselves and each other (masking)."""
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    return 0.6745 * (x - med) / (mad + 1e-12)   # 0.6745 -> comparable to a normal z


def _neighbour_corr(data: np.ndarray, pos: np.ndarray | None, k: int = 6) -> np.ndarray:
    """Median |correlation| with each channel's k nearest sensors.

    Correlation against *all* channels is the wrong test: a channel carrying real
    localized signal (C3 during motor imagery) is globally uncorrelated but agrees
    perfectly with its own neighbours, whereas a dead or noisy electrode agrees with
    nobody. Falls back to the global mean when no sensor positions are available.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        C = np.corrcoef(data)
    np.fill_diagonal(C, np.nan)
    if pos is None or not np.isfinite(pos).all() or len(pos) < k + 1:
        out = np.nanmean(np.abs(C), axis=1)
    else:
        d = np.linalg.norm(pos[:, None, :] - pos[None, :, :], axis=2)
        np.fill_diagonal(d, np.inf)
        nb = np.argsort(d, axis=1)[:, :k]
        with warnings.catch_warnings():          # all-NaN row -> a constant channel
            warnings.simplefilter("ignore", RuntimeWarning)
            out = np.array([np.nanmedian(np.abs(C[i, nb[i]])) for i in range(len(data))])
    # A channel whose correlation is undefined is flat or degenerate: score it 0,
    # which is exactly what "agrees with nobody" means.
    return np.nan_to_num(out, nan=0.0)


def detect_bad_channels(raw: mne.io.BaseRaw, z: float = 4.0, corr: float = 0.15) -> list[str]:
    """Flag flat, wildly-deviant, and neighbour-uncorrelated channels.

    Deliberately conservative: over-flagging a good channel silently deletes real
    data, so the thresholds under-flag marginal cases instead. Never returns more
    than 25% of the montage.

    Statistics run on a high-passed copy. On unfiltered data a shared drift makes
    *every* channel correlate at ~0.9, the spread collapses, and the frontal channels
    get flagged for the crime of containing eye blinks — while the genuinely dead
    ones hide in the noise.
    """
    work = raw
    try:
        hi = min(45.0, raw.info["sfreq"] / 2 - 1)
        if hi > 2.0:
            work = raw.copy().filter(1.0, hi, picks="eeg", verbose="ERROR")
    except Exception:  # noqa: BLE001 — filtering is an improvement, not a requirement
        work = raw

    picks = mne.pick_types(work.info, eeg=True)
    if len(picks) < 4:
        return []
    data = work.get_data(picks=picks)
    names = [work.ch_names[i] for i in picks]

    loc = np.array([work.info["chs"][i]["loc"][:3] for i in picks], dtype=float)
    pos = loc if np.isfinite(loc).all() and np.abs(loc).sum() > 0 else None

    var = np.var(data, axis=1)
    zv = _robust_z(np.log(var + 1e-30))
    nbc = _neighbour_corr(data, pos)

    # "Lonely" needs both halves, and neither works alone.
    #
    #   absolute (nbc < corr) — no usable electrode agrees with its neighbours less
    #   than this, so it rules out flagging real but focal signal (C3 during motor
    #   imagery sits around 0.18);
    #
    #   relative (nbc < half the recording's median) — how much neighbours agree at
    #   all depends entirely on the recording. On a drifty record every channel
    #   correlates at 0.9 and on a filtered clean one the median can be 0.15, so a
    #   fixed cut either flags half the montage or none of it.
    lonely = (nbc < corr) & (nbc < 0.5 * float(np.median(nbc)))

    flat = var < 1e-20
    quiet = zv < -z                       # far below everything else: disconnected
    # High variance on its own is not a bad channel — Fp1/Fp2 are the loudest sensors
    # in any recording with blinks, and blinks are signal their neighbours share.
    # It only counts as bad when the neighbours do *not* see the same thing.
    loud = (zv > z) & (nbc < 2.0 * corr)
    bad = sorted(set(np.where(flat | lonely | quiet | loud)[0]))

    # If a fifth of the montage looks broken, the montage is probably fine and the
    # heuristic is not. This happens after an aggressive clean — average reference on
    # top of ICA can leave so little shared signal that every channel looks isolated.
    # Abstaining is the honest answer; silently truncating to a cap would report an
    # arbitrary subset as bad and get them interpolated away.
    if len(bad) > 0.2 * len(names):
        log.info("bad-channel detection abstained: %d/%d channels flagged", len(bad), len(names))
        return []
    return [names[i] for i in bad]


def _mean_psd(raw: mne.io.BaseRaw) -> dict:
    r = raw.copy()
    r.info["bads"] = []  # QC spectrum spans all channels regardless of marks
    p = dsp.compute_psd(r, fmin=1.0, fmax=min(45.0, r.info["sfreq"] / 2 - 1))
    arr = np.asarray(p["psd_db"])
    return {"freqs": p["freqs"], "mean": arr.mean(axis=0).tolist()}


def run_pipeline(nd: NeuroData, steps: list[dict]) -> tuple[NeuroData, dict]:
    raw = nd.raw.copy()
    psd_before = _mean_psd(raw)
    detected_bads: list[str] = []
    ica_excluded: list[int] = []
    applied: list[dict] = []

    for step in steps:
        op = step.get("op")
        p = step.get("params", {}) or {}
        try:
            if op == "reference":
                if p.get("mode", "average") == "average":
                    raw.set_eeg_reference("average", projection=False, verbose="ERROR")
                else:
                    raw.set_eeg_reference([p["channel"]], verbose="ERROR")
            elif op == "filter":
                raw.filter(p.get("l_freq"), p.get("h_freq"), verbose="ERROR")
            elif op == "notch":
                f = float(p.get("freq", 50)); nyq = raw.info["sfreq"] / 2
                raw.notch_filter([f * k for k in range(1, 5) if f * k < nyq], verbose="ERROR")
            elif op == "resample":
                raw.resample(float(p.get("sfreq", 128)), verbose="ERROR")
            elif op == "detect_bads":
                detected_bads = detect_bad_channels(raw, float(p.get("z", 4.0)), float(p.get("corr", 0.15)))
                raw.info["bads"] = sorted(set(raw.info["bads"]) | set(detected_bads))
            elif op == "interpolate":
                if raw.info["bads"]:
                    raw.interpolate_bads(reset_bads=True, verbose="ERROR")
            elif op == "ica":
                ica = mne.preprocessing.ICA(
                    n_components=int(p.get("n_components", 15)),
                    method=p.get("method", "fastica"), max_iter="auto", random_state=42, verbose="ERROR")
                ica.fit(raw)
                try:
                    eog, _ = ica.find_bads_eog(raw, ch_name=p.get("eog_ch", "Fp1"), verbose="ERROR")
                except Exception:
                    eog = []
                ica.exclude = eog
                ica_excluded = list(map(int, eog))
                ica.apply(raw, verbose="ERROR")
            else:
                continue
            # Record what a step *chose*, not just that it ran — the reproduction
            # script needs the actual channel list and component indices.
            entry = {"op": op, "params": p}
            if op == "detect_bads":
                entry["detected"] = list(detected_bads)
            elif op == "ica":
                entry["excluded"] = list(ica_excluded)
            applied.append(entry)
        except Exception as e:  # noqa: BLE001 — surface step failures to QC
            applied.append({"op": op, "params": p, "error": str(e)})

    new = NeuroData(raw, entities=nd.entities, source_format=f"{nd.source_format} ▸ preprocessed")
    new.provenance = list(nd.provenance) + [ProvenanceStep(f"prep:{s['op']}", s.get("params", {})) for s in applied]
    new.extra = {**nd.extra, "parent": nd.id, "pipeline": applied}

    qc = {
        "new_id": new.id,
        "psd_before": psd_before,
        "psd_after": _mean_psd(raw),
        "detected_bads": detected_bads,
        "ica_excluded": ica_excluded,
        "applied": applied,
        "sfreq": new.sfreq,
        "n_channels": new.n_channels,
    }
    return new, qc
