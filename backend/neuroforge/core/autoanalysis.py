# Auto-Analysis Engine — "Analyze this recording" in one call.
#
# Runs a fixed battery and returns a plain-language report:
#   1. what kind of recording this is (paradigm detection, with reasons)
#   2. a data-health score with per-check detail
#   3. notable observations, each carrying the evidence needed to plot it
#   4. concrete suggested next steps
#
# Every section is independently guarded: a failing check degrades that section
# instead of killing the report.
from __future__ import annotations

import logging

import numpy as np
from scipy.signal import find_peaks, hilbert

import mne

from .features import analysis_picks
from . import montage as mtg
from .pipeline import detect_bad_channels

log = logging.getLogger("neuroforge.auto")

# np.trapz was renamed to np.trapezoid in NumPy 2.0; support both
_trapz = np.trapezoid if hasattr(np, "trapezoid") else np.trapz

BANDS = {"delta": (1.0, 4.0), "theta": (4.0, 8.0), "alpha": (8.0, 13.0),
         "beta": (13.0, 30.0), "gamma": (30.0, 45.0)}

# minimum trials per condition before an ERP average is worth trusting
MIN_TRIALS_PER_CONDITION = 30


# --------------------------------------------------------------------------- #
# shared measurements
# --------------------------------------------------------------------------- #
def _fmax(sfreq: float) -> float:
    return float(min(45.0, sfreq / 2.0 - 1.0))


def _measure(raw: mne.io.BaseRaw) -> dict:
    """Compute the shared quantities every section needs, once."""
    sf = float(raw.info["sfreq"])
    spec = raw.compute_psd(method="welch", fmin=0.5, fmax=_fmax(sf), verbose="ERROR")
    psd, freqs = spec.get_data(return_freqs=True)          # (n_ch, n_freq) V^2/Hz
    total = _trapz(psd, freqs, axis=1) + 1e-30

    rel = {}
    for name, (lo, hi) in BANDS.items():
        m = (freqs >= lo) & (freqs < hi)
        rel[name] = (_trapz(psd[:, m], freqs[m], axis=1) / total) if m.any() \
            else np.zeros(psd.shape[0])

    pos = mtg.project_raw(raw)
    idx = {"posterior": [], "frontal": [], "central": []}
    for i, ch in enumerate(raw.ch_names):
        if ch not in pos:
            continue
        x, y = pos[ch]
        if y < -0.35:
            idx["posterior"].append(i)
        elif y > 0.35:
            idx["frontal"].append(i)
        if abs(y) < 0.30 and abs(x) < 0.65:
            idx["central"].append(i)
    # fall back to all channels if the montage gave us nothing
    for k in idx:
        if not idx[k]:
            idx[k] = list(range(len(raw.ch_names)))

    # A second, wider spectrum purely for mains detection: the analysis band stops
    # at 45 Hz, so 50/60 Hz would otherwise be invisible.
    wide_max = float(min(70.0, sf / 2.0 - 1.0))
    if wide_max > _fmax(sf) + 1:
        spec_w = raw.compute_psd(method="welch", fmin=0.5, fmax=wide_max, verbose="ERROR")
        psd_w, freqs_w = spec_w.get_data(return_freqs=True)
    else:
        psd_w, freqs_w = psd, freqs

    return {"sfreq": sf, "freqs": freqs, "psd": psd, "psd_db": 10 * np.log10(psd + 1e-30),
            "freqs_wide": freqs_w, "psd_db_wide": 10 * np.log10(psd_w + 1e-30),
            "rel": rel, "groups": idx, "ch_names": list(raw.ch_names)}


def _summarize(onset_s: np.ndarray, labels: list[str], source: str,
               events=None, event_id=None) -> dict:
    counts: dict[str, int] = {}
    for d in labels:
        counts[d] = counts.get(d, 0) + 1
    isi = np.diff(np.sort(onset_s)) if onset_s.size > 2 else np.array([])
    return {
        "n": int(onset_s.size), "counts": counts, "stim_counts": counts,
        "labels": sorted(counts, key=lambda k: -counts[k]),
        "regular_isi": bool(isi.size > 5 and (np.std(isi) / (np.mean(isi) + 1e-9)) < 0.35),
        "median_isi": float(np.median(isi)) if isi.size else 0.0,
        "source": source, "events": events, "event_id": event_id,
    }


