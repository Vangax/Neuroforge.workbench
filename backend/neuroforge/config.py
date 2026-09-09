# Central settings. Override the data location with NEUROFORGE_DATA.
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# Frequency bands (Hz). Edit here, not in the modules.
DEFAULT_BANDS: dict[str, tuple[float, float]] = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

# Channel-type -> colour, kept in sync with the frontend palette.
CH_TYPE_COLORS: dict[str, str] = {
    "eeg": "#ff9a2e", "meg": "#2ee6ff", "ecog": "#ff5c7a", "seeg": "#c77dff",
    "eog": "#ffe14d", "ecg": "#7afcff", "emg": "#9dff5c", "stim": "#8a93a6", "misc": "#5a6172",
}

def _default_data_dir() -> str:
    """Where recordings live when NEUROFORGE_DATA is not set.

    In a source checkout that stays inside the repo (gitignored) so a clone behaves
    the way it always has. Installed as a package it must not be site-packages —
    that is read-only on managed installs and gets wiped on upgrade — so it goes to
    the user's home instead.
    """
    pkg = Path(__file__).resolve().parent          # .../neuroforge
    checkout = pkg.parent                          # .../backend  (in a repo)
    if (checkout.parent / "frontend").is_dir() and (checkout.parent / ".git").exists():
        return str(checkout / "data")
    return str(Path.home() / ".neuroforge" / "data")


_DEFAULT_DATA = _default_data_dir()


@dataclass
class Settings:
    app_name: str = "NeuroForge"
    version: str = "0.2.0"

    cors_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:5173", "http://127.0.0.1:5173",
    ])

    # Cap on samples/channel returned to the viewer so big montages stay responsive.
    max_points_per_channel: int = 4000

    # How many recordings keep their samples in RAM at once (LRU); others lazy-reload.
    max_loaded_datasets: int = 6

    # Reject uploads larger than this (MB). Streaming upload is the next step.
    max_upload_mb: int = 1024

    # User scripting (Module 11). Runs in an isolated subprocess with a timeout.
    # This executes user-supplied Python — keep it to authenticated, trusted users.
    # Disable entirely with NEUROFORGE_SCRIPTS=0 on locked-down deployments.
    scripts_enabled: bool = field(default_factory=lambda: os.environ.get("NEUROFORGE_SCRIPTS", "1") == "1")
    script_timeout_s: int = 30
    script_mem_mb: int = 2048

    # Where loaded data (FIF) and the SQLite index live.
    data_dir: str = field(default_factory=lambda: os.environ.get("NEUROFORGE_DATA", _DEFAULT_DATA))

    # Seed a small synthetic cohort only when the store is empty (first run).
    seed_synthetic: bool = True

    @property
    def db_path(self) -> str:
        return str(Path(self.data_dir) / "neuroforge.db")


settings = Settings()
