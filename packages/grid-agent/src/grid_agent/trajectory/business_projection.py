"""Pure business-facing projection with explicit event provenance."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from typing import Any, Literal, Protocol

from grid_agent.trajectory.projection_models import (
    BusinessNode,
    BusinessProblem,
    BusinessTrajectory,
)
from grid_agent.trajectory.replay import ReplayEventLike


RULE_TOOL_ACTION = "tool-action/v1"
RULE_CONTEXT_CHANGE = "context-state-delta/v1"
RULE_VERIFIED_RESULT = "verified-simulator-result/v1"

_SEMANTIC_TOOL_TITLES = {
    "environment.describe": "核对仿真器协议和已发布能力",
    "model.list": "确认可用的已注册网络模型",
    "context.open": "打开只读网络仿真环境上下文",
    "context.get": "读取已打开的仿真环境上下文",
    "model.element.get": "定位问题涉及的网络元件",
    "model.dataset.describe": "核对可查询的数据集与字段",
    "model.dataset.query": "查询网络模型数据",
    "topology.branch.endpoints.get": "核查支路两端母线",
    "topology.components.get": "核查网络拓扑连通性",
    "analysis.powerflow.ac.run": "运行交流潮流计算",
    "result.branches.rank": "按支路运行指标筛选和排序",
    "analysis.contingency.n_minus_one.run": "执行单支路 N-1 静态安全校核",
    "evidence.get": "读取已持久化的仿真证据",
    "grid_guide_open": "读取已发布的领域操作指南",
    "grid_submit_answer": "提交带结构化证据的最终答案",
}


class ProjectionIntegrityError(RuntimeError):
    """A business fact lacks its mandatory verified simulator evidence."""


class ArtifactResolver(Protocol):
    def verify(self, reference: str) -> Any: ...


def semantic_tool_title(capability: str) -> str:
    """Return the registered semantic title, preserving unknown identifiers verbatim."""
    return _SEMANTIC_TOOL_TITLES.get(capability, capability)


def _payload(event: ReplayEventLike) -> dict[str, Any]:
    return dict(event.payload)


def _source(event: ReplayEventLike) -> Literal["observed", "agent-declared"]:
    return "agent-declared" if event.source.kind == "agent-declared" else "observed"


def _problem_for(
    problems: OrderedDict[str, list[BusinessNode]], event: ReplayEventLike
) -> list[BusinessNode] | None:
    turn_id = event.scope.turn_id
    if turn_id is None:
        return None
    return problems.setdefault(turn_id, [])


def _verified_result_node(
    event: ReplayEventLike, artifacts: ArtifactResolver
) -> BusinessNode:
    references = (*event.refs.produced, *event.refs.evidence)
    documents = tuple(artifacts.verify(reference) for reference in references)
    if not documents or any(
        getattr(document, "authority", None) != "gridctl"
        or getattr(document, "integrity", None) != "verified"
        for document in documents
    ):
        raise ProjectionIntegrityError(
            "numerical business node requires a verified simulator artifact"
        )
    return BusinessNode(
        id=f"business:{event.analysis_id}:{event.sequence}:result",
        source="observed",
        source_sequences=(event.sequence,),
        status="completed",
        kind="verified-result",
        title=semantic_tool_title(str(_payload(event)["capability"])),
        refs=tuple(references),
        rule_id=None,
    )


def _is_verified_result_capability(capability: str) -> bool:
    """Return whether a completed tool can establish a simulator result fact."""
    return capability.startswith(("analysis.", "result."))


def _accepted_submissions(events: Sequence[ReplayEventLike]) -> dict[str, int]:
    return {
        str(_payload(event)["submission_id"]): event.sequence
        for event in events
        if event.event_type == "answer.submitted"
    }


def project_business(
    events: Sequence[ReplayEventLike], artifacts: ArtifactResolver
) -> BusinessTrajectory:
    """Project only explicit lifecycle/declaration records; answer prose is ignored."""
    problems: OrderedDict[str, list[BusinessNode]] = OrderedDict()
    analysis_id = events[0].analysis_id if events else "empty-analysis"
    accepted_submissions = _accepted_submissions(events)
    for event in events:
        nodes = _problem_for(problems, event)
        if nodes is None:
            continue
        payload = _payload(event)
        if event.event_type == "business.decision.declared":
            nodes.append(
                BusinessNode(
                    id=f"business:{event.analysis_id}:{event.sequence}:decision",
                    source="agent-declared",
                    source_sequences=(event.sequence,),
                    status="completed",
                    kind="decision",
                    title=str(payload["decision"]),
                    detail=str(payload["next_action"]),
                )
            )
        elif event.event_type == "business.claim.declared" and (
            submission_sequence := accepted_submissions.get(str(payload["submission_id"]))
        ) is not None:
            nodes.append(
                BusinessNode(
                    id=f"business:{event.analysis_id}:{event.sequence}:claim",
                    source="agent-declared",
                    source_sequences=(event.sequence, submission_sequence),
                    status="completed",
                    kind="claim",
                    title=str(payload["statement"]),
                    refs=tuple(
                        (
                            *payload.get("result_refs", ()),
                            *payload.get("evidence_refs", ()),
                        )
                    ),
                )
            )
        elif event.event_type in {"context.projected", "context.injected"}:
            nodes.append(
                BusinessNode(
                    id=f"business:{event.analysis_id}:{event.sequence}:context",
                    source="derived",
                    source_sequences=(event.sequence,),
                    rule_id=RULE_CONTEXT_CHANGE,
                    status="completed",
                    kind="context-change",
                    title="Context state changed",
                    refs=tuple(event.refs.produced),
                )
            )
        elif event.event_type in {"tool.completed", "tool.failed"}:
            capability = str(payload["capability"])
            status = (
                "completed"
                if event.event_type == "tool.completed"
                and payload.get("ok") is not False
                else "failed"
            )
            nodes.append(
                BusinessNode(
                    id=f"business:{event.analysis_id}:{event.sequence}:tool",
                    source="observed",
                    source_sequences=(event.sequence,),
                    status=status,
                    kind="tool-action",
                    title=semantic_tool_title(capability),
                    refs=tuple((*event.refs.produced, *event.refs.evidence)),
                )
            )
            if (
                status == "completed"
                and _is_verified_result_capability(capability)
                and (event.refs.produced or event.refs.evidence)
            ):
                nodes.append(_verified_result_node(event, artifacts))
        elif event.event_type in {
            "turn.failed",
            "step.failed",
            "model.response.failed",
            "answer.rejected",
        }:
            nodes.append(
                BusinessNode(
                    id=f"business:{event.analysis_id}:{event.sequence}:failure",
                    source=_source(event),
                    source_sequences=(event.sequence,),
                    status="failed",
                    kind="failure",
                    title=str(payload.get("message", event.event_type)),
                )
            )
        elif event.event_type == "audit.diagnostic.recorded":
            nodes.append(
                BusinessNode(
                    id=f"business:{event.analysis_id}:{event.sequence}:audit",
                    source="observed",
                    source_sequences=(event.sequence,),
                    status="completed",
                    kind="audit-finding",
                    title=str(payload["message"]),
                )
            )

    return BusinessTrajectory(
        analysis_id=analysis_id,
        problems=tuple(
            BusinessProblem(
                id=f"business:{analysis_id}:{turn_id}",
                source="derived",
                source_sequences=tuple(node.source_sequences[0] for node in nodes),
                rule_id="problem-grouping/v1",
                status="completed",
                turn_id=turn_id,
                title=turn_id,
                nodes=tuple(nodes),
            )
            for turn_id, nodes in problems.items()
            if nodes
        ),
    )


__all__ = [
    "ArtifactResolver",
    "ProjectionIntegrityError",
    "RULE_CONTEXT_CHANGE",
    "RULE_TOOL_ACTION",
    "RULE_VERIFIED_RESULT",
    "project_business",
    "semantic_tool_title",
]
