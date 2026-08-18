from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from grid_agent.analysis.integrity import ContentReferenceVerifier, SimulatorIntegrityError
from grid_agent.analysis.capabilities import CapabilityContextCatalog
from grid_agent.analysis.models import ContextEventDraft, VerifiedFact
from grid_agent.analysis.projector import AnalysisContextProjector
from grid_agent.analysis.store import AnalysisContextStore, ContextStoreError
from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry


INPUT = {
    "copied_path": "input/instructions.md.txt",
    "source_path": "task.md.txt",
    "sha256": "a" * 64,
    "instruction_count": 1,
}
RUNTIME = {
    "provider": "test",
    "model": "scripted",
    "grid_capability_protocol": "1.0",
    "pandapower_version": "3.4.0",
}


@dataclass(frozen=True)
class ContextHarness:
    workspace: AnalysisWorkspace
    store: AnalysisContextStore
    projector: AnalysisContextProjector

    def start_turn(self, turn_id: str, *, ordinal: int) -> None:
        self.store.append(
            ContextEventDraft(
                event_type="turn.started",
                turn_id=turn_id,
                payload={
                    "ordinal": ordinal,
                    "instruction": f"analysis instruction {ordinal}",
                    "instruction_sha256": f"{ordinal:x}" * 64,
                    "nonce_sha256": f"{ordinal + 1:x}" * 64,
                },
            )
        )

    def complete_turn(self, turn_id: str) -> None:
        self.store.append(
            ContextEventDraft(
                event_type="turn.completed",
                turn_id=turn_id,
                payload={
                    "status": "success",
                    "answer_path": f"turns/{turn_id}/answer.json",
                    "answer_sha256": "d" * 64,
                    "duration_seconds": 0.1,
                },
            )
        )


@dataclass(frozen=True)
class OpenedContext:
    context_ref: str
    revision_ref: str
    context_path: Path


@pytest.fixture
def context_harness(tmp_path: Path) -> ContextHarness:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    store = AnalysisContextStore.initialize(workspace, input_record=INPUT, runtime_record=RUNTIME)
    definition_root = Path(__file__).resolve().parents[4] / "packages/grid-simulator/src/grid_simulator/capabilities/definitions"
    documents = tuple(json.loads(path.read_text(encoding="utf-8")) for path in sorted(definition_root.glob("*.json")))
    return ContextHarness(
        workspace=workspace,
        store=store,
        projector=AnalysisContextProjector(
            store,
            ContentReferenceVerifier(workspace.root_path),
            CapabilityContextCatalog.from_documents(documents),
        ),
    )


def test_projector_registers_powerflow_and_ranking_dependency(context_harness: ContextHarness) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    powerflow_result, powerflow_evidence_ref = write_powerflow_result(
        context_harness.workspace,
        opened,
        converged=True,
        total_active_loss=1.25,
        branch_results=[
            {"branch_ref": "asset:line:11", "loading_percent": 91.2},
            {"branch_ref": "asset:line:12", "loading_percent": 88.1},
        ],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_analysis_powerflow_ac", {"context_ref": opened.context_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result("call-1", "analysis.powerflow.ac.run", powerflow_result, evidence_refs=[powerflow_evidence_ref]),
        turn_id="analysis-test-t001",
    )
    context_harness.complete_turn("analysis-test-t001")
    context_harness.start_turn("analysis-test-t002", ordinal=2)
    context_harness.projector.observe(
        tool_start(
            "call-2",
            "grid_result_branches_rank",
            {"result_ref": powerflow_result["result_ref"], "metric": "loading_percent", "limit": 5},
        ),
        turn_id="analysis-test-t002",
    )
    context_harness.projector.observe(
        tool_result(
            "call-2",
            "result.branches.rank",
            {
                "branches": [
                    {
                        "branch_ref": "asset:line:11",
                        "metric": "loading_percent",
                        "value": 91.2,
                        "unit": "%",
                    }
                ]
            },
        ),
        turn_id="analysis-test-t002",
    )

    state = context_harness.store.snapshot
    assert powerflow_result["result_ref"] in state.domain_state.calculations
    assert powerflow_result["result_ref"] in state.results
    ranking = next(item for item in state.observations.values() if item.capability == "result.branches.rank")
    assert ranking.consumed_refs == [powerflow_result["result_ref"]]
    assert ranking.produced_refs == []
    assert any(
        fact_statement(fact)["predicate"] == "branch.loading_percent"
        and fact_statement(fact)["source_observation_id"] == ranking.observation_ref
        and fact_statement(fact)["context_ref"] == opened.context_ref
        and fact_statement(fact)["revision_ref"] == opened.revision_ref
        for fact in state.verified_facts.values()
    )


