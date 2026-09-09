/* API client for Modules 3–10. These need the live MNE backend (heavy compute);
   on failure the calls throw and the module UIs show a "requires backend" note. */
import { authHeaders, type DatasetMeta } from "./client";

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: authHeaders() });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<T>;
}
async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<T>;
}

async function del<T>(url: string): Promise<T> {
  const r = await fetch(url, { method: "DELETE", headers: authHeaders() });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<T>;
}

export interface JobProgress {
  status: string; done_n: number; total_n: number; step: string;
  elapsed: number; eta: number | null;
}

// Poll a background job to completion. Heavy ops (ICA, decoding, cohort runs) go
// async on the server and return a job_id. `onProgress` gets every poll, so long
// jobs can show how far along they are instead of an unmoving spinner.
async function pollJob<T>(jobId: string, interval = 500, timeoutMs = 180_000,
                          onProgress?: (p: JobProgress) => void): Promise<T> {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const j = await get<JobProgress & { error?: string; result?: T }>(`/api/jobs/${jobId}`);
    onProgress?.(j);
    if (j.status === "done") return j.result as T;
    if (j.status === "error") throw new Error(j.error || "job failed");
    await new Promise((r) => setTimeout(r, interval));
  }
  throw new Error("job timed out");
}

export interface ModuleProps { dataset: DatasetMeta | null; onChanged: () => void }

// ---- response shapes (only fields the UI reads) ----------------------------
export interface StepDef { op: string; label: string; params: Record<string, unknown> }
export interface QC {
  new_id: string; psd_before: { freqs: number[]; mean: number[] }; psd_after: { freqs: number[]; mean: number[] };
  detected_bads: string[]; ica_excluded: number[]; applied: { op: string; params: Record<string, unknown>; error?: string }[];
}
export interface TopoVal { name: string; x: number; y: number; value: number }
export interface ERPResult {
  times_ms: number[];
  conditions: { name: string; n: number; wave: number[]; gfp: number[]; peak: { latency_ms: number; amp_uv: number } }[];
  difference?: { name: string; wave: number[]; peak: { latency_ms: number; amp_uv: number };
    topo: { latency_ms: number; vmin: number; vmax: number; positions: TopoVal[] } };
  clusters?: { start_ms: number; end_ms: number; p: number }[];
}
export interface FeaturesResult { rows: Record<string, number | string>[]; columns: string[] }
export interface ConnResult {
  method: string; band: string; band_hz: number[]; matrix: number[][]; names: string[];
  nodes: { name: string; x: number; y: number; degree: number; clustering: number; strength: number }[];
  threshold: number; global_clustering: number; density: number;
}
export interface MapperOverview {
  datasets: { id: string; label: string; subject: string; session: string | null; task: string | null; summary: Record<string, number> }[];
  bands: string[];
}
export interface MapperMatrix {
  metric: string; rows: { id: string; label: string; ch_names: string[]; values: number[] }[];
  labels: string[]; similarity: number[][]; mean_reliability: number;
}
export interface BenchResult {
  dataset: string; best: string;
  results: { name: string; alpha_snr_db: number; time_ms: number; ica_removed: number; sfreq: number }[];
  environment: Record<string, string>; repro_hash: string;
}
export interface QualityResult { ch_names: string[]; correlation: number[][]; mean_abs_corr: number; alpha_snr_db: number }
export interface DecodeResult {
  classifier: string; task: string; accuracy: number; kappa: number; auc: number; itr: number;
  confusion: number[][]; folds_acc: number[]; n_folds: number; n_epochs: number; classes: string[];
  control: number[]; truth: number[]; proba: number[];
  patterns: { comp: number; values: TopoVal[] }[] | null;
}
export interface ScriptMeta { id: string; name: string; description: string; author: string; created_at: number }
export interface ScriptFull extends ScriptMeta { code: string }
export interface ScriptResult {
  ok: boolean; result?: unknown; figures?: string[]; stdout?: string;
  error?: string; error_type?: string; duration?: number;
}
export interface ScriptRun {
  dataset_id: string; label: string; ok: boolean; error_type?: string; error?: string;
  result?: unknown; figures?: string[]; duration?: number;
}
export interface BatchResult { mode: "each"; runs: ScriptRun[]; n: number; ok: boolean }