def _events_from_stim(raw: mne.io.BaseRaw) -> dict | None:
    """Recover events from stim/trigger channels.

    Many acquisition systems (BCI2000, BrainVision, Biosemi) encode the paradigm in
    stim channels rather than annotations — without this a P300 session looks like
    an unmarked continuous recording.
    """
    try:
        picks = mne.pick_types(raw.info, meg=False, eeg=False, stim=True)
    except Exception:
        return None
    if len(picks) == 0:
        return None

    sf = float(raw.info["sfreq"])
    names = [raw.ch_names[i] for i in picks]
    data = raw.get_data(picks=picks)

    def rising(v: np.ndarray) -> np.ndarray:
        return np.flatnonzero((v[1:] > 0.5) & (v[:-1] <= 0.5)) + 1

    # 1) explicit onset channel, 2) a stimulus-code channel, 3) densest plausible
    order = (("begin", "onset"), ("code", "stimulus"), ())
    chosen_i, onsets = None, None
    for keys in order:
        for i, nm in enumerate(names):
            if keys and not any(k in nm.lower() for k in keys):
                continue
            on = rising(data[i])
            if 20 <= len(on) <= 50000:
                chosen_i, onsets = i, on
                break
        if chosen_i is not None:
            break
    if chosen_i is None or onsets is None:
        return None

    # label each onset from a "type"-like channel if one exists (target vs non-target)
    labels = ["stimulus"] * len(onsets)
    event_id = {"stimulus": 1}
    codes = np.ones(len(onsets), dtype=int)
    for i, nm in enumerate(names):
        if i == chosen_i or "type" not in nm.lower():
            continue
        at = np.clip(onsets + max(1, int(0.01 * sf)), 0, data.shape[1] - 1)
        vals = np.rint(data[i][at]).astype(int)
        uniq = np.unique(vals)
        if 1 < len(uniq) <= 4:
            mapping = {v: ("target" if v == uniq.max() else "non-target") for v in uniq} \
                if len(uniq) == 2 else {v: f"{nm}={v}" for v in uniq}
            labels = [mapping[v] for v in vals]
            event_id = {lab: int(code) + 1 for code, lab in enumerate(sorted(set(labels)))}
            codes = np.array([event_id[lab] for lab in labels], dtype=int)
        break

    events = np.column_stack([onsets.astype(int), np.zeros(len(onsets), int), codes])
    return _summarize(onsets / sf, labels, f"stim channel '{names[chosen_i]}'",
                      events=events, event_id=event_id)


def _events(raw: mne.io.BaseRaw) -> dict:
    ann = raw.annotations
    onsets = np.asarray(ann.onset, dtype=float)
    descs = [str(d) for d in ann.description]
    # drop obvious non-stimulus bookkeeping markers
    keep = [(o, d) for o, d in zip(onsets, descs) if d.lower() not in
            {"begin recording", "edge", "bad_acq_skip", "new segment"}]
    if len(keep) >= 20:
        try:
            events, event_id = mne.events_from_annotations(raw, verbose="ERROR")
        except Exception:
            events, event_id = None, None
        return _summarize(np.array([o for o, _ in keep]), [d for _, d in keep],
                          "annotations", events, event_id)

    from_stim = _events_from_stim(raw)
    if from_stim is not None:
        return from_stim
    return _summarize(np.array([o for o, _ in keep]), [d for _, d in keep], "annotations")


def _peak_in(freqs, curve, lo, hi):
    """Return (peak_freq, prominence_db) of the strongest peak inside [lo, hi]."""
    m = (freqs >= lo) & (freqs <= hi)
    if not m.any():
        return None, 0.0
    seg, fseg = curve[m], freqs[m]
    pk, props = find_peaks(seg, prominence=0.5)
    if not len(pk):
        return None, 0.0
    best = int(pk[np.argmax(props["prominences"])])
    return float(fseg[best]), float(props["prominences"][np.argmax(props["prominences"])])


# --------------------------------------------------------------------------- #
# 1. what kind of recording is this?
# --------------------------------------------------------------------------- #
_MI_WORDS = ("left", "right", "hand", "foot", "feet", "tongue", "imager", "motor", "mi_")


