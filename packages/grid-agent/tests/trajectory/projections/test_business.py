from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from grid_agent.trajectory.business_projection import (
    ProjectionIntegrityError,
    project_business,
)
from grid_agent.trajectory.events import (
    Causation,
    ContextBoundary,
    EventRefs,
    EventSource,
    RunScope,
)


@dataclass(frozen=True)
class Event:
    sequence: int
    event_type: str
    scope: RunScope = field(default_factory=RunScope)
    payload: dict[str, Any] = field(default_factory=dict)
    refs: EventRefs = field(default_factory=EventRefs)
    source: EventSource = field(default_factory=EventSource)
    analysis_id: str = "analysis-1"
    timestamp: str | None = None
    causation: Causation = field(default_factory=Causation)
    context: ContextBoundary = field(default_factory=ContextBoundary)


@dataclass(frozen=True)
class Document:
    authority: str
    integrity: str


class Artifacts:
    def __init__(self, integrity: str = "verified") -> None:
        self.integrity = integrity

    def verify(self, reference: str) -> Document:
        assert reference.startswith("artifact:")
        return Document(authority="gridctl", integrity=self.integrity)


def q7_events() -> tuple[Event, ...]:
    scope = RunScope(
        turn_id="turn-7",
        step_id="step-1",
        request_id="request-1",
        tool_call_id="call-1",
    )
    return (
        Event(1, "turn.started", RunScope(turn_id="turn-7"), {"ordinal": 7}),
        Event(
            2,
            "business.decision.declared",
            scope,
            {
                "intent": "Assess",
                "decision": "Run AC power flow",
                "next_action": "Inspect result",
            },
            source=EventSource(kind="agent-declared"),
        ),
        Event(
            3,
            "tool.completed",
            scope,
            {"capability": "analysis.powerflow.ac.run", "ok": True},
            EventRefs(produced=("artifact:result",), evidence=("artifact:evidence",)),
        ),
        Event(
            4, "context.projected", scope, {"revision": 3, "state_hash": "sha256:state"}
        ),
        Event(
            5,
            "business.claim.declared",
            scope,
            {
                "submission_id": "claim-1",
                "statement": "The verified calculation completed",
                "category": "numerical_result",
                "result_refs": ("artifact:result",),
                "evidence_refs": ("artifact:evidence",),
            },
            source=EventSource(kind="agent-declared"),
        ),
    )


def test_business_projection_separates_declared_derived_and_observed() -> None:
    events = (
        *q7_events(),
        Event(
            6,
            "answer.submitted",
            RunScope(turn_id="turn-7"),
            {"submission_id": "claim-1", "artifact_ref": "artifact:answer"},
        ),
    )

    trajectory = project_business(events, Artifacts())

    assert [node.source for node in trajectory.problems[0].nodes] == [
        "agent-declared",
        "observed",
        "observed",
        "derived",
        "agent-declared",
    ]
    derived = next(
        node for node in trajectory.problems[0].nodes if node.source == "derived"
    )
    assert derived.rule_id == "context-state-delta/v1"
    assert derived.source_sequences == (4,)
    assert trajectory.problems[0].nodes[-1].source_sequences == (5, 6)
    assert trajectory.problems[0].nodes[1].title == "运行交流潮流计算"


def test_business_projection_refuses_unverified_numeric_result() -> None:
    with pytest.raises(ProjectionIntegrityError, match="verified simulator artifact"):
        project_business(q7_events(), Artifacts(integrity="tampered"))


def test_business_projection_does_not_infer_nodes_from_answer_text() -> None:
    events = (
        *q7_events(),
        Event(
            6,
            "answer.submitted",
            RunScope(turn_id="turn-7"),
            {"submission_id": "answer", "artifact_ref": "artifact:answer"},
        ),
    )

    trajectory = project_business(events, Artifacts())

    assert len(trajectory.problems[0].nodes) == 4


def test_business_projection_accepts_claim_only_after_matching_submission() -> None:
    events = (
        *q7_events(),
        Event(
            6,
            "answer.submitted",
            RunScope(turn_id="turn-7"),
            {"submission_id": "other-submission", "artifact_ref": "artifact:answer"},
        ),
    )

    trajectory = project_business(events, Artifacts())

    assert all(node.kind != "claim" for node in trajectory.problems[0].nodes)


def test_business_projection_does_not_accept_claim_from_another_turn_submission() -> None:
    events = (
        *q7_events(),
        Event(
            6,
            "answer.submitted",
            RunScope(turn_id="turn-8"),
            {"submission_id": "claim-1", "artifact_ref": "artifact:answer"},
        ),
    )

    trajectory = project_business(events, Artifacts())

    assert all(node.kind != "claim" for node in trajectory.problems[0].nodes)


def test_business_projection_requires_every_verified_result_ref_to_be_verified() -> None:
    class MixedArtifacts(Artifacts):
        def verify(self, reference: str) -> Document:
            if reference == "artifact:evidence":
                return Document(authority="gridctl", integrity="tampered")
            return super().verify(reference)

    with pytest.raises(ProjectionIntegrityError, match="verified simulator artifact"):
        project_business(q7_events(), MixedArtifacts())


def test_business_projection_filters_non_simulator_tool_from_verified_results() -> None:
    events = (
        Event(1, "turn.started", RunScope(turn_id="turn-7"), {"ordinal": 7}),
        Event(
            2,
            "tool.completed",
            RunScope(turn_id="turn-7"),
            {"capability": "grid_guide_open", "ok": True},
            EventRefs(produced=("artifact:guide",)),
        ),
    )

    nodes = project_business(events, Artifacts()).problems[0].nodes

    assert [node.kind for node in nodes] == ["tool-action"]
