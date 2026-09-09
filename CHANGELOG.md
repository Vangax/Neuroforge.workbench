# Changelog

## Unreleased — 0.2.0 (in progress)

### Install it like software, not like a repository
- **`pip install neuroforge`** — the wheel carries the built interface, so one command
  gives you the whole application with no Node on the target machine.
- **A real CLI.** Bare `neuroforge` starts the server, waits until it answers, and opens
  your browser (moving to the next free port if 8420 is busy, and saying so).
  `neuroforge analyze recording.edf` prints the full auto-analysis report to a terminal —
  no browser, no server — and `--json` makes it scriptable. `neuroforge doctor` checks
  the install; `neuroforge version` reports the stack.
- **`install.sh` / `install.ps1`** build an isolated environment from a clone, build the
  UI if Node is present, install, run the self-check and leave a launcher behind.
- Data now defaults to `~/.neuroforge/data` when installed, and stays inside the repo
  when run from a checkout — site-packages is never written to.
- `scripts/build_release.py` bundles the Vite output into the package and builds the
  wheel + sdist.

### Cohort (Module 12) — a study treated as a study
Every other module answers a question about one recording; this one answers the question
you have once you have forty.
- **Analyse the whole cohort in one job** into a single sortable table — detected
  paradigm, health score and grade, and every artifact metric per run. Exports to CSV
  exactly as filtered and sorted on screen.
- **Clean the whole cohort in one pass**, each recording getting *its own* recommended
  pipeline, then re-scored; the summary reports how many improved, were unchanged, or
  got worse.
- **Outliers that explain themselves** — robust median/MAD z, so one bad run cannot mask
  another, and a second 15%-of-median test so a tight cohort does not make trivial
  differences look significant. Under five runs it declines to guess at all.
- Mixed paradigms in one cohort are called out rather than averaged over.

### BIDS, both directions
- **Import a folder or a BIDS study by path** — scan first (what was found, what entities
  were inferred, nothing invented), deselect what you do not want, then import. Failures
  are collected per file: one unreadable recording in a study of 200 no longer costs you
  the other 199. `derivatives/`, `sourcedata/` and `code/` are skipped.
- Entities are read from BIDS filenames and fall back to the folder above.
- **Export a valid BIDS derivatives tree** — data, `channels.tsv`, `events.tsv` where
  there are annotations, sidecar JSON and the provenance log for every run, plus
  `dataset_description.json` and `participants.tsv`. Export → scan → import round-trips.

### Jobs report progress
`GET /api/jobs/{id}` now returns `done_n`, `total_n`, the current `step` and an `eta`
computed from the rate actually achieved. A task opts in simply by accepting a
`progress` argument, so every existing job keeps working untouched. Cohort runs and
folder imports show a real progress bar instead of an unmoving spinner.

### Auto-Analysis Engine (Module 00)
One call answers "what is this recording, is it usable, what next":
- **Paradigm detection** — resting state / ERP / oddball / motor imagery / sleep, ranked
  with human-readable reasons.
- **Data-health score** (0–100) — bad channels, mains interference, slow drift, muscle
  artifact %, blink rate, trials-per-condition, length and sampling rate.
- **Findings** — posterior alpha, mains peaks, drowsiness trend, P300-like responses;
  each carries the evidence needed to plot it (PSD, topography, ERP, time trend).
- **Next steps** — concrete actions that deep-link into the matching module.
- **Events from stim channels** — BCI2000/BrainVision-style files store the paradigm in
  stim channels rather than annotations; these are now recovered automatically (a P300
  speller recording was previously misread as resting state).

### Guided mode — the new default interface
Five steps, one screen at a time: **Load → Analyze → Clean → Interpret → Export**.
- **Sample gallery** — six generated paradigms (each genuinely distinguishable) plus a
  one-click PhysioNet motor-imagery download, so a first run needs no data of your own.
- **Recommended cleanup** — the health report is turned into an ordered, ready-to-run
  pipeline where every step names the measurement that justifies it, and a
  *"deliberately not doing"* list explains what was skipped and why (a 50 Hz notch is
  declined when the 40 Hz low-pass already removes it; low trial counts are named as
  something preprocessing cannot fix).
- **Fixes are verified, not asserted** — applying the cleanup re-runs the full analysis
  and shows the health score before and after (artifact-heavy sample: 50 → 66).
- Pro mode (the 12-module HUD) is untouched and one click away; the choice is remembered.

### Reproducibility
- **`GET /api/report/{id}/script`** renders a dataset's provenance as a standalone
  MNE-Python script: it reloads the source file, replays every step in order, and checks
  the result against the recorded data hash. Verified end-to-end in CI on a real
  114-channel BCI2000 EDF — the generated script reproduces the derivative byte for byte.
- Load-time channel identification is now recorded and replayed, so a script cannot
  silently analyse the 82 state channels a BCI2000 file mislabels as EEG.
- `detect_bads` and `ica` now record what they *chose* (channel names, component indices),
  not just that they ran.

