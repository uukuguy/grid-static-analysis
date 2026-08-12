from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "validation/run.py"


def _run_topology_case(tmp_path: Path, event: dict[str, object], answer_output: str) -> subprocess.CompletedProcess[str]:
    trace_path = tmp_path / "events.jsonl"
    trace_path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    cli = tmp_path / "fake_agent.py"
    cli.write_text(
        "import json, sys\n"
        f"print(json.dumps({{'question_id': sys.argv[1], 'answer_output': {answer_output!r}}}, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--cases-root",
            str(ROOT / "validation"),
            "--case-id",
            "topology-line-endpoints-001",
            "--trace-template",
            str(trace_path),
            "--",
            sys.executable,
            str(cli),
            "{case_id}",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )


def _topology_event(*, to_bus: str = "11", evidence_refs: list[str] | None = None) -> dict[str, object]:
    return {
        "event": "tool_result",
        "capability": "topology.branch.endpoints.get",
        "ok": True,
        "result": {
            "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
            "from_bus": {"name": "6"},
            "to_bus": {"name": to_bus},
        },
        "evidence_refs": evidence_refs if evidence_refs is not None else ["evidence:sha256:" + "a" * 64],
    }


def test_run_harness_executes_command_template_and_reports_summary(tmp_path: Path) -> None:
    trace_path = tmp_path / "events.jsonl"
    trace_path.write_text(json.dumps(_topology_event(), ensure_ascii=False) + "\n", encoding="utf-8")
    cli = tmp_path / "fake_agent.py"
    cli.write_text(
        "import json, sys\n"
        "question_id = sys.argv[1]\n"
        "print(json.dumps({'question_id': question_id, 'answer_output': '线路11连接母线6与母线11。'}, ensure_ascii=False))\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--cases-root",
            str(ROOT / "validation"),
            "--suite",
            "task-required",
            "--case-id",
            "topology-line-endpoints-001",
            "--trace-template",
            str(trace_path),
            "--",
            sys.executable,
            str(cli),
            "{case_id}",
            "{question}",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert records[0]["type"] == "case"
    assert records[0]["case_id"] == "topology-line-endpoints-001"
    assert records[0]["passed"] is True
    assert records[1] == {"type": "summary", "total": 1, "passed": 1, "failed": 0}


def test_topology_validation_uses_structured_result_not_answer_wording(tmp_path: Path) -> None:
    completed = _run_topology_case(tmp_path, _topology_event(), "结论已生成。")
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 0
    assert records[0]["passed"] is True


def test_topology_validation_rejects_wrong_structured_result_not_prose(tmp_path: Path) -> None:
    completed = _run_topology_case(tmp_path, _topology_event(to_bus="12"), "线路11连接母线6与母线11。")
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 1
    assert records[0]["errors"] == ["structured_oracle_mismatch: topology_branch_endpoints"]


def test_topology_validation_requires_matching_result_evidence(tmp_path: Path) -> None:
    completed = _run_topology_case(tmp_path, _topology_event(evidence_refs=[]), "结论已生成。")
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 1
    assert records[0]["errors"] == ["verification_evidence_missing: topology.branch.endpoints.get"]


def test_topology_validation_requires_trace_for_structured_oracle(tmp_path: Path) -> None:
    cli = tmp_path / "fake_agent.py"
    cli.write_text(
        "import json, sys\n"
        "print(json.dumps({'question_id': sys.argv[1], 'answer_output': '线路11连接母线6与母线11。'}, ensure_ascii=False))\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--cases-root",
            str(ROOT / "validation"),
            "--case-id",
            "topology-line-endpoints-001",
            "--",
            sys.executable,
            str(cli),
            "{case_id}",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 1
    assert records[0]["errors"] == ["verification_trace_missing: topology.branch.endpoints.get"]


def test_topology_validation_requires_successful_structured_result_event(tmp_path: Path) -> None:
    completed = _run_topology_case(
        tmp_path,
        {"event": "tool_result", "capability": "topology.branch.endpoints.get", "ok": False},
        "线路11连接母线6与母线11。",
    )
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 1
    assert records[0]["errors"] == ["verification_result_missing: topology.branch.endpoints.get"]


def test_run_harness_reports_invalid_envelope_without_trace_requirement(tmp_path: Path) -> None:
    cli = tmp_path / "bad_agent.py"
    cli.write_text("print('not-json')\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--cases-root",
            str(ROOT / "validation"),
            "--suite",
            "task-required",
            "--case-id",
            "knowledge-voltage-range-001",
            "--",
            sys.executable,
            str(cli),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 1
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert records[0]["passed"] is False
    assert records[0]["errors"] == ["answer envelope is not valid JSON"]
    assert records[1] == {"type": "summary", "total": 1, "passed": 0, "failed": 1}


def test_run_harness_reports_forbidden_capabilities_from_trace(tmp_path: Path) -> None:
    trace_path = tmp_path / "events.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(_topology_event()),
                json.dumps(
                    {
                        "payload": {
                            "type": "tool_execution_start",
                            "toolName": "gridctl",
                            "args": {"operation": "powerflow.run_ac"},
                        }
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cli = tmp_path / "fake_agent.py"
    cli.write_text(
        "import json, sys\n"
        "print(json.dumps({'question_id': sys.argv[1], 'answer_output': '线路11连接母线6与母线11。'}, ensure_ascii=False))\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--cases-root",
            str(ROOT / "validation"),
            "--case-id",
            "topology-line-endpoints-001",
            "--trace-template",
            str(trace_path),
            "--",
            sys.executable,
            str(cli),
            "{case_id}",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 1
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert records[0]["passed"] is False
    assert records[0]["errors"] == ["forbidden capabilities observed: analysis.powerflow.ac.run"]


def test_run_harness_reports_timeout_and_summary_without_crashing() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--cases-root",
            str(ROOT / "validation"),
            "--case-id",
            "knowledge-voltage-range-001",
            "--timeout-seconds",
            "0.01",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(1)",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 1
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert records[0]["type"] == "case"
    assert records[0]["passed"] is False
    assert records[0]["returncode"] is None
    assert records[0]["errors"] == ["command_timeout: exceeded 0.01 seconds"]
    assert records[1] == {"type": "summary", "total": 1, "passed": 0, "failed": 1}


def test_run_harness_reports_missing_executable_and_summary_without_crashing() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--cases-root",
            str(ROOT / "validation"),
            "--case-id",
            "knowledge-voltage-range-001",
            "--",
            "missing-grid-agent-executable-for-validation-test",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert completed.returncode == 1
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert records[0]["type"] == "case"
    assert records[0]["passed"] is False
    assert records[0]["returncode"] is None
    assert records[0]["errors"] == [
        "command_os_error: executable not found: missing-grid-agent-executable-for-validation-test"
    ]
    assert records[1] == {"type": "summary", "total": 1, "passed": 0, "failed": 1}
