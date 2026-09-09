/* Module 12 — Cohort. A study treated as a study.
 *
 * Every other module answers a question about one recording. This one answers the
 * question you actually have once you have forty: are they the same kind of data,
 * which ones should I not trust, and can I fix them in one pass?
 */
import { useEffect, useMemo, useState } from "react";
import { Panel, Chip } from "../../components/hud";
import { authHeaders, type DatasetMeta } from "../../api/client";
import {
  mod, type CohortAnalysis, type CohortCleanResult,
  type CohortColumn, type JobProgress,
} from "../../api/modules";

const GRADE_COLOR: Record<string, string> = {
  excellent: "#36d6c0", good: "#36d6c0", fair: "var(--gold)", poor: "var(--crimson)",
};

interface Props {
  datasets: DatasetMeta[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onChanged: () => Promise<void> | void;
  onNavigate?: (moduleId: string) => void;
}

export default function Cohort({ datasets, onSelect, onChanged, onNavigate }: Props) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [analysis, setAnalysis] = useState<CohortAnalysis | null>(null);
  const [cleaned, setCleaned] = useState<CohortCleanResult | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "health", dir: 1 });

  // Default to everything: the whole point is the cohort, not a selection exercise.
  useEffect(() => {
    setPicked((cur) => (cur.size ? cur : new Set(datasets.map((d) => d.id))));
  }, [datasets]);

  const ids = [...picked].filter((id) => datasets.some((d) => d.id === id));

  const run = async (what: "analyze" | "clean") => {
    if (!ids.length) return;
    setErr(null); setProgress(null); setCleaned(null);
    setBusy(what === "analyze" ? "Analysing the cohort" : "Cleaning every recording");
    try {
      if (what === "analyze") {
        setAnalysis(await mod.batchAnalyze(ids, setProgress));
      } else {
        const r = await mod.batchClean(ids, null, setProgress);
        setCleaned(r);
        await onChanged();
      }
    } catch (e) { setErr(String(e)); }
    setBusy(null); setProgress(null);
  };

  const rows = useMemo(() => {
    if (!analysis) return [];
    const { key, dir } = sort;
    return [...analysis.rows].sort((a, b) => {
      const x = a[key], y = b[key];
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return String(x ?? "").localeCompare(String(y ?? "")) * dir;
    });
  }, [analysis, sort]);

  const exportCsv = async () => {
    const r = await fetch(mod.batchCsvUrl, {
      method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ rows }),
    });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "neuroforge_cohort.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="col" style={{ gap: 16, maxWidth: 1500, margin: "0 auto" }}>
      <div className="row wrap" style={{ gap: 14, alignItems: "flex-end" }}>
        <div className="col" style={{ gap: 3 }}>
          <span className="disp" style={{ fontSize: 22, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--hot)" }}>
            Cohort
          </span>
          <span className="tiny dim">
            {ids.length} of {datasets.length} recordings selected
          </span>
        </div>
        <div className="row wrap" style={{ gap: 8, marginLeft: "auto" }}>
          <button className="btn sm" onClick={() => setPicked(new Set(datasets.map((d) => d.id)))}>all</button>
          <button className="btn sm" onClick={() => setPicked(new Set())}>none</button>
          <button className="btn crim" disabled={!!busy || !ids.length} onClick={() => run("analyze")}>
            ▸ analyze {ids.length}
          </button>
          <button className="btn" disabled={!!busy || !ids.length} onClick={() => run("clean")}
            title="each recording gets its own recommended cleanup, then is re-scored">
            ⚙ clean all
          </button>
        </div>
      </div>

      {err && <Panel tag="!" title="cohort run failed">
        <pre style={{ margin: 0, fontSize: 11, color: "var(--crimson-hi)", whiteSpace: "pre-wrap" }}>{err}</pre>
      </Panel>}

      {busy && <ProgressPanel label={busy} p={progress} />}

      <Panel tag="PICK" title="Recordings" meta={`${datasets.length}`}>
        <div className="row wrap" style={{ gap: 6 }}>
          {datasets.map((d) => {
            const on = picked.has(d.id);
            return (
              <button key={d.id} className={`btn sm ${on ? "crim" : ""}`}
                onClick={() => setPicked((s) => {
                  const n = new Set(s); on ? n.delete(d.id) : n.add(d.id); return n;
                })}>
                {on ? "✓ " : ""}{d.label}
              </button>
            );
          })}
          {datasets.length === 0 && <span className="placeholder-note">No recordings loaded yet.</span>}
        </div>
      </Panel>

      {cleaned && <CleanSummary r={cleaned} onOpen={(id) => { onSelect(id); onNavigate?.("auto"); }} />}

      {analysis && !busy && (
        <>
          <CohortOverview a={analysis} onOpen={(id) => { onSelect(id); onNavigate?.("auto"); }} />
          <Panel tag="TAB" title="Cohort table" meta={
            <button className="btn sm" onClick={exportCsv}>⤓ CSV</button>
          }>
            <div style={{ overflowX: "auto" }}>
              <table className="cohort">
                <thead>
                  <tr>
                    {analysis.columns.map((c: CohortColumn) => (
                      <th key={c.key} onClick={() => setSort((s) =>
                        s.key === c.key ? { key: c.key, dir: (s.dir * -1) as 1 | -1 } : { key: c.key, dir: 1 })}>
                        {c.label}{sort.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.dataset_id} onClick={() => { onSelect(r.dataset_id); onNavigate?.("auto"); }}>
                      {analysis.columns.map((c) => (
                        <td key={c.key} style={c.key === "grade"
                          ? { color: GRADE_COLOR[String(r.grade)] ?? "var(--txt)" } : undefined}>
                          {fmt(r[c.key], c.kind)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {analysis.failed.length > 0 && (
              <div className="col" style={{ gap: 4, marginTop: 12, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                <span className="tiny up dim">could not analyse</span>
                {analysis.failed.map((f) => (
                  <span key={f.dataset_id} className="tiny" style={{ color: "var(--crimson-hi)" }}>
                    {f.label} — {f.error}
                  </span>
                ))}
              </div>
            )}
          </Panel>
        </>
      )}

      {!analysis && !cleaned && !busy && (
        <Panel tag="—" title="nothing run yet">
          <div className="placeholder-note">
            Select recordings and press <b>analyze</b>. You get one table — detected paradigm,
            health, and every artifact metric for each run — plus the runs that do not look
            like the rest of the cohort.
          </div>
        </Panel>
      )}
    </div>
  );
}

function ProgressPanel({ label, p }: { label: string; p: JobProgress | null }) {
  const pct = p && p.total_n ? Math.round((p.done_n / p.total_n) * 100) : 0;
  return (
    <Panel tag="RUN" title={label} meta={p?.total_n ? `${p.done_n}/${p.total_n}` : ""}>
      <div className="col" style={{ gap: 8 }}>
        <div style={{ width: "100%", height: 6, background: "rgba(0,0,0,0.42)" }}>
          <div style={{ width: `${pct}%`, height: "100%", background: "var(--crimson)", transition: "width 0.3s" }} />
        </div>
        <div className="row" style={{ gap: 14 }}>
          <span className="tiny dim">{p?.step || "starting…"}</span>
          <span className="tiny dim" style={{ marginLeft: "auto" }}>
            {p?.elapsed != null ? `${p.elapsed.toFixed(0)}s elapsed` : ""}
            {p?.eta != null ? ` · ~${Math.ceil(p.eta)}s left` : ""}
          </span>
        </div>
      </div>
    </Panel>
  );
}

function CohortOverview({ a, onOpen }: { a: CohortAnalysis; onOpen: (id: string) => void }) {
  const s = a.summary;
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1.2fr)", gap: 14, alignItems: "stretch" }}>
      <Panel tag="SUM" title="What you have">
        <div className="col" style={{ gap: 12 }}>
          <div className="row wrap" style={{ gap: 22, alignItems: "baseline" }}>
            <Stat v={String(s.n)} k="recordings" />
            <Stat v={s.mean_health != null ? String(s.mean_health) : "—"} k="mean health" />
            <Stat v={`${s.n_usable}/${s.n}`} k="good or better" />
          </div>
          <div className="col" style={{ gap: 5 }}>
            <span className="tiny up dim" style={{ letterSpacing: "0.14em" }}>detected as</span>
            {Object.entries(s.types).map(([t, n]) => (
              <div key={t} className="row" style={{ gap: 8 }}>
                <span className="tiny" style={{ color: "var(--gold-hi)", minWidth: 26 }}>{n}×</span>
                <span className="tiny dim">{t}</span>
              </div>
            ))}
            {!s.consistent && (
              <span className="tiny" style={{ color: "var(--gold-hi)", lineHeight: 1.6, marginTop: 4 }}>
                Mixed paradigms in one cohort — check that these belong in the same analysis.
              </span>
            )}
          </div>
        </div>
      </Panel>

      <Panel tag="ODD" title="Runs that don't look like the others"
        meta={`${s.outliers.length}`}>
        {s.outliers.length === 0 ? (
          <div className="placeholder-note">
            {s.n < 5
              ? "Fewer than five recordings — too few for outlier detection to mean anything."
              : "No recording is a robust outlier on any metric. The cohort is internally consistent."}
          </div>
        ) : (
          <div className="col" style={{ gap: 10 }}>
            {s.outliers.map((o) => (
              <div key={o.dataset_id} className="col" style={{ gap: 3, borderLeft: "2px solid var(--crimson)", paddingLeft: 11 }}>
                <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => onOpen(o.dataset_id)}>
                  {o.label}
                </button>
                {o.reasons.map((r, i) => (
                  <span key={i} className="tiny dim" style={{ lineHeight: 1.55 }}>— {r}</span>
                ))}
              </div>
            ))}
            <span className="tiny dim" style={{ lineHeight: 1.6, marginTop: 2 }}>
              Flagged at 3.5 robust z <em>and</em> at least 15% from the cohort median —
              median/MAD so one bad run cannot hide another, and the second test so a
              tight cohort does not make trivial differences look significant.
            </span>
          </div>
        )}
      </Panel>
    </div>
  );
}

function CleanSummary({ r, onOpen }: { r: CohortCleanResult; onOpen: (id: string) => void }) {
  return (
    <Panel tag="✓" title="Cohort cleaned"
      meta={`${r.n_improved} better · ${r.n_unchanged} unchanged · ${r.n_worse} worse`}>
      <div className="col" style={{ gap: 10 }}>
        <span style={{ fontSize: 13 }}>
          Mean health change <b style={{ color: r.mean_delta >= 0 ? "#36d6c0" : "var(--crimson)" }}>
            {r.mean_delta >= 0 ? "+" : ""}{r.mean_delta}
          </b> points. Each recording got its own recommended pipeline — originals untouched.
        </span>
        <div className="col" style={{ gap: 5 }}>
          {r.results.map((x) => (
            <div key={x.dataset_id} className="row" style={{ gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className="tiny" style={{ minWidth: 200, color: "var(--txt-bright)" }}>{x.label}</span>
              <span className="tiny dim">{x.before} → {x.after}</span>
              <span className="tiny" style={{ color: x.delta > 0 ? "#36d6c0" : x.delta < 0 ? "var(--crimson)" : "var(--txt-dim)" }}>
                {x.delta > 0 ? "+" : ""}{x.delta}
              </span>
              {x.skipped && <Chip kind="ok">{x.skipped}</Chip>}
              {x.steps && <span className="tiny dim">{x.steps.join(" · ")}</span>}
              {x.new_id && (
                <button className="btn sm" style={{ marginLeft: "auto" }} onClick={() => onOpen(x.new_id!)}>open</button>
              )}
            </div>
          ))}
        </div>
        {r.failed.length > 0 && (
          <div className="col" style={{ gap: 4, borderTop: "1px solid var(--line)", paddingTop: 9 }}>
            <span className="tiny up dim">failed</span>
            {r.failed.map((f) => (
              <span key={f.dataset_id} className="tiny" style={{ color: "var(--crimson-hi)" }}>
                {f.label} — {f.error}
              </span>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

function Stat({ v, k }: { v: string; k: string }) {
  return (
    <div className="col" style={{ gap: 1 }}>
      <span className="disp" style={{ fontSize: 30, lineHeight: 1, color: "var(--gold-hi)" }}>{v}</span>
      <span className="tiny up dim">{k}</span>
    </div>
  );
}

function fmt(v: unknown, kind: string): string {
  if (v === null || v === undefined || v === "") return "—";
  if (kind === "num" && typeof v === "number") return v.toFixed(1);
  if (kind === "int" && typeof v === "number") return String(Math.round(v));
  return String(v);
}
