# The `neuroforge` command.
#
# One entry point, no arguments needed: `neuroforge` starts the server, waits until
# it answers, and opens the browser. Everything else is a subcommand for the cases
# where you do not want a browser at all — CI, a cluster, a quick look at one file.
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

BANNER = r"""
  ███╗   ██╗███████╗██╗   ██╗██████╗  ██████╗ ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
  ████╗  ██║██╔════╝██║   ██║██╔══██╗██╔═══██╗██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
  ██╔██╗ ██║█████╗  ██║   ██║██████╔╝██║   ██║█████╗  ██║   ██║██████╔╝██║  ███╗█████╗
  ██║╚██╗██║██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝
  ██║ ╚████║███████╗╚██████╔╝██║  ██║╚██████╔╝██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
  ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
"""

_STATUS_MARK = {"ok": "  ok ", "warn": " warn", "fail": " FAIL", "na": "  -- "}


def _free_port(preferred: int) -> int:
    """Use the requested port if it is free, otherwise the next one that is.

    A second instance failing with 'address already in use' is a bad first minute;
    moving over one port and saying so is not.
    """
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def _open_when_ready(url: str, timeout: float = 60.0) -> None:
    """Open the browser only once the server actually answers."""
    import urllib.error
    import urllib.request

    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1):
                webbrowser.open(url)
                return
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.3)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    if args.data:
        os.environ["NEUROFORGE_DATA"] = str(Path(args.data).expanduser().resolve())

    from .config import settings  # imported after NEUROFORGE_DATA is set

    port = args.port if args.no_port_scan else _free_port(args.port)
    url = f"http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{port}"

    if not args.quiet:
        print(BANNER)
        print(f"  {settings.app_name} {settings.version}")
        print(f"  data      {settings.data_dir}")
        print(f"  interface {url}")
        if port != args.port:
            print(f"  (port {args.port} was busy, using {port})")
        print(f"  API docs  {url}/docs")
        print("\n  Ctrl+C to stop.\n")

    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()

    uvicorn.run("neuroforge.main:app", host=args.host, port=port,
                log_level=args.log_level, reload=args.reload)
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    from .config import settings
    from .core import doctor

    rep = doctor.run(settings)
    print(f"\n  {settings.app_name} {settings.version} — install check")
    print(f"  {rep['summary']}\n")
    for c in rep["checks"]:
        print(f"  [{_STATUS_MARK.get(c['status'], '  ? ')}]  {c['label']:<22} {c['detail']}")
        if c["fix"]:
            print(f"            fix: {c['fix']}")
    print()
    return 1 if rep["n_fail"] else 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Auto-analysis on a file, without a browser. The whole report, on stdout."""
    from .core import autoanalysis, loaders

    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    try:
        nd = loaders.load_file(str(path))
    except Exception as e:  # noqa: BLE001 — a CLI must explain, not traceback
        print(f"could not read {path.name}: {e}", file=sys.stderr)
        return 2

    report = autoanalysis.analyze(nd)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    if report.get("error"):
        print(report["error"], file=sys.stderr)
        return 2

    t, h = report["recording_type"], report["health"]
    print(f"\n  {path.name}")
    print(f"  {report['dataset']['n_channels']} channels · "
          f"{report['dataset']['duration_s']:.0f} s · "
          f"{report['dataset']['sfreq']:.0f} Hz · "
          f"{report['dataset']['n_events']} events ({report['dataset']['event_source']})")
    print(f"\n  WHAT IS IT   {t['label']}  ({t['confidence'] * 100:.0f}% confident)")
    for why in t["why"]:
        print(f"               · {why}")
    print(f"\n  HEALTH       {h['score']}/100 ({h['grade']})")
    for c in h["checks"]:
        if c["status"] != "ok":
            print(f"      [{_STATUS_MARK.get(c['status'], '  ? ')}] {c['label']}: {c['detail']}")
    if report["findings"]:
        print("\n  NOTABLE")
        for f in report["findings"]:
            print(f"      · {f['title']}")
            print(f"        {f['plain']}")
    if report["cleanup"]["steps"]:
        print("\n  RECOMMENDED CLEANUP")
        for i, s in enumerate(report["cleanup"]["steps"], 1):
            print(f"      {i}. {s['label']} — {s['why']}")
    for s in report["cleanup"]["skipped"]:
        print(f"      (not doing) {s}")
    print(f"\n  {report['disclaimer']}\n")
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    import platform

    from .config import settings

    line = f"{settings.app_name} {settings.version}"
    try:
        import mne
        import numpy as np
        line += f" · MNE {mne.__version__} · NumPy {np.__version__}"
    except Exception:  # noqa: BLE001
        pass
    print(f"{line} · Python {platform.python_version()} ({platform.system()})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="neuroforge",
        description="NeuroForge — BIDS-native brain-data platform. "
                    "Run with no arguments to start the app and open it in your browser.",
    )
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="start the server and open the interface")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8420)
    s.add_argument("--data", help="where recordings and the index live "
                                  "(default: NEUROFORGE_DATA or a folder next to the package)")
    s.add_argument("--no-browser", action="store_true", help="do not open a browser")
    s.add_argument("--no-port-scan", action="store_true",
                   help="fail if --port is busy instead of moving to the next free one")
    s.add_argument("--reload", action="store_true", help="reload on code changes (development)")
    s.add_argument("--log-level", default="info",
                   choices=["critical", "error", "warning", "info", "debug"])
    s.add_argument("--quiet", "-q", action="store_true")
    s.set_defaults(func=cmd_serve)

    d = sub.add_parser("doctor", help="check this install and say how to fix what is wrong")
    d.set_defaults(func=cmd_doctor)

    a = sub.add_parser("analyze", help="auto-analyse one recording and print the report")
    a.add_argument("path")
    a.add_argument("--json", action="store_true", help="machine-readable output")
    a.set_defaults(func=cmd_analyze)

    v = sub.add_parser("version", help="print versions")
    v.set_defaults(func=cmd_version)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Bare `neuroforge` is the common case: start it and open the browser.
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["serve", *argv]
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n  stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