### Correctness (each of these was a real wrong answer)
- **Bad-channel detection rewritten.** Statistics now run on a high-passed copy —
  on unfiltered data a shared drift makes every channel correlate at ~0.9, which flagged
  the frontal channels for containing eye blinks while the genuinely dead ones hid in the
  noise. Detection uses neighbour correlation (nearest sensors by position) with both an
  absolute floor and a recording-relative one, plus flat/quiet/loud rules. Across 13
  validation cases — six paradigms, filtered and unfiltered, and a real 114-channel
  recording — it now finds exactly the three broken channels and zero false positives.
  It also **abstains instead of truncating**: if more than a fifth of the montage looks
  broken, the heuristic is what is wrong, so it reports nothing rather than letting an
  arbitrary subset get interpolated away.
- **Muscle contamination is measured against physiology, not against itself.** The old
  `3 × median` threshold rose with the contamination it was measuring, so a recording
  that was 100% muscle-contaminated scored *better* than its own cleaned version.
  Now anchored at 10 µV in the 30–45 Hz band (scalp EEG there is 1–3 µV): the
  artifact-heavy sample reads 100% before cleaning and 26% after, and five clean
  paradigms plus a real recording all read 0%.
- **Blink detection no longer scales with its own artifact.** A purely relative threshold
  shrank as ICA cleaned the data and kept reporting the same blink rate on a cleaned
  recording. Now requires an absolute amplitude and frontal dominance: rates land within
  ~15% of ground truth and fall to zero once the ocular component is removed.
- **Health grade is capped by failures** — two failing checks can no longer average out
  to "fair" (the artifact-heavy sample now grades *poor*, as a human would call it).
- Blink thresholds relaxed to reflect that 15–20 blinks/min is a normal human.
- Findings are worded for the recording type — strong alpha in a task recording is no
  longer described as "the typical eyes-closed resting rhythm".

### Reliability & usability
- **Install self-check** (`/api/doctor`, and a badge in the top bar) — Python, NumPy/SciPy
  compatibility, MNE, metadata store, data-directory writability, optional dependencies
  and the bundled UI, each with the command that fixes it. Also logged at startup.
- **Error boundary** — a crash in one module shows what broke, with a "try again" and a
  "copy details" button, instead of a blank page.
- **Command palette** (Ctrl/⌘-K) — jump to any module, mode or dataset by name; modules
  carry search keywords, so "p300" finds the ERP module and "ica" finds Preprocessing.
- **SQLite is no longer required.** Storage goes through a small `kvstore` layer that
  falls back to JSON when the `sqlite3` stdlib module is missing, so a trimmed or broken
  Python build can no longer prevent the app from starting. Backend shown in `/api/system`.
- **One command, one URL** — the backend serves the built UI at `/`, so no second server
  or port is needed for normal use.
- **XDF (Lab Streaming Layer)** files are readable: best signal stream auto-selected,
  sampling rate derived from timestamps when `nominal_srate` is absent, marker streams
  folded into annotations.
- NumPy pinned `<2.5` to match SciPy's supported range.

## 0.1.0 — first public release

First end-to-end release: a BIDS-native, MNE-powered brain-data platform with a
FastAPI backend, a React/WebGL HUD frontend, a Python client, and a test suite.

### Modules
- **M1 Universal Loader / BIDS repository** — EDF/BDF/GDF/BrainVision/EEGLAB/FIFF/EGI
  via MNE; synthetic generator; subject/session tree; durable SQLite + FIF store.
- **M2 Interactive visualization** — multichannel viewer, Welch/multitaper PSD,
  inferno topomap, 3D head, band-power matrix, real-time scroll.
- **M3 Preprocessing** — visual pipeline (re-ref/filter/notch/resample/bad-channels/ICA),
  before/after QC, non-destructive derivatives.
- **M4 ERP/ERF** — epoching, condition averages, GFP, peaks, difference waves,
  **spatio-temporal cluster permutation** stats, difference topographies.
- **M5 Signal analyzer** — Hjorth/entropy/Higuchi/DFA, spectral metrics,
  PLV/PLI/wPLI/coherence + connectogram + graph metrics, **aperiodic 1/f (specparam)**,
  **EEG microstates**.
- **M6 Cross-session mapper** — cohort dashboard, datasets×channels map, similarity.
- **M7 Benchmarking** — pipeline shootout, data-quality QC, reproducibility hash.
- **M8 BCI workbench** — CSP / Riemannian decoding, accuracy/κ/AUC/ITR, confusion, CSP maps.
- **M9 Data editor** — channel/crop/annotation edits, **set-montage**, versioned derivatives.
- **M10 Reporting/export** — HTML report, FIF/CSV/NumPy/HDF5/EDF export.
- **M11 Code Lab** — run custom Python in an isolated subprocess, across one or many
  datasets (each/group), `nf.*` engine helpers, save/reuse scripts.

### Platform
- Background **job queue** for heavy ops; **token + RBAC** auth (opt-in); structured
  logging + request IDs; **LRU memory** cache + lazy FIF loading; upload limits +
  integrity checks; `/api/system`; **Python client SDK**; Docker + compose + GitHub CI.

### Real-data handling
- **Automatic channel detection**: identifies real EEG among mixed channels (e.g. a
  114-channel BigP3BCI EDF → 32 EEG, renamed from `EEG_*`, montaged; the rest typed
  stim/misc), so analyses use the right channels automatically.
- Topographies use the **recording's own electrode positions** (any cap), not a fixed layout.
- Imports are named from the source filename.

### Known limitations (see README → Production readiness)
Single-node in-process job queue; scripting isolation is for trusted users; no source
localization / mne-bids / ICLabel yet; single very large files still load fully.
