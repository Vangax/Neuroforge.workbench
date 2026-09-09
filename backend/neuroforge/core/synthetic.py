# Synthetic EEG so the app is useful without real recordings.
#
# Each paradigm is a different recipe over a shared 1/f background: resting
# eyes-open/closed, an oddball with a real P300, motor imagery with mu/beta ERD,
# a drowsy recording, and a deliberately artifact-heavy one for QC demos.
# Everything returns a real RawArray on a standard_1020 montage, so every
# downstream MNE operation works on it unchanged.
from __future__ import annotations

import numpy as np
import mne

from .montage import DEFAULT_32

# Channels where each generator source projects most strongly.
_POSTERIOR = {"P7", "P3", "Pz", "P4", "P8", "PO3", "POz", "PO4", "O1", "O2"}
_FRONTAL = {"Fp1", "Fp2", "AF3", "AF4", "F7", "F3", "Fz", "F4", "F8"}
_BLINK_GAIN = {"Fp1": 1.0, "Fp2": 1.0, "AF3": 0.7, "AF4": 0.7,
               "F7": 0.4, "F8": 0.4, "Fz": 0.3}
# centro-parietal weighting for the P300
_P300_GAIN = {"Pz": 1.0, "CP1": 0.9, "CP2": 0.9, "Cz": 0.85, "P3": 0.8, "P4": 0.8,
              "POz": 0.6, "CP5": 0.5, "CP6": 0.5, "C3": 0.5, "C4": 0.5, "Fz": 0.25}

PARADIGMS: dict[str, dict] = {
    "resting_closed": {
        "label": "Resting state — eyes closed",
        "blurb": "Strong posterior alpha. The classic 'is my setup working' recording.",
        "duration": 90.0, "task": "restEC",
    },
    "resting_open": {
        "label": "Resting state — eyes open",
        "blurb": "Alpha suppressed, more beta and more blinks than eyes-closed.",
        "duration": 90.0, "task": "restEO",
    },
    "oddball": {
        "label": "Oddball / P300 paradigm",
        "blurb": "Rare targets among frequent standards, with a genuine P300 response.",
        "duration": 120.0, "task": "oddball",
    },
    "motor_imagery": {
        "label": "Motor imagery — left vs right",
        "blurb": "Cued imagery with mu/beta desynchronisation over the opposite hemisphere.",
        "duration": 150.0, "task": "motorimagery",
    },
    "drowsy": {
        "label": "Drowsy / descending vigilance",
        "blurb": "Alpha fades and slow-wave activity grows across the recording.",
        "duration": 150.0, "task": "drowsy",
    },
    "artifact_heavy": {
        "label": "Artifact-heavy recording",
        "blurb": "Dead channels, strong mains, drift, muscle bursts — for testing the QC pass.",
        "duration": 90.0, "task": "noisy",
    },
}


def _pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """1/f noise via spectral shaping of white noise."""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1] if len(freqs) > 1 else 1.0
    spec = spec / np.sqrt(freqs)
    out = np.fft.irfft(spec, n=n)
    return out / (np.std(out) or 1.0)


def _band_noise(n: int, sfreq: float, lo: float, hi: float,
                rng: np.random.Generator) -> np.ndarray:
    """Unit-variance band-limited noise.

    Real cortical rhythms are narrowband noise with a wandering phase, not pure
    tones — a single sine gives an implausibly sharp spectral line.
    """
    spec = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, d=1.0 / sfreq)
    band = np.zeros_like(freqs)
    band[(freqs >= lo) & (freqs <= hi)] = 1.0
    for f0, f1, rising in ((max(lo - 1.0, 0.0), lo, True), (hi, hi + 1.0, False)):
        m = (freqs > f0) & (freqs < f1)
        if m.any() and f1 > f0:
            u = (freqs[m] - f0) / (f1 - f0)
            band[m] = u if rising else 1.0 - u
    out = np.fft.irfft(spec * band, n=n)
    return out / (np.std(out) or 1.0)


def _bump(t_rel: np.ndarray, centre: float, width: float) -> np.ndarray:
    return np.exp(-((t_rel - centre) ** 2) / (2 * width ** 2))


