from __future__ import annotations

from pathlib import Path
import re


_CONTEXT_REF_PATTERN = re.compile(r"^context:sha256:([0-9a-f]{64})$")
_REVISION_REF_PATTERN = re.compile(r"^revision:sha256:([0-9a-f]{64})$")
_LINEAGE_REF_PATTERN = re.compile(r"^lineage:sha256:([0-9a-f]{64})$")


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

    def result_document(self, prefix: str, digest: str) -> Path:
        return self.root / "evidence" / "results" / f"{prefix}-{digest}.json"

    def context_document(self, context_ref: str) -> Path:
        return self.contexts_dir / f"{_parse_context_ref(context_ref)}.json"

    def model_artifact(self, revision_ref: str) -> Path:
        return self.model_artifacts_dir / f"{_parse_revision_ref(revision_ref)}.json"

    def lineage_document(self, lineage_ref: str) -> Path:
        return self.root / "evidence" / "revisions" / f"{_parse_lineage_ref(lineage_ref)}.json"


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


def _parse_lineage_ref(lineage_ref: str) -> str:
    match = _LINEAGE_REF_PATTERN.fullmatch(lineage_ref)
    if match is None:
        raise ValueError("invalid lineage reference")
    return match.group(1)
