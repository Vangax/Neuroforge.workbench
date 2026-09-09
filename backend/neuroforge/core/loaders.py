# Universal loader: dispatch by file extension to the right MNE reader and
# normalise into NeuroData. Formats MNE can't read yet are marked "planned" in
# the registry (UI shows the full matrix; wire optional deps to enable them).
from __future__ import annotations

import os

import numpy as np
import mne

from .neurodata import NeuroData, BidsEntities
from . import synthetic


def read_xdf(path: str) -> mne.io.RawArray:
    """Read a Lab Streaming Layer .xdf recording.

    XDF holds several parallel streams; we take the best continuous signal stream
    as the data and fold every marker stream into annotations, aligned on the LSL
    clock. Requires `pyxdf`.
    """
    try:
        import pyxdf
    except ModuleNotFoundError:
        raise NotImplementedError(
            "XDF support needs the 'pyxdf' package — install it with: pip install pyxdf")

    streams, _header = pyxdf.load_xdf(path, dejitter_timestamps=True)
    if not streams:
        raise ValueError("no streams found in this XDF file")

    def info_of(s, key, default=""):
        try:
            return s["info"][key][0]
        except Exception:
            return default

    def is_signal(s) -> bool:
        try:
            return np.asarray(s["time_series"]).ndim == 2 and \
                not isinstance(s["time_series"][0][0], str)
        except Exception:
            return False

    signals = [s for s in streams if is_signal(s)]
    if not signals:
        raise ValueError("no numeric signal stream in this XDF file")
    # prefer a stream that calls itself EEG, else the widest one
    signals.sort(key=lambda s: (info_of(s, "type").upper() != "EEG",
                                -int(np.asarray(s["time_series"]).shape[1])))
    sig = signals[0]

    data = np.asarray(sig["time_series"], dtype=float).T          # (n_ch, n_times)
    stamps = np.asarray(sig["time_stamps"], dtype=float)
    sfreq = float(info_of(sig, "nominal_srate", 0) or 0)
    if sfreq <= 0:                                                 # derive from timestamps
        if stamps.size < 2:
            raise ValueError("stream has no usable sampling rate")
        sfreq = float(1.0 / np.median(np.diff(stamps)))

    # channel labels + units from the stream description
    labels, units = [], []
    try:
        chans = sig["info"]["desc"][0]["channels"][0]["channel"]
        for i, ch in enumerate(chans):
            labels.append(str(ch.get("label", [f"ch{i + 1}"])[0]))
            units.append(str(ch.get("unit", ["microvolts"])[0]).lower())
    except Exception:
        labels, units = [], []
    if len(labels) != data.shape[0]:
        labels = [f"ch{i + 1}" for i in range(data.shape[0])]
        units = ["microvolts"] * data.shape[0]

    # XDF EEG is conventionally in microvolts; MNE wants volts
    scale = 1e-6 if not units or any("micro" in u or u in ("uv", "µv") for u in units) else 1.0
    raw = mne.io.RawArray(data * scale,
                          mne.create_info(labels, sfreq, ch_types="eeg"), verbose="ERROR")

    # marker streams -> annotations, relative to the signal stream start
    t0 = stamps[0] if stamps.size else 0.0
    onsets, descs = [], []
    for s in streams:
        if s is sig or is_signal(s):
            continue
        ts = np.asarray(s.get("time_stamps", []), dtype=float)
        for stamp, val in zip(ts, s.get("time_series", [])):
            try:
                text = val[0] if isinstance(val, (list, tuple, np.ndarray)) else val
            except Exception:
                text = "marker"
            rel = float(stamp - t0)
            if 0 <= rel <= raw.n_times / sfreq:
                onsets.append(rel)
                descs.append(str(text))
    if onsets:
        order = np.argsort(onsets)
        raw.set_annotations(mne.Annotations(
            onset=np.asarray(onsets)[order], duration=np.zeros(len(onsets)),
            description=[descs[i] for i in order]))
    return raw


# ext -> (label, reader callable | None). None == declared but not yet wired.
_REGISTRY: dict[str, tuple[str, object]] = {
    ".xdf": ("Lab Streaming Layer (XDF)", read_xdf),
    ".edf": ("European Data Format", lambda p: mne.io.read_raw_edf(p, preload=True, verbose="ERROR")),
    ".bdf": ("BioSemi Data Format", lambda p: mne.io.read_raw_bdf(p, preload=True, verbose="ERROR")),
    ".gdf": ("General Data Format", lambda p: mne.io.read_raw_gdf(p, preload=True, verbose="ERROR")),
    ".vhdr": ("BrainVision", lambda p: mne.io.read_raw_brainvision(p, preload=True, verbose="ERROR")),
    ".cnt": ("Neuroscan CNT", lambda p: mne.io.read_raw_cnt(p, preload=True, verbose="ERROR")),
    ".set": ("EEGLAB", lambda p: mne.io.read_raw_eeglab(p, preload=True, verbose="ERROR")),
    ".fif": ("MNE-Python / FIFF", lambda p: mne.io.read_raw_fif(p, preload=True, verbose="ERROR")),
    ".mff": ("EGI NetStation", lambda p: mne.io.read_raw_egi(p, preload=True, verbose="ERROR")),
    ".nwb": ("Neurodata Without Borders", None),
    ".nev": ("Blackrock", None),
    ".ns3": ("Blackrock NSx", None),
    ".plx": ("Plexon", None),
    ".csv": ("Generic ASCII/CSV", None),
}


