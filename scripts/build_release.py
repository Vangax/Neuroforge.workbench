#!/usr/bin/env python
"""Build a distributable NeuroForge: UI + backend in one wheel.

    python scripts/build_release.py            # build the wheel + sdist
    python scripts/build_release.py --ui-only  # just refresh the bundled interface

The wheel has to carry the built interface, otherwise `pip install neuroforge`
would leave you with an API and no app — and installing Node on the target machine
is exactly the friction this is meant to remove. So the Vite bundle is copied into
``neuroforge/web/`` first, and the server looks there before the source-tree path.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
WEB = ROOT / "backend" / "neuroforge" / "web"


def run(cmd: list[str], cwd: Path) -> None:
    print(f"  $ {' '.join(cmd)}   ({cwd})")
    # npm/npx are .cmd shims on Windows and are not executable without a shell.
    subprocess.run(cmd, cwd=cwd, check=True, shell=(sys.platform == "win32"))


def build_ui(skip_npm: bool = False) -> None:
    if not FRONTEND.is_dir():
        raise SystemExit("no frontend/ directory — nothing to bundle")
    if not skip_npm:
        if not (FRONTEND / "node_modules").is_dir():
            run(["npm", "install"], FRONTEND)
        run(["npm", "run", "build"], FRONTEND)
    if not (DIST / "index.html").is_file():
        raise SystemExit(f"{DIST} has no index.html — the UI build did not produce output")

    if WEB.exists():
        shutil.rmtree(WEB)
    shutil.copytree(DIST, WEB)
    n = sum(1 for _ in WEB.rglob("*") if _.is_file())
    size = sum(p.stat().st_size for p in WEB.rglob("*") if p.is_file())
    print(f"  bundled interface -> {WEB.relative_to(ROOT)}  ({n} files, {size / 1e6:.1f} MB)")


def build_wheel() -> None:
    try:
        import build  # noqa: F401
    except ModuleNotFoundError:
        raise SystemExit("the 'build' package is missing — pip install build")
    run([sys.executable, "-m", "build"], ROOT)
    out = ROOT / "dist"
    for p in sorted(out.glob("neuroforge-*")):
        print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size / 1e6:.1f} MB)")
    print("\n  install it with:")
    print(f"      pip install {next(iter(sorted(out.glob('*.whl'))), out / '*.whl').name}")
    print("  then run:")
    print("      neuroforge")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ui-only", action="store_true", help="bundle the interface, skip the wheel")
    ap.add_argument("--skip-npm", action="store_true",
                    help="reuse the existing frontend/dist instead of rebuilding it")
    args = ap.parse_args()

    print("\n  NeuroForge release build\n")
    build_ui(skip_npm=args.skip_npm)
    if not args.ui_only:
        build_wheel()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
