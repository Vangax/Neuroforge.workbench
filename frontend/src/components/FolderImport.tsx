/* Import a whole study folder by path.
 *
 * A browser file picker cannot hand a server a directory path, and uploading 40 GB
 * through an HTTP form is not how anyone works with a study. NeuroForge normally
 * runs on the same machine as the data, so the honest interface is: tell it where
 * the folder is, see exactly what it found and what it inferred, then import.
 */
import { useState } from "react";
import { Panel, Spinner, Chip } from "./hud";
import { mod, type ScanResult, type JobProgress } from "../api/modules";

export default function FolderImport({ onImported }: { onImported: () => Promise<void> | void }) {
  const [path, setPath] = useState("");
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [skip, setSkip] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const doScan = async () => {
    if (!path.trim()) return;
    setErr(null); setDone(null); setScan(null); setSkip(new Set());
    setBusy("Looking for recordings");
    try { setScan(await mod.bidsScan(path.trim())); }
    catch (e) { setErr(String(e)); }
    setBusy(null);
  };

  const doImport = async () => {
    if (!scan) return;
    const files = scan.candidates.filter((c) => !skip.has(c.path)).map((c) => c.path);
    if (!files.length) return;
    setErr(null); setBusy(`Reading ${files.length} recording${files.length > 1 ? "s" : ""}`);
    try {
      const r = await mod.bidsImport(scan.root, files, setProgress);
      await onImported();
      setDone(`Imported ${r.n_loaded} of ${r.n_found}.`
        + (r.failed.length ? ` ${r.failed.length} could not be read.` : ""));
      setScan(null);
    } catch (e) { setErr(String(e)); }
    setBusy(null); setProgress(null);
  };

  const pct = progress && progress.total_n
    ? Math.round((progress.done_n / progress.total_n) * 100) : 0;

  return (
    <Panel tag="DIR" title="Import a folder or BIDS study"
      meta={scan ? `${scan.n_found} found` : ""}>
      <div className="col" style={{ gap: 12 }}>
        <div className="row wrap" style={{ gap: 8 }}>
          <input
            className="nf" value={path} placeholder="path to a folder on this machine"
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") doScan(); }}
            style={{ flex: 1, minWidth: 260, padding: "7px 10px" }}
          />
          <button className="btn sm" disabled={!!busy || !path.trim()} onClick={doScan}>scan</button>
        </div>

        {err && <pre style={{ margin: 0, fontSize: 11, color: "var(--crimson-hi)", whiteSpace: "pre-wrap" }}>{err}</pre>}
        {done && <span className="tiny" style={{ color: "#36d6c0" }}>{done}</span>}

        {busy && (progress
          ? <div className="col" style={{ gap: 6 }}>
              <div style={{ width: "100%", height: 5, background: "rgba(0,0,0,0.42)" }}>
                <div style={{ width: `${pct}%`, height: "100%", background: "var(--crimson)" }} />
              </div>
              <span className="tiny dim">{progress.step} · {progress.done_n}/{progress.total_n}</span>
            </div>
          : <Spinner label={busy} />)}

        {scan && !busy && (
          <div className="col" style={{ gap: 10 }}>
            <div className="row wrap" style={{ gap: 10, alignItems: "center" }}>
              {scan.is_bids && <Chip kind="ok">BIDS dataset</Chip>}
              <span className="tiny dim">
                {scan.n_found} readable recording{scan.n_found === 1 ? "" : "s"} ·{" "}
                {scan.n_subjects} subject{scan.n_subjects === 1 ? "" : "s"}
              </span>
              <button className="btn crim" style={{ marginLeft: "auto" }}
                disabled={skip.size >= scan.n_found} onClick={doImport}>
                ▸ import {scan.n_found - skip.size}
              </button>
            </div>

            {scan.n_found === 0 && (
              <div className="placeholder-note">
                Nothing readable here. NeuroForge looks for EDF, BDF, GDF, BrainVision,
                EEGLAB, FIFF, EGI and XDF, and skips derivatives/ and sourcedata/.
              </div>
            )}

            {scan.n_found > 0 && (
              <div style={{ maxHeight: 260, overflow: "auto" }}>
                <table className="cohort">
                  <thead>
                    <tr><th></th><th>File</th><th>sub</th><th>ses</th><th>task</th><th>run</th><th>MB</th></tr>
                  </thead>
                  <tbody>
                    {scan.candidates.map((c) => (
                      <tr key={c.path} style={{ opacity: skip.has(c.path) ? 0.4 : 1 }}>
                        <td>
                          <input type="checkbox" checked={!skip.has(c.path)}
                            style={{ accentColor: "var(--crimson)" }}
                            onChange={(e) => setSkip((s) => {
                              const n = new Set(s);
                              e.target.checked ? n.delete(c.path) : n.add(c.path);
                              return n;
                            })} />
                        </td>
                        <td title={c.path}>{c.relative}</td>
                        <td>{c.subject}</td><td>{c.session ?? "—"}</td>
                        <td>{c.task ?? "—"}</td><td>{c.run ?? "—"}</td>
                        <td>{c.size_mb}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <span className="tiny dim" style={{ lineHeight: 1.6 }}>
              Subject, session, task and run are read from BIDS entities in the filename,
              falling back to the folder above it. Nothing is invented — what you see here
              is what gets stored.
            </span>
          </div>
        )}
      </div>
    </Panel>
  );
}
