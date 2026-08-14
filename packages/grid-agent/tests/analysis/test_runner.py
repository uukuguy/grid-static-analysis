from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from grid_agent.analysis.integrity import SimulatorIntegrityError
from grid_agent.analysis.models import ContextEventDraft
from grid_agent.analysis.runner import AnalysisOutcome, AnalysisRequest, AnalysisRunner
from grid_agent.analysis.store import AnalysisContextStore, ContextStoreError
from grid_agent.analysis.turns import ActiveTurnHandle, FinalizedTurn, TurnController
from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.runtime.rpc import PiProtocolError
from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry
from grid_agent.trajectory.capture import NativeCaptureAdapter
from grid_agent.trajectory.context_bridge import NativeContextBridge
from grid_agent.trajectory.events import EventDraft
from grid_agent.trajectory.reader import RunEventReader
from grid_agent.trajectory.recorder import RecorderIntegrityError, RunEventRecorder


RESULT_REF = "result:sha256:" + "1" * 64
BASELINE_REF = "context:sha256:" + "3" * 64
REVISION_REF = "revision:sha256:" + "4" * 64
NO_DRAFT_AGENT_END = {"type": "agent_end", "stop_status": "no_answer"}
TAMPERED_SUCCESSFUL_RESULT = {"type": "tool_result", "capability": "tampered.success", "ok": True}
SHOULD_NOT_RUN = {"answer": "should not run"}


@dataclass
class FakePi:
    workspace: AnalysisWorkspace
    behavior: list[Any] = field(default_factory=list)
    start_error: BaseException | None = None
    start_calls: int = 0
    stop_calls: int = 0
    prompts: list[str] = field(default_factory=list)
    captures: list[Any] = field(default_factory=list)

    def start(self) -> None:
        self.start_calls += 1
        # The Node extension reads this file during process startup, before it
        # receives its first prompt.
        assert self.workspace.context_view_path.is_file()
        if self.start_error is not None:
            raise self.start_error

    def stop(self) -> None:
        self.stop_calls += 1

    def prompt_and_wait(self, question: str, **kwargs: Any) -> str:
        self.prompts.append(question)
        self.captures.append(kwargs.get("capture"))
        index = len(self.prompts) - 1
        action = self.behavior[index] if index < len(self.behavior) else {"answer": f"answer {index + 1}"}
        on_semantic_event = kwargs.get("on_semantic_event")
        if isinstance(action, BaseException):
            raise action
        if action == NO_DRAFT_AGENT_END:
            return ""
        if action == TAMPERED_SUCCESSFUL_RESULT:
            assert callable(on_semantic_event)
            on_semantic_event(action, 1)
            return ""
        if isinstance(action, dict) and action.get("tool_error"):
            assert callable(on_semantic_event)
            on_semantic_event({"type": "tool_result", "capability": "analysis.powerflow.ac.run", "ok": False}, 1)
        if isinstance(action, dict) and "produce_result_ref" in action:
            assert callable(on_semantic_event)
            on_semantic_event({"type": "fake_result", "result_ref": action["produce_result_ref"]}, 1)
        if isinstance(action, dict) and "consume_result_ref" in action:
            assert callable(on_semantic_event)
            on_semantic_event({"type": "fake_consume", "result_ref": action["consume_result_ref"]}, 1)
        if isinstance(action, dict) and action.get("store_error"):
            assert callable(on_semantic_event)
            on_semantic_event({"type": "fake_store_error"}, 1)
        if isinstance(action, dict) and action.get("projection_error"):
            assert callable(on_semantic_event)
            on_semantic_event({"type": "fake_projection_error"}, 1)
        if isinstance(action, dict) and action.get("write_draft", True):
            handle = _read_active_turn(self.workspace)
            _write_draft(
                self.workspace.active_answer_draft_path,
                handle,
                answer=str(action.get("answer", f"answer {index + 1}")),
                result_refs=[str(action["produce_result_ref"])] if "produce_result_ref" in action else [],
            )
        if isinstance(action, dict) and action.get("corrupt_native"):
            with self.workspace.events_path.open("ab") as stream:
                stream.write(b"not-json\n")
        return str(action.get("answer", "")) if isinstance(action, dict) else ""


