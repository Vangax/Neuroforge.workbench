/* Install self-check, surfaced where the user will actually see it.
 *
 * The backend already knows why something is broken — it just used to keep that to
 * itself until a job blew up mid-analysis. This puts the answer one click from the
 * top bar, with the command that fixes it, before anything goes wrong.
 */
import { useEffect, useState } from "react";
import { api, type DoctorReport } from "../api/client";

const COLOR: Record<string, string> = {
  ok: "#36d6c0", warn: "var(--gold)", fail: "var(--crimson)",
};

export default function SetupCheck() {
  const [rep, setRep] = useState<DoctorReport | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => { api.doctor().then(setRep); }, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!rep) return null;

  const bad = rep.status !== "ok";
  const count = rep.n_fail + rep.n_warn;

  return (
    <>
      <button className="led" onClick={() => setOpen((o) => !o)}
        title={rep.summary}
        style={{ background: "none", border: "none", cursor: "pointer", font: "inherit",
                 letterSpacing: "inherit", textTransform: "uppercase" }}>
        <span className="dot" style={{
          background: COLOR[rep.status],
          boxShadow: bad ? `0 0 8px ${COLOR[rep.status]}` : "none",
        }} />
        {bad ? `setup ${count}` : "setup✓"}
      </button>

      {open && <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 55 }} />}
      {open && (
        <div style={{
          position: "fixed", top: 46, right: 16, zIndex: 60, width: 460, maxWidth: "calc(100vw - 32px)",
          maxHeight: "72vh", overflow: "auto", background: "var(--panel)",
          border: "1px solid var(--bevel-lo)", boxShadow: "0 26px 70px -24px rgba(0,0,0,0.95)",
        }}>
          <div className="panel-head">
            <span className="tag">SYS</span>
            <span>Install check</span>
            <span className="spacer" />
            <span className="meta" style={{ cursor: "pointer" }} onClick={() => setOpen(false)}>✕</span>
          </div>
          <div className="panel-body col" style={{ gap: 11 }}>
            <span className="tiny dim">{rep.summary}</span>
            {rep.checks.map((c) => (
              <div key={c.id} className="row" style={{ gap: 10, alignItems: "flex-start" }}>
                <span style={{
                  width: 8, height: 8, borderRadius: "50%", flexShrink: 0, marginTop: 5,
                  background: COLOR[c.status],
                }} />
                <div className="col" style={{ gap: 3, minWidth: 0 }}>
                  <span style={{ fontSize: 12.5, color: "var(--txt-bright)" }}>{c.label}</span>
                  <span className="tiny dim" style={{ lineHeight: 1.6 }}>{c.detail}</span>
                  {c.fix && (
                    <code style={{
                      fontSize: 10.5, lineHeight: 1.6, color: "var(--gold-hi)", padding: "5px 8px",
                      background: "rgba(0,0,0,0.42)", border: "1px solid var(--line)",
                      wordBreak: "break-word",
                    }}>{c.fix}</code>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
