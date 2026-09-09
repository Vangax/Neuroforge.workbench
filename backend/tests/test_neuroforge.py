# Test suite. Persistence is isolated to a temp dir via NEUROFORGE_DATA, set
# before any neuroforge import so the global settings pick it up.
import os
import math
import time
import tempfile

os.environ["NEUROFORGE_DATA"] = tempfile.mkdtemp(prefix="nf_test_")

import numpy as np
import pytest

from neuroforge.core import loaders, dsp, montage, pipeline, features, decoding, synthetic
from neuroforge.core.store import Store
from neuroforge.core.registry import Registry


def _syn(seconds=15, seed=11):
    return loaders.make_synthetic(seed=seed, n_seconds=seconds)


def test_synthetic_shape():
    raw, info = synthetic.generate(n_seconds=10, seed=0)
    assert raw.info["sfreq"] == 256
    assert len(raw.ch_names) == 32
    assert info["n_events"] > 0


def test_neurodata_window_and_metadata():
    nd = _syn(20, 4)
    w = nd.get_window(start=0, duration=5, max_points=500)
    assert len(w["times"]) <= 500
    assert len(w["data"]) == nd.n_channels
    md = nd.metadata_dict()
    assert md["n_channels"] == 32 and md["duration"] > 0


def test_montage_projection_in_disk():
    pos = montage.project_2d(montage.DEFAULT_32)
    assert len(pos) == 32
    for x, y in pos.values():
        assert math.hypot(x, y) < 1.6


def test_dsp_psd_band_topo():
    nd = _syn(15, 1)
    p = dsp.compute_psd(nd.raw)
    assert len(p["freqs"]) > 0 and len(p["psd_db"]) == 32
    bp = dsp.band_powers(nd.raw)
    assert {"alpha", "beta", "delta"} <= set(bp["bands"])
    tm = dsp.topomap_grid(nd.raw, fmin=8, fmax=13, resolution=20)
    assert tm["resolution"] == 20 and len(tm["positions"]) > 0


def test_pipeline_creates_derivative():
    nd = _syn(15, 7)
    new, qc = pipeline.run_pipeline(nd, [
        {"op": "filter", "params": {"l_freq": 1.0, "h_freq": 40.0}},
        {"op": "notch", "params": {"freq": 50}},
    ])
    assert new.id != nd.id
    assert qc["psd_after"]["mean"]
    assert any(p.op.startswith("prep:") for p in new.provenance)


def test_features_and_connectivity():
    nd = _syn(15, 2)
    f = features.channel_features(nd.raw)
    assert len(f["rows"]) == nd.n_channels and "higuchi" in f["columns"]
    c = features.connectivity(nd.raw, "plv", "alpha")
    m = c["matrix"]
    assert abs(m[0][1] - m[1][0]) < 1e-9          # symmetric
    assert 0.0 <= c["density"] <= 1.0


def test_decoding_metrics_valid():
    nd = _syn(30, 11)
    r = decoding.decode(nd.raw, classifier="lda", folds=3)
    assert 0.0 <= r["accuracy"] <= 1.0
    assert -1.0 <= r["kappa"] <= 1.0
    assert r["n_epochs"] > 10
    assert np.array(r["confusion"]).shape == (2, 2)


def test_store_roundtrip_and_lazy():
    d = tempfile.mkdtemp()
    store = Store(os.path.join(d, "t.db"), d)
    nd = _syn(10, 5)
    store.save(nd)
    assert nd.fif_path and os.path.exists(nd.fif_path)

    fresh = Store(os.path.join(d, "t.db"), d)
    items = {x.id: x for x in fresh.load_all()}
    assert nd.id in items
    got = items[nd.id]
    assert not got.loaded                          # lazy: nothing read yet
    assert got.metadata_dict()["n_channels"] == 32  # served from cached summary
    assert not got.loaded                          # still lazy
    assert got.raw.info["sfreq"] == nd.sfreq       # now reads the FIF
    assert got.loaded

    fresh.delete(nd.id)
    assert not os.path.exists(nd.fif_path)