class FakeProjector:
    def __init__(self, store: AnalysisContextStore) -> None:
        self.store = store
        self.events: list[tuple[str, Mapping[str, Any]]] = []

    def observe(self, event: Mapping[str, Any], *, turn_id: str, trace_sequence: int | None = None) -> None:
        self.events.append((turn_id, event))
        if event.get("type") == "fake_result":
            _append_baseline_if_missing(self.store, turn_id)
            self.store.append(
                ContextEventDraft(
                    event_type="result.registered",
                    turn_id=turn_id,
                    capability="analysis.powerflow.ac.run",
                    payload={
                        "result_ref": event["result_ref"],
                        "revision_ref": REVISION_REF,
                        "path": "evidence/results/powerflow.json",
                        "evidence_refs": [],
                        "solver_summary": {"converged": True},
                        "producer_observation": {"tool_name": "grid_analysis_powerflow_ac"},
                    },
                )
            )
            self.store.append(
                ContextEventDraft(
                    event_type="domain.state.projected",
                    turn_id=turn_id,
                    capability="analysis.powerflow.ac.run",
                    payload={
                        "projector": "powerflow-ac-v1",
                        "model": {
                            "context_ref": BASELINE_REF,
                            "revision_ref": REVISION_REF,
                            "model_id": "ieee39",
                            "source": "pandapower.networks.case39",
                            "counts": {"bus": 39},
                        },
                        "constraints": [
                            {
                                "constraint_ref": "constraint:sha256:" + "8" * 64,
                                "context_ref": BASELINE_REF,
                                "revision_ref": REVISION_REF,
                                "quantity": "bus.vm_pu",
                                "subject_kind": "bus",
                                "lower": 0.94,
                                "upper": 1.06,
                                "unit": "p.u.",
                                "applies_to_count": 39,
                                "source_kind": "model",
                                "source_ref": "model:test",
                                "source": {"table": "bus"},
                                "producer_capability": "analysis.powerflow.ac.run",
                                "producer_turn_id": turn_id,
                            }
                        ],
                        "calculations": [
                            {
                                "result_ref": event["result_ref"],
                                "kind": "powerflow.ac",
                                "context_ref": BASELINE_REF,
                                "revision_ref": REVISION_REF,
                                "status": "converged",
                                "artifact_path": "evidence/results/powerflow.json",
                                "producer_capability": "analysis.powerflow.ac.run",
                                "producer_turn_id": turn_id,
                            }
                        ],
                    },
                )
            )
        if event.get("type") == "fake_consume":
            self.store.append(
                ContextEventDraft(
                    event_type="tool.observation.recorded",
                    turn_id=turn_id,
                    capability="result.branches.rank",
                    payload={
                        "observation_ref": "observation:sha256:" + "5" * 64,
                        "path": "tool-results/ranking.json",
                        "summary": {"ok": True},
                        "producer_observation": {"tool_name": "grid_result_branches_rank"},
                        "consumed_refs": [event["result_ref"]],
                        "produced_refs": [],
                    },
                )
            )
        if event.get("type") == "fake_store_error":
            raise ContextStoreError("durable append failed while active")
        if event.get("type") == "fake_projection_error":
            raise SimulatorIntegrityError("evidence projection rejected")
        if event == TAMPERED_SUCCESSFUL_RESULT:
            raise SimulatorIntegrityError("tampered result")
        if event.get("ok") is False:
            self.store.append(
                ContextEventDraft(
                    event_type="limitation.recorded",
                    turn_id=turn_id,
                    capability=str(event.get("capability", "unknown")),
                    payload={
                        "limitation_ref": "limitation:normal-gridctl-error",
                        "message": "normal gridctl error",
                        "refs": [],
                    },
                ),
                integrity="diagnostic",
            )
            self.store.append(
                ContextEventDraft(
                    event_type="tool.failed",
                    turn_id=turn_id,
                    capability=str(event.get("capability", "unknown")),
                    payload={"message": "normal gridctl error"},
                ),
                integrity="diagnostic",
            )


