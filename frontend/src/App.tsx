import { useEffect, useState, useCallback } from "react";
import Boot from "./components/Boot";
import { api, getToken, setToken, type DatasetMeta } from "./api/client";
import { nowStamp } from "./lib/format";
import AutoAnalysis from "./modules/auto/AutoAnalysis";
import Guided from "./modules/guided/Guided";
import Repository from "./modules/repository/Repository";
import Visualize from "./modules/visualize/Visualize";
import Preprocess from "./modules/preprocess/Preprocess";
import ERP from "./modules/erp/ERP";
import Analyze from "./modules/analyze/Analyze";
import Mapper from "./modules/mapper/Mapper";
import Bench from "./modules/bench/Bench";
import BCI from "./modules/bci/BCI";
import Editor from "./modules/editor/Editor";
import Report from "./modules/report/Report";
import CodeLab from "./modules/lab/CodeLab";
import Cohort from "./modules/cohort/Cohort";
import { MODULE_INFO } from "./modules/placeholder/ModulePlaceholder";
import SceneDecor from "./components/SceneDecor";
import ErrorBoundary from "./components/ErrorBoundary";
import SetupCheck from "./components/SetupCheck";
import CommandPalette, { useCommandPalette, type Command } from "./components/CommandPalette";

interface ModDef { id: string; idx: string; label: string; gly: string; live: boolean }

const MODULES: ModDef[] = [
  { id: "auto", idx: "00", label: "Auto", gly: "◉", live: true },
  { id: "repository", idx: "01", label: "Repo", gly: "▤", live: true },
  { id: "visualize", idx: "02", label: "View", gly: "∿", live: true },
  { id: "preprocess", idx: "03", label: "Prep", gly: "⚙", live: true },
  { id: "erp", idx: "04", label: "ERP", gly: "Λ", live: true },
  { id: "analyze", idx: "05", label: "Analyze", gly: "∑", live: true },
  { id: "mapper", idx: "06", label: "Mapper", gly: "◎", live: true },
  { id: "bench", idx: "07", label: "Bench", gly: "▥", live: true },
  { id: "bci", idx: "08", label: "BCI", gly: "◈", live: true },
  { id: "editor", idx: "09", label: "Editor", gly: "✎", live: true },
  { id: "report", idx: "10", label: "Report", gly: "▣", live: true },
  { id: "lab", idx: "11", label: "Lab", gly: "⌨", live: true },
  { id: "cohort", idx: "12", label: "Cohort", gly: "⦿", live: true },
];

// How people actually describe each module when they search for it, rather than the
// name we happened to give it.
const MODULE_KEYWORDS: Record<string, string> = {
  auto: "analyze report health findings summary what is this",
  repository: "import upload load open files bids browse datasets",
  visualize: "signal traces viewer waveform browse raw scroll",
  preprocess: "filter notch ica clean artifact reference resample bad channels",
  erp: "p300 n170 mmn evoked average epochs latency cluster peak",
  analyze: "psd spectrum bandpower fooof aperiodic microstates connectivity coherence features",
  mapper: "cohort group compare subjects reliability matrix",
  bench: "benchmark pipeline compare quality snr",
  bci: "decode classify csp lda accuracy motor imagery kappa itr",
  editor: "channels crop montage annotate rename drop virtual",
  report: "export html pdf fif csv provenance reproduce script hash",
  lab: "python code script custom notebook run",
  cohort: "batch group study all subjects table csv outliers many",
};

// Guided is the default face; the choice sticks so returning users land where they left.
const MODE_KEY = "nf_mode";
type Mode = "guided" | "pro";