def _detect_type(m: dict, ev: dict, duration: float, thirds: dict | None = None) -> dict:
    post = m["groups"]["posterior"]
    cent = m["groups"]["central"]
    alpha_post = float(np.mean(m["rel"]["alpha"][post]))
    delta_all = float(np.mean(m["rel"]["delta"]))
    alpha_all = float(np.mean(m["rel"]["alpha"]))
    post_curve = m["psd_db"][post].mean(axis=0)
    cent_curve = m["psd_db"][cent].mean(axis=0)
    apk, aprom = _peak_in(m["freqs"], post_curve, 7.0, 14.0)
    mpk, mprom = _peak_in(m["freqs"], cent_curve, 8.0, 13.0)

    n_labels = len(ev["stim_counts"])
    n_ev = sum(ev["stim_counts"].values())
    label_text = " ".join(ev["labels"]).lower()

    scores: dict[str, float] = {}
    why: dict[str, list[str]] = {}

    # --- event-driven paradigms ---
    erp = 0.0
    r_erp: list[str] = []
    if n_ev >= 20 and n_labels >= 1:
        erp += 0.45
        r_erp.append(f"{n_ev} event markers across {n_labels} label(s)")
        if ev.get("source", "annotations") != "annotations":
            r_erp.append(f"events recovered from {ev['source']}")
    if ev["regular_isi"] and ev["median_isi"] > 0:
        erp += 0.25
        r_erp.append(f"regular stimulus timing (~{ev['median_isi']:.2f}s apart)")
    if n_labels >= 2:
        erp += 0.15
        r_erp.append("more than one condition label present")
    scores["erp_paradigm"] = erp
    why["erp_paradigm"] = r_erp

    # oddball: two classes, one rare
    odd = 0.0
    r_odd: list[str] = []
    if n_labels >= 2 and n_ev >= 20:
        vals = sorted(ev["stim_counts"].values(), reverse=True)
        rare_frac = vals[-1] / max(1, sum(vals))
        if 0.03 <= rare_frac <= 0.35:
            odd = erp + 0.25
            r_odd = r_erp + [f"one condition is rare ({rare_frac * 100:.0f}% of trials) — oddball-like"]
    scores["oddball"] = odd
    why["oddball"] = r_odd

    # motor imagery
    mi = 0.0
    r_mi: list[str] = []
    if any(w in label_text for w in _MI_WORDS) and n_ev >= 10:
        # a lateralised cue structure is more specific than "some ERP paradigm"
        mi = erp + 0.30
        r_mi = r_erp + ["cues name a side or limb (left/right/hand/foot/imagery)"]
    if mprom > 1.0 and mpk and mprom >= aprom * 0.8:
        mi += 0.2
        r_mi.append(f"central mu-band peak at {mpk:.1f} Hz (sensorimotor rhythm)")
    scores["motor_imagery"] = mi
    why["motor_imagery"] = r_mi

    # resting state
    rest = 0.0
    r_rest: list[str] = []
    if n_ev < 20:
        rest += 0.45
        r_rest.append("no structured stimulus markers")
    if aprom > 1.5 and apk and alpha_post > 0.15:
        rest += 0.35
        r_rest.append(f"clear posterior alpha peak at {apk:.1f} Hz "
                      f"({alpha_post * 100:.0f}% of posterior power)")
    if duration >= 30:
        rest += 0.1
        r_rest.append(f"continuous {duration / 60:.1f} min recording")
    scores["resting_state"] = rest
    why["resting_state"] = r_rest

    # sleep / drowsy
    sleep = 0.0
    r_sleep: list[str] = []
    if delta_all > 0.45:
        sleep += 0.45
        r_sleep.append(f"delta dominates the spectrum ({delta_all * 100:.0f}% of total power)")
    if alpha_all < 0.10:
        sleep += 0.2
        r_sleep.append("very little alpha activity")
    if duration > 600:
        sleep += 0.2
        r_sleep.append("long recording, typical of a sleep study")
    if thirds and len(thirds.get("delta", [])) == 3 and thirds["delta"][0] > 0:
        if thirds["delta"][2] > thirds["delta"][0] * 1.3:
            sleep += 0.35
            r_sleep.append("slow-wave activity grows steadily across the recording")
        if thirds["alpha"][0] > 0 and thirds["alpha"][2] < thirds["alpha"][0] * 0.6:
            sleep += 0.2
            r_sleep.append("alpha fades toward the end — declining vigilance")
    scores["sleep"] = sleep
    why["sleep"] = r_sleep

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    if top_score < 0.35:
        top, top_score = "unknown", top_score

    labels = {
        "erp_paradigm": "Event-related paradigm (ERP)",
        "oddball": "Oddball / target-detection paradigm",
        "motor_imagery": "Motor imagery / sensorimotor task",
        "resting_state": "Resting state",
        "sleep": "Drowsy / sleep-like (slow-wave dominant)",
        "unknown": "Unclassified continuous recording",
    }
    label = labels[top]
    if top == "resting_state":
        if alpha_post > 0.35 and aprom > 6.0:
            label = "Resting state (eyes-closed dominant)"
        elif alpha_post < 0.15:
            label = "Resting state (low alpha — eyes-open like)"

    return {
        "code": top, "label": label,
        "confidence": round(float(min(0.98, top_score)), 2),
        "why": why.get(top, []) or ["not enough structure to classify confidently"],
        "candidates": [{"code": c, "label": labels.get(c, c), "score": round(float(s), 2)}
                       for c, s in ranked if s > 0],
        "alpha_peak_hz": apk, "alpha_prominence_db": round(float(aprom), 2),
        "alpha_posterior_rel": round(float(alpha_post), 3),
    }


# --------------------------------------------------------------------------- #
# 2. data health
# --------------------------------------------------------------------------- #
def _line_noise(m: dict) -> tuple[float, float]:
    """Return (mains_hz, excess_dB above the local spectral neighbourhood)."""
    best = (50.0, 0.0)
    freqs = m["freqs_wide"]
    curve = m["psd_db_wide"].mean(axis=0)
    for f0 in (50.0, 60.0):
        if f0 + 6 > freqs.max():
            continue
        at = (freqs >= f0 - 1) & (freqs <= f0 + 1)
        near = ((freqs >= f0 - 6) & (freqs <= f0 - 2)) | \
               ((freqs >= f0 + 2) & (freqs <= f0 + 6))
        if not at.any() or not near.any():
            continue
        excess = float(curve[at].max() - np.median(curve[near]))
        if excess > best[1]:
            best = (f0, excess)
    return best


#: Scalp EEG between 30 and 45 Hz sits at 1–3 µV. Sustained activity above this is
#: muscle, not brain — an absolute anchor, because a threshold relative to the
#: recording's own background *rises with the contamination it is measuring*: on a
#: badly contaminated record 3×median is 33 µV and almost nothing crosses it, while
#: on the cleaned version of the same record it drops to 6 µV and everything does.
#: That produced the absurd result of muscle contamination appearing to triple after
#: a successful cleanup.
_EMG_UV = 10.0