@dataclass
class RunnerHarness:
    workspace: AnalysisWorkspace
    store: AnalysisContextStore
    pi: FakePi
    projector: FakeProjector
    runner: AnalysisRunner


@dataclass
class NativeRunnerHarness(RunnerHarness):
    recorder: RunEventRecorder
    artifacts: ImmutableArtifactRegistry
    bridge: NativeContextBridge
    capture: NativeCaptureAdapter


@pytest.fixture
def runner_harness(tmp_path: Path) -> RunnerHarness:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    store = AnalysisContextStore.initialize(
        workspace,
        input_record={
            "copied_path": "input/instructions.md.txt",
            "source_path": "task.md.txt",
            "sha256": "a" * 64,
            "instruction_count": 3,
        },
        runtime_record={
            "provider": "test-provider",
            "model": "test-model",
            "grid_capability_protocol": "1.0",
            "pandapower_version": "3.4.0",
        },
    )
    pi = FakePi(workspace)
    projector = FakeProjector(store)
    runner = AnalysisRunner(
        workspace=workspace,
        store=store,
        turn_controller=TurnController(workspace, store, audit_callback=lambda _claimed, _results: ()),
        pi_client=pi,
        projector=projector,
        environment={"provider": "test-provider", "model": "test-model"},
    )
    return RunnerHarness(workspace=workspace, store=store, pi=pi, projector=projector, runner=runner)


def _native_runner_harness(tmp_path: Path) -> NativeRunnerHarness:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    artifacts = ImmutableArtifactRegistry(workspace.root_path)
    recorder = RunEventRecorder(
        workspace.events_path,
        workspace.analysis_id,
        artifact_registry=artifacts,
    )
    bridge = NativeContextBridge(recorder, artifacts, workspace)
    store = AnalysisContextStore.initialize(
        workspace,
        input_record={
            "copied_path": "input/instructions.md.txt",
            "source_path": "task.md.txt",
            "sha256": "a" * 64,
            "instruction_count": 1,
        },
        runtime_record={
            "provider": "test-provider",
            "model": "test-model",
            "grid_capability_protocol": "1.0",
            "pandapower_version": "3.4.0",
        },
        transition_commit=bridge.commit,
    )
    capture = NativeCaptureAdapter(recorder, artifacts, workspace)
    pi = FakePi(workspace)
    projector = FakeProjector(store)
    runner = AnalysisRunner(
        workspace=workspace,
        store=store,
        turn_controller=TurnController(
            workspace,
            store,
            audit_callback=lambda _claimed, _results: (),
        ),
        pi_client=pi,
        projector=projector,
        environment={"provider": "test-provider", "model": "test-model"},
        capture=capture,
        context_bridge=bridge,
    )
    return NativeRunnerHarness(
        workspace=workspace,
        store=store,
        pi=pi,
        projector=projector,
        runner=runner,
        recorder=recorder,
        artifacts=artifacts,
        bridge=bridge,
        capture=capture,
    )


def test_runner_records_context_injection_after_artifact_write(
    tmp_path: Path,
) -> None:
    harness = _native_runner_harness(tmp_path)

    outcome = harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一",))
    )

    prefix = RunEventReader(harness.recorder.events_path).read_prefix()
    injected = [
        event for event in prefix.events if event.event_type == "context.injected"
    ]
    assert outcome.status == "completed", outcome.error
    assert prefix.failure is None
    assert prefix.events[-1].event_type == "analysis.completed"
    assert injected
    assert all(
        event.context.before_revision == event.context.after_revision
        for event in injected
    )
    assert all(
        event.payload["artifact_ref"] in event.refs.produced
        for event in injected
    )
    assert all(
        harness.artifacts.verify_reference(event.payload["artifact_ref"])
        for event in injected
    )
    assert harness.pi.captures == [harness.capture]
    assert harness.capture._turn_id is None
    with pytest.raises(RecorderIntegrityError, match="closed"):
        harness.recorder.append(EventDraft(event_type="analysis.started"))


