/* Ctrl/⌘-K — go anywhere, switch anything, without hunting the rail.
 *
 * The point is not speed for its own sake: it is that the whole application becomes
 * searchable by *name*. Someone who has never seen the HUD can type "p300" and land
 * on the ERP module, or type a dataset label and switch to it.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { DatasetMeta } from "../api/client";

export interface Command {
  id: string; title: string; hint?: string; group: string; run: () => void;
  /** Extra search terms — how people actually describe the thing ("p300", "ica"). */
  keywords?: string;
}

export function useCommandPalette() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return { open, setOpen };
}

/** Fuzzy subsequence match — "psd" finds "Power Spectral Density". */
function score(text: string, q: string): number {
  if (!q) return 1;
  const t = text.toLowerCase();
  if (t.includes(q)) return 100 - t.indexOf(q);
  let i = 0, hits = 0;
  for (const ch of t) {
    if (ch === q[i]) { i++; hits++; if (i === q.length) break; }
  }
  return i === q.length ? hits : 0;
}

export default function CommandPalette({ commands, datasets, onSelectDataset, onClose }: {
  commands: Command[];
  datasets: DatasetMeta[];
  onSelectDataset: (id: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const all: Command[] = useMemo(() => [
    ...commands,
    ...datasets.map((d) => ({
      id: `ds:${d.id}`, group: "Datasets", title: d.label,
      hint: `${d.n_channels} ch · ${d.duration.toFixed(0)} s · ${d.source_format}`,
      run: () => onSelectDataset(d.id),
    })),
  ], [commands, datasets, onSelectDataset]);

  const results = useMemo(() => {
    const query = q.trim().toLowerCase();
    return all
      .map((c) => ({
        c, s: Math.max(score(c.title, query), score(c.group, query) * 0.5,
                       c.keywords ? score(c.keywords, query) * 0.9 : 0),
      }))
      .filter((r) => r.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 40)
      .map((r) => r.c);
  }, [all, q]);

  useEffect(() => { setCursor(0); }, [q]);

  const fire = (c: Command | undefined) => { if (c) { c.run(); onClose(); } };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 90, background: "rgba(4,2,4,0.62)",
        display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "12vh",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 620, maxWidth: "calc(100vw - 28px)", background: "var(--panel)",
          border: "1px solid var(--bevel-lo)", boxShadow: "0 30px 90px -22px rgba(0,0,0,0.95)",
        }}
      >
        <input
          ref={inputRef}
          className="nf"
          value={q}
          placeholder="jump to a module, action or dataset…"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, results.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
            else if (e.key === "Enter") { e.preventDefault(); fire(results[cursor]); }
          }}
          style={{
            width: "100%", padding: "13px 15px", fontSize: 14, border: "none",
            borderBottom: "1px solid var(--line)", background: "rgba(0,0,0,0.3)",
          }}
        />
        <div style={{ maxHeight: "52vh", overflow: "auto" }}>
          {results.length === 0 && (
            <div className="tiny dim" style={{ padding: 18, textAlign: "center" }}>
              nothing matches “{q}”
            </div>
          )}
          {results.map((c, i) => (
            <div
              key={c.id}
              onMouseEnter={() => setCursor(i)}
              onClick={() => fire(c)}
              className="row"
              style={{
                gap: 12, padding: "9px 15px", cursor: "pointer", alignItems: "baseline",
                background: i === cursor ? "rgba(255,47,94,0.14)" : "transparent",
                borderLeft: `2px solid ${i === cursor ? "var(--crimson)" : "transparent"}`,
              }}
            >
              <span className="tiny up dim" style={{ minWidth: 74, letterSpacing: "0.12em" }}>{c.group}</span>
              <span style={{ fontSize: 13, color: i === cursor ? "var(--gold-hi)" : "var(--txt-bright)" }}>{c.title}</span>
              {c.hint && <span className="tiny dim" style={{ marginLeft: "auto" }}>{c.hint}</span>}
            </div>
          ))}
        </div>
        <div className="row tiny dim" style={{ gap: 16, padding: "7px 15px", borderTop: "1px solid var(--line)" }}>
          <span>↑↓ move</span><span>⏎ open</span><span>esc close</span>
        </div>
      </div>
    </div>
  );
}
