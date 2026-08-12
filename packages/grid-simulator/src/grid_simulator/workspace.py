from __future__ import annotations

from pathlib import Path
import re


_CONTEXT_REF_PATTERN = re.compile(r"^context:sha256:([0-9a-f]{64})$")
_REVISION_REF_PATTERN = re.compile(r"^revision:sha256:([0-9a-f]{64})$")


class SimulatorWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def networks_dir(self) -> Path:
        directory = self.root / "evidence" / "networks"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def contexts_dir(self) -> Path:
        return self.root / "evidence" / "contexts"

    @property
    def model_artifacts_dir(self) -> Path:
        return self.root / "evidence" / "models"

    @property
    def results_dir(self) -> Path:
        directory = self.root / "evidence" / "results"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def context_document(self, context_ref: str) -> Path:
        return self.contexts_dir / f"{_parse_context_ref(context_ref)}.json"

    def model_artifact(self, revision_ref: str) -> Path:
        return self.model_artifacts_dir / f"{_parse_revision_ref(revision_ref)}.json"


def _parse_context_ref(context_ref: str) -> str:
    match = _CONTEXT_REF_PATTERN.fullmatch(context_ref)
    if match is None:
        raise ValueError("invalid context reference")
    return match.group(1)


def _parse_revision_ref(revision_ref: str) -> str:
    match = _REVISION_REF_PATTERN.fullmatch(revision_ref)
    if match is None:
        raise ValueError("invalid revision reference")
    return match.group(1)
