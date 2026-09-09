import { useEffect, useState } from "react";
import { Panel, Spinner, KV } from "../../components/hud";
import { NoData } from "../preprocess/Preprocess";
import { mod, type ModuleProps, type BidsExportResult } from "../../api/modules";
import type { DatasetMeta } from "../../api/client";

export default function Report({ dataset }: ModuleProps) {
  const [formats, setFormats] = useState<{ fmt: string; label: string }[]>([]);
  const [env, setEnv] = useState<{ environment: Record<string, string>; repro_hash: string } | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [script, setScript] = useState<string | null>(null);
  const [tab, setTab] = useState<"report" | "script">("report");
  const [busy, setBusy] = useState(false);
  const id = dataset?.id;

  useEffect(() => { mod.reportFormats().then((f) => setFormats(f.export_formats)).catch(() => {}); }, []);
  useEffect(() => {
    setEnv(null); setHtml(null); setScript(null); setTab("report");
    if (id) mod.reportEnv(id).then(setEnv).catch(() => {});
  }, [id]);

  if (!dataset) return <NoData />;

  const gen = async () => {
    setBusy(true); setTab("report");
    try { setHtml(await mod.reportHtml(dataset.id)); } catch { /* */ }
    setBusy(false);
  };

  return (
    <div className="grid" style={{ gridTemplateColumns: "300px minmax(0,1fr)", alignItems: "start" }}>
      <div className="col">
        <Panel tag="M10" title="Reporting & Export" meta={dataset.label}>
          <div className="col" style={{ gap: 12 }}>
            <button className="btn crim" disabled={busy} onClick={gen}>{busy ? "rendering…" : "▣ generate report"}</button>
            <div>
              <div className="tiny up dim" style={{ marginBottom: 6 }}>export dataset ›</div>
              <div className="row wrap" style={{ gap: 6 }}>
                {formats.map((f) => (
                  <a key={f.fmt} className="btn sm" href={mod.exportUrl(dataset.id, f.fmt)} target="_blank" rel="noreferrer" title={f.label}>{f.fmt.toUpperCase()}</a>
                ))}
              </div>
            </div>
          </div>
        </Panel>

        <Panel tag="ENV" title="Reproducibility">
          {!env ? <Spinner /> : (
            <div className="col" style={{ gap: 12 }}>
              <KV items={[
                ["python", env.environment.python],
                ["mne", env.environment.mne],
                ["numpy", env.environment.numpy],
                ["platform", env.environment.platform?.split("-")[0] ?? "?"],
                ["data hash", env.repro_hash, true],
              ]} />
              <button className="btn sm" onClick={() => { setScript(null); setTab("script"); mod.reportScript(dataset.id).then((r) => setScript(r.code)).catch((e) => setScript(String(e))); }}>
                ⌗ build reproduction script
              </button>
            </div>
          )}
        </Panel>

        <BidsExport dataset={dataset} />
      </div>

      <Panel
        tag={tab === "script" ? "PY" : "DOC"}
        title={tab === "script" ? "Reproduction script" : "Report Preview"}
        meta={tab === "script"
          ? <a className="btn sm" href={mod.scriptUrl(dataset.id)}>⤓ .py</a>
          : (html ? "html · embedded figures" : "not generated")}
        bodyClass="tight">
        {tab === "script"
          ? (script === null ? <Spinner label="rendering provenance as python" />
            : <pre style={{ margin: 0, padding: 14, height: 620, overflow: "auto", fontSize: 11, lineHeight: 1.55 }}>{script}</pre>)
          : busy ? <Spinner label="rendering matplotlib figures" />
            : html ? <iframe title="report" srcDoc={html} style={{ width: "100%", height: 620, border: "none", background: "#0a0609" }} />
              : <div className="placeholder-note" style={{ padding: 16 }}>Generate a publication-style HTML report with embedded PSD &amp; topography figures, dataset metadata and full provenance. Export derivatives as FIF / CSV / NumPy / HDF5 / EDF (BIDS-preserving), or build a standalone MNE script that replays this exact pipeline and verifies it against the data hash.</div>}
      </Panel>
    </div>
  );
}

/* Hand the result to someone else's tool, not just to a reader.
 *
 * A .fif and an HTML page are for you. A BIDS derivatives tree — with channels.tsv,
 * events.tsv, sidecar JSON and the provenance log beside every run — is what another
 * lab, a pipeline, or a reviewer can actually consume without asking you anything. */
function BidsExport({ dataset }: { dataset: DatasetMeta }) {
  const [out, setOut] = useState<BidsExportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dir, setDir] = useState("");

  const run = async () => {
    setBusy(true); setErr(null); setOut(null);
    try {
      setOut(await mod.bidsExport([dataset.id], dir.trim() || null,
        `NeuroForge — ${dataset.label}`, true));
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  };

  return (
    <Panel tag="BIDS" title="BIDS derivatives">
      <div className="col" style={{ gap: 10 }}>
        <span className="tiny dim" style={{ lineHeight: 1.6 }}>
          Writes a valid tree: data, channels.tsv, events.tsv, sidecar JSON and the
          provenance log for every run.
        </span>
        <input className="nf" value={dir} placeholder="output folder (blank = data dir)"
          onChange={(e) => setDir(e.target.value)} style={{ padding: "6px 9px" }} />
        <button className="btn sm" disabled={busy} onClick={run}>
          {busy ? "writing…" : "▣ export BIDS"}
        </button>
        {err && <span className="tiny" style={{ color: "var(--crimson-hi)" }}>{err}</span>}
        {out && (
          <div className="col" style={{ gap: 3 }}>
            <span className="tiny" style={{ color: "#36d6c0" }}>
              {out.n_written} run(s), {out.n_subjects} subject(s)
            </span>
            <span className="tiny dim" style={{ wordBreak: "break-all" }}>{out.root}</span>
          </div>
        )}
      </div>
    </Panel>
  );
}
