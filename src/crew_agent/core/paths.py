from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    config_file: Path
    inventory_file: Path
    runs_dir: Path
    backups_dir: Path
    state_file: Path


def get_app_paths() -> AppPaths:
    root = Path(os.getenv("CODY_HOME", Path.cwd() / ".cody")).resolve()
    return AppPaths(
        root=root,
        config_file=root / "config.yaml",
        inventory_file=root / "hosts.yaml",
        runs_dir=root / "runs",
        backups_dir=root / "backups",
        state_file=root / "state.json",
    )


def ensure_app_dirs() -> AppPaths:
    paths = get_app_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    return paths
