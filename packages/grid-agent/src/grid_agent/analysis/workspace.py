from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path


def _count_instructions(source_bytes: bytes, *, source_path: Path) -> int:
    lines = source_bytes.decode("utf-8").splitlines()
    instructions = tuple(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))
    if not instructions:
        raise ValueError(f"question file contains no questions: {source_path}")
    return len(instructions)


def _write_bytes_with_fsync(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True, slots=True)
class CopiedInstructions:
    source_path: str
    copied_path: str
    sha256: str
    instruction_count: int


@dataclass(frozen=True, slots=True)
class AnalysisWorkspace:
    analysis_id: str
    root_path: Path
    manifest_path: Path
    copied_instructions_path: Path
    answers_path: Path
    report_path: Path
    context_snapshot_path: Path
    context_events_path: Path
    trace_path: Path
    events_path: Path
    requests_path: Path
    projections_path: Path
    agent_projection_path: Path
    business_projection_path: Path
    context_timeline_path: Path
    artifact_index_path: Path
    turns_path: Path
    evidence_path: Path
    results_path: Path
    tool_results_path: Path
    bin_path: Path
    pi_path: Path
    active_turn_path: Path
    active_answer_draft_path: Path
    context_view_path: Path
    trajectory_capture_state_path: Path

    @classmethod
    def create(cls, root: Path, analysis_id: str | None = None) -> AnalysisWorkspace:
        resolved_analysis_id = analysis_id or f"analysis-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        root_path = root / resolved_analysis_id
        root_path.mkdir(parents=True, exist_ok=False)

        input_path = root_path / "input"
        output_path = root_path / "output"
        context_path = root_path / "context"
        trace_dir_path = root_path / "trace"
        events_path = root_path / "events"
        requests_path = root_path / "requests"
        projections_path = root_path / "projections"
        turns_path = root_path / "turns"
        evidence_path = root_path / "evidence"
        results_path = evidence_path / "results"
        tool_results_path = root_path / "tool-results"
        bin_path = root_path / "bin"
        pi_path = root_path / "pi"

        for path in (
            input_path,
            output_path,
            context_path,
            trace_dir_path,
            events_path,
            requests_path,
            projections_path,
            turns_path,
            evidence_path / "contexts",
            evidence_path / "network-facts",
            evidence_path / "analysis",
            results_path,
            tool_results_path,
            bin_path,
            pi_path,
        ):
            path.mkdir(parents=True, exist_ok=True)

        return cls(
            analysis_id=resolved_analysis_id,
            root_path=root_path,
            manifest_path=root_path / "manifest.json",
            copied_instructions_path=input_path / "instructions.md.txt",
            answers_path=output_path / "answers.jsonl",
            report_path=root_path / "report.md",
            context_snapshot_path=context_path / "analysis-context.json",
            context_events_path=context_path / "context-events.jsonl",
            trace_path=trace_dir_path / "events.jsonl",
            events_path=events_path / "run-events.jsonl",
            requests_path=requests_path,
            projections_path=projections_path,
            agent_projection_path=projections_path / "agent-trajectory.json",
            business_projection_path=projections_path / "business-trajectory.json",
            context_timeline_path=projections_path / "context-timeline.json",
            artifact_index_path=projections_path / "artifact-index.json",
            turns_path=turns_path,
            evidence_path=evidence_path,
            results_path=results_path,
            tool_results_path=tool_results_path,
            bin_path=bin_path,
            pi_path=pi_path,
            active_turn_path=root_path / "active-turn.json",
            active_answer_draft_path=root_path / "answer-draft.json",
            context_view_path=context_path / "analysis-context-view.json",
            trajectory_capture_state_path=context_path / "trajectory-capture-state.json",
        )

    def turn_path(self, ordinal: int) -> Path:
        path = self.turns_path / f"{ordinal:03d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def copy_instructions(self, source: Path) -> CopiedInstructions:
        source_bytes = source.read_bytes()
        instruction_count = _count_instructions(source_bytes, source_path=source)
        digest = sha256(source_bytes).hexdigest()

        if self.copied_instructions_path.exists():
            copied_bytes = self.copied_instructions_path.read_bytes()
            if copied_bytes != source_bytes:
                raise RuntimeError(f"{self.copied_instructions_path} already contains copied instructions")
        else:
            _write_bytes_with_fsync(self.copied_instructions_path, source_bytes)

        return CopiedInstructions(
            source_path=str(source),
            copied_path=str(self.copied_instructions_path.relative_to(self.root_path)),
            sha256=digest,
            instruction_count=instruction_count,
        )