def test_projector_treats_generic_result_views_as_consumers_not_producers(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    body = {
        "result_type": "analysis.operation",
        "operation": "powerflow.ac",
        "context_ref": opened.context_ref,
        "revision_ref": opened.revision_ref,
        "status": "succeeded",
        "datasets": {"result.res_bus": {"source_table": "res_bus", "row_count": 39, "fields": [], "rows": []}},
    }
    result_ref = write_result_document(context_harness.workspace, "result", body)
    evidence_ref = write_evidence_document(
        context_harness.workspace,
        "analysis",
        "analysis-evidence",
        {
            "evidence_type": "analysis_result",
            "capability_id": "analysis.run",
            "context_ref": opened.context_ref,
            "revision_ref": opened.revision_ref,
            "result_ref": result_ref,
            "facts": {"status": "succeeded"},
        },
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("run", "grid_analysis_run", {"context_ref": opened.context_ref, "operation": "powerflow.ac", "options": {}}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "run",
            "analysis.run",
            {
                "result_ref": result_ref,
                "context_ref": opened.context_ref,
                "revision_ref": opened.revision_ref,
                "operation": "powerflow.ac",
                "status": "succeeded",
                "datasets": [{"dataset": "result.res_bus", "row_count": 39}],
                "evidence_refs": [evidence_ref],
            },
            evidence_refs=[evidence_ref],
        ),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_start("list", "grid_result_dataset_list", {"result_ref": result_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "list",
            "result.dataset.list",
            {
                "result_ref": result_ref,
                "context_ref": opened.context_ref,
                "revision_ref": opened.revision_ref,
                "operation": "powerflow.ac",
                "datasets": [],
            },
        ),
        turn_id="analysis-test-t001",
    )

    state = context_harness.store.snapshot
    views = [item for item in state.observations.values() if item.capability == "result.dataset.list"]
    assert len(views) == 1
    assert views[0].consumed_refs == [result_ref]
    assert views[0].produced_refs == []
    assert list(state.results) == [result_ref]


def test_projector_stops_on_integrity_failure_but_records_normal_tool_error(
    context_harness: ContextHarness,
) -> None:
    context_harness.start_turn("analysis-test-t001", ordinal=1)

    context_harness.projector.observe(
        tool_result(
            "call-1",
            "analysis.powerflow.ac.run",
            {},
            ok=False,
            error={"code": "powerflow_non_convergence"},
        ),
        turn_id="analysis-test-t001",
        trace_sequence=42,
    )
    assert context_harness.store.snapshot.unresolved_limitations
    events = [json.loads(line) for line in context_harness.workspace.context_events_path.read_text().splitlines()]
    observation = next(event for event in events if event["event_type"] == "tool.observation.recorded")
    assert observation["trace_sequence"] == 42

    with pytest.raises(SimulatorIntegrityError):
        context_harness.projector.observe(
            tool_start("call-2", "grid_analysis_powerflow_ac", {"context_ref": "context:sha256:" + "9" * 64}),
            turn_id="analysis-test-t001",
        )
        context_harness.projector.observe(
            tool_result(
                "call-2",
                "analysis.powerflow.ac.run",
                {"context_ref": "context:sha256:" + "9" * 64, "result_ref": "result:sha256:" + "8" * 64},
            ),
            turn_id="analysis-test-t001",
        )


def test_projector_keeps_compatibility_observation_disjoint_from_native_sidecar(
    context_harness: ContextHarness,
) -> None:
    turn_id = "analysis-test-t001"
    call_id = "call-1"
    context_harness.start_turn(turn_id, ordinal=1)
    artifacts = ImmutableArtifactRegistry(context_harness.workspace.root_path)
    native = artifacts.write_json(
        "tool-result",
        f"{turn_id}:{call_id}",
        {
            "schema_version": "grid-tool-invocation/1.0",
            "turn_id": turn_id,
            "tool_call_id": call_id,
            "arguments": {},
        },
    )
    native_path = artifacts.verify(native)
    native_bytes = native_path.read_bytes()

    context_harness.projector.observe(
        tool_result(
            call_id,
            "analysis.powerflow.ac.run",
            {},
            ok=False,
            error={"code": "powerflow_non_convergence"},
        ),
        turn_id=turn_id,
    )

    observation = next(
        iter(context_harness.store.snapshot.observations.values())
    )
    compatibility_path = (
        context_harness.workspace.root_path / observation.path
    )
    assert artifacts.verify(native) == native_path
    assert native_path.read_bytes() == native_bytes
    assert compatibility_path != native_path
    assert compatibility_path.is_file()
    assert json.loads(compatibility_path.read_text(encoding="utf-8"))[
        "capability"
    ] == "analysis.powerflow.ac.run"


def test_projector_requires_start_for_success_but_not_for_normal_failure(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    powerflow_result, powerflow_evidence_ref = write_powerflow_result(
        context_harness.workspace,
        opened,
        converged=True,
        total_active_loss=1.25,
        branch_results=[],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)

    with pytest.raises(SimulatorIntegrityError, match="matching tool start"):
        context_harness.projector.observe(
            tool_result(
                "call-1",
                "analysis.powerflow.ac.run",
                powerflow_result,
                evidence_refs=[powerflow_evidence_ref],
            ),
            turn_id="analysis-test-t001",
        )

    context_harness.projector.observe(
        tool_result(
            "call-2",
            "analysis.powerflow.ac.run",
            {},
            ok=False,
            error={"code": "powerflow_non_convergence"},
        ),
        turn_id="analysis-test-t001",
    )


@pytest.mark.parametrize(
    "capability",
    [
        "grid_analysis_context_get",
        "grid_guide_open",
        "grid_record_decision",
        "grid_submit_answer",
    ],
)
def test_projector_ignores_non_simulator_tools(
    context_harness: ContextHarness,
    capability: str,
) -> None:
    context_harness.start_turn("analysis-test-t001", ordinal=1)
    revision_before = context_harness.store.snapshot.revision

    context_harness.projector.observe(
        tool_start("non-simulator-1", capability, {"answer_output": "答案"}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "non-simulator-1",
            capability,
            {"turn_id": "analysis-test-t001"},
        ),
        turn_id="analysis-test-t001",
    )

    assert context_harness.store.snapshot.revision == revision_before
    assert not context_harness.store.snapshot.unresolved_limitations


def test_projector_failed_ranking_with_unknown_result_ref_records_limitation(
    context_harness: ContextHarness,
) -> None:
    unknown_result_ref = "result:sha256:" + "9" * 64

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_result_branches_rank", {"result_ref": unknown_result_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "call-1",
            "result.branches.rank",
            {},
            ok=False,
            error={"code": "unknown_result_ref"},
        ),
        turn_id="analysis-test-t001",
    )

    state = context_harness.store.snapshot
    assert state.unresolved_limitations
    observation = next(item for item in state.observations.values() if item.capability == "result.branches.rank")
    assert observation.consumed_refs == []
    assert observation.producer_observation["args"] == {"result_ref": unknown_result_ref}
    assert state.diagnostics[-1].details["error"]["code"] == "unknown_result_ref"
    assert state.diagnostics[-1].details["tool_name"] == "grid_result_branches_rank"


def test_projector_rejects_forged_inline_powerflow_fact_values(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    powerflow_result, powerflow_evidence_ref = write_powerflow_result(
        context_harness.workspace,
        opened,
        converged=True,
        total_active_loss=1.25,
        branch_results=[],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_analysis_powerflow_ac", {"context_ref": opened.context_ref}),
        turn_id="analysis-test-t001",
    )

    with pytest.raises(SimulatorIntegrityError, match="total_active_loss"):
        context_harness.projector.observe(
            tool_result(
                "call-1",
                "analysis.powerflow.ac.run",
                {**powerflow_result, "total_active_loss": 9999.0},
                evidence_refs=[powerflow_evidence_ref],
            ),
            turn_id="analysis-test-t001",
        )


def test_projector_opens_context_and_promotes_topology_endpoint_facts(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    endpoint_evidence_ref = write_topology_evidence(
        context_harness.workspace,
        opened,
        branch_ref="asset:line:11",
        from_bus="asset:bus:6",
        to_bus="asset:bus:11",
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_context_open", {"model_id": "ieee39"}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "call-1",
            "context.open",
            {
                "context_ref": opened.context_ref,
                "revision_ref": opened.revision_ref,
                "model": "ieee39",
                "source": "registered",
                "engine": "pandapower",
                "pandapower_version": "3.4.0",
                "counts": {"bus": 39, "line": 35, "trafo": 11},
            },
        ),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_start(
            "call-2",
            "grid_topology_branch_endpoints",
            {
                "context_ref": opened.context_ref,
                "kind": "line",
                "namespace": "pandapower_index",
                "identifier": "11",
            },
        ),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "call-2",
            "topology.branch.endpoints.get",
            {
                "context_ref": opened.context_ref,
                "revision_ref": opened.revision_ref,
                "branch_ref": "asset:line:11",
                "from_bus": "asset:bus:6",
                "to_bus": "asset:bus:11",
                "evidence_ref": endpoint_evidence_ref,
            },
            evidence_refs=[endpoint_evidence_ref],
        ),
        turn_id="analysis-test-t001",
    )

    state = context_harness.store.snapshot
    assert state.active_context_ref == opened.context_ref
    predicates = {fact_statement(fact)["predicate"] for fact in state.verified_facts.values()}
    assert {"topology.branch.from_bus", "topology.branch.to_bus"} <= predicates


def test_projector_reuses_registered_evidence_when_evidence_is_read_again(
    context_harness: ContextHarness,
) -> None:
    """A content-addressed evidence artifact is not scoped to a tool call."""
    opened = write_context(context_harness.workspace, model_id="ieee39")
    endpoint_evidence_ref = write_topology_evidence(
        context_harness.workspace,
        opened,
        branch_ref="asset:line:11",
        from_bus="asset:bus:6",
        to_bus="asset:bus:11",
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("open", "grid_context_open", {"model_id": "ieee39"}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result("open", "context.open", {"context_ref": opened.context_ref, "revision_ref": opened.revision_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_start("endpoints", "grid_topology_branch_endpoints", {"context_ref": opened.context_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "endpoints",
            "topology.branch.endpoints.get",
            {
                "context_ref": opened.context_ref,
                "revision_ref": opened.revision_ref,
                "branch_ref": "asset:line:11",
                "from_bus": "asset:bus:6",
                "to_bus": "asset:bus:11",
                "evidence_ref": endpoint_evidence_ref,
            },
            evidence_refs=[endpoint_evidence_ref],
        ),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_start("evidence", "grid_evidence_get", {"evidence_ref": endpoint_evidence_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "evidence",
            "evidence.get",
            {"evidence_ref": endpoint_evidence_ref},
            evidence_refs=[endpoint_evidence_ref],
        ),
        turn_id="analysis-test-t001",
    )

    evidence = context_harness.store.snapshot.evidence
    assert list(evidence) == [endpoint_evidence_ref]
    assert evidence[endpoint_evidence_ref].turn_id is None
    assert evidence[endpoint_evidence_ref].capability is None


def test_projector_reuses_registered_result_when_its_evidence_is_read_again(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    powerflow_result, powerflow_evidence_ref = write_powerflow_result(
        context_harness.workspace,
        opened,
        converged=True,
        total_active_loss=1.25,
        branch_results=[],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("powerflow", "grid_analysis_powerflow_ac", {"context_ref": opened.context_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "powerflow",
            "analysis.powerflow.ac.run",
            powerflow_result,
            evidence_refs=[powerflow_evidence_ref],
        ),
        turn_id="analysis-test-t001",
    )
    context_harness.complete_turn("analysis-test-t001")
    context_harness.start_turn("analysis-test-t002", ordinal=2)
    context_harness.projector.observe(
        tool_start("evidence", "grid_evidence_get", {"evidence_ref": powerflow_evidence_ref}),
        turn_id="analysis-test-t002",
    )
    context_harness.projector.observe(
        tool_result(
            "evidence",
            "evidence.get",
            {"evidence_ref": powerflow_evidence_ref},
            evidence_refs=[powerflow_evidence_ref],
        ),
        turn_id="analysis-test-t002",
    )

    assert list(context_harness.store.snapshot.results) == [powerflow_result["result_ref"]]


def test_projector_rejects_forged_inline_topology_fact_values(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    endpoint_evidence_ref = write_topology_evidence(
        context_harness.workspace,
        opened,
        branch_ref="asset:line:11",
        from_bus="asset:bus:6",
        to_bus="asset:bus:11",
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_context_open", {"model_id": "ieee39"}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result("call-1", "context.open", {"context_ref": opened.context_ref, "revision_ref": opened.revision_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_start("call-2", "grid_topology_branch_endpoints", {"context_ref": opened.context_ref}),
        turn_id="analysis-test-t001",
    )
    with pytest.raises(SimulatorIntegrityError, match="from_bus"):
        context_harness.projector.observe(
            tool_result(
                "call-2",
                "topology.branch.endpoints.get",
                {
                    "context_ref": opened.context_ref,
                    "revision_ref": opened.revision_ref,
                    "branch_ref": "asset:line:11",
                    "from_bus": "asset:bus:999",
                    "to_bus": "asset:bus:998",
                    "evidence_ref": endpoint_evidence_ref,
                },
                evidence_refs=[endpoint_evidence_ref],
            ),
            turn_id="analysis-test-t001",
        )


def test_projector_promotes_n_minus_one_aggregate_and_scenario_facts(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    n1_result, n1_evidence_ref = write_n1_result(
        context_harness.workspace,
        opened,
        scenarios=[
            {
                "scenario_result_ref": "result:sha256:" + "6" * 64,
                "status": "succeeded",
                "max_loading_percent": 103.4,
                "violations": [{"branch_ref": "asset:line:11"}],
            },
            {
                "scenario_result_ref": "result:sha256:" + "7" * 64,
                "status": "succeeded",
                "max_loading_percent": 87.2,
                "violations": [],
            },
        ],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start(
                "call-1",
                "grid_analysis_contingency_n_minus_one",
                {"context_ref": opened.context_ref, "branch_refs": ["asset:line:11"]},
        ),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "call-1",
            "analysis.contingency.n_minus_one.run",
            n1_result,
            evidence_refs=[n1_evidence_ref],
        ),
        turn_id="analysis-test-t001",
    )

    facts = [fact_statement(fact) for fact in context_harness.store.snapshot.verified_facts.values()]
    registered = context_harness.store.snapshot.results
    assert registered[n1_result["result_ref"]].capability == "analysis.contingency.n_minus_one.run"
    for scenario in n1_result["scenarios"]:
        assert registered[scenario["scenario_result_ref"]].capability == "analysis.contingency.n_minus_one.scenario"
    assert {"n1.status", "n1.scenario_count", "n1.max_loading_percent", "n1.violation_count"} <= {
        fact["predicate"] for fact in facts
    }
    assert next(fact for fact in facts if fact["predicate"] == "n1.scenario_count")["value"] == 2
    assert next(fact for fact in facts if fact["predicate"] == "n1.max_loading_percent")["value"] == 103.4
    assert next(fact for fact in facts if fact["predicate"] == "n1.violation_count")["value"] == 1


def test_projector_deduplicates_references_and_ignores_unknown_fields(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    powerflow_result, powerflow_evidence_ref = write_powerflow_result(
        context_harness.workspace,
        opened,
        converged=True,
        total_active_loss=0.5,
        branch_results=[],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_analysis_powerflow_ac", {"context_ref": opened.context_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "call-1",
            "analysis.powerflow.ac.run",
            {**powerflow_result, "untrusted_extra_loss": 9999},
            evidence_refs=[powerflow_evidence_ref, powerflow_evidence_ref],
        ),
        turn_id="analysis-test-t001",
    )

    state = context_harness.store.snapshot
    result = state.results[powerflow_result["result_ref"]]
    assert result.evidence_refs == [powerflow_evidence_ref]
    assert not any("untrusted_extra_loss" in fact.statement for fact in state.verified_facts.values())


def test_projector_records_observation_before_projected_artifacts(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    powerflow_result, powerflow_evidence_ref = write_powerflow_result(
        context_harness.workspace,
        opened,
        converged=True,
        total_active_loss=1.25,
        branch_results=[],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_analysis_powerflow_ac", {"context_ref": opened.context_ref}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result("call-1", "analysis.powerflow.ac.run", powerflow_result, evidence_refs=[powerflow_evidence_ref]),
        turn_id="analysis-test-t001",
    )

    event_types = [
        json.loads(line)["event_type"]
        for line in context_harness.workspace.context_events_path.read_text(encoding="utf-8").splitlines()
    ]
    projected = event_types[event_types.index("tool.observation.recorded") :]
    assert projected[:5] == [
        "tool.observation.recorded",
        "simulator.context.opened",
        "result.registered",
        "evidence.registered",
        "fact.verified",
    ]


def test_projector_rejects_successful_result_that_does_not_match_started_context(
    context_harness: ContextHarness,
) -> None:
    requested = write_context(context_harness.workspace, model_id="ieee39")
    returned = write_context(context_harness.workspace, model_id="case14")
    powerflow_result, powerflow_evidence_ref = write_powerflow_result(
        context_harness.workspace,
        returned,
        converged=True,
        total_active_loss=0.5,
        branch_results=[],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_analysis_powerflow_ac", {"context_ref": requested.context_ref}),
        turn_id="analysis-test-t001",
    )

    with pytest.raises(SimulatorIntegrityError, match="context_ref"):
        context_harness.projector.observe(
            tool_result(
                "call-1",
                "analysis.powerflow.ac.run",
                powerflow_result,
                evidence_refs=[powerflow_evidence_ref],
            ),
            turn_id="analysis-test-t001",
        )


def test_projector_surfaces_store_rejection_for_mismatched_active_baseline(
    context_harness: ContextHarness,
) -> None:
    opened = write_context(context_harness.workspace, model_id="ieee39")
    powerflow_result, powerflow_evidence_ref = write_powerflow_result(
        context_harness.workspace,
        opened,
        converged=True,
        total_active_loss=0.5,
        branch_results=[],
    )

    context_harness.start_turn("analysis-test-t001", ordinal=1)
    context_harness.projector.observe(
        tool_start("call-1", "grid_context_open", {"model_id": "ieee39"}),
        turn_id="analysis-test-t001",
    )
    context_harness.projector.observe(
        tool_result(
            "call-1",
            "context.open",
            {"context_ref": opened.context_ref, "revision_ref": "revision:sha256:" + "9" * 64},
        ),
        turn_id="analysis-test-t001",
    )

    with pytest.raises(ContextStoreError, match="revision_ref"):
        context_harness.projector.observe(
            tool_start("call-2", "grid_analysis_powerflow_ac", {"context_ref": opened.context_ref}),
            turn_id="analysis-test-t001",
        )
        context_harness.projector.observe(
            tool_result(
                "call-2",
                "analysis.powerflow.ac.run",
                powerflow_result,
                evidence_refs=[powerflow_evidence_ref],
            ),
            turn_id="analysis-test-t001",
        )


def tool_start(call_id: str, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "tool_execution_start",
        "tool_call_id": call_id,
        "tool_name": tool_name,
        "toolName": tool_name,
        "args": args,
    }


def tool_result(
    call_id: str,
    capability: str,
    result: dict[str, Any],
    *,
    ok: bool = True,
    error: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "tool_result",
        "event": "tool_result",
        "tool_call_id": call_id,
        "capability": capability,
        "ok": ok,
        "result": result,
        "evidence_refs": evidence_refs or [],
    }
    if error is not None:
        event["error"] = error
    return event


def write_context(workspace: AnalysisWorkspace, *, model_id: str) -> OpenedContext:
    revision = {"model_id": model_id, "pandapower_version": "3.4.0", "bus": [1, 2]}
    revision_payload = canonical_json(revision)
    revision_digest = hashlib.sha256(revision_payload.encode("utf-8")).hexdigest()
    revision_ref = "revision:sha256:" + revision_digest
    (workspace.evidence_path / "models").mkdir(parents=True, exist_ok=True)
    (workspace.evidence_path / "models" / f"{revision_digest}.json").write_text(revision_payload, encoding="utf-8")

    context = {
        "revision_ref": revision_ref,
        "model_id": model_id,
        "source": "registered",
        "engine": "pandapower",
        "pandapower_version": "3.4.0",
        "counts": {"bus": 39, "line": 35, "trafo": 11},
    }
    context_ref = "context:sha256:" + hashlib.sha256(canonical_json(context).encode("utf-8")).hexdigest()
    context_path = workspace.evidence_path / "contexts" / f"{context_ref.removeprefix('context:sha256:')}.json"
    context_path.write_text(canonical_json(context), encoding="utf-8")
    return OpenedContext(context_ref=context_ref, revision_ref=revision_ref, context_path=context_path)


def write_powerflow_result(
    workspace: AnalysisWorkspace,
    opened: OpenedContext,
    *,
    converged: bool,
    total_active_loss: float,
    branch_results: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    body = {
        "result_type": "analysis.powerflow.ac",
        "context_ref": opened.context_ref,
        "revision_ref": opened.revision_ref,
        "converged": converged,
        "total_active_loss": total_active_loss,
        "solver_summary": {"success": converged, "total_active_loss": total_active_loss, "algorithm": "nr"},
        "branch_results": branch_results,
    }
    result_ref = write_result_document(workspace, "powerflow", body)
    evidence_ref = write_evidence_document(
        workspace,
        "analysis",
        "analysis-evidence",
        {
            "evidence_type": "analysis_result",
            "capability_id": "analysis.powerflow.ac.run",
            "context_ref": opened.context_ref,
            "revision_ref": opened.revision_ref,
            "result_ref": result_ref,
            "facts": {"converged": converged, "total_active_loss": total_active_loss},
        },
    )
    return (
        {
            "context_ref": opened.context_ref,
            "revision_ref": opened.revision_ref,
            "result_ref": result_ref,
            "evidence_refs": [evidence_ref],
            "converged": converged,
            "total_active_loss": total_active_loss,
        },
        evidence_ref,
    )


def write_n1_result(
    workspace: AnalysisWorkspace,
    opened: OpenedContext,
    *,
    scenarios: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    linked_scenarios: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_body = {
            "result_type": "analysis.contingency.n_minus_one.scenario",
            "context_ref": opened.context_ref,
            "revision_ref": opened.revision_ref,
            "status": scenario.get("status"),
            "max_loading_percent": scenario.get("max_loading_percent"),
            "violations": scenario.get("violations", []),
        }
        scenario_ref = write_result_document(workspace, "contingency-scenario", scenario_body)
        linked_scenarios.append({**scenario, "scenario_result_ref": scenario_ref})
    body = {
        "result_type": "analysis.contingency.n_minus_one.aggregate",
        "context_ref": opened.context_ref,
        "revision_ref": opened.revision_ref,
        "status": "succeeded",
        "scenarios": linked_scenarios,
    }
    result_ref = write_result_document(workspace, "contingency", body)
    evidence_ref = write_evidence_document(
        workspace,
        "analysis",
        "analysis-evidence",
        {
            "evidence_type": "contingency_scenario",
            "capability_id": "analysis.contingency.n_minus_one.run",
            "context_ref": opened.context_ref,
            "revision_ref": opened.revision_ref,
            "result_ref": result_ref,
            "facts": {"status": "succeeded"},
        },
    )
    return (
        {
            "context_ref": opened.context_ref,
            "revision_ref": opened.revision_ref,
            "result_ref": result_ref,
            "evidence_refs": [evidence_ref],
            "status": "succeeded",
            "scenarios": linked_scenarios,
        },
        evidence_ref,
    )


def write_topology_evidence(
    workspace: AnalysisWorkspace,
    opened: OpenedContext,
    *,
    branch_ref: str,
    from_bus: str,
    to_bus: str,
) -> str:
    return write_evidence_document(
        workspace,
        "network-facts",
        "network-fact",
        {
            "evidence_type": "network_fact",
            "capability_id": "topology.branch.endpoints.get",
            "context_ref": opened.context_ref,
            "revision_ref": opened.revision_ref,
            "facts": {"branch_ref": branch_ref, "from_bus": from_bus, "to_bus": to_bus},
        },
    )


def write_result_document(workspace: AnalysisWorkspace, prefix: str, body: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    result_ref = "result:sha256:" + digest
    result_path = workspace.results_path / f"{prefix}-{digest}.json"
    result_path.write_text(canonical_json({"result_ref": result_ref, **body}), encoding="utf-8")
    return result_ref


def write_evidence_document(
    workspace: AnalysisWorkspace,
    directory: str,
    prefix: str,
    document: dict[str, Any],
) -> str:
    digest = hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()
    evidence_ref = "evidence:sha256:" + digest
    evidence_path = workspace.evidence_path / directory / f"{prefix}-{digest}.json"
    evidence_path.write_text(canonical_json(document), encoding="utf-8")
    return evidence_ref


def canonical_json(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fact_statement(fact: VerifiedFact) -> dict[str, Any]:
    statement = json.loads(fact.statement)
    assert isinstance(statement, dict)
    return statement
