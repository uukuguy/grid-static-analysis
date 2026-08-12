import json
from datetime import UTC, datetime

from grid_agent.application.workspace import RunWorkspace
from grid_agent.observability.trace import JsonlTraceWriter


def test_workspace_create_sets_expected_paths(tmp_path) -> None:
    workspace = RunWorkspace.create(tmp_path, run_id="run-1")

    assert workspace.root_path == tmp_path / "run-1"
    assert workspace.input_path == workspace.root_path / "input.json"
    assert workspace.run_path == workspace.root_path / "run.json"
    assert workspace.events_path == workspace.root_path / "events.jsonl"
    assert workspace.answer_path == workspace.root_path / "answer.json"
    assert workspace.pi_path == workspace.root_path / "pi"
    assert workspace.evidence_path == workspace.root_path / "evidence"
    assert workspace.tool_results_path == workspace.root_path / "tool-results"
    assert workspace.bin_path == workspace.root_path / "bin"
    assert workspace.pi_path.is_dir()
    assert workspace.evidence_path.is_dir()
    assert workspace.tool_results_path.is_dir()
    assert workspace.bin_path.is_dir()


def test_trace_is_append_only_and_redacted(tmp_path) -> None:
    workspace = RunWorkspace.create(tmp_path, run_id="run-1")
    writer = JsonlTraceWriter(workspace.events_path, secret_values={"sk-secret"})

    writer.append(
        "run_started",
        {
            "key": "prefix sk-secret suffix",
            "nested": ["sk-secret", {"url": "token=sk-secret"}],
        },
    )
    writer.append("run_finished", {"status": "answered_with_evidence"})

    raw_text = workspace.events_path.read_text()
    records = [json.loads(line) for line in raw_text.splitlines()]

    assert raw_text.endswith("\n")
    assert "sk-secret" not in raw_text
    assert [record["sequence"] for record in records] == [1, 2]
    assert [record["event"] for record in records] == ["run_started", "run_finished"]
    assert records[0]["payload"]["key"] == "prefix [REDACTED] suffix"
    assert records[0]["payload"]["nested"] == ["[REDACTED]", {"url": "token=[REDACTED]"}]
    assert records[1]["payload"]["status"] == "answered_with_evidence"

    for record in records:
        timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
        assert timestamp.tzinfo == UTC


def test_trace_redacts_mapping_keys(tmp_path) -> None:
    workspace = RunWorkspace.create(tmp_path, run_id="run-keys")
    writer = JsonlTraceWriter(workspace.events_path, secret_values={"sk-secret"})

    writer.append("run_started", {"header-sk-secret": "visible"})

    record = json.loads(workspace.events_path.read_text().splitlines()[0])

    assert "header-sk-secret" not in workspace.events_path.read_text()
    assert record["payload"] == {"header-[REDACTED]": "visible"}
