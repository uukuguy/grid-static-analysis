from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path

    @classmethod
    def from_root(cls, root: Path) -> "ProjectPaths":
        return cls(Path(root).resolve())

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def internal_dir(self) -> Path:
        return self.root / ".grid-agent"

    @property
    def pi_runtime_dir(self) -> Path:
        return self.internal_dir / "runtime/pi"

    @property
    def pi_agent_dir(self) -> Path:
        return self.internal_dir / "auth/pi"

    @property
    def sessions_dir(self) -> Path:
        return self.internal_dir / "sessions"

    @property
    def runtime_lock(self) -> Path:
        return self.root / "configs/runtime/pi-runtime.lock.json"
