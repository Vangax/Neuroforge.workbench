import { useEffect, useRef, useState, useCallback } from "react";
import { Panel, KV, Chip, Spinner } from "../../components/hud";
import HeroBurst from "../../components/HeroBurst";
import FolderImport from "../../components/FolderImport";
import {
  api, type DatasetMeta, type TreeData, type FormatInfo, type ChannelsData,
} from "../../api/client";

interface Props {
  datasets: DatasetMeta[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onChanged: () => void;
  onOpenViewer: () => void;
}

export default function Repository({ datasets, selectedId, onSelect, onChanged, onOpenViewer }: Props) {
  const [tree, setTree] = useState<TreeData["tree"]>({});
  const [formats, setFormats] = useState<FormatInfo[]>([]);
  const [channels, setChannels] = useState<ChannelsData | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { api.tree().then((t) => setTree(t.tree)); }, [datasets]);
  useEffect(() => { api.formats().then((f) => setFormats(f.formats)); }, []);
  useEffect(() => {
    setChannels(null);
    if (selectedId) api.channels(selectedId).then(setChannels);
  }, [selectedId]);

  const selected = datasets.find((d) => d.id === selectedId) ?? null;
  const det = (selected?.extra as { channel_detection?: { n_eeg: number; n_total: number; auto_detected: boolean } } | undefined)?.channel_detection;

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setMsg(null);
    let ok = 0; const errs: string[] = [];
    for (const f of Array.from(files)) {
      const res = await api.upload(f, { subject: "imported" });  // backend names it from the file
      if (res.ok) ok++; else errs.push(`${f.name}: ${res.detail}`);
    }
    setBusy(false);
    setMsg(errs.length ? errs.join(" · ") : `imported ${ok} file(s)`);
    onChanged();
  }, [onChanged]);

  const genSynthetic = useCallback(async () => {
    setBusy(true); setMsg(null);
    const meta = await api.createSynthetic({
      subject: String(10 + Math.floor(Math.random() * 89)),
      session: "01", task: "rest", n_seconds: 60, sfreq: 256, seed: Math.floor(Math.random() * 9999),
    });
    setBusy(false);
    setMsg(meta ? `forged ${meta.label}` : "synthetic needs the live backend (offline demo is read-only)");
    if (meta) onChanged();
  }, [onChanged]);

  return (
    <div className="grid" style={{ gridTemplateColumns: "330px minmax(0,1fr) 300px", alignItems: "start" }}>
      {/* ---- hero banner ---- */}
      <div className="panel hero" style={{ gridColumn: "1 / -1", height: 170 }}>
        <HeroBurst animate floor seed={9} />
        <span className="corner-br" />
        <div className="hero-overlay">
          <div>
            <div className="disp" style={{ fontSize: 30, fontWeight: 300, letterSpacing: "0.4em", textTransform: "uppercase", color: "var(--hot)", textShadow: "0 0 24px rgba(255,47,94,0.5)" }}>
              Neuro·Data Repository
            </div>
            <div className="tiny up dim" style={{ marginTop: 4 }}>universal loader · BIDS-native · reproducible · real-time capable</div>
          </div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="chip ok">{datasets.length} runs indexed</span>
            <span className="tiny up" style={{ color: "var(--gold-deep)", letterSpacing: "0.3em" }}>module 01 ◇ online</span>
          </div>
        </div>
      </div>

      {/* ---- column 1: import + tree ---- */}
      <div className="col">
        <DropZone busy={busy} onPick={() => fileRef.current?.click()} onFiles={handleFiles} />
        <input ref={fileRef} type="file" multiple hidden
          onChange={(e) => handleFiles(e.target.files)} />
        {msg && <div className="tiny" style={{ color: "var(--amber-hi)", padding: "0 2px" }}>» {msg}</div>}

        <FolderImport onImported={onChanged} />

        <Panel tag="M01" title="BIDS Repository" meta={`${datasets.length} runs`} style={{ maxHeight: 460 }}>
          <Tree tree={tree} selectedId={selectedId} onSelect={onSelect} />
        </Panel>
      </div>

      {/* ---- column 2: metadata + channels ---- */}
      <div className="col">
        <Panel tag="META" title={selected ? selected.label : "no dataset selected"}
          meta={selected?.source_format}>
          {selected ? (
            <div className="col" style={{ gap: 14 }}>
              <KV items={[
                ["dataset id", selected.id],
                ["file", selected.source_path ?? "—"],
                ["sampling rate", `${selected.sfreq} Hz`, true],
                ["channels", selected.n_channels, true],
                ...(det?.auto_detected ? [["EEG detected", `${det.n_eeg} of ${det.n_total}`, true] as [string, string, boolean]] : []),
                ["samples", selected.n_times.toLocaleString()],
                ["duration", `${selected.duration.toFixed(2)} s`],
                ["passband", `${selected.highpass.toFixed(1)} – ${selected.lowpass.toFixed(1)} Hz`],
                ["events", selected.n_events],
                ["subject / session", `${selected.entities.subject} / ${selected.entities.session ?? "—"}`],
                ["task", selected.entities.task ?? "—"],
              ]} />
              <div className="row wrap" style={{ gap: 6 }}>
                {Object.entries(selected.channel_type_counts).map(([t, c]) => (
                  <Chip key={t}>{t.toUpperCase()} ×{c}</Chip>
                ))}
              </div>
              <div>
                <div className="tiny up dim" style={{ marginBottom: 6 }}>provenance ›</div>
                <div className="col" style={{ gap: 3 }}>
                  {selected.provenance.map((p, i) => (
                    <div key={i} className="tiny" style={{ color: "var(--txt)" }}>
                      <span className="cyan">{String(i).padStart(2, "0")}</span>{" "}
                      <span className="amber">{p.op}</span>{" "}
                      <span className="dim">{JSON.stringify(p.params)}</span>
                    </div>
                  ))}
                </div>
              </div>
              <button className="btn amber" onClick={onOpenViewer}>open in visualizer ›</button>
            </div>
          ) : (
            <div className="placeholder-note">Select a run from the repository tree, drop a file, or forge synthetic data.</div>
          )}
        </Panel>

        <Panel tag="CH" title="Channels & Montage"
          meta={channels ? `${channels.channels.length} ch · ${channels.positions.length} positioned` : ""}
          style={{ maxHeight: 320 }} bodyClass="tight">
          {!selected ? <div className="placeholder-note" style={{ padding: 10 }}>—</div>
            : !channels ? <Spinner label="reading channels.tsv" />
              : (
                <table className="nf">
                  <thead><tr><th>#</th><th>name</th><th>type</th><th>units</th><th>x</th><th>y</th></tr></thead>
                  <tbody>
                    {channels.channels.map((c, i) => (
                      <tr key={c.name}>
                        <td className="dim">{i + 1}</td>
                        <td className="cyan">{c.name}</td>
                        <td>{c.type}</td>
                        <td className="dim">{c.units}</td>
                        <td className="dim">{c.x?.toFixed(2) ?? "—"}</td>
                        <td className="dim">{c.y?.toFixed(2) ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
        </Panel>
      </div>

      {/* ---- column 3: synth + formats ---- */}
      <div className="col">
        <Panel tag="GEN" title="Synthetic Forge">
          <div className="col" style={{ gap: 10 }}>
            <div className="placeholder-note tiny">
              Generate physiologically-plausible 32-ch EEG (posterior alpha, frontal
              blinks, mains noise, oddball events) via the MNE backend.
            </div>
            <button className="btn amber" disabled={busy} onClick={genSynthetic}>+ forge synthetic run</button>
          </div>
        </Panel>

        <Panel tag="FMT" title="Supported Formats" meta={`${formats.filter((f) => f.status === "ready").length} live`}>
          <div className="col" style={{ gap: 4 }}>
            {formats.map((f) => (
              <div key={f.ext} className="row" style={{ justifyContent: "space-between" }}>
                <span><span className="cyan">{f.ext}</span> <span className="dim tiny">{f.label}</span></span>
                <Chip kind={f.status === "ready" ? "ok" : "plan"}>{f.status}</Chip>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function DropZone({ busy, onPick, onFiles }: { busy: boolean; onPick: () => void; onFiles: (f: FileList) => void }) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={`panel reticle ${over ? "sweep" : ""}`}
      style={{
        height: 150, cursor: "pointer",
        borderColor: over ? "var(--amber)" : "var(--line)",
        boxShadow: over ? "var(--glow-amber)" : "none",
      }}
      onClick={onPick}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onFiles(e.dataTransfer.files); }}
    >
      <span className="corner-tr" /><span className="corner-br" />
      <div className="center col" style={{ gap: 8, textAlign: "center" }}>
        <span style={{ fontSize: 26, color: "var(--amber)" }}>⤓</span>
        <span className="up" style={{ color: over ? "var(--amber-hi)" : "var(--cyan-hi)", letterSpacing: "0.2em" }}>
          {busy ? "ingesting…" : "drop neural data"}
        </span>
        <span className="tiny dim">EDF · BDF · BrainVision · FIFF · SET · EGI · …</span>
      </div>
    </div>
  );
}

function Tree({ tree, selectedId, onSelect }: {
  tree: TreeData["tree"]; selectedId: string | null; onSelect: (id: string) => void;
}) {
  const subjects = Object.entries(tree);
  if (!subjects.length) return <Spinner label="indexing repository" />;
  return (
    <div className="col" style={{ gap: 2 }}>
      {subjects.map(([sk, sub]) => (
        <div key={sk}>
          <div className="row" style={{ gap: 6, color: "var(--amber-hi)", marginTop: 4 }}>
            <span>▾</span><span className="up" style={{ letterSpacing: "0.1em" }}>{sk}</span>
          </div>
          {Object.entries(sub.sessions).map(([ssk, ses]) => (
            <div key={ssk} style={{ marginLeft: 14 }}>
              <div className="tiny dim up" style={{ marginTop: 4 }}>{ssk}</div>
              {ses.datasets.map((d) => (
                <div
                  key={d.id}
                  onClick={() => onSelect(d.id)}
                  className="row"
                  style={{
                    gap: 8, marginLeft: 10, padding: "3px 6px", cursor: "pointer",
                    borderLeft: `2px solid ${selectedId === d.id ? "var(--amber)" : "transparent"}`,
                    background: selectedId === d.id ? "rgba(255,138,30,0.1)" : "transparent",
                    color: selectedId === d.id ? "var(--amber-hi)" : "var(--txt)",
                  }}
                >
                  <span className="cyan tiny">∿</span>
                  <span style={{ fontSize: 12 }}>task-{d.task ?? "?"}</span>
                  <span className="tiny dim" style={{ marginLeft: "auto" }}>{d.n_channels}ch·{d.duration}s</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
