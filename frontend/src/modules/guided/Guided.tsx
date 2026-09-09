/* Guided mode — the default face of NeuroForge.
 *
 * Five steps, one screen at a time, answers instead of controls:
 *   01 Load  ▸  02 Analyze  ▸  03 Clean  ▸  04 Interpret  ▸  05 Export
 *
 * Everything here is a thin shell over the same endpoints Pro mode uses; nothing
 * is computed twice and nothing is hidden — every step names the dataset it is
 * acting on and every claim keeps its evidence plot.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, Spinner, Chip } from "../../components/hud";
import { api, type DatasetMeta } from "../../api/client";
import {
  mod, type AutoReport, type CleanupStep, type SampleItem, type QC,
} from "../../api/modules";
import { AutoReportView } from "../auto/AutoAnalysis";
import FolderImport from "../../components/FolderImport";

const STEPS = [
  { id: 0, idx: "01", label: "Load", hint: "bring in a recording" },
  { id: 1, idx: "02", label: "Analyze", hint: "what is this data?" },
  { id: 2, idx: "03", label: "Clean", hint: "fix what's wrong" },
  { id: 3, idx: "04", label: "Interpret", hint: "what's notable" },
  { id: 4, idx: "05", label: "Export", hint: "take it with you" },
];

const GRADE_COLOR: Record<string, string> = {
  excellent: "#36d6c0", good: "#36d6c0", fair: "var(--gold)", poor: "var(--crimson)",
};

interface Props {
  datasets: DatasetMeta[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onChanged: () => Promise<void> | void;
  onNavigate: (moduleId: string) => void;
  onExit: () => void;
}

export default function Guided({ datasets, selectedId, onSelect, onChanged, onNavigate, onExit }: Props) {
  const [step, setStep] = useState(0);
  const [report, setReport] = useState<AutoReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cleaned, setCleaned] = useState<{ before: number; after: number; qc: QC; id: string } | null>(null);
  const analysedFor = useRef<string | null>(null);

  const selected = datasets.find((d) => d.id === selectedId) ?? null;

  const analyze = useCallback(async (id: string) => {
    setBusy("Reading the signal — spectra, artifacts, events, evoked response");
    setErr(null);
    try {
      const r = await mod.autoAnalyze(id);
      setReport(r);
      analysedFor.current = id;
    } catch (e) { setErr(String(e)); }
    setBusy(null);
  }, []);

  // Step 02 runs itself. That is the whole point of guided mode.
  useEffect(() => {
    if (step === 1 && selectedId && analysedFor.current !== selectedId && !busy) analyze(selectedId);
  }, [step, selectedId, analyze, busy]);

  const pick = async (id: string) => {
    onSelect(id);
    setReport(null); setCleaned(null); analysedFor.current = null;
    setStep(1);
  };

  // 02 needs a dataset; 03–05 need a finished report to act on.
  const unlocked = report && !report.error ? 4 : selected ? 1 : 0;
  const goto = (s: number) => { if (s <= unlocked) setStep(s); };

  return (
    <div className="col" style={{ gap: 18, maxWidth: 1180, margin: "0 auto", width: "100%" }}>
      <Header selected={selected} onExit={onExit} />
      <Stepper step={step} onStep={goto} unlocked={unlocked} />

      {err && (
        <Panel tag="!" title="something went wrong">
          <pre style={{ margin: 0, fontSize: 11, color: "var(--crimson-hi)", whiteSpace: "pre-wrap" }}>{err}</pre>
        </Panel>
      )}
      {busy && <Spinner label={busy} />}

      {!busy && step === 0 && (
        <StepLoad datasets={datasets} onPicked={pick} onChanged={onChanged} setErr={setErr} setBusy={setBusy} />
      )}
      {!busy && step === 1 && (
        <StepAnalyze report={report} onNext={() => setStep(2)} onRerun={() => selectedId && analyze(selectedId)} />
      )}
      {!busy && step === 2 && (
        <StepClean
          report={report} datasetId={selectedId} cleaned={cleaned}
          onApplied={async (res) => {
            setCleaned(res); await onChanged(); onSelect(res.id);
            analysedFor.current = res.id;
          }}
          setReport={setReport} setBusy={setBusy} setErr={setErr}
          onNext={() => setStep(3)} onSkip={() => setStep(3)}
        />
      )}
      {!busy && step === 3 && report && (
        <StepInterpret report={report} onNavigate={onNavigate} onNext={() => setStep(4)} />
      )}
      {!busy && step === 4 && selected && report && (
        <StepExport dataset={selected} report={report} onNavigate={onNavigate} />
      )}
      {!busy && step > 0 && !err && (!selected || (step > 1 && !report)) && (
        <Panel tag="—" title="nothing to show yet">
          <div className="placeholder-note">
            {selected ? "Run step 02 first — the rest of the flow works from that report."
                      : "Go back to step 01 and load a recording."}
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn sm" onClick={() => setStep(selected ? 1 : 0)}>
              ◂ back to step {selected ? "02" : "01"}
            </button>
          </div>
        </Panel>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ header */
