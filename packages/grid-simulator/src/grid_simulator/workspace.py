from __future__ import annotations

from pathlib import Path


class SimulatorWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def networks_dir(self) -> Path:
        directory = self.root / "evidence" / "networks"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def results_dir(self) -> Path:
        directory = self.root / "evidence" / "results"
        directory.mkdir(parents=True, exist_ok=True)
        return directory