// ---- Auto-Analysis Engine -------------------------------------------------
export interface HealthCheck {
  id: string; label: string; status: "ok" | "warn" | "fail" | "na";
  value: number | string | null; detail: string; evidence?: string | null;
}
export interface Finding {
  title: string; plain: string; confidence: number;
  evidence: { kind: string; key: string; highlight?: number[]; marker_ms?: number };
}
export interface NextStep { action: string; why: string; module: string; params: Record<string, unknown> }
export interface CleanupStep { op: string; params: Record<string, unknown>; label: string; why: string }
export interface Cleanup { steps: CleanupStep[]; skipped: string[]; estimate: string }
export interface AutoEvidence {
  psd?: { freqs: number[]; mean_db: number[]; posterior_db: number[]; frontal_db: number[] };
  alpha_topo?: { positions: TopoVal[] };
  erp?: {
    times_ms: number[]; difference: number[]; channels_used: string[];
    conditions: { name: string; n: number; wave: number[] }[];
  };
  thirds?: { labels: string[]; delta: number[]; alpha: number[] };
}
export interface AutoReport {
  dataset: {
    id: string; label: string; sfreq: number; n_channels: number; n_channels_total: number;
    duration_s: number; n_events: number; event_source: string;
    source_format: string; source_path: string | null;
  };
  summary: string;
  recording_type: {
    code: string; label: string; confidence: number; why: string[];
    candidates: { code: string; label: string; score: number }[];
  };
  health: { score: number; grade: string; checks: HealthCheck[]; n_fail: number; n_warn: number };
  findings: Finding[];
  next_steps: NextStep[];
  cleanup: Cleanup;
  evidence: AutoEvidence;
  disclaimer: string;
  error?: string;
}

// ---- cohort / batch --------------------------------------------------------
export interface CohortColumn { key: string; label: string; kind: string }
export interface CohortRow {
  dataset_id: string; label: string; subject: string; session: string | null;
  task: string | null; run: string | null;
  recording_type: string; type_code: string; type_confidence: number;
  health: number; grade: string; n_fail: number; n_warn: number;
  n_channels: number; duration_s: number; sfreq: number; n_events: number;
  bad_channels: number | null; line_noise_db: number | null; drift_uv: number | null;
  muscle_pct: number | null; blinks_per_min: number | null; alpha_peak_hz: number | null;
  alpha_finding: string | null; p300_finding: string | null;
  [k: string]: unknown;
}
export interface CohortSummary {
  n: number; mean_health: number | null; n_usable: number; consistent: boolean;
  types: Record<string, number>; grades: Record<string, number>;
  stats: Record<string, { median: number; mad: number; min: number; max: number }>;
  outliers: { dataset_id: string; label: string; reasons: string[] }[];
}
export interface CohortAnalysis {
  rows: CohortRow[]; columns: CohortColumn[]; summary: CohortSummary;
  failed: { dataset_id: string; label: string; error: string }[];
}
export interface CohortCleanResult {
  results: {
    dataset_id: string; new_id: string | null; label: string; skipped?: string;
    before: number; after: number; delta: number;
    grade_before?: string; grade_after?: string; steps?: string[];
    detected_bads?: string[]; ica_excluded?: number[]; row?: CohortRow;
  }[];
  failed: { dataset_id: string; label: string; error: string }[];
  n_improved: number; n_unchanged: number; n_worse: number; mean_delta: number;
}