def test_runner_prevents_completion_after_native_replay_failure(
    tmp_path: Path,
) -> None:
    harness = _native_runner_harness(tmp_path)
    harness.pi.behavior = [{"answer": "done", "corrupt_native": True}]

    outcome = harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一",))
    )

    prefix = RunEventReader(harness.recorder.events_path).read_prefix()
    assert outcome.status == "failed"
    assert "native trajectory" in (outcome.error or "")
    assert prefix.failure is not None
    assert not any(
        event.event_type == "analysis.completed" for event in prefix.events
    )
    assert b'"event_type":"analysis.failed"' not in (
        harness.recorder.events_path.read_bytes()
    )


def test_runner_rejects_completed_manifest_when_terminal_replay_is_corrupt(
    tmp_path: Path,
) -> None:
    harness = _native_runner_harness(tmp_path)

    def corrupt_after_terminal(event: Any) -> None:
        if event.event_type == "analysis.completed":
            with harness.recorder.events_path.open("ab") as stream:
                stream.write(b'{"sequence":')

    harness.bridge.on_native_commit = corrupt_after_terminal

    outcome = harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一",))
    )

    prefix = RunEventReader(harness.recorder.events_path).read_prefix()
    manifest = json.loads(harness.workspace.manifest_path.read_text(encoding="utf-8"))
    assert outcome.status == "failed"
    assert prefix.failure is not None
    assert prefix.events[-1].event_type == "analysis.completed"
    assert harness.recorder.events_path.read_bytes().endswith(b'{"sequence":')
    assert manifest["status"] == "failed"


def test_runner_reuses_one_pi_process_and_injects_finalized_prior_context(runner_harness: RunnerHarness) -> None:
    runner_harness.pi.behavior = [
        {"answer": "运行完成", "produce_result_ref": RESULT_REF},
        {"answer": "排序完成", "consume_result_ref": RESULT_REF},
    ]

    outcome = runner_harness.runner.run(
        AnalysisRequest(
            analysis_id="analysis-test",
            instructions=("运行交流潮流", "按负载率排序"),
        )
    )

    assert runner_harness.pi.start_calls == 1
    assert runner_harness.pi.stop_calls == 1
    assert len(runner_harness.pi.prompts) == 2
    assert "运行交流潮流" in runner_harness.pi.prompts[0]
    assert RESULT_REF in runner_harness.pi.prompts[1]
    assert '"active_model"' in runner_harness.pi.prompts[1]
    assert '"model_id":"ieee39"' in runner_harness.pi.prompts[1]
    assert '"quantity":"bus.vm_pu"' in runner_harness.pi.prompts[1]
    assert "后续指令省略模型、场景或结果时" in runner_harness.pi.prompts[1]
    assert "不得写入 context/result/evidence/asset/constraint 等内部引用 ID" in runner_harness.pi.prompts[1]
    assert outcome.status == "completed"
    assert runner_harness.store.snapshot.turns[1].consumed_refs == [RESULT_REF]


def test_runner_records_submitted_answer_before_completing_turn(runner_harness: RunnerHarness) -> None:
    outcome = runner_harness.runner.run(AnalysisRequest(analysis_id="analysis-test", instructions=("一",)))

    events = [json.loads(line) for line in runner_harness.workspace.context_events_path.read_text(encoding="utf-8").splitlines()]
    submitted = next(event for event in events if event["event_type"] == "answer.submitted")
    completed = next(event for event in events if event["event_type"] == "turn.completed")
    assert submitted["sequence"] < completed["sequence"]
    assert submitted["payload"]["turn_id"] == "analysis-test-t001"
    assert submitted["payload"]["answer_path"] == "turns/001/answer.json"
    assert submitted["payload"]["answer_sha256"]
    assert outcome.status == "completed"


def test_runner_continues_after_missing_answer_and_projection_integrity_diagnostic(
    runner_harness: RunnerHarness,
) -> None:
    runner_harness.pi.behavior = [NO_DRAFT_AGENT_END, {"answer": "已提交答案", "projection_error": True}, {"answer": "后续答案"}]

    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一", "二", "三"))
    )

    assert len(runner_harness.pi.prompts) == 3
    assert outcome.status == "completed"
    assert runner_harness.store.snapshot.turns[0].status == "failed"
    assert [turn.status for turn in runner_harness.store.snapshot.turns] == ["failed", "success", "success"]
    assert [json.loads(line)["answer_output"] for line in runner_harness.workspace.answers_path.read_text().splitlines()] == [
        "执行限制 / execution limitation: grid_submit_answer did not create an answer draft",
        "已提交答案",
        "后续答案",
    ]


