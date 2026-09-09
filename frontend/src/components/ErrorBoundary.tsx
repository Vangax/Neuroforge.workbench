/* One broken module must not take the whole application with it.
 *
 * Without this, any render-time exception anywhere in the tree unmounts everything
 * and leaves a blank page with the real message buried in the console — the single
 * worst failure mode a tool can have, because the user has nothing to report and
 * nothing to click. Here the rest of the HUD keeps working, the module says what
 * broke, and "try again" re-mounts just that subtree.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props { children: ReactNode; label?: string; onReset?: () => void }
interface State { error: Error | null; info: string | null; attempt: number }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null, attempt: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the component stack — it is the only thing that says *where* it broke.
    this.setState({ info: info.componentStack ?? null });
    console.error("[neuroforge] module crashed:", error, info.componentStack);
  }

  reset = () => {
    this.setState((s) => ({ error: null, info: null, attempt: s.attempt + 1 }));
    this.props.onReset?.();
  };

  render() {
    const { error, info, attempt } = this.state;
    if (!error) return <div key={attempt} style={{ display: "contents" }}>{this.props.children}</div>;

    return (
      <div className="panel" style={{ maxWidth: 720, margin: "8px auto", padding: 0 }}>
        <span className="corner-tr" /><span className="corner-br" />
        <div className="panel-head">
          <span className="tag">!</span>
          <span>{this.props.label ?? "this view"} stopped</span>
        </div>
        <div className="panel-body col" style={{ gap: 14 }}>
          <div style={{ fontSize: 13, lineHeight: 1.7 }}>
            Something in this view threw an error. The rest of NeuroForge is unaffected —
            your datasets are safe and every other module still works.
          </div>
          <pre style={{
            margin: 0, padding: 11, fontSize: 11, lineHeight: 1.5, whiteSpace: "pre-wrap",
            color: "var(--crimson-hi)", background: "rgba(0,0,0,0.4)", border: "1px solid var(--line)",
            maxHeight: 220, overflow: "auto",
          }}>
            {error.name}: {error.message}
            {info ? `\n${info.trim().split("\n").slice(0, 8).join("\n")}` : ""}
          </pre>
          <div className="row" style={{ gap: 8 }}>
            <button className="btn crim" onClick={this.reset}>↻ try again</button>
            <button className="btn sm" onClick={() => {
              navigator.clipboard?.writeText(
                `${error.name}: ${error.message}\n${error.stack ?? ""}\n${info ?? ""}`);
            }}>copy details</button>
          </div>
        </div>
      </div>
    );
  }
}
