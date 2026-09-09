/* Typed API client. Probes /api/health once; if the backend is down, calls fall
 * back to the local synthetic engine. `api.online` reflects the live source. */
import { fallback } from "../lib/synthetic";

// --- wire types (mirror backend schemas) -----------------------------------
export interface Entities {
  subject: string; session: string | null; task: string | null;
  run: string | null; datatype: string;
}
export interface ProvStep { op: string; params: Record<string, unknown>; timestamp: number; software: string }
export interface DatasetMeta {
  id: string; label: string; entities: Entities;
  source_format: string; source_path: string | null;
  sfreq: number; n_channels: number; n_times: number; duration: number;
  highpass: number; lowpass: number;
  channel_type_counts: Record<string, number>; n_events: number;
  extra: Record<string, unknown>; provenance: ProvStep[];
}
export interface TreeDataset {
  id: string; label: string; task: string | null; run: string | null;
  n_channels: number; duration: number; sfreq: number; source_format: string;
}
export interface TreeData {
  tree: Record<string, { subject: string; sessions: Record<string, { session: string | null; datasets: TreeDataset[] }> }>;
}
export interface FormatInfo { ext: string; label: string; status: "ready" | "planned" }
export interface ChannelRow { name: string; type: string; units: string; x: number | null; y: number | null; has_position: boolean }
export interface ChannelsData { channels: ChannelRow[]; positions: { name: string; x: number; y: number }[] }
export interface NeuroEvent { onset: number; duration: number; description: string }
export interface WindowData {
  start: number; duration: number; sfreq: number; decimation: number;
  times: number[]; ch_names: string[]; data: number[][]; units: string;
}
export interface PSDData { freqs: number[]; psd_db: number[][]; ch_names: string[]; method: string; units: string }
export interface BandPowerData { bands: Record<string, number[]>; ch_names: string[]; relative: boolean; band_defs: Record<string, number[]> }
export interface TopoPos { name: string; x: number; y: number; value: number }
export interface TopomapData {
  grid: (number | null)[][]; resolution: number; extent: number[];
  vmin: number; vmax: number; band: number[]; positions: TopoPos[];
}
export interface Health { app: string; version: string; mne: string; numpy: string; n_datasets: number }
export interface DoctorCheck {
  id: string; label: string; status: "ok" | "warn" | "fail"; detail: string; fix: string | null;
}
export interface DoctorReport {
  status: "ok" | "warn" | "fail"; n_fail: number; n_warn: number;
  summary: string; checks: DoctorCheck[];
}

// --- auth (token stored client-side; only needed when the server enables auth) ---
const TOKEN_KEY = "nf_token";
export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? "";
export const setToken = (t: string) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);
export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// --- transport -------------------------------------------------------------
let backendUp: boolean | null = null;

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: authHeaders() });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<T>;
}

async function ensure(): Promise<boolean> {
  if (backendUp !== null) return backendUp;
  try {
    const ctl = new AbortController();
    const id = setTimeout(() => ctl.abort(), 1500);
    const r = await fetch("/api/health", { signal: ctl.signal });
    clearTimeout(id);
    backendUp = r.ok;
  } catch {
    backendUp = false;
  }
  return backendUp;
}

/** Try the live backend; on any failure mark offline and use the fallback. */
async function live<T>(realUrl: string, fb: () => T): Promise<T> {
  if (await ensure()) {
    try {
      return await getJSON<T>(realUrl);
    } catch {
      backendUp = false;
    }
  }
  return fb();
}

