from __future__ import annotations

import os
from pathlib import Path


class GridctlLocatorError(RuntimeError):
    pass


class GridctlLocator:
    def __init__(self, repository_root: Path, environ: dict[str, str] | None = None) -> None:
        self.repository_root = Path(repository_root)
        self.environ = dict(environ or os.environ)

    def resolve(self) -> Path:
        explicit = self.environ.get("GRID_AGENT_GRIDCTL_EXECUTABLE")
        candidate = Path(explicit) if explicit else self._managed_path()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise GridctlLocatorError("Grid simulator executable is unavailable")
        return candidate

    def _managed_path(self) -> Path:
        bin_name = "gridctl.exe" if os.name == "nt" else "gridctl"
        folder = "Scripts" if os.name == "nt" else "bin"
        return self.repository_root / "packages/grid-simulator/.venv" / folder / bin_name