// ---- folder import / BIDS export -------------------------------------------
export interface ScanCandidate {
  path: string; relative: string; format: string; size_mb: number;
  subject: string; session: string | null; task: string | null; run: string | null;
}
export interface ScanResult {
  root: string; n_found: number; candidates: ScanCandidate[];
  subjects: string[]; n_subjects: number; is_bids: boolean;
}
export interface ImportResult {
  n_found: number; n_loaded: number; datasets: DatasetMeta[];
  failed: { path: string; error: string }[];
}
export interface BidsExportResult {
  root: string; n_written: number; n_subjects: number;
  written: { dataset_id: string; path: string }[];
  failed: { dataset_id: string; label: string; error: string }[];
}

export interface SampleItem {
  id: string; kind: "synthetic" | "download"; label: string; blurb: string;
  duration_s: number | null; task: string; needs_network: boolean;
}

export const mod = {
  prepCatalog: () => get<{ catalog: StepDef[] }>("/api/preprocess/catalog"),
  prepRun: async (id: string, steps: unknown[]) => {
    const { job_id } = await post<{ job_id: string }>(`/api/preprocess/${id}/run`, { steps });
    return pollJob<{ dataset: DatasetMeta; qc: QC }>(job_id);
  },

  erpConditions: (id: string) => get<{ conditions: { name: string; code: number; count: number }[] }>(`/api/erp/${id}/conditions`),
  erpCompute: (id: string, body: unknown) => post<ERPResult>(`/api/erp/${id}/compute`, body),

  features: (id: string) => get<FeaturesResult>(`/api/analyze/${id}/features`),
  connectivity: (id: string, method: string, band: string) => get<ConnResult>(`/api/analyze/${id}/connectivity?method=${method}&band=${band}`),

  mapperOverview: () => get<MapperOverview>("/api/mapper/overview"),
  mapperMatrix: (metric: string) => get<MapperMatrix>(`/api/mapper/matrix?metric=${metric}`),

  benchPipelines: async (id: string) => {
    const { job_id } = await get<{ job_id: string }>(`/api/bench/${id}/pipelines`);
    return pollJob<BenchResult>(job_id);
  },
  benchQuality: (id: string) => get<QualityResult>(`/api/bench/${id}/quality`),

  bciClassifiers: () => get<{ classifiers: { id: string; label: string }[] }>("/api/bci/classifiers"),
  bciDecode: async (id: string, classifier: string, folds: number) => {
    const { job_id } = await post<{ job_id: string }>(`/api/bci/${id}/decode`, { classifier, folds });
    return pollJob<DecodeResult>(job_id);
  },

  editChannels: (id: string, body: unknown) => post<DatasetMeta>(`/api/edit/${id}/channels`, body),
  editCrop: (id: string, body: unknown) => post<DatasetMeta>(`/api/edit/${id}/crop`, body),
  editVirtual: (id: string, body: unknown) => post<DatasetMeta>(`/api/edit/${id}/virtual`, body),
  editAnnotation: (id: string, body: unknown) => post<DatasetMeta>(`/api/edit/${id}/annotation`, body),
  editMontages: () => get<{ montages: string[] }>("/api/edit/montages"),
  editMontage: (id: string, montage: string) => post<DatasetMeta>(`/api/edit/${id}/montage`, { montage }),

  reportFormats: () => get<{ export_formats: { fmt: string; label: string }[] }>("/api/report/formats"),
  reportHtml: (id: string) => fetch(`/api/report/${id}/html`).then((r) => r.text()),
  reportEnv: (id: string) => get<{ environment: Record<string, string>; repro_hash: string }>(`/api/report/${id}/environment`),
  reportScript: (id: string) => get<{ filename: string; code: string }>(`/api/report/${id}/script`),
  scriptUrl: (id: string) => `/api/report/${id}/script?download=true`,
  exportUrl: (id: string, fmt: string) => `/api/report/${id}/export?fmt=${fmt}`,

  // M11 — user scripting
  scriptsList: () => get<{ scripts: ScriptMeta[]; enabled: boolean; timeout_s: number }>("/api/scripts"),
  scriptExamples: () => get<{ examples: { name: string; code: string }[] }>("/api/scripts/examples"),
  scriptGet: (id: string) => get<ScriptFull>(`/api/scripts/${id}`),
  scriptSave: (body: { name: string; description?: string; code: string; id?: string }) =>
    post<ScriptFull>("/api/scripts", body),
  scriptDelete: (id: string) => del<{ deleted: string }>(`/api/scripts/${id}`),
  scriptRun: async (datasetIds: string[], code: string, params: Record<string, unknown>, mode: "each" | "group" = "each") => {
    const body: Record<string, unknown> = { code, params, mode };
    if (datasetIds.length === 1) body.dataset_id = datasetIds[0];
    else body.dataset_ids = datasetIds;
    const { job_id } = await post<{ job_id: string }>("/api/scripts/run", body);
    return pollJob<ScriptResult | BatchResult>(job_id);
  },

  aperiodic: (id: string) => get<{
    channels: string[]; exponent: number[]; offset: number[]; mean: { exponent: number; offset: number; r2: number };
    freqs: number[]; mean_psd_db: number[]; mean_aperiodic_db: number[]; peaks: { cf: number; power: number }[];
    positions: TopoVal[];
  }>(`/api/analyze/${id}/aperiodic`),

  // Auto-Analysis Engine — one call, plain-language report
  autoAnalyze: async (id: string) => {
    const { job_id } = await post<{ job_id: string }>(`/api/auto/${id}/analyze`, {});
    return pollJob<AutoReport>(job_id);
  },

  // Cohort — the same thing, to all of them, at once
  batchColumns: () => get<{ columns: CohortColumn[] }>("/api/batch/columns"),
  batchAnalyze: async (ids: string[], onProgress?: (p: JobProgress) => void) => {
    const { job_id } = await post<{ job_id: string }>("/api/batch/analyze", { dataset_ids: ids });
    return pollJob<CohortAnalysis>(job_id, 700, 3_600_000, onProgress);
  },
  batchClean: async (ids: string[], steps: unknown[] | null, onProgress?: (p: JobProgress) => void) => {
    const { job_id } = await post<{ job_id: string }>("/api/batch/clean", { dataset_ids: ids, steps });
    return pollJob<CohortCleanResult>(job_id, 700, 3_600_000, onProgress);
  },
  batchCsvUrl: "/api/batch/csv",

  // Folder import / BIDS export
  bidsScan: (path: string) => post<ScanResult>("/api/bids/scan", { path }),
  bidsImport: async (path: string, files: string[], onProgress?: (p: JobProgress) => void) => {
    const { job_id } = await post<{ job_id: string }>("/api/bids/import", { path, files });
    return pollJob<ImportResult>(job_id, 700, 3_600_000, onProgress);
  },
  bidsExport: async (ids: string[], outDir: string | null, name: string, derivative: boolean) => {
    const { job_id } = await post<{ job_id: string }>("/api/bids/export", {
      dataset_ids: ids, out_dir: outDir, name, derivative,
    });
    return pollJob<BidsExportResult>(job_id, 700, 1_800_000);
  },

  // Sample gallery — one click from empty app to something worth analysing
  samplesList: () => get<{ samples: SampleItem[] }>("/api/samples"),
  sampleLoad: async (id: string) => {
    const r = await post<{ dataset?: DatasetMeta; job_id?: string }>(`/api/samples/${id}/load`, {});
    if (r.dataset) return r.dataset;
    // downloads run as a job and can take a while on first use
    return pollJob<DatasetMeta>(r.job_id!, 1000, 900_000);
  },

  microstates: (id: string, nStates = 4) => get<{
    n_states: number; letters: string[]; gev: number;
    coverage: number[]; mean_duration_ms: number[]; occurrence_per_s: number[];
    transitions: number[][]; maps: { label: string; positions: TopoVal[] }[]; sequence: number[];
  }>(`/api/analyze/${id}/microstates?n_states=${nStates}`),
};