export const api = {
  get online() {
    return backendUp === true;
  },
  get source() {
    return backendUp === true ? "MNE backend" : backendUp === false ? "offline demo" : "probing";
  },

  async health(): Promise<Health | null> {
    try {
      const h = await getJSON<Health>("/api/health");
      backendUp = true;
      return h;
    } catch {
      backendUp = false;
      return null;
    }
  },

  async doctor(): Promise<DoctorReport | null> {
    try { return await getJSON<DoctorReport>("/api/doctor"); } catch { return null; }
  },

  listDatasets: () =>
    live<{ datasets: DatasetMeta[] }>("/api/datasets", () => ({ datasets: fallback.listDatasets() })),
  tree: () => live<TreeData>("/api/datasets/tree", () => fallback.tree()),
  formats: () => live<{ formats: FormatInfo[] }>("/api/datasets/formats", () => ({ formats: FALLBACK_FORMATS })),
  channels: (id: string) => live<ChannelsData>(`/api/datasets/${id}/channels`, () => fallback.channels()),
  events: (id: string) => live<{ events: NeuroEvent[] }>(`/api/datasets/${id}/events`, () => ({ events: [] })),

  window: (id: string, start: number, duration: number, picks?: string[], maxPoints = 4000) => {
    const q = new URLSearchParams({ start: String(start), duration: String(duration), max_points: String(maxPoints) });
    if (picks?.length) q.set("picks", picks.join(","));
    return live<WindowData>(`/api/signal/${id}/window?${q}`, () => fallback.window(id, start, duration, maxPoints));
  },
  psd: (id: string, fmin = 0.5, fmax = 45, method = "welch", picks?: string[]) => {
    const q = new URLSearchParams({ fmin: String(fmin), fmax: String(fmax), method });
    if (picks?.length) q.set("picks", picks.join(","));
    return live<PSDData>(`/api/spectral/${id}/psd?${q}`, () => fallback.psd(id));
  },
  bandpower: (id: string, relative = false) =>
    live<BandPowerData>(`/api/spectral/${id}/bandpower?relative=${relative}`, () => fallback.bandpower(id, relative)),
  topomap: (id: string, fmin = 8, fmax = 13, resolution = 48) =>
    live<TopomapData>(`/api/spectral/${id}/topomap?fmin=${fmin}&fmax=${fmax}&resolution=${resolution}`,
      () => fallback.topomap(id, fmin, fmax, resolution)),

  async createSynthetic(body: Record<string, unknown>): Promise<DatasetMeta | null> {
    if (!(await ensure())) return null;
    const r = await fetch("/api/datasets/synthetic", {
      method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify(body),
    });
    return r.ok ? r.json() : null;
  },
  async upload(file: File, fields: Record<string, string>): Promise<{ ok: boolean; detail?: string; meta?: DatasetMeta }> {
    if (!(await ensure())) return { ok: false, detail: "backend offline — upload needs the MNE engine" };
    const fd = new FormData();
    fd.append("file", file);
    for (const [k, v] of Object.entries(fields)) if (v) fd.append(k, v);
    const r = await fetch("/api/datasets/upload", { method: "POST", body: fd, headers: authHeaders() });
    if (r.ok) return { ok: true, meta: await r.json() };
    const d = await r.json().catch(() => ({}));
    return { ok: false, detail: (d as { detail?: string }).detail ?? `HTTP ${r.status}` };
  },
};

const FALLBACK_FORMATS: FormatInfo[] = [
  { ext: ".edf", label: "European Data Format", status: "ready" },
  { ext: ".bdf", label: "BioSemi Data Format", status: "ready" },
  { ext: ".gdf", label: "General Data Format", status: "ready" },
  { ext: ".vhdr", label: "BrainVision", status: "ready" },
  { ext: ".cnt", label: "Neuroscan CNT", status: "ready" },
  { ext: ".set", label: "EEGLAB", status: "ready" },
  { ext: ".fif", label: "MNE-Python / FIFF", status: "ready" },
  { ext: ".mff", label: "EGI NetStation", status: "ready" },
  { ext: ".nwb", label: "Neurodata Without Borders", status: "planned" },
  { ext: ".nev", label: "Blackrock", status: "planned" },
  { ext: ".csv", label: "Generic ASCII/CSV", status: "planned" },
];