def test_registry_survives_restart():
    d = tempfile.mkdtemp()
    reg = Registry()
    reg.attach(Store(os.path.join(d, "r.db"), d))
    nd = _syn(10, 3)
    reg.add(nd)

    reg2 = Registry()
    reg2.attach(Store(os.path.join(d, "r.db"), d))
    assert any(x.id == nd.id for x in reg2.all())
    assert reg2.tree()  # tree builds from cached summaries without loading FIFs


def test_api_endpoints():
    from fastapi.testclient import TestClient
    from neuroforge.main import app
    with TestClient(app) as c:
        assert c.get("/api/health").json()["n_datasets"] >= 3
        ds = c.get("/api/datasets").json()["datasets"]
        did = ds[0]["id"]
        assert c.get(f"/api/signal/{did}/window?duration=2").status_code == 200
        assert c.get(f"/api/spectral/{did}/topomap?resolution=16").status_code == 200
        assert c.get("/api/preprocess/catalog").status_code == 200
        assert c.get("/api/bci/classifiers").status_code == 200


def test_loaders_format_registry():
    fmts = {f["ext"]: f["status"] for f in loaders.supported_formats()}
    assert fmts[".edf"] == "ready" and fmts[".fif"] == "ready"
    with pytest.raises(NotImplementedError):
        loaders.load_file("x.nwb")