def test_runner_keeps_normal_gridctl_error_nonterminal_and_checkpoints_report(
    runner_harness: RunnerHarness,
) -> None:
    runner_harness.pi.behavior = [
        {"answer": "工具失败但已说明", "tool_error": True},
        {"answer": "后续继续"},
    ]

    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("潮流不收敛", "继续整理"))
    )

    assert outcome.status == "completed"
    assert len(runner_harness.pi.prompts) == 2
    assert "normal gridctl error" in runner_harness.workspace.report_path.read_text(encoding="utf-8")
    assert runner_harness.store.snapshot.diagnostics[-1].event_type == "tool.failed"


def test_runner_stops_on_pi_protocol_error_and_still_stops_process(
    runner_harness: RunnerHarness,
) -> None:
    runner_harness.pi.behavior = [PiProtocolError("provider died"), SHOULD_NOT_RUN]

    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一", "二"))
    )

    assert outcome.status == "failed"
    assert "provider died" in (outcome.error or "")
    assert runner_harness.pi.start_calls == 1
    assert runner_harness.pi.stop_calls == 1
    assert len(runner_harness.pi.prompts) == 1
    assert runner_harness.store.snapshot.status == "failed"


def test_runner_start_failure_terminalizes_artifacts_and_still_stops_process(
    runner_harness: RunnerHarness,
) -> None:
    runner_harness.pi.start_error = PiProtocolError("launch failed")

    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一",))
    )

    manifest = json.loads(runner_harness.workspace.manifest_path.read_text(encoding="utf-8"))
    assert outcome.status == "failed"
    assert "launch failed" in (outcome.error or "")
    assert runner_harness.pi.start_calls == 1
    assert runner_harness.pi.stop_calls == 1
    assert runner_harness.pi.prompts == []
    assert runner_harness.store.snapshot.current_turn is None
    assert runner_harness.store.snapshot.status == "failed"
    assert manifest["status"] == "failed"


def test_runner_records_active_context_store_error_as_diagnostic_and_continues(
    runner_harness: RunnerHarness,
) -> None:
    runner_harness.pi.behavior = [{"store_error": True, "write_draft": False}, SHOULD_NOT_RUN]

    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一", "二"))
    )

    manifest = json.loads(runner_harness.workspace.manifest_path.read_text(encoding="utf-8"))
    assert outcome.status == "completed"
    assert runner_harness.pi.stop_calls == 1
    assert len(runner_harness.pi.prompts) == 2
    assert runner_harness.store.snapshot.current_turn is None
    assert runner_harness.store.snapshot.turns[0].status == "failed"
    assert runner_harness.store.snapshot.turns[1].status == "success"
    assert runner_harness.store.snapshot.status == "completed"
    assert manifest["status"] == "completed"
    assert manifest["context_available"] is True
    assert any("durable append failed while active" in item.message for item in runner_harness.store.snapshot.unresolved_limitations)


def test_runner_does_not_write_context_events_after_terminal_completion(
    runner_harness: RunnerHarness,
    tmp_path: Path,
) -> None:
    from grid_agent.observability.trace import JsonlTraceWriter

    runner_harness.runner._trace = JsonlTraceWriter(runner_harness.workspace.trace_path)
    outcome = runner_harness.runner.run(AnalysisRequest(analysis_id="analysis-test", instructions=("一",)))

    assert outcome.status == "completed"
    events = [json.loads(line)["event_type"] for line in runner_harness.workspace.context_events_path.read_text().splitlines()]
    assert events[-1] == "analysis.completed"


