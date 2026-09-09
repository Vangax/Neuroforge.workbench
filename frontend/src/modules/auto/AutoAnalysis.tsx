import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, Spinner, Chip } from "../../components/hud";
import ScalpDots from "../../components/ScalpDots";
import { NoData } from "../preprocess/Preprocess";
import {
  mod, type ModuleProps, type AutoReport, type Finding, type HealthCheck, type AutoEvidence,
} from "../../api/modules";

const STATUS_COLOR: Record<string, string> = {
  ok: "#36d6c0", warn: "var(--gold)", fail: "var(--crimson)", na: "var(--txt-dim)",
};
const GRADE_COLOR: Record<string, string> = {
  excellent: "#36d6c0", good: "#36d6c0", fair: "var(--gold)", poor: "var(--crimson)",
};

type Props = ModuleProps & { onNavigate?: (moduleId: string) => void };

export default function AutoAnalysis({ dataset, onNavigate }: Props) {
  const [report, setReport] = useState<AutoReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const cache = useRef<Record<string, AutoReport>>({});
  const id = dataset?.id;

  const run = useCallback(async (force = false) => {
    if (!id) return;
    if (!force && cache.current[id]) { setReport(cache.current[id]); return; }
    setBusy(true); setErr(null); setReport(null);
    try {
      const r = await mod.autoAnalyze(id);
      cache.current[id] = r;
      setReport(r);
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }, [id]);

  // Default to answers, not controls: analysing starts as soon as a dataset is open.
  useEffect(() => { if (id) run(); }, [id, run]);

  if (!dataset) return <NoData />;

  return (
    <div className="col" style={{ gap: 16, maxWidth: 1180, margin: "0 auto" }}>
      <div className="row wrap" style={{ gap: 14, alignItems: "center" }}>
        <div className="col" style={{ gap: 2 }}>
          <span className="disp" style={{ fontSize: 22, letterSpacing: "0.18em", textTransform: "uppercase", color: "var(--hot)" }}>
            Analyze this recording
          </span>
          <span className="tiny dim">{dataset.label}{dataset.source_path ? ` · ${dataset.source_path}` : ""}</span>
        </div>
        <button className="btn crim" style={{ marginLeft: "auto" }} disabled={busy} onClick={() => run(true)}>
          {busy ? "analyzing…" : report ? "↻ re-analyze" : "▸ analyze"}
        </button>
      </div>

      {err && <Panel tag="!" title="could not analyze"><pre style={{ margin: 0, fontSize: 11, color: "var(--crimson-hi)", whiteSpace: "pre-wrap" }}>{err}</pre></Panel>}
      {busy && <Spinner label="running the battery — spectra, artifacts, events, evoked response" />}

      {report && !report.error && <AutoReportView report={report} onNavigate={onNavigate} />}
      {report?.error && (
        <Panel tag="!" title="nothing to analyze"><div className="placeholder-note">{report.error}</div></Panel>
      )}
    </div>
  );
}

/** The report body on its own — shared by the Pro module and by Guided mode. */
export function AutoReportView({ report, onNavigate }: { report: AutoReport; onNavigate?: (m: string) => void }) {
  return (
    <>
      <Verdict r={report} />
      <HealthPanel health={report.health} />
      <Panel tag="FIND" title="What's notable" meta={`${report.findings.length}`}>
        <div className="col" style={{ gap: 16 }}>
          {report.findings.map((f, i) => (
            <FindingCard key={i} f={f} evidence={report.evidence} />
          ))}
        </div>
      </Panel>
      <Panel tag="NEXT" title="Suggested next steps" meta={`${report.next_steps.length}`}>
        <div className="col" style={{ gap: 8 }}>
          {report.next_steps.map((s, i) => (
            <div key={i} className="row" style={{ gap: 12, alignItems: "flex-start" }}>
              <button className="btn sm" onClick={() => onNavigate?.(s.module)} style={{ minWidth: 150, flexShrink: 0 }}>
                {s.action}
              </button>
              <span className="tiny dim" style={{ lineHeight: 1.6, paddingTop: 4 }}>{s.why}</span>
            </div>
          ))}
        </div>
      </Panel>
      <div className="tiny dim" style={{ lineHeight: 1.6, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
        {report.disclaimer}
      </div>
    </>
  );
}

function Verdict({ r }: { r: AutoReport }) {
  const t = r.recording_type;
  const h = r.health;
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.5fr) 260px", gap: 14, alignItems: "stretch" }}>
      <Panel tag="WHAT" title="What is this data?">
        <div className="col" style={{ gap: 10 }}>
          <div className="row" style={{ gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
            <span className="disp" style={{ fontSize: 24, color: "var(--gold-hi)", letterSpacing: "0.04em" }}>{t.label}</span>
            <Chip kind="ok">{Math.round(t.confidence * 100)}% confident</Chip>
          </div>
          <div className="col" style={{ gap: 4 }}>
            {t.why.map((w, i) => (
              <div key={i} className="row" style={{ gap: 8, alignItems: "flex-start" }}>
                <span className="crim" style={{ fontSize: 11 }}>▹</span>
                <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>{w}</span>
              </div>
            ))}
          </div>
          <div className="row wrap" style={{ gap: 12, marginTop: 4 }}>
            <Meta k="channels" v={`${r.dataset.n_channels}${r.dataset.n_channels_total !== r.dataset.n_channels ? ` of ${r.dataset.n_channels_total}` : ""}`} />
            <Meta k="duration" v={`${r.dataset.duration_s}s`} />
            <Meta k="rate" v={`${Math.round(r.dataset.sfreq)} Hz`} />
            <Meta k="events" v={`${r.dataset.n_events}`} />
            <Meta k="events from" v={r.dataset.event_source} />
          </div>
        </div>
      </Panel>

      <Panel tag="QC" title="Data health">
        <div className="col" style={{ alignItems: "center", gap: 6, paddingTop: 4 }}>
          <span className="disp" style={{ fontSize: 52, lineHeight: 1, color: GRADE_COLOR[h.grade] ?? "var(--gold-hi)" }}>
            {h.score}
          </span>
          <span className="tiny up dim">out of 100 · {h.grade}</span>
          <div style={{ width: "100%", height: 6, background: "rgba(0,0,0,0.4)", marginTop: 8 }}>
            <div style={{ width: `${h.score}%`, height: "100%", background: GRADE_COLOR[h.grade] ?? "var(--gold)" }} />
          </div>
        </div>
      </Panel>
    </div>
  );
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <span className="tiny">
      <span className="dim up" style={{ letterSpacing: "0.12em" }}>{k} </span>
      <span style={{ color: "var(--txt-bright)" }}>{v}</span>
    </span>
  );
}

function HealthPanel({ health }: { health: AutoReport["health"] }) {
  return (
    <Panel tag="QC" title="Health checks" meta={`${health.checks.filter((c) => c.status === "ok").length}/${health.checks.length} clear`}>
      <div className="col" style={{ gap: 7 }}>
        {health.checks.map((c: HealthCheck) => (
          <div key={c.id} className="row" style={{ gap: 10, alignItems: "flex-start" }}>
            <span style={{
              width: 8, height: 8, borderRadius: "50%", flexShrink: 0, marginTop: 5,
              background: STATUS_COLOR[c.status], boxShadow: c.status === "fail" ? "0 0 8px var(--crimson)" : "none",
            }} />
            <span style={{ minWidth: 168, fontSize: 12.5, color: "var(--txt-bright)" }}>{c.label}</span>
            <span className="tiny dim" style={{ lineHeight: 1.6 }}>{c.detail}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function FindingCard({ f, evidence }: { f: Finding; evidence: AutoEvidence }) {
  return (
    <div className="col" style={{ gap: 8, borderLeft: "2px solid var(--crimson)", paddingLeft: 12 }}>
      <div className="row" style={{ gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, color: "var(--gold-hi)", letterSpacing: "0.04em" }}>{f.title}</span>
        <span className="tiny dim">{Math.round(f.confidence * 100)}% confidence</span>
      </div>
      <div style={{ fontSize: 12.5, lineHeight: 1.65, color: "var(--txt)" }}>{f.plain}</div>
      <Evidence kind={f.evidence.kind} ev={evidence} highlight={f.evidence.highlight} markerMs={f.evidence.marker_ms} />
    </div>
  );
}

function Evidence({ kind, ev, highlight, markerMs }: {
  kind: string; ev: AutoEvidence; highlight?: number[]; markerMs?: number;
}) {
  if (kind === "psd" && ev.psd) {
    return (
      <div className="row wrap" style={{ gap: 14, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 280 }}><PsdPlot psd={ev.psd} highlight={highlight} /></div>
        {ev.alpha_topo && (
          <div className="col" style={{ alignItems: "center", gap: 2 }}>
            <ScalpDots values={ev.alpha_topo.positions} size={110} />
            <span className="tiny dim">relative alpha</span>
          </div>
        )}
      </div>
    );
  }
  if (kind === "erp" && ev.erp) return <ErpPlot erp={ev.erp} markerMs={markerMs} />;
  if (kind === "timeline" && ev.thirds) return <ThirdsBars t={ev.thirds} />;
  return null;
}

/* ---------------- evidence plots ---------------- */
function useCanvas(draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void, h: number, deps: unknown[]) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const wrap = wrapRef.current, canvas = canRef.current;
    if (!wrap || !canvas) return;
    const render = () => {
      const dpr = window.devicePixelRatio || 1, w = wrap.clientWidth;
      canvas.width = w * dpr; canvas.height = h * dpr;
      canvas.style.width = w + "px"; canvas.style.height = h + "px";
      const ctx = canvas.getContext("2d")!;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.font = "9px 'Share Tech Mono', monospace";
      draw(ctx, w, h);
    };
    render();
    const ro = new ResizeObserver(render); ro.observe(wrap);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { wrapRef, canRef };
}

function PsdPlot({ psd, highlight }: { psd: NonNullable<AutoEvidence["psd"]>; highlight?: number[] }) {
  const H = 150;
  const { wrapRef, canRef } = useCanvas((ctx, w) => {
    const f = psd.freqs, a = psd.mean_db, p = psd.posterior_db;
    const ml = 34, mr = 8, mt = 8, mb = 20;
    const pw = w - ml - mr, ph = H - mt - mb;
    const all = [...a, ...p];
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
    const X = (hz: number) => ml + ((hz - f[0]) / (f[f.length - 1] - f[0])) * pw;
    const Y = (db: number) => mt + (1 - (db - lo) / (hi - lo)) * ph;

    if (highlight && highlight.length === 2) {
      ctx.fillStyle = "rgba(255,47,94,0.16)";
      const x0 = X(Math.max(highlight[0], f[0])), x1 = X(Math.min(highlight[1], f[f.length - 1]));
      ctx.fillRect(x0, mt, Math.max(2, x1 - x0), ph);
    }
    ctx.strokeStyle = "rgba(255,47,94,0.10)"; ctx.fillStyle = "rgba(184,150,118,0.85)";
    [0, 10, 20, 30, 40, 50, 60].forEach((hz) => {
      if (hz < f[0] || hz > f[f.length - 1]) return;
      ctx.beginPath(); ctx.moveTo(X(hz), mt); ctx.lineTo(X(hz), mt + ph); ctx.stroke();
      ctx.fillText(String(hz), X(hz) - 5, H - 6);
    });
    const line = (arr: number[], color: string, width: number) => {
      ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath();
      f.forEach((hz, i) => { const x = X(hz), y = Y(arr[i]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    };
    line(a, "rgba(255,200,90,0.9)", 1.4);
    line(p, "rgba(255,47,94,0.95)", 1.6);
    ctx.fillStyle = "rgba(184,150,118,0.8)"; ctx.fillText("Hz", ml + pw - 12, H - 6);
    ctx.fillStyle = "rgba(255,47,94,0.95)"; ctx.fillText("posterior", ml + 4, mt + 10);
    ctx.fillStyle = "rgba(255,200,90,0.9)"; ctx.fillText("all channels", ml + 4, mt + 22);
  }, H, [psd, highlight]);
  return <div ref={wrapRef} style={{ width: "100%" }}><canvas ref={canRef} style={{ display: "block" }} /></div>;
}

function ErpPlot({ erp, markerMs }: { erp: NonNullable<AutoEvidence["erp"]>; markerMs?: number }) {
  const H = 170;
  const { wrapRef, canRef } = useCanvas((ctx, w) => {
    const t = erp.times_ms;
    const series = [...erp.conditions.map((c) => c.wave), erp.difference];
    const ml = 38, mr = 10, mt = 10, mb = 22;
    const pw = w - ml - mr, ph = H - mt - mb;
    let lo = Infinity, hi = -Infinity;
    for (const s of series) for (const v of s) { if (v < lo) lo = v; if (v > hi) hi = v; }
    const pad = (hi - lo) * 0.1 || 1; lo -= pad; hi += pad;
    const X = (ms: number) => ml + ((ms - t[0]) / (t[t.length - 1] - t[0])) * pw;
    const Y = (uv: number) => mt + (1 - (uv - lo) / (hi - lo)) * ph;

    if (markerMs != null) {
      ctx.fillStyle = "rgba(255,47,94,0.18)";
      ctx.fillRect(X(markerMs) - 6, mt, 12, ph);
    }
    ctx.strokeStyle = "rgba(255,178,46,0.28)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(X(0), mt); ctx.lineTo(X(0), mt + ph); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(ml, Y(0)); ctx.lineTo(ml + pw, Y(0)); ctx.stroke();
    ctx.fillStyle = "rgba(184,150,118,0.85)";
    for (let ms = 0; ms <= t[t.length - 1]; ms += 200) ctx.fillText(`${ms}`, X(ms) - 8, H - 6);
    ctx.fillText("ms", ml + pw - 12, H - 6);
    ctx.fillText(`${hi.toFixed(1)}`, 4, Y(hi) + 8);
    ctx.fillText(`${lo.toFixed(1)} µV`, 4, Y(lo));

    const colors = ["rgba(255,47,94,0.95)", "rgba(255,200,90,0.9)"];
    erp.conditions.forEach((c, i) => {
      ctx.strokeStyle = colors[i % colors.length]; ctx.lineWidth = 1.5; ctx.setLineDash([]);
      ctx.beginPath();
      t.forEach((ms, k) => { const x = X(ms), y = Y(c.wave[k]); k ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
      ctx.fillStyle = colors[i % colors.length];
      ctx.fillText(`${c.name} (n=${c.n})`, ml + 6, mt + 11 + i * 12);
    });
    ctx.strokeStyle = "rgba(245,232,223,0.95)"; ctx.lineWidth = 1.3; ctx.setLineDash([4, 3]);
    ctx.beginPath();
    t.forEach((ms, k) => { const x = X(ms), y = Y(erp.difference[k]); k ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "rgba(245,232,223,0.9)";
    ctx.fillText("difference", ml + 6, mt + 11 + erp.conditions.length * 12);
  }, H, [erp, markerMs]);
  return (
    <div>
      <div ref={wrapRef} style={{ width: "100%" }}><canvas ref={canRef} style={{ display: "block" }} /></div>
      <div className="tiny dim" style={{ marginTop: 4 }}>averaged over {erp.channels_used.join(", ")}</div>
    </div>
  );
}

function ThirdsBars({ t }: { t: NonNullable<AutoEvidence["thirds"]> }) {
  const max = Math.max(...t.delta, ...t.alpha, 0.01);
  return (
    <div className="row" style={{ gap: 18 }}>
      {t.labels.map((lab, i) => (
        <div key={lab} className="col" style={{ gap: 4, flex: 1 }}>
          <div className="row" style={{ gap: 4, alignItems: "flex-end", height: 60 }}>
            <Bar v={t.delta[i]} max={max} color="var(--crimson)" />
            <Bar v={t.alpha[i]} max={max} color="var(--gold)" />
          </div>
          <span className="tiny dim">{lab}</span>
        </div>
      ))}
      <div className="col tiny dim" style={{ gap: 4, justifyContent: "flex-end" }}>
        <span><span style={{ color: "var(--crimson-hi)" }}>■</span> delta</span>
        <span><span style={{ color: "var(--gold-hi)" }}>■</span> alpha</span>
      </div>
    </div>
  );
}

function Bar({ v, max, color }: { v: number; max: number; color: string }) {
  return <div style={{ width: 18, height: `${Math.max(2, (v / max) * 100)}%`, background: color }} />;
}