def supported_formats() -> list[dict]:
    return [
        {"ext": ext, "label": label, "status": "ready" if fn else "planned"}
        for ext, (label, fn) in sorted(_REGISTRY.items())
    ]


def detect_format(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in _REGISTRY else None


def _validate(raw: mne.io.BaseRaw) -> None:
    # cheap integrity checks so a corrupt/empty file fails on import, not later
    if raw.info["sfreq"] <= 0:
        raise ValueError("invalid sampling rate")
    if raw.n_times == 0:
        raise ValueError("recording contains no samples")
    sample = raw.get_data(start=0, stop=min(raw.n_times, int(raw.info["sfreq"])))
    if not np.isfinite(sample).all():
        raise ValueError("data contains NaN/Inf in the first second")


_EEG_PREFIXES = ("EEG_", "EEG ", "EEG-", "EEG.")
_STIM_HINTS = ("stim", "trig", "code", "target", "phase", "marker", "status",
               "event", "begin", "feedback", "result", "selected")


def _canon_names() -> dict[str, str]:
    # UPPERCASE -> canonical spelling, from the 10-05 superset
    return {n.upper(): n for n in mne.channels.make_standard_montage("standard_1005").ch_names}


def auto_detect_channels(raw: mne.io.BaseRaw) -> dict:
    """Find the real EEG channels among possibly many non-EEG ones.

    Many formats (e.g. BigP3BCI EDF: 114 channels, 32 real EEG named ``EEG_F3``…
    plus speller/state channels) mark everything as EEG. We strip ``EEG_`` style
    prefixes, match against standard 10-05 names, rename matches to canonical
    spelling, demote the rest to stim/misc, and attach a montage. Only acts when
    confident (>= 4 standard names found) so non-standard files are left untouched.
    """
    canon = _canon_names()
    cur = dict(zip(raw.ch_names, raw.get_channel_types()))
    rename: dict[str, str] = {}
    eeg: list[str] = []
    demoted: list[str] = []
    taken: set[str] = set()

    for ch in list(raw.ch_names):
        if cur[ch] != "eeg":
            continue  # respect channels MNE already typed (eog/ecg/stim/…)
        base = ch
        for p in _EEG_PREFIXES:
            if base.upper().startswith(p.upper()):
                base = base[len(p):]
                break
        target = canon.get(base.strip().upper())
        if target and target not in taken:
            taken.add(target)
            if target != ch:
                rename[ch] = target
            eeg.append(target)
        else:
            demoted.append(ch)

    confident = len(eeg) >= 4
    retypes: dict[str, str] = {}
    if confident:
        if rename:
            raw.rename_channels(rename)
        if demoted:
            retypes = {ch: ("stim" if any(h in ch.lower() for h in _STIM_HINTS) else "misc")
                       for ch in demoted}
            raw.set_channel_types(retypes, verbose="ERROR")
        try:
            raw.set_montage("standard_1005", on_missing="ignore", match_case=False, verbose="ERROR")
        except Exception:
            pass

    return {
        "n_total": len(raw.ch_names),
        "n_eeg": raw.get_channel_types().count("eeg"),
        "n_demoted": len(demoted) if confident else 0,
        "auto_detected": confident,
        "eeg_channels": eeg if confident else [],
        # Kept so the reproduction script can replay the exact same decision
        # instead of quietly analysing 114 "EEG" channels that are really states.
        "rename": rename if confident else {},
        "retypes": retypes,
        "montage": "standard_1005" if confident else None,
    }


def load_file(path: str, *, entities: BidsEntities | None = None) -> NeuroData:
    ext = detect_format(path)
    if ext is None:
        raise ValueError(f"unrecognized format for {path!r}")
    label, reader = _REGISTRY[ext]
    if reader is None:
        raise NotImplementedError(
            f"{label} ({ext}) is declared but not wired — install its optional dependency"
        )
    raw = reader(path)
    _validate(raw)
    detection = auto_detect_channels(raw)
    nd = NeuroData(raw, entities=entities, source_format=label, source_path=path)
    nd.extra = {**nd.extra, "channel_detection": detection}
    return nd


def make_synthetic(
    *,
    subject: str = "01",
    session: str | None = "01",
    task: str = "rest",
    run: str | None = None,
    seed: int | None = None,
    **kwargs,
) -> NeuroData:
    raw, paradigm = synthetic.generate(seed=seed, **kwargs)
    ent = BidsEntities(subject=subject, session=session, task=task, run=run)
    return NeuroData(raw, entities=ent, source_format="synthetic", extra=paradigm)
