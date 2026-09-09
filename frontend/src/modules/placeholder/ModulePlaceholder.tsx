import { Panel, Chip } from "../../components/hud";

interface Info { name: string; tagline: string; features: string[]; status: "live" | "roadmap" }

export const MODULE_INFO: Record<string, Info> = {
  auto: {
    name: "Auto-Analysis Engine", status: "live",
    tagline: "One button: what is this recording, is it usable, what next.",
    features: ["Paradigm detection with reasons", "Data-health score and checks",
      "Notable findings with evidence plots", "Concrete suggested next steps"],
  },
  cohort: {
    name: "Cohort / Batch", status: "live",
    tagline: "A study treated as a study — analyse and clean every recording at once.",
    features: ["Auto-analysis across the whole cohort", "One sortable, exportable table",
      "Robust outlier detection (median/MAD)", "Per-recording recommended cleanup in one pass"],
  },
  repository: {
    name: "Universal Loader / BIDS Repository", status: "live",
    tagline: "Ingest anything, normalize to NeuroData, index BIDS-native.",
    features: ["EDF/BDF/GDF/BrainVision/EEGLAB/FIFF/EGI loaders", "Synthetic generator", "BIDS subject/session/run tree", "Channel & event sidecars"],
  },
  visualize: {
    name: "Interactive Visualization Engine", status: "live",
    tagline: "Signals, spectra, topographies and a 3D head model.",
    features: ["Multichannel time-series viewer", "Welch / multitaper PSD", "2D topographic scalp maps", "3D electrode head model"],
  },
  preprocess: {
    name: "Preprocessing Pipeline Engine", status: "roadmap",
    tagline: "Modular, visual, reproducible cleaning with live preview.",
    features: ["Re-referencing (avg / REST / bipolar / Laplacian)", "FIR/IIR filtering + notch (50/60 Hz)", "Bad channel & segment detection", "ICA (Picard/Infomax) + ICLabel auto-classify", "Autoreject · SSP · PREP", "Drag-and-drop pipeline builder + QC reports"],
  },
  erp: {
    name: "ERP / ERF Finder & Analyzer", status: "roadmap",
    tagline: "From triggers to grand averages with cluster statistics.",
    features: ["Event parsing (BIDS / Psychopy / E-Prime)", "Flexible epoching + baseline", "Peak / area / fractional latency", "Cluster-based permutation tests", "Difference waves + GFP / TANOVA", "Topographic animation"],
  },
  analyze: {
    name: "Signal Analyzer & Feature Extractor", status: "roadmap",
    tagline: "Time, frequency, time-frequency and connectivity features.",
    features: ["Hjorth · entropy · fractal (Higuchi/DFA)", "Band power · spectral edge · peak freq", "Morlet / Hilbert-Huang / matching pursuit", "Coherence · PLV · PLI · wPLI", "Granger · DTF · PDC", "Graph metrics + dynamic connectivity"],
  },
  mapper: {
    name: "Cross-Session / Cross-Subject Mapper", status: "roadmap",
    tagline: "Align, normalize and compare across time and people.",
    features: ["DTW temporal alignment", "Montage / MNI spatial normalization", "Test-retest reliability + ICC", "Mixed-effects (subject random effect)", "Leave-one-subject-out", "Normative modeling vs group"],
  },
  bench: {
    name: "Benchmarking & Validation Suite", status: "roadmap",
    tagline: "Standardized datasets, pipeline shootouts, reproducibility.",
    features: ["EEGBCI / MOABB / OpenNeuro loaders", "Pipeline & algorithm comparison", "SNR & data-quality metrics", "Simulated ground truth", "Hash-based provenance + env capture", "MOABB leaderboards"],
  },
  bci: {
    name: "BCI / Neurotechnology Workbench", status: "roadmap",
    tagline: "From CSP & Riemann to real-time closed-loop decoding.",
    features: ["CSP / FBCSP / CSSP", "Riemannian tangent-space", "EEGNet / DeepConvNet / LSTM", "LDA/SVM/RF/XGBoost decoders", "Kappa · AUC · ITR", "LSL <50 ms real-time loop"],
  },
  editor: {
    name: "Data Editor & Annotation System", status: "roadmap",
    tagline: "Edit channels, time, events — with git-like versioning.",
    features: ["Virtual channels (bipolar/Laplacian/PCA)", "Crop / concat / split runs", "Multi-track annotation layers", "Channel arithmetic & formulas", "Montage transforms", "Audit trail + diff view"],
  },
  lab: {
    name: "Code Lab / Scripting", status: "live",
    tagline: "Write and run custom analysis code against any dataset.",
    features: ["Isolated subprocess execution + timeout", "np / scipy / mne / pandas in scope",
      "Captured stdout + matplotlib figures", "Save & reuse scripts (protocols)"],
  },
  report: {
    name: "Reporting & Export Engine", status: "roadmap",
    tagline: "HTML reports and multi-format export.",
    features: ["Automated HTML / PDF reports", "BIDS-compliant derivatives", "FIF / SET / EDF / HDF5 / CSV export", "Vector + MP4/GIF figure export", "Python API + Jupyter widgets", "Plugin system + REST API"],
  },
};

export default function ModulePlaceholder({ moduleId }: { moduleId: string }) {
  const info = MODULE_INFO[moduleId];
  if (!info) return null;
  const num = Object.keys(MODULE_INFO).indexOf(moduleId) + 1;

  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr", maxWidth: 880, margin: "0 auto" }}>
      <Panel
        tag={`MODULE ${String(num).padStart(2, "0")}`}
        title={info.name}
        meta={<Chip kind="plan">roadmap</Chip>}
      >
        <div className="col" style={{ gap: 16 }}>
          <div className="reticle sweep" style={{ height: 92, border: "1px solid var(--line)", background: "rgba(0,0,0,0.25)" }}>
            <div className="center col" style={{ gap: 6 }}>
              <span className="up amber" style={{ letterSpacing: "0.3em" }}>not yet enabled</span>
              <span className="tiny dim">{info.tagline}</span>
            </div>
          </div>

          <div>
            <div className="tiny up dim" style={{ marginBottom: 8 }}>specified capabilities ›</div>
            <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {info.features.map((f, i) => (
                <div key={i} className="row" style={{ gap: 8, alignItems: "flex-start" }}>
                  <span className="cyan" style={{ fontSize: 11 }}>▹</span>
                  <span style={{ fontSize: 12, lineHeight: 1.4 }}>{f}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="placeholder-note" style={{ borderTop: "1px solid var(--line)", paddingTop: 12 }}>
            This module has a reserved home in the architecture (<span className="cyan">backend/neuroforge/api</span> +
            a frontend module shell). The MVP ships <span className="amber">Module 01</span> and{" "}
            <span className="amber">Module 02</span> end-to-end; the rest activate incrementally against the same
            NeuroData model and API contract.
          </div>
        </div>
      </Panel>
    </div>
  );
}
