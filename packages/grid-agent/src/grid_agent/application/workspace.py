from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class RunWorkspace:
    run_id: str
    root_path: Path
    input_path: Path
    run_path: Path
    events_path: Path
    answer_path: Path
    pi_path: Path
    evidence_path: Path
    tool_results_path: Path
    bin_path: Path

    @classmethod
    def create(cls, root: Path, run_id: str | None = None) -> "RunWorkspace":
        resolved_run_id = run_id or f"run-{uuid4().hex}"
        root_path = root / resolved_run_id

        root_path.mkdir(parents=True, exist_ok=True)
        tool_results_path = root_path / "tool-results"
        pi_path = root_path / "pi"
        evidence_path = root_path / "evidence"
        bin_path = root_path / "bin"

        for path in (tool_results_path, evidence_path, pi_path, bin_path):
            path.mkdir(parents=True, exist_ok=True)

        return cls(
            run_id=resolved_run_id,
            root_path=root_path,
            input_path=root_path / "input.json",
            run_path=root_path / "run.json",
            events_path=root_path / "events.jsonl",
            answer_path=root_path / "answer.json",
            pi_path=pi_path,
            evidence_path=evidence_path,
            tool_results_path=tool_results_path,
            bin_path=bin_path,
        )