function Header({ selected, onExit }: { selected: DatasetMeta | null; onExit: () => void }) {
  return (
    <div className="row wrap" style={{ gap: 14, alignItems: "flex-end" }}>
      <div className="col" style={{ gap: 3 }}>
        <span className="disp" style={{ fontSize: 24, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--hot)" }}>
          Guided
        </span>
        <span className="tiny dim">
          {selected
            ? `${selected.label} · ${selected.n_channels} ch · ${selected.duration.toFixed(0)} s · ${selected.sfreq} Hz`
            : "load a recording and NeuroForge will tell you what it is"}
        </span>
      </div>
      <button className="btn sm" style={{ marginLeft: "auto" }} onClick={onExit}
        title="the full 12-module HUD — nothing here is hidden from it">
        pro mode ▸
      </button>
    </div>
  );
}

/* ----------------------------------------------------------------- stepper */
function Stepper({ step, onStep, unlocked }: { step: number; onStep: (s: number) => void; unlocked: number }) {
  return (
    <div className="row" style={{ gap: 0, flexWrap: "wrap" }}>
      {STEPS.map((s, i) => {
        const state = i === step ? "on" : i < step ? "done" : "off";
        const locked = i > unlocked;
        return (
          <button
            key={s.id}
            disabled={locked}
            onClick={() => onStep(i)}
            className="col"
            style={{
              gap: 2, flex: 1, minWidth: 128, alignItems: "flex-start", cursor: locked ? "not-allowed" : "pointer",
              padding: "9px 12px", textAlign: "left", font: "inherit",
              background: state === "on" ? "rgba(255,47,94,0.10)" : "transparent",
              border: "1px solid var(--line)", borderLeftWidth: i === 0 ? 1 : 0,
              borderTop: `2px solid ${state === "on" ? "var(--crimson)" : state === "done" ? "var(--gold)" : "var(--line)"}`,
              opacity: locked ? 0.35 : 1,
            }}
          >
            <span className="tiny up" style={{ letterSpacing: "0.16em", color: state === "on" ? "var(--crimson-hi)" : "var(--txt-dim)" }}>
              {state === "done" ? "✓" : s.idx} {s.label}
            </span>
            <span className="tiny dim" style={{ fontSize: 10 }}>{s.hint}</span>
          </button>
        );
      })}
    </div>
  );
}

/* --------------------------------------------------------------- 01 · load */
function StepLoad({ datasets, onPicked, onChanged, setErr, setBusy }: {
  datasets: DatasetMeta[];
  onPicked: (id: string) => void;
  onChanged: () => Promise<void> | void;
  setErr: (s: string | null) => void;
  setBusy: (s: string | null) => void;
}) {
  const [samples, setSamples] = useState<SampleItem[] | null>(null);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    mod.samplesList().then((r) => setSamples(r.samples)).catch(() => setSamples([]));
  }, []);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setErr(null); setBusy(`Importing ${files[0].name}`);
    let last: string | null = null;
    for (const f of Array.from(files)) {
      const r = await api.upload(f, {});
      if (!r.ok) { setErr(`${f.name}: ${r.detail}`); break; }
      last = r.meta?.id ?? null;
    }
    await onChanged();
    setBusy(null);
    if (last) onPicked(last);
  };

  const loadSample = async (s: SampleItem) => {
    setErr(null);
    setBusy(s.needs_network
      ? `Downloading ${s.label} — first run only, then it is cached`
      : `Generating ${s.label}`);
    try {
      const d = await mod.sampleLoad(s.id);
      await onChanged();
      setBusy(null);
      onPicked(d.id);
    } catch (e) { setErr(String(e)); setBusy(null); }
  };

  return (
    <div className="col" style={{ gap: 16 }}>
      <div
        className="panel"
        style={{
          padding: 26, cursor: "pointer", textAlign: "center",
          borderColor: over ? "var(--gold)" : "var(--line)",
          boxShadow: over ? "var(--glow-amber)" : "none",
        }}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}
      >
        <span className="corner-tr" /><span className="corner-br" />
        <div className="center col" style={{ gap: 8 }}>
          <span style={{ fontSize: 30, color: "var(--gold)" }}>⤓</span>
          <span className="up" style={{ color: over ? "var(--gold-hi)" : "var(--hot)", letterSpacing: "0.2em" }}>
            drop a recording
          </span>
          <span className="tiny dim">EDF · BDF · GDF · BrainVision · FIFF · SET · EGI · XDF</span>
        </div>
      </div>
      <input ref={fileRef} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />

      <FolderImport onImported={onChanged} />

      <Panel tag="TRY" title="…or start from something real"
        meta={samples ? `${samples.length} available` : ""}>
        {samples === null ? <Spinner label="loading gallery" /> : (
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(258px,1fr))", gap: 12 }}>
            {samples.map((s) => (
              <button key={s.id} className="col sample-card" onClick={() => loadSample(s)}
                style={{
                  gap: 7, alignItems: "flex-start", textAlign: "left", font: "inherit", cursor: "pointer",
                  padding: 13, background: "rgba(0,0,0,0.22)", border: "1px solid var(--line)",
                }}>
                <span style={{ fontSize: 13, color: "var(--gold-hi)", lineHeight: 1.35 }}>{s.label}</span>
                <span className="tiny dim" style={{ lineHeight: 1.55, flex: 1 }}>{s.blurb}</span>
                <div className="row" style={{ gap: 7, alignItems: "center" }}>
                  {s.needs_network
                    ? <Chip kind="plan">download</Chip>
                    : <Chip kind="ok">{s.duration_s ? `${s.duration_s}s` : "instant"}</Chip>}
                  <span className="tiny dim" style={{ fontSize: 10 }}>{s.task}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </Panel>

      {datasets.length > 0 && (
        <Panel tag="OPEN" title="already in your repository" meta={`${datasets.length}`}>
          <div className="row wrap" style={{ gap: 8 }}>
            {datasets.map((d) => (
              <button key={d.id} className="btn sm" onClick={() => onPicked(d.id)}>{d.label}</button>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ 02 · analyze */
function StepAnalyze({ report, onNext, onRerun }: {
  report: AutoReport | null; onNext: () => void; onRerun: () => void;
}) {
  if (!report) return <Spinner label="analyzing" />;
  if (report.error) {
    return (
      <Panel tag="!" title="nothing to analyze">
        <div className="placeholder-note">{report.error}</div>
      </Panel>
    );
  }
  const h = report.health;
  const t = report.recording_type;
  const problems = h.checks.filter((c) => c.status === "warn" || c.status === "fail");

  return (
    <div className="col" style={{ gap: 16 }}>
      <Panel tag="=" title="Here is what you have">
        <div className="col" style={{ gap: 14 }}>
          <div className="row wrap" style={{ gap: 18, alignItems: "center" }}>
            <div className="col" style={{ gap: 4, flex: 1, minWidth: 260 }}>
              <span className="disp" style={{ fontSize: 26, color: "var(--gold-hi)", letterSpacing: "0.03em" }}>
                {t.label}
              </span>
              <span className="tiny dim">{Math.round(t.confidence * 100)}% confident · {t.why[0]}</span>
            </div>
            <div className="col" style={{ alignItems: "center", gap: 2 }}>
              <span className="disp" style={{ fontSize: 46, lineHeight: 1, color: GRADE_COLOR[h.grade] ?? "var(--gold-hi)" }}>
                {h.score}
              </span>
              <span className="tiny up dim">health · {h.grade}</span>
            </div>
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.7, color: "var(--txt)" }}>
            {problems.length === 0
              ? "Every quality check passed. You can go straight to the findings."
              : <>
                  {problems.length} quality issue{problems.length > 1 ? "s" : ""} to know about
                  before you draw conclusions: {problems.map((c) => c.label.toLowerCase()).join(", ")}.
                  {" "}
                  <span className="dim">
                    {report.cleanup.steps.length
                      ? `The next step proposes ${report.cleanup.steps.length} cleanup operations for these, `
                        + "and tells you which of them preprocessing cannot touch."
                      : "None of these can be fixed by preprocessing."}
                  </span>
                </>}
          </div>
        </div>
      </Panel>

      <div className="row" style={{ gap: 10 }}>
        <button className="btn crim" onClick={onNext}>
          {problems.length ? "▸ fix these issues" : "▸ continue"}
        </button>
        <button className="btn sm" onClick={onRerun}>↻ re-analyze</button>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- 03 · fix */
function StepClean({ report, datasetId, cleaned, onApplied, setReport, setBusy, setErr, onNext, onSkip }: {
  report: AutoReport | null;
  datasetId: string | null;
  cleaned: { before: number; after: number; qc: QC; id: string } | null;
  onApplied: (r: { before: number; after: number; qc: QC; id: string }) => Promise<void> | void;
  setReport: (r: AutoReport) => void;
  setBusy: (s: string | null) => void;
  setErr: (s: string | null) => void;
  onNext: () => void; onSkip: () => void;
}) {
  const cleanup = report?.cleanup;
  const [chosen, setChosen] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (cleanup) setChosen(new Set(cleanup.steps.map((s) => s.op)));
  }, [cleanup]);

  if (!report || !cleanup) return <Spinner label="waiting for the analysis" />;

  const steps = cleanup.steps.filter((s) => chosen.has(s.op));

  const apply = async () => {
    if (!datasetId || !steps.length) return;
    setErr(null);
    setBusy(`Cleaning — ${steps.map((s) => s.label.toLowerCase()).join(", ")}`);
    try {
      const before = report.health.score;
      const { dataset, qc } = await mod.prepRun(datasetId, steps.map((s) => ({ op: s.op, params: s.params })));
      setBusy("Re-checking the cleaned data");
      const after = await mod.autoAnalyze(dataset.id);
      setReport(after);
      await onApplied({ before, after: after.health.score, qc, id: dataset.id });
    } catch (e) { setErr(String(e)); }
    setBusy(null);
  };

  if (cleaned) {
    const delta = cleaned.after - cleaned.before;
    return (
      <div className="col" style={{ gap: 16 }}>
        <Panel tag="✓" title="Cleaned">
          <div className="col" style={{ gap: 14 }}>
            <div className="row" style={{ gap: 20, alignItems: "center", flexWrap: "wrap" }}>
              <ScoreDelta label="before" v={cleaned.before} />
              <span className="disp" style={{ fontSize: 22, color: "var(--txt-dim)" }}>▸</span>
              <ScoreDelta label="after" v={cleaned.after} />
              <span className="disp" style={{
                fontSize: 18, color: delta >= 0 ? "#36d6c0" : "var(--crimson)", marginLeft: 6,
              }}>
                {delta >= 0 ? "+" : ""}{delta} points
              </span>
            </div>
            {cleaned.qc.detected_bads.length > 0 && (
              <span className="tiny dim">Interpolated: {cleaned.qc.detected_bads.join(", ")}</span>
            )}
            {cleaned.qc.ica_excluded.length > 0 && (
              <span className="tiny dim">ICA removed component{cleaned.qc.ica_excluded.length > 1 ? "s" : ""} {cleaned.qc.ica_excluded.join(", ")} as ocular.</span>
            )}
            <span className="tiny dim" style={{ lineHeight: 1.6 }}>
              Your original recording is untouched — this is a new derivative with the full
              pipeline recorded in its provenance.
            </span>
          </div>
        </Panel>
        <div className="row"><button className="btn crim" onClick={onNext}>▸ see what's notable</button></div>
      </div>
    );
  }

  return (
    <div className="col" style={{ gap: 16 }}>
      <Panel tag="FIX" title="Recommended cleanup" meta={cleanup.estimate}>
        <div className="col" style={{ gap: 12 }}>
          {cleanup.steps.length === 0 && (
            <div className="placeholder-note">Nothing to fix — this recording is already clean.</div>
          )}
          {cleanup.steps.map((s: CleanupStep, i) => (
            <label key={s.op} className="row" style={{ gap: 11, alignItems: "flex-start", cursor: "pointer" }}>
              <input
                type="checkbox" checked={chosen.has(s.op)} style={{ marginTop: 3, accentColor: "var(--crimson)" }}
                onChange={(e) => setChosen((c) => {
                  const n = new Set(c);
                  e.target.checked ? n.add(s.op) : n.delete(s.op);
                  return n;
                })}
              />
              <div className="col" style={{ gap: 3 }}>
                <span style={{ fontSize: 13, color: "var(--gold-hi)" }}>
                  <span className="dim tiny" style={{ marginRight: 8 }}>{String(i + 1).padStart(2, "0")}</span>
                  {s.label}
                </span>
                <span className="tiny dim" style={{ lineHeight: 1.6 }}>{s.why}</span>
              </div>
            </label>
          ))}
          {cleanup.skipped.length > 0 && (
            <div className="col" style={{ gap: 4, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
              <span className="tiny up dim" style={{ letterSpacing: "0.14em" }}>deliberately not doing</span>
              {cleanup.skipped.map((s, i) => <span key={i} className="tiny dim" style={{ lineHeight: 1.6 }}>— {s}</span>)}
            </div>
          )}
        </div>
      </Panel>
      <div className="row" style={{ gap: 10 }}>
        <button className="btn crim" disabled={!steps.length} onClick={apply}>
          ▸ apply {steps.length} step{steps.length === 1 ? "" : "s"}
        </button>
        <button className="btn sm" onClick={onSkip}>skip — use the raw data</button>
      </div>
    </div>
  );
}

function ScoreDelta({ label, v }: { label: string; v: number }) {
  return (
    <div className="col" style={{ alignItems: "center", gap: 1 }}>
      <span className="disp" style={{ fontSize: 34, lineHeight: 1, color: "var(--gold-hi)" }}>{v}</span>
      <span className="tiny up dim">{label}</span>
    </div>
  );
}

/* --------------------------------------------------------- 04 · interpret */
function StepInterpret({ report, onNavigate, onNext }: {
  report: AutoReport; onNavigate: (m: string) => void; onNext: () => void;
}) {
  return (
    <div className="col" style={{ gap: 16 }}>
      <AutoReportView report={report} onNavigate={onNavigate} />
      <div className="row"><button className="btn crim" onClick={onNext}>▸ export</button></div>
    </div>
  );
}

/* ------------------------------------------------------------- 05 · export */
function StepExport({ dataset, report, onNavigate }: {
  dataset: DatasetMeta; report: AutoReport; onNavigate: (m: string) => void;
}) {
  const [formats, setFormats] = useState<{ fmt: string; label: string }[]>([]);
  const [script, setScript] = useState<string | null>(null);
  useEffect(() => { mod.reportFormats().then((r) => setFormats(r.export_formats)).catch(() => {}); }, []);

  return (
    <div className="col" style={{ gap: 16 }}>
      <Panel tag="OUT" title="Take it with you">
        <div className="col" style={{ gap: 14 }}>
          <div style={{ fontSize: 13, lineHeight: 1.7 }}>{report.summary}</div>
          <div className="row wrap" style={{ gap: 8 }}>
            <a className="btn crim" href={`/api/report/${dataset.id}/html`} target="_blank" rel="noreferrer">
              ▸ open full report
            </a>
            {formats.map((f) => (
              <a key={f.fmt} className="btn sm" href={mod.exportUrl(dataset.id, f.fmt)}>{f.label}</a>
            ))}
          </div>
          <span className="tiny dim" style={{ lineHeight: 1.6 }}>
            Every export carries the provenance log — the exact ordered steps applied to this
            recording, the library versions, and a reproducibility hash. Someone else can rerun it.
          </span>
        </div>
      </Panel>

      <Panel tag="PY" title="Reproduce this without NeuroForge"
        meta={<a className="btn sm" href={mod.scriptUrl(dataset.id)}>⤓ download .py</a>}>
        <div className="col" style={{ gap: 12 }}>
          <span style={{ fontSize: 12.5, lineHeight: 1.7 }}>
            Your provenance log rendered as a standalone MNE-Python script. It reloads the
            original file, replays every step in order, and checks the result against the
            fingerprint recorded here — so a reviewer can verify your pipeline with nothing
            installed but MNE.
          </span>
          {script === null
            ? <div className="row">
                <button className="btn sm" onClick={() => mod.reportScript(dataset.id).then((r) => setScript(r.code)).catch((e) => setScript(String(e)))}>
                  preview the script
                </button>
              </div>
            : <pre style={{
                margin: 0, maxHeight: 320, overflow: "auto", fontSize: 11, lineHeight: 1.55,
                background: "rgba(0,0,0,0.4)", padding: 12, border: "1px solid var(--line)",
              }}>{script}</pre>}
        </div>
      </Panel>

      <Panel tag="→" title="Where to go from here">
        <div className="col" style={{ gap: 8 }}>
          {report.next_steps.map((s, i) => (
            <div key={i} className="row" style={{ gap: 12, alignItems: "flex-start" }}>
              <button className="btn sm" style={{ minWidth: 168, flexShrink: 0 }} onClick={() => onNavigate(s.module)}>
                {s.action}
              </button>
              <span className="tiny dim" style={{ lineHeight: 1.6, paddingTop: 4 }}>{s.why}</span>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