def _muscle_fraction(raw: mne.io.BaseRaw, sf: float) -> float:
    """Fraction of 1-second windows carrying EMG-level high-frequency power."""
    hi = _fmax(sf)
    if hi <= 32:
        return 0.0
    flt = raw.copy().filter(30.0, hi, verbose="ERROR")
    env = np.abs(hilbert(flt.get_data(), axis=1)).mean(axis=0) * 1e6   # µV
    n = int(sf)
    usable = (env.size // n) * n
    if usable < n * 4:
        return 0.0
    win = env[:usable].reshape(-1, n).mean(axis=1)
    return float(np.mean(win > _EMG_UV))


#: Blinks are largest at the very front of the head; averaging the whole frontal
#: group dilutes a 90 µV deflection into something the detector can miss.
_FRONTMOST = ("Fp1", "Fp2", "Fpz", "AF7", "AF8", "AF3", "AF4", "Fz")

#: A blink is a *large* deflection. 20 µV is far below a real one (50–200 µV at Fp)
#: and far above the residue left behind once ICA has removed them — without this
#: floor a purely relative threshold shrinks with the data it is measuring and
#: happily reports the same blink rate on a cleaned recording.
_BLINK_MIN_UV = 20.0
_BLINK_MAX_UV = 60.0     # never demand more than a real blink actually is


def _blink_rate(raw: mne.io.BaseRaw, frontal: list[int], posterior: list[int], sf: float) -> float:
    """Blink-like transients per minute.

    Three conditions, all required: the deflection stands out from the local
    background (robust threshold), it is physically big enough to be an eye
    movement (absolute floor), and it is frontally dominant (posterior channels
    do not see it). Deliberately conservative — under a heavy slow-wave load it
    under-counts rather than inventing blinks that are not there.
    """
    if not frontal:
        return 0.0
    names = [c for c in raw.ch_names if c in _FRONTMOST] or [raw.ch_names[i] for i in frontal]
    try:
        flt = raw.copy().filter(1.0, min(10.0, _fmax(sf)), verbose="ERROR")
        data = flt.get_data() * 1e6
    except Exception:
        data = raw.get_data() * 1e6
    front = data[[raw.ch_names.index(c) for c in names]].mean(axis=0)
    front = front - np.median(front)
    back = data[posterior].mean(axis=0) if posterior else np.zeros_like(front)
    back = back - np.median(back)

    mad = float(np.median(np.abs(front))) + 1e-30
    thresh = min(max(3.5 * mad, _BLINK_MIN_UV), _BLINK_MAX_UV)
    pk, _ = find_peaks(np.abs(front), height=thresh, distance=max(1, int(0.25 * sf)))
    if len(pk):
        pk = pk[np.abs(front[pk]) > 2.0 * np.abs(back[pk])]
    minutes = raw.n_times / sf / 60.0
    return float(len(pk) / max(minutes, 1e-6))


def _drift_uv(raw: mne.io.BaseRaw, sf: float) -> float:
    """Peak-to-peak of the 1-Hz block-averaged signal — slow drift indicator (µV)."""
    data = raw.get_data() * 1e6
    n = int(sf)
    usable = (data.shape[1] // n) * n
    if usable < n * 3:
        return 0.0
    blocks = data[:, :usable].reshape(data.shape[0], -1, n).mean(axis=2)
    return float(np.median(blocks.max(axis=1) - blocks.min(axis=1)))


def _health(raw: mne.io.BaseRaw, m: dict, ev: dict, duration: float) -> dict:
    checks: list[dict] = []
    penalty = 0.0

    def add(cid, label, status, value, detail, weight=0.0, evidence=None):
        nonlocal penalty
        checks.append({"id": cid, "label": label, "status": status, "value": value,
                       "detail": detail, "evidence": evidence})
        penalty += weight

    n_ch = len(m["ch_names"])

    # bad channels
    try:
        bad = detect_bad_channels(raw)
        frac = len(bad) / max(1, n_ch)
        st = "ok" if not bad else ("warn" if frac <= 0.10 else "fail")
        add("bad_channels", "Bad channels", st, len(bad),
            "No obviously bad channels." if not bad else
            f"{len(bad)} channel(s) look bad: {', '.join(bad[:6])}"
            f"{'…' if len(bad) > 6 else ''}.",
            0 if st == "ok" else (8 if st == "warn" else 20))
    except Exception as e:
        add("bad_channels", "Bad channels", "na", None, f"Could not run: {e}")

    # line noise
    try:
        f0, excess = _line_noise(m)
        st = "ok" if excess < 6 else ("warn" if excess < 12 else "fail")
        add("line_noise", "Mains interference", st, round(excess, 1),
            f"No strong mains peak (best case {excess:.1f} dB at {f0:.0f} Hz)." if st == "ok"
            else f"{excess:.1f} dB peak at {f0:.0f} Hz — apply a notch filter.",
            0 if st == "ok" else (6 if st == "warn" else 14), evidence="psd")
    except Exception as e:
        add("line_noise", "Mains interference", "na", None, f"Could not run: {e}")

    # drift
    try:
        drift = _drift_uv(raw, m["sfreq"])
        st = "ok" if drift < 150 else ("warn" if drift < 400 else "fail")
        add("drift", "Slow drift", st, round(drift, 1),
            f"Slow baseline swing is {drift:.0f} µV peak-to-peak."
            + ("" if st == "ok" else " A 0.5–1 Hz high-pass will help."),
            0 if st == "ok" else (5 if st == "warn" else 12))
    except Exception as e:
        add("drift", "Slow drift", "na", None, f"Could not run: {e}")

    # muscle
    try:
        mus = _muscle_fraction(raw, m["sfreq"])
        st = "ok" if mus < 0.05 else ("warn" if mus < 0.20 else "fail")
        add("muscle", "Muscle artifact", st, round(mus * 100, 1),
            f"{mus * 100:.1f}% of the recording shows high-frequency (muscle-like) bursts.",
            0 if st == "ok" else (6 if st == "warn" else 14), evidence="timeline")
    except Exception as e:
        add("muscle", "Muscle artifact", "na", None, f"Could not run: {e}")

    # blinks
    try:
        rate = _blink_rate(raw, m["groups"]["frontal"], m["groups"]["posterior"], m["sfreq"])
        # A resting adult blinks 15–20 times a minute. Calling that "contaminated"
        # would mark almost every healthy recording as unhealthy, so only an
        # unusually high rate counts against the score.
        st = "ok" if rate < 18 else ("warn" if rate < 35 else "fail")
        add("blinks", "Eye-blink contamination", st, round(rate, 1),
            f"About {rate:.0f} blink-like transients per minute on frontal channels."
            + (" That is a normal spontaneous blink rate." if st == "ok"
               else " ICA will remove these cleanly."),
            0 if st == "ok" else (5 if st == "warn" else 10))
    except Exception as e:
        add("blinks", "Eye-blink contamination", "na", None, f"Could not run: {e}")

    # trial counts
    if ev["stim_counts"]:
        low = {k: v for k, v in ev["stim_counts"].items() if v < MIN_TRIALS_PER_CONDITION}
        st = "ok" if not low else ("warn" if min(low.values()) >= 10 else "fail")
        detail = ("Trial counts look adequate for averaging: "
                  + ", ".join(f"{k}={v}" for k, v in ev["stim_counts"].items()) + ".") if not low else \
                 ("Below the ~%d trials/condition usually needed for a stable average: "
                  % MIN_TRIALS_PER_CONDITION
                  + ", ".join(f"{k}={v}" for k, v in low.items()) + ".")
        add("trials", "Trials per condition", st, min(ev["stim_counts"].values()), detail,
            0 if st == "ok" else (8 if st == "warn" else 16))
    else:
        add("trials", "Trials per condition", "na", None,
            "No stimulus markers found — nothing to epoch.")

    # recording length / sampling rate
    st = "ok" if duration >= 60 else ("warn" if duration >= 20 else "fail")
    add("duration", "Recording length", st, round(duration, 1),
        f"{duration:.0f} s of data." + ("" if st == "ok" else " Short recordings give noisy estimates."),
        0 if st == "ok" else (4 if st == "warn" else 10))

    st = "ok" if m["sfreq"] >= 200 else ("warn" if m["sfreq"] >= 100 else "fail")
    add("sfreq", "Sampling rate", st, m["sfreq"],
        f"{m['sfreq']:.0f} Hz." + ("" if st == "ok" else " Limits the usable frequency range."),
        0 if st == "ok" else (3 if st == "warn" else 8))

    score = int(max(0, min(100, round(100 - penalty))))
    grade = "excellent" if score >= 85 else "good" if score >= 70 else \
            "fair" if score >= 50 else "poor"

    # Penalties add up, but quality does not average. Two outright failures make a
    # recording you should not trust, whatever the arithmetic says — so the worst
    # check caps the grade instead of being diluted by the ones that passed.
    n_fail = sum(1 for c in checks if c["status"] == "fail")
    order = ["poor", "fair", "good", "excellent"]
    cap = "poor" if n_fail >= 2 else "fair" if n_fail == 1 else "excellent"
    if order.index(grade) > order.index(cap):
        grade = cap
    return {"score": score, "grade": grade, "checks": checks,
            "n_fail": n_fail, "n_warn": sum(1 for c in checks if c["status"] == "warn")}


# --------------------------------------------------------------------------- #
# 3. notable observations
# --------------------------------------------------------------------------- #
def _erp_probe(raw: mne.io.BaseRaw, ev: dict, m: dict) -> tuple[list[dict], dict | None]:
    """If the events look oddball-like, test for a P300-style positivity."""
    labels = ev["labels"]
    if len(labels) < 2 or sum(ev["stim_counts"].values()) < 20:
        return [], None
    try:
        events, event_id = ev.get("events"), ev.get("event_id")
        if events is None or not event_id:
            return [], None
        keep = {k: v for k, v in event_id.items() if k in ev["stim_counts"]}
        if len(keep) < 2:
            return [], None
        epochs = mne.Epochs(raw, events, keep, tmin=-0.2, tmax=0.8, baseline=(None, 0),
                            picks="eeg", preload=True, verbose="ERROR")
        counts = {k: len(epochs[k]) for k in keep if len(epochs[k]) > 0}
        if len(counts) < 2:
            return [], None
        rare = min(counts, key=counts.get)
        frequent = max(counts, key=counts.get)
        if counts[rare] < 5:
            return [], None

        # P300 is maximal centro-parietally; prefer that ROI by name and only fall
        # back to geometry when those electrodes aren't present.
        roi = ("Pz", "CPz", "Cz", "P3", "P4", "CP1", "CP2", "CP3", "CP4", "POz")
        names = [c for c in epochs.ch_names if c in roi]
        if len(names) < 2:
            post = m["groups"]["posterior"]
            names = [epochs.ch_names[i] for i in post if i < len(epochs.ch_names)] or epochs.ch_names
        ev_r = epochs[rare].average().pick(names)
        ev_f = epochs[frequent].average().pick(names)
        times_ms = (ev_r.times * 1000.0)
        diff = (ev_r.data.mean(axis=0) - ev_f.data.mean(axis=0)) * 1e6

        win = (times_ms >= 250) & (times_ms <= 600)
        findings: list[dict] = []
        if win.any():
            i = int(np.argmax(diff[win]))
            amp = float(diff[win][i])
            lat = float(times_ms[win][i])
            baseline_sd = float(np.std(diff[times_ms < 0])) + 1e-9
            if amp > 2.5 * baseline_sd and amp > 0.5:
                findings.append({
                    "title": f"P300-like response ~{lat:.0f} ms",
                    "plain": (f"'{rare}' trials produce a positive deflection of "
                              f"{amp:.1f} µV at {lat:.0f} ms over {', '.join(names[:4])}"
                              f"{'…' if len(names) > 4 else ''}, relative to '{frequent}'. "
                              f"That is the classic target-detection (P300) pattern."),
                    "confidence": round(float(min(0.95, amp / (4 * baseline_sd))), 2),
                    "evidence": {"kind": "erp", "key": "erp", "marker_ms": lat},
                })
        payload = {
            "times_ms": np.round(times_ms, 1).tolist(),
            "conditions": [
                {"name": rare, "n": counts[rare],
                 "wave": np.round(ev_r.data.mean(axis=0) * 1e6, 3).tolist()},
                {"name": frequent, "n": counts[frequent],
                 "wave": np.round(ev_f.data.mean(axis=0) * 1e6, 3).tolist()},
            ],
            "difference": np.round(diff, 3).tolist(),
            "channels_used": names[:12],
        }
        return findings, payload
    except Exception as e:  # noqa: BLE001 — probing is best-effort
        log.info("ERP probe skipped: %s", e)
        return [], None


def _thirds_trend(raw: mne.io.BaseRaw, m: dict) -> tuple[list[dict], dict]:
    """Delta/alpha balance across the first vs last third of the recording."""
    sf = m["sfreq"]
    n = raw.n_times
    third = n // 3
    out = {"labels": ["first third", "middle", "final third"], "delta": [], "alpha": []}
    findings: list[dict] = []
    if third < int(sf) * 5:
        return findings, out
    for k in range(3):
        seg = raw.get_data(start=k * third, stop=(k + 1) * third)
        p, f = mne.time_frequency.psd_array_welch(   # returns (psds, freqs)
            seg, sfreq=sf, fmin=1.0, fmax=_fmax(sf),
            n_fft=int(min(seg.shape[1], sf * 2)), verbose="ERROR")
        tot = _trapz(p, f, axis=1) + 1e-30
        for band, store in (("delta", out["delta"]), ("alpha", out["alpha"])):
            lo, hi = BANDS[band]
            msk = (f >= lo) & (f < hi)
            store.append(float(np.mean(_trapz(p[:, msk], f[msk], axis=1) / tot)))
    if out["alpha"][0] > 0.02 and out["alpha"][2] < out["alpha"][0] * 0.6:
        findings.append({
            "title": "Alpha fades across the recording",
            "plain": (f"Posterior alpha drops from {out['alpha'][0] * 100:.0f}% to "
                      f"{out['alpha'][2] * 100:.0f}% of total power between the first and final "
                      f"third — the usual signature of declining vigilance."),
            "confidence": 0.65,
            "evidence": {"kind": "timeline", "key": "thirds"},
        })
    if out["delta"][0] > 0 and out["delta"][2] > out["delta"][0] * 1.3:
        findings.append({
            "title": "Slow-wave activity increases toward the end",
            "plain": (f"Delta power rises from {out['delta'][0] * 100:.0f}% to "
                      f"{out['delta'][2] * 100:.0f}% of total power between the first and "
                      f"final third — often a sign of drowsiness late in the session."),
            "confidence": 0.6,
            "evidence": {"kind": "timeline", "key": "thirds"},
        })
    return findings, out


def _findings(raw, m, ev, rtype, trend_findings, thirds) -> tuple[list[dict], dict]:
    out: list[dict] = []
    evidence: dict = {}

    post = m["groups"]["posterior"]
    post_curve = m["psd_db"][post].mean(axis=0)
    evidence["psd"] = {
        "freqs": np.round(m["freqs"], 2).tolist(),
        "mean_db": np.round(m["psd_db"].mean(axis=0), 2).tolist(),
        "posterior_db": np.round(post_curve, 2).tolist(),
        "frontal_db": np.round(m["psd_db"][m["groups"]["frontal"]].mean(axis=0), 2).tolist(),
    }

    # alpha topography as evidence
    try:
        pos = mtg.project_raw(raw)
        alpha = m["rel"]["alpha"]
        vals = [{"name": ch, "x": pos[ch][0], "y": pos[ch][1], "value": float(alpha[i])}
                for i, ch in enumerate(m["ch_names"]) if ch in pos]
        if vals:
            evidence["alpha_topo"] = {"positions": vals}
    except Exception:
        pass

    # posterior alpha
    apk = rtype.get("alpha_peak_hz")
    aprom = rtype.get("alpha_prominence_db", 0.0)
    arel = rtype.get("alpha_posterior_rel", 0.0)
    if apk and aprom > 1.5 and arel > 0.12:
        strength = "Strong" if arel > 0.35 else "Clear" if arel > 0.20 else "Modest"
        # In a task recording the same rhythm means something different — say the
        # thing that is actually useful there instead of "eyes-closed resting".
        if rtype["code"] in ("resting_state", "unknown"):
            gloss = "the typical eyes-closed resting rhythm"
        elif rtype["code"] == "sleep":
            gloss = "alpha is still present despite the slow-wave dominance"
        else:
            gloss = ("strong background alpha during a task — often a sign of low "
                     "arousal, and it will inflate single-trial variance")
        out.append({
            "title": f"{strength} posterior alpha at {apk:.1f} Hz",
            "plain": (f"A {aprom:.1f} dB peak at {apk:.1f} Hz carries {arel * 100:.0f}% of "
                      f"posterior power — {gloss}."),
            "confidence": round(float(min(0.95, arel * 2.0)), 2),
            "evidence": {"kind": "psd", "key": "psd", "highlight": [8, 13]},
        })

    # mains
    try:
        f0, excess = _line_noise(m)
        if excess >= 6:
            out.append({
                "title": f"Mains interference at {f0:.0f} Hz",
                "plain": (f"A {excess:.1f} dB narrow peak sits at {f0:.0f} Hz. It is electrical, "
                          f"not brain activity — remove it with a notch filter."),
                "confidence": round(float(min(0.98, excess / 15.0)), 2),
                "evidence": {"kind": "psd", "key": "psd", "highlight": [f0 - 2, f0 + 2]},
            })
    except Exception:
        pass

    # drowsiness trend (computed once, shared with the classifier)
    if thirds:
        evidence["thirds"] = thirds
    out.extend(trend_findings)

    # P300 probe
    try:
        f_erp, erp_payload = _erp_probe(raw, ev, m)
        if erp_payload:
            evidence["erp"] = erp_payload
        out.extend(f_erp)
    except Exception as e:
        log.info("erp probe skipped: %s", e)

    if not out:
        out.append({
            "title": "No standout features detected",
            "plain": ("The recording looks unremarkable to the automatic battery. That is not a "
                      "problem — it just means nothing crossed the detection thresholds."),
            "confidence": 0.4, "evidence": {"kind": "psd", "key": "psd"},
        })
    return out, evidence


# --------------------------------------------------------------------------- #
# 4. next steps
# --------------------------------------------------------------------------- #
def _recommended_pipeline(health: dict, m: dict, n_ch: int) -> dict:
    """Turn the health report into an ordered, ready-to-run cleanup pipeline.

    Order is not cosmetic: filtering before ICA keeps drift out of the components,
    and interpolation before referencing keeps a dead channel out of the average.
    Every step carries the measurement that justifies it, so nothing is applied
    "because it is standard".
    """
    by_id = {c["id"]: c for c in health["checks"]}

    def bad(cid) -> bool:
        return by_id.get(cid, {}).get("status") in ("warn", "fail")

    steps: list[dict] = []
    skipped: list[str] = []
    nyq = m["sfreq"] / 2.0
    h_freq = min(40.0, round(nyq - 1, 1))

    # 1. band-pass — always worth it, but say which half is doing the work
    why_bp = []
    if bad("drift"):
        why_bp.append(f"slow drift is {by_id['drift']['value']} µV peak-to-peak")
    if bad("muscle"):
        why_bp.append(f"{by_id['muscle']['value']}% of the record has muscle-band bursts")
    steps.append({
        "op": "filter", "params": {"l_freq": 1.0, "h_freq": h_freq},
        "label": f"Band-pass 1–{h_freq:g} Hz",
        "why": ("Keeps the range every downstream analysis actually uses"
                + (" — " + " and ".join(why_bp) if why_bp else "")) + ".",
    })

    # 2. notch — redundant if the low-pass already sits below mains
    f0, excess = _line_noise(m)
    if bad("line_noise"):
        if h_freq < f0 - 2:
            skipped.append(f"Notch at {f0:.0f} Hz — unnecessary, the {h_freq:g} Hz "
                           f"low-pass already removes it.")
        else:
            steps.append({
                "op": "notch", "params": {"freq": float(f0)},
                "label": f"Notch {f0:.0f} Hz",
                "why": f"{excess:.1f} dB mains peak at {f0:.0f} Hz sits inside the passband.",
            })

    # 3. bad channels — detect, then interpolate so they do not poison the average ref
    if bad("bad_channels"):
        steps.append({"op": "detect_bads", "params": {"z": 4.0, "corr": 0.15},
                      "label": "Detect bad channels",
                      "why": by_id["bad_channels"]["detail"]})
        steps.append({"op": "interpolate", "params": {},
                      "label": "Interpolate bads",
                      "why": "Rebuilds them from their neighbours instead of dropping them."})

    # 4. ICA for blinks — after filtering, which is what makes the components clean
    if bad("blinks"):
        steps.append({
            "op": "ica", "params": {"n_components": min(15, max(5, n_ch - 1)),
                                    "method": "fastica", "eog_ch": "Fp1"},
            "label": "ICA (remove eye components)",
            "why": by_id["blinks"]["detail"],
        })

    # 5. average reference — only meaningful with enough coverage
    if n_ch >= 16:
        steps.append({"op": "reference", "params": {"mode": "average"},
                      "label": "Average reference",
                      "why": f"{n_ch} channels give enough coverage for a stable average reference."})
    else:
        skipped.append(f"Average reference — only {n_ch} channels, too few to average safely.")

    # Be explicit about the problems no filter can solve, rather than letting the
    # step list quietly imply that everything flagged is about to be fixed.
    if bad("trials"):
        skipped.append("Low trial count — preprocessing cannot create trials. "
                       "This one needs more data collection.")
    if bad("duration"):
        skipped.append("Short recording — no pipeline makes a recording longer.")
    if bad("sfreq"):
        skipped.append("Low sampling rate — the missing frequencies are gone at acquisition.")

    return {"steps": steps, "skipped": skipped,
            "estimate": "seconds" if not bad("blinks") else "up to a minute (ICA)"}


def _next_steps(health: dict, rtype: dict, ev: dict, mains_hz: float = 50.0) -> list[dict]:
    steps: list[dict] = []
    by_id = {c["id"]: c for c in health["checks"]}

    def bad(cid):
        return by_id.get(cid, {}).get("status") in ("warn", "fail")

    if bad("line_noise"):
        steps.append({"action": f"Apply a {mains_hz:.0f} Hz notch",
                      "why": by_id["line_noise"]["detail"], "module": "preprocess",
                      "params": {"op": "notch", "freq": float(mains_hz)}})
    if bad("drift"):
        steps.append({"action": "High-pass filter at 1 Hz",
                      "why": "Removes the slow baseline drift before any other analysis.",
                      "module": "preprocess", "params": {"op": "filter", "l_freq": 1.0}})
    if bad("blinks"):
        steps.append({"action": "Run ICA to remove eye artifacts",
                      "why": by_id["blinks"]["detail"], "module": "preprocess",
                      "params": {"op": "ica", "n_components": 15}})
    if bad("bad_channels"):
        steps.append({"action": "Interpolate the bad channels",
                      "why": by_id["bad_channels"]["detail"], "module": "preprocess",
                      "params": {"op": "interpolate"}})
    if bad("trials"):
        steps.append({"action": "Collect more trials before averaging",
                      "why": by_id["trials"]["detail"], "module": "erp", "params": {}})

    code = rtype["code"]
    if code in ("oddball", "erp_paradigm") and not bad("trials"):
        steps.append({"action": "Compute the evoked response",
                      "why": "The event structure supports ERP averaging with cluster statistics.",
                      "module": "erp", "params": {}})
    if code in ("resting_state", "sleep", "unknown"):
        steps.append({"action": "Run spectral parameterization and microstates",
                      "why": "Standard descriptors for continuous, task-free data.",
                      "module": "analyze", "params": {}})
    if code == "motor_imagery":
        steps.append({"action": "Train a CSP decoder",
                      "why": "Sensorimotor rhythms are the classic feature for motor-imagery BCI.",
                      "module": "bci", "params": {"classifier": "lda"}})
    steps.append({"action": "Export a report",
                  "why": "Saves these findings with the figures and a reproducibility hash.",
                  "module": "report", "params": {}})
    return steps


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def analyze(nd) -> dict:
    """Run the full battery on a NeuroData and return the report."""
    raw_full = nd.raw
    try:
        raw = analysis_picks(raw_full)
    except ValueError as e:
        return {"error": str(e), "dataset": {"id": nd.id, "label": nd.entities.label()}}

    duration = raw.n_times / float(raw.info["sfreq"])
    m = _measure(raw)
    ev = _events(raw_full)

    try:
        trend_findings, thirds = _thirds_trend(raw, m)
    except Exception as e:  # noqa: BLE001 — trend is best-effort
        log.info("thirds trend skipped: %s", e)
        trend_findings, thirds = [], {}

    rtype = _detect_type(m, ev, duration, thirds)
    health = _health(raw, m, ev, duration)
    findings, evidence = _findings(raw, m, ev, rtype, trend_findings, thirds)
    mains_hz, _ = _line_noise(m)
    steps = _next_steps(health, rtype, ev, mains_hz)
    cleanup = _recommended_pipeline(health, m, len(raw.ch_names))

    summary = (f"{rtype['label']} — data health {health['score']}/100 ({health['grade']}). "
               f"{len(findings)} notable observation(s), {len(steps)} suggested next step(s).")

    return {
        "dataset": {
            "id": nd.id, "label": nd.entities.label(),
            "sfreq": float(raw.info["sfreq"]), "n_channels": len(raw.ch_names),
            "n_channels_total": len(raw_full.ch_names),
            "duration_s": round(duration, 1), "n_events": ev["n"],
            "event_source": ev.get("source", "annotations"),
            "source_format": nd.source_format, "source_path": nd.source_path,
        },
        "summary": summary,
        "recording_type": rtype,
        "health": health,
        "findings": findings,
        "next_steps": steps,
        "cleanup": cleanup,
        "evidence": evidence,
        "disclaimer": ("Automated research summary. Observations are statistical patterns in the "
                       "signal, not a clinical interpretation or diagnosis."),
    }