def test_runner_does_not_publish_running_context_when_turn_failure_cannot_persist(
    runner_harness: RunnerHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_harness.pi.behavior = [PiProtocolError("provider died")]

    def fail_unpersisted(*_args: Any, **_kwargs: Any) -> FinalizedTurn:
        raise ContextStoreError("ledger unavailable")

    monkeypatch.setattr(runner_harness.runner._turns, "fail", fail_unpersisted)
    outcome = runner_harness.runner.run(AnalysisRequest(analysis_id="analysis-test", instructions=("一",)))

    manifest = json.loads(runner_harness.workspace.manifest_path.read_text())
    assert outcome.status == "failed"
    assert runner_harness.store.snapshot.current_turn is not None
    assert manifest["context_available"] is False
    assert manifest["report_path"] is None
    assert not runner_harness.workspace.report_path.exists()


def test_runner_replays_final_ledger_and_writes_manifest(runner_harness: RunnerHarness) -> None:
    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一",))
    )

    replayed = AnalysisContextStore.replay(runner_harness.workspace.context_events_path)
    manifest = json.loads(runner_harness.workspace.manifest_path.read_text(encoding="utf-8"))

    assert isinstance(outcome, AnalysisOutcome)
    assert replayed == runner_harness.store.snapshot
    assert replayed.status == "completed"
    assert manifest["status"] == "completed"
    assert manifest["report_path"] == "report.md"
    assert outcome.report_path == runner_harness.workspace.report_path


def test_runner_verifies_running_snapshot_before_completion_and_final_report(
    runner_harness: RunnerHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_verify = AnalysisContextStore.verify_materialized_snapshot

    def record_verify(self: AnalysisContextStore) -> Any:
        calls.append(f"verify:{self.snapshot.status}")
        return original_verify(self)

    def record_checkpoint(**kwargs: Any) -> None:
        calls.append(f"report:{kwargs['context'].status}")

    monkeypatch.setattr(AnalysisContextStore, "verify_materialized_snapshot", record_verify)
    monkeypatch.setattr("grid_agent.analysis.runner.write_analysis_report_checkpoint", record_checkpoint)

    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一",))
    )

    assert outcome.status == "completed"
    assert "verify:running" in calls
    assert "report:completed" in calls
    assert "verify:completed" not in calls
    assert calls.index("verify:running") < calls.index("report:completed")


def test_runner_terminally_fails_when_final_replay_verification_fails(
    runner_harness: RunnerHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_materialized_snapshot(self: AnalysisContextStore) -> Any:
        raise RuntimeError("durable state mismatch")

    monkeypatch.setattr(AnalysisContextStore, "verify_materialized_snapshot", fail_materialized_snapshot)

    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一",))
    )

    assert outcome.status == "failed"
    assert "durable state mismatch" in (outcome.error or "")
    manifest = json.loads(runner_harness.workspace.manifest_path.read_text(encoding="utf-8"))
    assert runner_harness.store.snapshot.status == "failed"
    assert manifest["status"] == "failed"
    assert "durable state mismatch" in manifest["error"]


def _read_active_turn(workspace: AnalysisWorkspace) -> ActiveTurnHandle:
    payload = json.loads(workspace.active_turn_path.read_text(encoding="utf-8"))
    return ActiveTurnHandle(
        ordinal=payload["ordinal"],
        turn_id=payload["turn_id"],
        instruction=payload["instruction"],
        instruction_sha256=payload["instruction_sha256"],
        turn_nonce=payload["turn_nonce"],
        started_monotonic=payload["started_monotonic"],
    )


def _write_draft(
    path: Path,
    turn: ActiveTurnHandle,
    *,
    answer: str,
    result_refs: list[str] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "turn_id": turn.turn_id,
                "turn_nonce": turn.turn_nonce,
                "answer_output": answer,
                "claim_evidence_refs": [],
                "result_refs": result_refs or [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _append_baseline_if_missing(store: AnalysisContextStore, turn_id: str) -> None:
    if BASELINE_REF in store.snapshot.baselines:
        return
    store.append(
        ContextEventDraft(
            event_type="simulator.context.opened",
            turn_id=turn_id,
            capability="context.open",
            payload={
                "context_ref": BASELINE_REF,
                "revision_ref": REVISION_REF,
                "path": "evidence/contexts/context.json",
                "source": {"model": "ieee39", "source": "test"},
                "network": {"pandapower_version": "3.4.0"},
            },
        )
    )
