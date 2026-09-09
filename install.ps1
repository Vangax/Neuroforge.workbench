# NeuroForge installer — Windows.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Creates an isolated environment next to this script, installs NeuroForge into it,
# and leaves you with a `neuroforge` command. Nothing is installed system-wide and
# your existing Python packages are not touched.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $Root ".venv"

function Fail($msg) { Write-Host ""; Write-Host "  $msg" -ForegroundColor Red; Write-Host ""; exit 1 }
function Step($msg) { Write-Host "  $msg" -ForegroundColor DarkCyan }

Write-Host ""
Write-Host "  NeuroForge installer" -ForegroundColor Yellow
Write-Host ""

# --- 1. Python ---------------------------------------------------------------
$py = $null
foreach ($c in @("py -3.12", "py -3.11", "py -3", "python3", "python")) {
    $parts = $c.Split(" ")
    $exe = Get-Command $parts[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    try {
        $v = & $parts[0] $parts[1..($parts.Length - 1)] -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
    } catch { continue }
    if ($v -and [version]$v -ge [version]"3.10") { $py = $c; $pyv = $v; break }
}
if (-not $py) { Fail "Python 3.10 or newer is required. Install it from https://python.org/downloads and run this again." }
Step "Python $pyv  ($py)"

# --- 2. environment ----------------------------------------------------------
if (Test-Path $VenvDir) {
    Step "Reusing the existing environment at .venv"
} else {
    Step "Creating an isolated environment in .venv"
    $parts = $py.Split(" ")
    & $parts[0] $parts[1..($parts.Length - 1)] -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment." }
}
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { Fail "The environment looks incomplete: $VenvPy is missing." }

# --- 3. the interface --------------------------------------------------------
# A wheel in dist/ already carries the built interface. From a source checkout we
# build it here if Node is available, and carry on without it if not — the API
# still runs, and `npm run build` can be done later.
$Wheel = Get-ChildItem (Join-Path $Root "dist\neuroforge-*.whl") -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Wheel -and (Test-Path (Join-Path $Root "frontend"))) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Step "Building the interface (npm)"
        Push-Location (Join-Path $Root "frontend")
        if (-not (Test-Path "node_modules")) { npm install --silent }
        npm run build --silent
        Pop-Location
        & $VenvPy (Join-Path $Root "scripts\build_release.py") --ui-only --skip-npm
    } else {
        Write-Host "  Node.js not found — installing the API only." -ForegroundColor DarkYellow
        Write-Host "  Install Node, then run: npm --prefix frontend install; npm --prefix frontend run build" -ForegroundColor DarkGray
    }
}

# --- 4. install --------------------------------------------------------------
Step "Installing NeuroForge and its dependencies (this takes a few minutes the first time)"
& $VenvPy -m pip install --quiet --upgrade pip
if ($Wheel) {
    & $VenvPy -m pip install --quiet $Wheel.FullName
} else {
    & $VenvPy -m pip install --quiet $Root
}
if ($LASTEXITCODE -ne 0) { Fail "Installation failed. Scroll up for the reason." }

# --- 5. verify ---------------------------------------------------------------
$Neuro = Join-Path $VenvDir "Scripts\neuroforge.exe"
if (-not (Test-Path $Neuro)) { Fail "Installed, but the `neuroforge` command is missing." }
Write-Host ""
& $Neuro doctor
Write-Host ""

# --- 6. a shortcut so you never type the path --------------------------------
$Launcher = Join-Path $Root "NeuroForge.cmd"
"@echo off`r`n`"$Neuro`" %*" | Set-Content -Path $Launcher -Encoding ASCII
Step "Created NeuroForge.cmd — double-click it, or run it from a terminal."

Write-Host ""
Write-Host "  Done. Start it with:" -ForegroundColor Green
Write-Host "      .\NeuroForge.cmd" -ForegroundColor White
Write-Host "  or activate the environment and use the command directly:" -ForegroundColor Gray
Write-Host "      .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "      neuroforge" -ForegroundColor White
Write-Host ""