def _wait(jm, jid, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        j = jm.get(jid)
        if j and j.status in ("done", "error"):
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_job_manager():
    from neuroforge.core.jobs import JobManager
    jm = JobManager(workers=1)
    ok = jm.submit("t", lambda: 21 * 2)
    assert _wait(jm, ok.id).result == 42
    bad = jm.submit("t", lambda: 1 / 0)
    assert _wait(jm, bad.id).status == "error"


def test_security_roles():
    from fastapi import HTTPException
    from neuroforge.core.security import require, auth
    dep = require("analyst")
    auth.enabled = False
    assert dep(None) == "admin"                 # disabled -> open
    auth.enabled, auth.tokens = True, {"a": "admin", "v": "viewer"}
    with pytest.raises(HTTPException):
        dep(None)                               # missing token -> 401
    with pytest.raises(HTTPException):
        dep("Bearer v")                         # viewer < analyst -> 403
    assert dep("Bearer a") == "admin"
    auth.enabled, auth.tokens = False, {}        # restore for other tests


def test_api_async_job_and_system():
    from fastapi.testclient import TestClient
    from neuroforge.main import app
    with TestClient(app) as c:
        did = c.get("/api/datasets").json()["datasets"][0]["id"]
        r = c.post(f"/api/preprocess/{did}/run",
                   json={"steps": [{"op": "filter", "params": {"l_freq": 1.0, "h_freq": 40.0}}]})
        assert r.status_code == 200
        jid = r.json()["job_id"]
        end = time.time() + 15
        jr = {}
        while time.time() < end:
            jr = c.get(f"/api/jobs/{jid}").json()
            if jr["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert jr["status"] == "done"
        assert "dataset" in jr["result"] and "qc" in jr["result"]

        sysr = c.get("/api/system").json()
        assert sysr["datasets"] >= 3 and "jobs" in sysr and "auth_enabled" in sysr


def test_script_store():
    from neuroforge.core.scripts import ScriptStore
    ss = ScriptStore(os.path.join(tempfile.mkdtemp(), "sc.db"))
    s = ss.save("t", "desc", "result = 1")
    assert s["id"] and s["name"] == "t"
    assert any(x["id"] == s["id"] for x in ss.list())
    assert ss.get(s["id"])["code"] == "result = 1"
    ss.delete(s["id"])
    assert ss.get(s["id"]) is None


def test_script_run_subprocess():
    from neuroforge.core import scripts
    from neuroforge.core.store import Store
    d = tempfile.mkdtemp()
    Store(os.path.join(d, "s.db"), d).save(nd := _syn(10, 8))  # sets fif_path
    out = scripts.run_script(nd, "result = {'n': len(raw.ch_names), 'sf': raw.info['sfreq']}", {})
    assert out["ok"] is True and out["result"]["n"] == 32
    bad = scripts.run_script(nd, "1/0", {})
    assert bad["ok"] is False and "error" in bad


def test_api_script_run():
    from fastapi.testclient import TestClient
    from neuroforge.main import app
    with TestClient(app) as c:
        did = c.get("/api/datasets").json()["datasets"][0]["id"]
        assert c.get("/api/scripts").status_code == 200
        r = c.post("/api/scripts/run",
                   json={"dataset_id": did, "code": "result = {'m': float(raw.get_data().mean())}"})
        assert r.status_code == 200
        jid = r.json()["job_id"]
        end, jr = time.time() + 30, {}
        while time.time() < end:
            jr = c.get(f"/api/jobs/{jid}").json()
            if jr["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert jr["status"] == "done" and jr["result"]["ok"] is True
        assert "m" in jr["result"]["result"]


def test_raw_cache_eviction():
    from neuroforge.core.cache import RawCache
    from neuroforge.core.store import Store
    d = tempfile.mkdtemp()
    store = Store(os.path.join(d, "c.db"), d)
    nds = [_syn(8, 30 + i) for i in range(3)]
    for nd in nds:
        store.save(nd)          # persisted; samples freed to disk
    rc = RawCache(max_loaded=2)
    for nd in nds:
        _ = nd.raw              # reload from disk
        rc.touch(nd)
    assert len(rc.loaded_ids()) == 2
    assert nds[0]._raw is None  # least-recently-used was evicted


def test_aperiodic_1f():
    from neuroforge.core import features
    a = features.aperiodic(_syn(20, 11).raw)
    assert len(a["exponent"]) == 32
    assert a["mean"]["exponent"] > 0          # 1/f: power falls with frequency
    assert len(a["mean_psd_db"]) == len(a["freqs"])


def test_microstates():
    from neuroforge.core import features
    m = features.microstates(_syn(20, 11).raw, n_states=4)
    assert len(m["maps"]) == 4 and len(m["maps"][0]["positions"]) > 0
    assert abs(sum(m["coverage"]) - 1.0) < 1e-6      # every sample labelled
    assert 0.0 <= m["gev"] <= 1.0
    assert len(m["transitions"]) == 4 and len(m["transitions"][0]) == 4


def test_script_batch_group_and_errors():
    from neuroforge.core import scripts
    from neuroforge.core.store import Store
    d = tempfile.mkdtemp()
    store = Store(os.path.join(d, "g.db"), d)
    a, b = _syn(8, 1), _syn(8, 2)
    store.save(a); store.save(b)

    rb = scripts.run_batch([a, b], "result = {'n': len(raw.ch_names)}")
    assert rb["mode"] == "each" and rb["n"] == 2 and rb["ok"]
    assert rb["runs"][0]["result"]["n"] == 32

    rg = scripts.run_group([a, b], "result = {'k': len(raws), 'helper': nf.band_powers(raws[0])['relative']}")
    assert rg["ok"] and rg["result"]["k"] == 2

    err = scripts.run_script(a, "this is not valid python !!")
    assert err["ok"] is False and err["error_type"] == "user"


def test_montage_endpoint_and_project_raw():
    from neuroforge.core.registry import registry
    from neuroforge.core import montage
    from neuroforge.api import edit as editmod
    nd = _syn(8, 5)
    registry.add(nd)
    assert "standard_1020" in editmod.montages()["montages"]
    out = editmod.set_montage(nd.id, editmod.MontageOps(montage="standard_1020"))
    assert out["id"] != nd.id and out["n_channels"] == 32
    # project_raw uses the recording's own positions
    pos = montage.project_raw(nd.raw)
    assert len(pos) == 32


def test_erp_spatiotemporal_clusters():
    from neuroforge.core.registry import registry
    from neuroforge.api import erp as erpmod
    nd = _syn(30, 12)
    registry.add(nd)
    res = erpmod.compute(nd.id, erpmod.ERPRequest())
    assert res["conditions"] and "times_ms" in res
    if "difference" in res:
        assert "cluster_method" in res        # spatio-temporal (or 1-D fallback)


def test_xdf_reader_converts_streams_and_markers(monkeypatch):
    # pyxdf has no writer, so feed the reader a fabricated LSL stream set and
    # check the conversion: channel labels, rate, µV->V scaling and markers.
    import pyxdf
    from neuroforge.core import loaders
    sf, n = 250.0, 500
    eeg = {
        "info": {"type": ["EEG"], "nominal_srate": [str(sf)],
                 "desc": [{"channels": [{"channel": [
                     {"label": ["Cz"], "unit": ["microvolts"]},
                     {"label": ["Pz"], "unit": ["microvolts"]}]}]}]},
        "time_series": (np.random.default_rng(0).standard_normal((n, 2)) * 20.0),
        "time_stamps": 1000.0 + np.arange(n) / sf,
    }
    markers = {
        "info": {"type": ["Markers"], "nominal_srate": ["0"], "desc": [{}]},
        "time_series": [["go"], ["stop"]],
        "time_stamps": np.array([1000.5, 1001.5]),
    }
    monkeypatch.setattr(pyxdf, "load_xdf", lambda *a, **k: ([eeg, markers], {}))

    raw = loaders.read_xdf("dummy.xdf")
    assert raw.ch_names == ["Cz", "Pz"]
    assert abs(raw.info["sfreq"] - sf) < 1e-6
    assert np.abs(raw.get_data()).max() < 1e-3          # scaled to volts, not µV
    assert list(raw.annotations.description) == ["go", "stop"]
    assert abs(raw.annotations.onset[0] - 0.5) < 0.01   # aligned to stream start
    assert ".xdf" in {f["ext"] for f in loaders.supported_formats() if f["status"] == "ready"}


def test_autoanalysis_synthetic():
    import json
    from neuroforge.core import autoanalysis
    nd = loaders.make_synthetic(subject="01", session="01", task="oddball", seed=12, n_seconds=60.0)
    r = autoanalysis.analyze(nd)

    assert set(["dataset", "summary", "recording_type", "health", "findings",
                "next_steps", "evidence"]) <= set(r)
    # synthetic data is an oddball-style event stream
    assert r["recording_type"]["code"] in ("oddball", "erp_paradigm")
    assert r["recording_type"]["why"]
    # health is a bounded score with per-check detail
    assert 0 <= r["health"]["score"] <= 100
    ids = {c["id"] for c in r["health"]["checks"]}
    assert {"bad_channels", "line_noise", "blinks", "trials"} <= ids
    # the generator injects 50 Hz mains -> must be caught
    mains = next(c for c in r["health"]["checks"] if c["id"] == "line_noise")
    assert mains["status"] in ("warn", "fail") and mains["value"] > 5
    # every finding carries evidence the UI can plot
    assert r["findings"] and all("evidence" in f and "plain" in f for f in r["findings"])
    assert r["next_steps"]
    json.dumps(r)          # must survive the API boundary


def test_autoanalysis_recovers_events_from_stim_channels():
    # BCI2000-style files put the paradigm in stim channels, not annotations
    from pathlib import Path
    from neuroforge.core import autoanalysis
    p = Path(__file__).resolve().parents[2] / "test" / "A_01_SE001_CB_Test08.edf"
    if not p.exists():
        pytest.skip("BigP3BCI test file not present")
    nd = loaders.load_file(str(p))
    r = autoanalysis.analyze(nd)

    assert r["dataset"]["n_channels"] == 32          # only the real EEG is analysed
    assert r["dataset"]["n_channels_total"] == 114
    assert "stim channel" in r["dataset"]["event_source"]
    assert r["dataset"]["n_events"] > 100
    assert r["recording_type"]["code"] in ("oddball", "erp_paradigm")
    trials = next(c for c in r["health"]["checks"] if c["id"] == "trials")
    assert trials["status"] == "ok"                  # 70 targets / 770 non-targets


def test_real_edf_channel_detection():
    # BigP3BCI: 114 channels, 32 real EEG (prefixed EEG_) + speller/state channels
    from pathlib import Path
    from neuroforge.core import loaders, features
    p = Path(__file__).resolve().parents[2] / "test" / "A_01_SE001_CB_Test08.edf"
    if not p.exists():
        pytest.skip("BigP3BCI test file not present")
    nd = loaders.load_file(str(p))
    det = nd.extra["channel_detection"]
    assert det["n_total"] == 114
    assert det["n_eeg"] == 32 and det["auto_detected"] is True
    assert "Fz" in nd.raw.ch_names and "EEG_Fz" not in nd.raw.ch_names   # renamed
    assert len(nd.topomap_positions()) >= 30                              # real montage
    assert len(features.channel_features(nd.raw)["rows"]) == 32           # analysis uses the 32 EEG


def test_bad_channel_detection_ground_truth():
    """Exactly the broken channels, and nothing else.

    The artifact_heavy generator kills T7/P8 and makes F8 noisy. Every other
    paradigm is clean — flagging a good channel silently deletes real data, so
    a false positive is the more serious failure of the two.
    """
    from neuroforge.core import samples
    from neuroforge.core.features import analysis_picks

    def bads(pid, seed, filtered):
        raw = analysis_picks(samples.build(pid, seed=seed).raw)
        if filtered:
            raw = raw.copy().filter(1.0, 40.0, verbose="ERROR")
        return pipeline.detect_bad_channels(raw)

    # Filtered is the case that matters: the recommended pipeline always band-passes
    # before detecting, because drift makes every channel correlate with every other.
    assert set(bads("artifact_heavy", 7, True)) == {"F8", "T7", "P8"}
    assert set(bads("artifact_heavy", 21, True)) == {"F8", "T7", "P8"}
    assert set(bads("artifact_heavy", 21, False)) == {"F8", "T7", "P8"}

    for pid in ("resting_closed", "resting_open", "oddball", "motor_imagery", "drowsy"):
        for filt in (False, True):
            clean = bads(pid, 7, filt)
            assert clean == [], f"{pid} (filtered={filt}) should be clean, got {clean}"


def test_blink_rate_falls_after_ica_removes_blinks():
    """A purely relative threshold shrinks with the data and reports the same
    blink rate on a cleaned recording. The absolute floor is what stops that."""
    from neuroforge.core import samples, autoanalysis
    from neuroforge.core.features import analysis_picks

    nd = samples.build("resting_open", seed=7)

    def rate(d):
        raw = analysis_picks(d.raw)
        m = autoanalysis._measure(raw)
        return autoanalysis._blink_rate(raw, m["groups"]["frontal"], m["groups"]["posterior"], m["sfreq"])

    before = rate(nd)
    assert before > 10                                  # the generator injects 21/min

    cleaned, qc = pipeline.run_pipeline(nd, [
        {"op": "filter", "params": {"l_freq": 1.0, "h_freq": 40.0}},
        {"op": "ica", "params": {"n_components": 15, "method": "fastica", "eog_ch": "Fp1"}},
    ])
    assert qc["ica_excluded"], "ICA should have found an ocular component"
    assert rate(cleaned) < before / 2


def test_health_grade_is_capped_by_failures():
    from neuroforge.core import samples, autoanalysis
    r = autoanalysis.analyze(samples.build("artifact_heavy", seed=7))
    assert r["health"]["n_fail"] >= 2
    assert r["health"]["grade"] == "poor"       # two failures cannot average out to "fair"

    clean = autoanalysis.analyze(samples.build("resting_closed", seed=7))
    assert clean["health"]["n_fail"] == 0 and clean["health"]["grade"] == "excellent"


def test_recommended_cleanup_is_ordered_and_honest():
    from neuroforge.core import samples, autoanalysis
    r = autoanalysis.analyze(samples.build("artifact_heavy", seed=7))
    ops = [s["op"] for s in r["cleanup"]["steps"]]

    assert ops[0] == "filter"                                   # drift out before ICA
    assert ops.index("detect_bads") < ops.index("interpolate")
    assert ops.index("interpolate") < ops.index("reference")     # no dead channel in the average
    assert all(s["why"] for s in r["cleanup"]["steps"])          # every step justified
    # 40 Hz low-pass already removes 50 Hz, so the notch must be declined, not applied
    assert "notch" not in ops
    assert any("otch" in s for s in r["cleanup"]["skipped"])


def test_reproduction_script_matches_the_engine(tmp_path):
    """The generated script must reproduce the derivative byte for byte.

    A script that merely looks plausible is worse than none — it would let someone
    publish a pipeline that is not the one that produced the numbers.
    """
    import subprocess
    import sys
    from pathlib import Path
    from neuroforge.core import repro

    src = Path(__file__).resolve().parents[2] / "test" / "A_01_SE001_CB_Test08.edf"
    if not src.exists():
        pytest.skip("BigP3BCI test file not present")

    nd = loaders.load_file(str(src))
    derived, qc = pipeline.run_pipeline(nd, [
        {"op": "filter", "params": {"l_freq": 1.0, "h_freq": 40.0}},
        {"op": "detect_bads", "params": {"z": 4.0, "corr": 0.15}},
        {"op": "interpolate", "params": {}},
        {"op": "reference", "params": {"mode": "average"}},
    ])
    derived.source_path = nd.source_path

    script = tmp_path / "reproduce.py"
    script.write_text(repro.build_script(derived, filename="reproduce.py"), encoding="utf-8")

    # the load-time channel identification must be in there, or the script silently
    # analyses 114 "EEG" channels that are really BCI2000 state channels
    text = script.read_text(encoding="utf-8")
    assert "set_channel_types" in text and "rename_channels" in text

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run([sys.executable, "-W", "ignore", str(script)],
                         capture_output=True, text=True, timeout=600, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "MATCH" in out.stdout and "DIFFERENT" not in out.stdout


def test_doctor_reports_actionable_checks():
    from neuroforge.core import doctor
    from neuroforge.config import settings
    d = doctor.run(settings)
    assert d["status"] in ("ok", "warn", "fail")
    ids = {c["id"] for c in d["checks"]}
    assert {"python", "numpy", "mne", "sqlite", "data_dir"} <= ids
    # anything not ok must come with a command the user can actually run
    assert all(c["fix"] for c in d["checks"] if c["status"] != "ok")


def test_samples_catalog_and_build():
    from neuroforge.core import samples
    cat = samples.catalog()
    ids = {s["id"] for s in cat}
    assert {"resting_closed", "oddball", "artifact_heavy", "physionet_mi"} <= ids
    assert all(s["label"] and s["blurb"] and s["kind"] in ("synthetic", "download") for s in cat)

    nd = samples.build("oddball", seed=3)
    assert nd.n_channels > 8 and nd.duration > 30
    assert nd.extra["sample_id"] == "oddball"


def test_cleaning_never_makes_a_metric_look_worse():
    """The contract that keeps the tool trustworthy.

    Every health metric that used a threshold relative to the recording's own
    background inverted after a successful cleanup: the background dropped, the
    threshold dropped with it, and the tool reported *more* muscle and the same
    blink rate on data it had just cleaned. Anchoring those detectors to physiology
    instead of to themselves is what makes 'apply cleanup' verifiable.
    """
    from neuroforge.core import samples, autoanalysis

    nd = samples.build("artifact_heavy", seed=21)
    before = autoanalysis.analyze(nd)
    steps = [{"op": s["op"], "params": s["params"]} for s in before["cleanup"]["steps"]]
    cleaned, _ = pipeline.run_pipeline(nd, steps)
    after = autoanalysis.analyze(cleaned)

    assert after["health"]["score"] > before["health"]["score"]
    assert after["health"]["n_fail"] < before["health"]["n_fail"]

    b = {c["id"]: c for c in before["health"]["checks"]}
    a = {c["id"]: c for c in after["health"]["checks"]}
    rank = {"ok": 0, "warn": 1, "fail": 2, "na": 0}
    for cid in ("line_noise", "drift", "muscle", "blinks", "bad_channels"):
        assert rank[a[cid]["status"]] <= rank[b[cid]["status"]], (
            f"{cid} got worse after cleaning: {b[cid]['status']} -> {a[cid]['status']}")


def test_muscle_and_blink_detectors_are_quiet_on_clean_data():
    """No false alarms on five clean paradigms or on a real recording."""
    from pathlib import Path
    from neuroforge.core import samples, autoanalysis
    from neuroforge.core.features import analysis_picks

    for pid in ("resting_closed", "resting_open", "oddball", "motor_imagery", "drowsy"):
        raw = analysis_picks(samples.build(pid, seed=7).raw)
        assert autoanalysis._muscle_fraction(raw, raw.info["sfreq"]) < 0.02, pid

    p = Path(__file__).resolve().parents[2] / "test" / "A_01_SE001_CB_Test08.edf"
    if p.exists():
        raw = analysis_picks(loaders.load_file(str(p)).raw)
        assert autoanalysis._muscle_fraction(raw, raw.info["sfreq"]) < 0.02


def test_bids_entity_parsing():
    from neuroforge.core import bids
    e = bids.parse_entities("study/sub-07/ses-02/eeg/sub-07_ses-02_task-rest_run-03_eeg.edf")
    assert (e.subject, e.session, e.task, e.run) == ("07", "02", "rest", "03")

    # directory structure alone still identifies the subject
    e = bids.parse_entities("study/sub-12/oddball.edf")
    assert e.subject == "12" and e.task == "oddball"

    # nothing to infer -> no invention
    e = bids.parse_entities("random.edf")
    assert e.subject == "imported" and e.session is None


def test_bids_export_import_roundtrip(tmp_path):
    """Export a cohort, scan it back, and get the same entities out."""
    from neuroforge.core import bids, samples
    from neuroforge.core.neurodata import BidsEntities

    ds = []
    for i, pid in enumerate(("resting_closed", "oddball"), start=1):
        nd = samples.build(pid, seed=5)
        nd.entities = BidsEntities(subject=f"{i:02d}", session="01", task=pid[:8], run="1")
        ds.append(nd)

    out = bids.export_bids(ds, tmp_path / "bids", name="test study")
    assert out["n_written"] == 2 and out["n_subjects"] == 2 and not out["failed"]

    root = tmp_path / "bids"
    assert (root / "dataset_description.json").is_file()
    assert (root / "participants.tsv").is_file()
    assert bids.is_bids_root(root)
    # the oddball run has annotations, so it must carry an events.tsv
    assert any(p.name.endswith("_events.tsv") for p in root.rglob("*"))
    # every run carries its provenance
    assert len(list(root.rglob("*_provenance.json"))) == 2

    back = bids.scan_folder(root)
    assert len(back) == 2
    assert {c["subject"] for c in back} == {"01", "02"}
    assert all(c["session"] == "01" and c["run"] == "1" for c in back)

    loaded = bids.import_folder(root)
    assert len(loaded["loaded"]) == 2 and not loaded["failed"]
    assert {nd.entities.subject for nd in loaded["loaded"]} == {"01", "02"}


def test_cohort_table_and_outliers():
    from neuroforge.core import batch, samples

    ds = [samples.build(p, seed=7) for p in
          ("resting_closed", "resting_open", "oddball", "motor_imagery",
           "drowsy", "artifact_heavy")]
    out = batch.analyze_many(ds)

    assert len(out["rows"]) == 6 and not out["failed"]
    assert {c["key"] for c in out["columns"]} >= {"label", "health", "grade", "muscle_pct"}

    s = out["summary"]
    assert s["n"] == 6 and s["consistent"] is False      # six different paradigms
    # the deliberately broken recording must be the one that stands out
    labels = {o["label"] for o in s["outliers"]}
    noisy = next(r for r in out["rows"] if "artifact" in r["label"] or r["health"] < 60)
    assert noisy["label"] in labels
    assert all(o["reasons"] for o in s["outliers"])      # every flag is explained

    csv = batch.to_csv(out["rows"])
    assert csv.count("\n") == 7                          # header + 6 rows
    assert "Health" in csv.splitlines()[0]


def test_cohort_outliers_need_a_cohort():
    """With three runs, 'outlier' is not a meaningful word — say nothing."""
    from neuroforge.core import batch, samples
    ds = [samples.build(p, seed=7) for p in ("resting_closed", "oddball", "artifact_heavy")]
    out = batch.analyze_many(ds)
    assert out["summary"]["outliers"] == []


def test_batch_clean_improves_and_persists_nothing_unasked():
    from neuroforge.core import batch, samples
    ds = [samples.build("artifact_heavy", seed=21), samples.build("resting_closed", seed=7)]
    out = batch.clean_many(ds, None)

    assert not out["failed"]
    assert out["n_worse"] == 0                    # cleaning may not make a run worse
    broken = next(r for r in out["results"] if "noisy" in r["label"] or r["delta"] > 0)
    assert broken["delta"] > 0 and broken["new_id"]
    # originals are untouched; the derivatives are handed back for the caller to store
    assert len(out["derived"]) == sum(1 for r in out["results"] if r["new_id"])


def test_jobs_report_progress():
    import time as _t
    from neuroforge.core.jobs import JobManager

    jm = JobManager(workers=1)

    def slow(progress=None):
        for i in range(4):
            progress(i, 4, f"item {i}")
            _t.sleep(0.05)
        return "ok"

    job = jm.submit("t", slow)
    seen = False
    end = _t.time() + 10
    while _t.time() < end:
        if job.total_n == 4 and job.step:
            seen = True
        if job.status in ("done", "error"):
            break
        _t.sleep(0.01)
    assert job.status == "done" and job.result == "ok"
    assert seen and job.done_n == 4
    # a plain zero-argument task still works
    assert _wait(jm, jm.submit("t", lambda: 7).id).result == 7


def test_cli_analyze_and_doctor(capsys):
    from pathlib import Path
    from neuroforge import cli

    assert cli.main(["version"]) == 0
    assert "NeuroForge" in capsys.readouterr().out

    assert cli.main(["doctor"]) == 0            # advisories are fine, failures are not
    assert "install check" in capsys.readouterr().out

    p = Path(__file__).resolve().parents[2] / "test" / "A_01_SE001_CB_Test08.edf"
    if not p.exists():
        pytest.skip("BigP3BCI test file not present")
    assert cli.main(["analyze", str(p)]) == 0
    out = capsys.readouterr().out
    assert "WHAT IS IT" in out and "HEALTH" in out and "Oddball" in out

    assert cli.main(["analyze", str(p), "--json"]) == 0
    import json as _json
    rep = _json.loads(capsys.readouterr().out)
    assert rep["recording_type"]["code"] in ("oddball", "erp_paradigm")

    assert cli.main(["analyze", "no_such_file.edf"]) == 2


def test_api_batch_and_bids_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from neuroforge.main import app

    with TestClient(app) as c:
        ids = [d["id"] for d in c.get("/api/datasets").json()["datasets"]][:2]
        assert c.get("/api/batch/columns").json()["columns"]

        r = c.post("/api/batch/analyze", json={"dataset_ids": ids})
        assert r.status_code == 200
        jid = r.json()["job_id"]
        end = time.time() + 300
        jr = {}
        while time.time() < end:
            jr = c.get(f"/api/jobs/{jid}").json()
            if jr["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert jr["status"] == "done", jr.get("error")
        assert len(jr["result"]["rows"]) == len(ids)

        csv = c.post("/api/batch/csv", json={"rows": jr["result"]["rows"]})
        assert csv.status_code == 200 and b"Health" in csv.content

        assert c.post("/api/batch/analyze", json={"dataset_ids": []}).status_code == 400
        assert c.post("/api/batch/analyze", json={"dataset_ids": ["nope"]}).status_code == 404

        sc = c.post("/api/bids/scan", json={"path": str(tmp_path)})
        assert sc.status_code == 200 and sc.json()["n_found"] == 0
        assert c.post("/api/bids/scan", json={"path": str(tmp_path / "missing")}).status_code == 400