export default function App() {
  const [booted, setBooted] = useState(false);
  const [active, setActive] = useState("auto");
  const [mode, setMode] = useState<Mode>(
    () => (localStorage.getItem(MODE_KEY) === "pro" ? "pro" : "guided"));
  const [datasets, setDatasets] = useState<DatasetMeta[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [clock, setClock] = useState(nowStamp());
  const [hasKey, setHasKey] = useState(getToken().length > 0);

  const palette = useCommandPalette();

  const switchMode = (m: Mode) => { setMode(m); localStorage.setItem(MODE_KEY, m); };
  const openInPro = (moduleId: string) => { setActive(moduleId); switchMode("pro"); };

  const commands: Command[] = [
    { id: "mode:guided", group: "Mode", title: "Guided mode", hint: "five steps, answers first",
      keywords: "wizard simple beginner steps", run: () => switchMode("guided") },
    { id: "mode:pro", group: "Mode", title: "Pro mode", hint: "all 12 modules",
      keywords: "advanced hud expert modules", run: () => switchMode("pro") },
    ...MODULES.map((m) => ({
      id: `mod:${m.id}`, group: "Module", title: MODULE_INFO[m.id]?.name ?? m.label,
      hint: m.idx, keywords: MODULE_KEYWORDS[m.id] ?? "", run: () => openInPro(m.id),
    })),
  ];

  const setKey = () => {
    const t = window.prompt("API bearer token (blank to clear):", getToken());
    if (t !== null) { setToken(t.trim()); setHasKey(t.trim().length > 0); }
  };

  const refresh = useCallback(async () => {
    const { datasets } = await api.listDatasets();
    setDatasets(datasets);
    setSelectedId((cur) => cur && datasets.some((d) => d.id === cur) ? cur : datasets[0]?.id ?? null);
  }, []);

  useEffect(() => {
    if (booted) refresh();
  }, [booted, refresh]);

  useEffect(() => {
    const t = setInterval(() => setClock(nowStamp()), 1000);
    return () => clearInterval(t);
  }, []);

  if (!booted) return <Boot onDone={() => setBooted(true)} />;

  const selected = datasets.find((d) => d.id === selectedId) ?? null;
  const activeMod = MODULES.find((m) => m.id === active)!;

  return (
    <div className="app">
      {palette.open && (
        <CommandPalette
          commands={commands}
          datasets={datasets}
          onSelectDataset={setSelectedId}
          onClose={() => palette.setOpen(false)}
        />
      )}

      {/* ---- top bar ---- */}
      <header className="topbar">
        <div className="brand">
          <span className="mark">Neuroforge<sup>²</sup></span>
          <span className="sub">// desktop imperium</span>
        </div>

        <div className="mode-toggle row" style={{ marginLeft: 14 }}>
          {(["guided", "pro"] as Mode[]).map((m) => (
            <button key={m} className={`mode-btn ${mode === m ? "on" : ""}`} onClick={() => switchMode(m)}
              title={m === "guided" ? "five steps, answers first" : "all 12 modules, full control"}>
              {m}
            </button>
          ))}
        </div>

        <div className="row" style={{ marginLeft: 12, gap: 8 }}>
          <span className="tiny up dim">dataset</span>
          <select
            className="nf"
            value={selectedId ?? ""}
            onChange={(e) => setSelectedId(e.target.value)}
            style={{ minWidth: 230 }}
          >
            {datasets.length === 0 && <option>— none —</option>}
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </select>
          <button className="btn sm" onClick={refresh} title="rescan repository">⟳</button>
        </div>

        <div className="topbar-right">
          <span className="led">
            <span className={`dot ${api.online ? "on" : "off"}`} />
            {api.source}
          </span>
          <SetupCheck />
          <button className="led" onClick={setKey} title="set bearer token (for auth-enabled servers)"
            style={{ background: "none", border: "none", cursor: "pointer", font: "inherit", letterSpacing: "inherit", textTransform: "uppercase" }}>
            <span className="dot" style={{ background: hasKey ? "var(--gold)" : "var(--txt-dim)", boxShadow: hasKey ? "0 0 8px var(--gold)" : "none" }} />
            {hasKey ? "auth✓" : "auth"}
          </button>
          <span className="clock">{clock}</span>
        </div>
      </header>

      {/* ---- body: rail + content ---- */}
      <div className={`app-body ${mode === "guided" ? "no-rail" : ""}`}>
        {mode === "pro" && (
        <nav className="rail">
          {MODULES.map((m) => (
            <button
              key={m.id}
              className={`rail-btn ${active === m.id ? "active" : ""}`}
              onClick={() => setActive(m.id)}
              title={`${m.idx} · ${MODULE_INFO[m.id]?.name ?? m.label}${m.live ? "" : " (roadmap)"}`}
            >
              <span className="gly">{m.gly}</span>
              <span className="lbl">{m.label}</span>
            </button>
          ))}
          <div className="rail-spacer" />
          <div className="rail-meta">v0.2<br />HUD</div>
        </nav>
        )}

        <main className="content">
          <SceneDecor />
          {/* keyed on the module so switching away from a crashed one clears it */}
          <ErrorBoundary key={mode === "guided" ? "guided" : active}
            label={mode === "guided" ? "Guided mode" : (MODULE_INFO[active]?.name ?? activeMod.label)}>
          {mode === "guided" && (
            <Guided
              datasets={datasets}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onChanged={refresh}
              onNavigate={openInPro}
              onExit={() => switchMode("pro")}
            />
          )}
          {mode === "pro" && <>
          {active === "auto" && (
            <AutoAnalysis dataset={selected} onChanged={refresh} onNavigate={setActive} />
          )}
          {active === "repository" && (
            <Repository
              datasets={datasets}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onChanged={refresh}
              onOpenViewer={() => setActive("visualize")}
            />
          )}
          {active === "visualize" && <Visualize dataset={selected} />}
          {active === "preprocess" && <Preprocess dataset={selected} onChanged={refresh} />}
          {active === "erp" && <ERP dataset={selected} onChanged={refresh} />}
          {active === "analyze" && <Analyze dataset={selected} onChanged={refresh} />}
          {active === "mapper" && <Mapper dataset={selected} onChanged={refresh} />}
          {active === "bench" && <Bench dataset={selected} onChanged={refresh} />}
          {active === "bci" && <BCI dataset={selected} onChanged={refresh} />}
          {active === "editor" && <Editor dataset={selected} onChanged={refresh} />}
          {active === "report" && <Report dataset={selected} onChanged={refresh} />}
          {active === "lab" && <CodeLab dataset={selected} onChanged={refresh} />}
          {active === "cohort" && (
            <Cohort
              datasets={datasets}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onChanged={refresh}
              onNavigate={setActive}
            />
          )}
          </>}
          </ErrorBoundary>
        </main>
      </div>

      {/* ---- status bar ---- */}
      <footer className="statusbar">
        <div className="status-cell amber">
          <span>mode</span>
          <span className="v">
            {mode === "guided" ? "guided · 5 steps" : `${activeMod.idx} · ${MODULE_INFO[active]?.name ?? activeMod.label}`}
          </span>
        </div>
        <div className="status-cell">
          <span>source</span><span className="v">{api.source}</span>
        </div>
        {selected && (
          <>
            <div className="status-cell"><span>fs</span><span className="v">{selected.sfreq} Hz</span></div>
            <div className="status-cell"><span>ch</span><span className="v">{selected.n_channels}</span></div>
            <div className="status-cell"><span>dur</span><span className="v">{selected.duration.toFixed(1)} s</span></div>
            <div className="status-cell"><span>evt</span><span className="v">{selected.n_events}</span></div>
          </>
        )}
        <div className="status-cell grow">
          <span>NEUROFORGE // {datasets.length} datasets indexed · press ctrl+K to jump anywhere</span>
        </div>
      </footer>
    </div>
  );
}
