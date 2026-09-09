#!/usr/bin/env bash
# NeuroForge installer — macOS and Linux.
#
#   bash install.sh
#
# Creates an isolated environment next to this script, installs NeuroForge into it,
# and leaves you with a `neuroforge` command. Nothing is installed system-wide and
# your existing Python packages are not touched.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"

step() { printf '  \033[36m%s\033[0m\n' "$1"; }
fail() { printf '\n  \033[31m%s\033[0m\n\n' "$1"; exit 1; }

printf '\n  \033[33mNeuroForge installer\033[0m\n\n'

# --- 1. Python ---------------------------------------------------------------
PY=""
for c in python3.12 python3.11 python3.10 python3 python; do
  command -v "$c" >/dev/null 2>&1 || continue
  v="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)"
  [ -n "$v" ] || continue
  if [ "$(printf '%s\n3.10\n' "$v" | sort -V | head -1)" = "3.10" ]; then PY="$c"; PYV="$v"; break; fi
done
[ -n "$PY" ] || fail "Python 3.10 or newer is required. Install it and run this again."
step "Python $PYV  ($PY)"

# --- 2. environment ----------------------------------------------------------
if [ -d "$VENV" ]; then
  step "Reusing the existing environment at .venv"
else
  step "Creating an isolated environment in .venv"
  "$PY" -m venv "$VENV" || fail "Could not create the virtual environment. On Debian/Ubuntu: sudo apt install python3-venv"
fi
VPY="$VENV/bin/python"
[ -x "$VPY" ] || fail "The environment looks incomplete: $VPY is missing."

# --- 3. the interface --------------------------------------------------------
# A wheel in dist/ already carries the built interface. From a source checkout we
# build it here if Node is available, and carry on without it if not — the API
# still runs, and `npm run build` can be done later.
WHEEL="$(ls -t "$ROOT"/dist/neuroforge-*.whl 2>/dev/null | head -1 || true)"
if [ -z "$WHEEL" ] && [ -d "$ROOT/frontend" ]; then
  if command -v npm >/dev/null 2>&1; then
    step "Building the interface (npm)"
    ( cd "$ROOT/frontend" && { [ -d node_modules ] || npm install --silent; } && npm run build --silent )
    "$VPY" "$ROOT/scripts/build_release.py" --ui-only --skip-npm
  else
    printf '  \033[33mNode.js not found — installing the API only.\033[0m\n'
    printf '  \033[90mInstall Node, then: npm --prefix frontend install && npm --prefix frontend run build\033[0m\n'
  fi
fi

# --- 4. install --------------------------------------------------------------
step "Installing NeuroForge and its dependencies (this takes a few minutes the first time)"
"$VPY" -m pip install --quiet --upgrade pip
if [ -n "$WHEEL" ]; then
  "$VPY" -m pip install --quiet "$WHEEL"
else
  "$VPY" -m pip install --quiet "$ROOT"
fi

# --- 5. verify ---------------------------------------------------------------
NEURO="$VENV/bin/neuroforge"
[ -x "$NEURO" ] || fail "Installed, but the 'neuroforge' command is missing."
echo
"$NEURO" doctor || true
echo

# --- 6. a shortcut so you never type the path --------------------------------
cat > "$ROOT/neuroforge" <<EOF
#!/usr/bin/env bash
exec "$NEURO" "\$@"
EOF
chmod +x "$ROOT/neuroforge"
step "Created ./neuroforge — run it from here."

printf '\n  \033[32mDone. Start it with:\033[0m\n'
printf '      ./neuroforge\n'
printf '  \033[90mor activate the environment and use the command directly:\033[0m\n'
printf '      source .venv/bin/activate\n'
printf '      neuroforge\n\n'