def _add_event_response(data, ch_names, sfreq, onsets, gains, amp, latency, width, rng):
    """Add a Gaussian evoked response after each onset, weighted per channel."""
    n = data.shape[1]
    span = np.arange(int((latency + 4 * width) * sfreq) + 1) / sfreq
    kernel = _bump(span, latency, width)
    for i, name in enumerate(ch_names):
        g = gains.get(name, 0.15)
        if g <= 0:
            continue
        for onset in onsets:
            s0 = int(onset * sfreq)
            s1 = min(n, s0 + kernel.size)
            if s0 >= n:
                continue
            data[i, s0:s1] += g * amp * kernel[: s1 - s0] * rng.uniform(0.75, 1.25)


def generate(
    *,
    paradigm: str = "oddball",
    n_seconds: float | None = None,
    sfreq: float = 256.0,
    ch_names: list[str] | None = None,
    line_freq: float | None = 50.0,
    seed: int | None = None,
) -> tuple[mne.io.RawArray, dict]:
    """Return (raw, info_dict). ``info_dict`` carries paradigm details."""
    spec = PARADIGMS.get(paradigm, PARADIGMS["oddball"])
    rng = np.random.default_rng(seed)
    ch_names = list(ch_names or DEFAULT_32)
    n_ch = len(ch_names)
    n_seconds = float(n_seconds if n_seconds is not None else spec["duration"])
    n = int(round(n_seconds * sfreq))
    t = np.arange(n) / sfreq
    data = np.zeros((n_ch, n), dtype=np.float64)

    # ---- paradigm-specific background weights ----------------------------- #
    alpha_amp = {"resting_closed": 22.0, "resting_open": 2.0, "oddball": 14.0,
                 "motor_imagery": 10.0, "drowsy": 10.0, "artifact_heavy": 10.0}[paradigm]
    delta_amp = {"drowsy": 30.0, "artifact_heavy": 6.0}.get(paradigm, 3.0)
    beta_amp = {"resting_open": 7.0}.get(paradigm, 2.0)
    blink_rate = {"resting_open": 0.35, "artifact_heavy": 0.5}.get(paradigm, 0.25)
    # clean recordings should look genuinely clean; only some carry mains
    mains_amp = {"artifact_heavy": 15.0, "oddball": 3.0,
                 "motor_imagery": 1.5}.get(paradigm, 0.0)

    # alpha envelope: sustained when eyes-closed, waxing/waning otherwise
    if paradigm == "resting_closed":
        alpha_env = 0.9 + 0.25 * np.sin(2 * np.pi * 0.03 * t)
    elif paradigm == "drowsy":
        alpha_env = np.clip(1.3 - 1.1 * (t / max(t[-1], 1e-9)), 0.05, None)
    else:
        alpha_env = 0.6 + 0.4 * np.sin(2 * np.pi * 0.05 * t)
        for c0, c1 in [(0.15, 0.30), (0.62, 0.80)]:   # eyes-closed style boosts
            alpha_env[int(c0 * n):int(c1 * n)] *= 2.2
    # slow waves grow toward the end when drowsy
    delta_env = (0.4 + 1.6 * (t / max(t[-1], 1e-9))) if paradigm == "drowsy" else np.ones(n)

    # Shared band-limited sources projected onto the scalp with topographic gains,
    # plus independent 1/f noise per channel.
    alpha_src = _band_noise(n, sfreq, 8.0, 12.0, rng) * alpha_env
    delta_src = _band_noise(n, sfreq, 1.0, 4.0, rng) * delta_env
    theta_src = _band_noise(n, sfreq, 4.0, 8.0, rng)
    beta_src = _band_noise(n, sfreq, 13.0, 30.0, rng)

    for i, name in enumerate(ch_names):
        post = 1.0 if name in _POSTERIOR else 0.18
        front = 1.0 if name in _FRONTAL else 0.3
        data[i] = (8.0 * _pink_noise(n, rng)
                   + post * alpha_amp * alpha_src
                   + delta_amp * delta_src
                   + front * 4.0 * theta_src
                   + beta_amp * rng.uniform(0.7, 1.3) * beta_src)

    # ---- events + task-locked activity ------------------------------------ #
    onsets_all: list[float] = []
    descs: list[str] = []

    if paradigm == "oddball":
        soa = 1.2
        onsets = np.arange(2.0, n_seconds - 1.5, soa)
        is_target = rng.random(onsets.size) < 0.15
        onsets_all = list(onsets)
        descs = ["stim/target" if k else "stim/standard" for k in is_target]
        # a genuine P300: centro-parietal positivity ~350 ms after targets only
        _add_event_response(data, ch_names, sfreq, onsets[is_target], _P300_GAIN,
                            amp=6.0, latency=0.35, width=0.07, rng=rng)
        # small sensory response to every stimulus
        _add_event_response(data, ch_names, sfreq, onsets, {"Cz": 0.6, "Fz": 0.5, "Pz": 0.4},
                            amp=2.0, latency=0.12, width=0.03, rng=rng)

    elif paradigm == "motor_imagery":
        soa = 5.0
        onsets = np.arange(3.0, n_seconds - soa, soa)
        side = rng.integers(0, 2, onsets.size)          # 0 = left, 1 = right
        onsets_all = list(onsets)
        descs = ["cue/left" if s == 0 else "cue/right" for s in side]
        # mu/beta ERD contralateral to the imagined hand (left hand -> C4)
        erd = {name: np.ones(n) for name in ("C3", "C4")}
        for onset, s in zip(onsets, side):
            a, b = int((onset + 0.5) * sfreq), int((onset + 3.5) * sfreq)
            target = "C4" if s == 0 else "C3"
            erd[target][a:min(b, n)] *= 0.35
        mu_src = _band_noise(n, sfreq, 9.0, 13.0, rng)
        smr_src = _band_noise(n, sfreq, 18.0, 25.0, rng)
        for i, name in enumerate(ch_names):
            if name not in erd:
                continue
            data[i] += 14.0 * erd[name] * mu_src + 7.0 * erd[name] * smr_src

    # ---- artifacts --------------------------------------------------------- #
    n_blinks = int(n_seconds * blink_rate)
    blink_times = np.sort(rng.uniform(0, n_seconds, n_blinks))
    span = np.linspace(-0.2, 0.4, int(0.6 * sfreq))
    blink = np.exp(-(span ** 2) / (2 * 0.06 ** 2))
    for i, name in enumerate(ch_names):
        gain = _BLINK_GAIN.get(name, 0.05)
        if gain <= 0.05:
            continue
        for bt in blink_times:
            s0 = int((bt - 0.2) * sfreq)
            s1 = s0 + blink.size
            if s0 < 0 or s1 > n:
                continue
            data[i, s0:s1] += gain * 90.0 * blink * rng.uniform(0.8, 1.2)

    if paradigm == "artifact_heavy":
        # dead channels, one very noisy channel, slow drift, muscle bursts
        for dead in ("T7", "P8"):
            if dead in ch_names:
                data[ch_names.index(dead)] = 0.02 * rng.standard_normal(n)
        if "F8" in ch_names:
            data[ch_names.index("F8")] += 120.0 * rng.standard_normal(n)
        data += (220.0 * np.sin(2 * np.pi * 0.08 * t + rng.uniform(0, 6.28)))[None, :]
        for _ in range(int(n_seconds / 8)):
            s0 = int(rng.uniform(0, max(1.0, n_seconds - 3.0)) * sfreq)
            s1 = min(n, s0 + int(2.0 * sfreq))
            data[:, s0:s1] += 60.0 * rng.standard_normal((n_ch, s1 - s0))

    if line_freq and mains_amp > 0:
        for h in (1, 2):
            data += (mains_amp / h) * np.sin(2 * np.pi * line_freq * h * t)[None, :]

    data *= 1e-6  # µV -> V

    info = mne.create_info(ch_names, sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info, verbose="ERROR")
    raw.set_montage("standard_1020", on_missing="ignore", verbose="ERROR")

    if onsets_all:
        raw.set_annotations(mne.Annotations(
            onset=np.asarray(onsets_all), duration=np.zeros(len(onsets_all)),
            description=descs))

    return raw, {
        "paradigm": paradigm,
        "label": spec["label"],
        "blurb": spec["blurb"],
        "n_events": len(onsets_all),
        "line_freq": line_freq,
        "synthetic": True,
        "notes": f"Synthetic {spec['label'].lower()} — generated by NeuroForge.",
    }
