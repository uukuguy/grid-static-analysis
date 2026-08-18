from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from grid_agent.analysis.capabilities import CapabilityContextCatalog
from grid_agent.analysis.domain_projection import project_domain_result
from grid_agent.analysis.integrity import ContentReferenceVerifier, SimulatorIntegrityError, VerifiedArtifact
from grid_agent.analysis.models import ContextEventDraft, ResultRecord
from grid_agent.analysis.store import AnalysisContextStore


PROMOTED_FACT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "topology.branch.endpoints.get": ("from_bus", "to_bus"),
    "analysis.powerflow.ac.run": ("converged", "total_active_loss"),
    "result.branches.rank": ("branches",),
    "analysis.contingency.n_minus_one.run": ("status", "scenarios"),
}

_TOOL_NAME_TO_CAPABILITY: Mapping[str, str] = {
    "grid_context_open": "context.open",
    "grid_topology_branch_endpoints": "topology.branch.endpoints.get",
    "grid_analysis_powerflow_ac": "analysis.powerflow.ac.run",
    "grid_analysis_operation_list": "analysis.operation.list",
    "grid_analysis_operation_describe": "analysis.operation.describe",
    "grid_analysis_run": "analysis.run",
    "grid_analysis_result_violations_evaluate": "analysis.result.violations.evaluate",
    "grid_analysis_result_risk_rank": "analysis.result.risk.rank",
    "grid_model_equivalent_derive": "model.equivalent.derive",
    "grid_result_branches_rank": "result.branches.rank",
    "grid_result_dataset_list": "result.dataset.list",
    "grid_result_dataset_describe": "result.dataset.describe",
    "grid_result_dataset_query": "result.dataset.query",
    "grid_result_aggregate": "result.aggregate",
    "grid_result_compare": "result.compare",
    "grid_analysis_contingency_n_minus_one": "analysis.contingency.n_minus_one.run",
}

_NON_SIMULATOR_CAPABILITIES = frozenset(
    {
        "grid_analysis_context_get",
        "grid_guide_open",
        "grid_record_decision",
        "grid_submit_answer",
    }
)


class AnalysisContextProjector:
    """Project canonical semantic tool events into the analysis context store."""

    def __init__(
        self,
        store: AnalysisContextStore,
        verifier: ContentReferenceVerifier,
        capability_catalog: CapabilityContextCatalog,
    ) -> None:
        self._store = store
        self._verifier = verifier
        self._capability_catalog = capability_catalog
        self._starts: dict[str, Mapping[str, Any]] = {}

    def observe(self, event: Mapping[str, Any], *, turn_id: str, trace_sequence: int | None = None) -> None:
        event_type = event.get("type")
        if event_type == "tool_execution_start":
            call_id = _tool_call_id(event)
            if call_id is not None:
                self._starts[call_id] = dict(event)
            return

        if event_type != "tool_result" and event.get("event") != "tool_result":
            return

        capability = event.get("capability")
        if not isinstance(capability, str):
            return
        call_id = _tool_call_id(event)
        if capability in _NON_SIMULATOR_CAPABILITIES:
            if call_id is not None:
                self._starts.pop(call_id, None)
            return
        result = event.get("result")
        if not isinstance(result, Mapping):
            result = {}
        evidence_refs = _event_evidence_refs(event, result)
        ok = event.get("ok") is True
        start = self._starts.pop(call_id, {}) if call_id is not None and call_id in self._starts else {}

        if not ok:
            self._record_tool_error(
                capability,
                result,
                event,
                start=start,
                turn_id=turn_id,
                call_id=call_id,
                trace_sequence=trace_sequence,
            )
            return

        if not start:
            raise SimulatorIntegrityError(f"successful {capability} result has no matching tool start")
        self._assert_result_matches_started_inputs(capability, result, start)

        context_artifacts: tuple[VerifiedArtifact, ...] = ()
        if capability == "result.branches.rank":
            ranking_source_artifact = self._verified_ranking_source(start)
            result_artifacts: tuple[VerifiedArtifact, ...] = ()
            evidence_artifacts: tuple[VerifiedArtifact, ...] = ()
        elif capability.startswith("result."):
            self._verify_result_consumers(capability, start, result)
            result_artifacts = ()
            evidence_artifacts = ()
            ranking_source_artifact = None
        else:
            references = self._verifier.admit_successful_tool_references(
                capability,
                result,
                tuple(evidence_refs),
            )
            result_artifacts = references.results
            evidence_artifacts = references.evidence
            context_artifacts = references.context
            ranking_source_artifact = None

        observation_ref = self._append_observation(
            capability,
            result,
            event,
            start=start,
            turn_id=turn_id,
            call_id=call_id,
            trace_sequence=trace_sequence,
        )
        if capability != "result.branches.rank":
            self._append_missing_baselines(capability, result, context_artifacts, turn_id=turn_id)
        self._append_results(capability, result_artifacts, evidence_refs, observation_ref, turn_id=turn_id, start=start)
        self._append_evidence(capability, evidence_artifacts, turn_id=turn_id)
        self._append_facts(
            capability,
            result,
            result_artifacts,
            evidence_artifacts,
            ranking_source_artifact,
            observation_ref,
            turn_id=turn_id,
            start=start,
            evidence_refs=evidence_refs,
        )
        self._append_domain_state(
            capability,
            result,
            result_artifacts,
            turn_id=turn_id,
            start=start,
        )

    def _append_domain_state(
        self,
        capability: str,
        result: Mapping[str, Any],
        result_artifacts: tuple[VerifiedArtifact, ...],
        *,
        turn_id: str,
        start: Mapping[str, Any],
    ) -> None:
        spec = self._capability_catalog.require(capability)
        result_paths = {
            artifact.reference: _relative_path(artifact.path, self._verifier.workspace_root)
            for artifact in result_artifacts
        }
        context_ref = result.get("context_ref")
        baseline = self._store.snapshot.baselines.get(context_ref) if isinstance(context_ref, str) else None
        active_revision_ref = baseline.revision_ref if baseline is not None else None
        projection_result = dict(result)
        if spec.projector == "model-context-v1" and baseline is not None:
            projection_result.setdefault("model", baseline.network.get("name"))
            origin = projection_result.get("origin")
            projection_result.setdefault("source", origin if isinstance(origin, str) else "registered")
            projection_result.setdefault(
                "counts",
                {
                    "bus": baseline.network.get("bus_count", 0),
                    "line": baseline.network.get("line_count", 0),
                    "trafo": baseline.network.get("trafo_count", 0),
                },
            )
        delta = project_domain_result(
            spec,
            result=projection_result,
            arguments=_start_args(start),
            turn_id=turn_id,
            result_paths=result_paths,
            active_revision_ref=active_revision_ref,
        )
        self._store.append(
            ContextEventDraft(
                event_type="domain.state.projected",
                turn_id=turn_id,
                capability=capability,
                payload=delta.model_dump(mode="json"),
            )
        )

    def _record_tool_error(
        self,
        capability: str,
        result: Mapping[str, Any],
        event: Mapping[str, Any],
        *,
        start: Mapping[str, Any],
        turn_id: str,
        call_id: str | None,
        trace_sequence: int | None = None,
    ) -> None:
        observation_ref = self._append_observation(
            capability,
            result,
            event,
            start=start,
            turn_id=turn_id,
            call_id=call_id,
            trace_sequence=trace_sequence,
            consume_dependencies=False,
        )
        error = event.get("error")
        if not isinstance(error, Mapping):
            error = {}
        code = error.get("code")
        message = error.get("message") or code or f"{capability} failed"
        diagnostic_payload = {
            "message": str(message),
            "call_id": call_id,
            "tool_name": _tool_name(start),
            "args": dict(_start_args(start)),
            "error": dict(error),
            "observation_ref": observation_ref,
        }
        self._store.append(
            ContextEventDraft(
                event_type="limitation.recorded",
                turn_id=turn_id,
                capability=capability,
                payload={
                    "limitation_ref": _stable_ref("limitation", capability, turn_id, call_id, dict(error)),
                    "message": str(message),
                    "refs": [observation_ref],
                },
            ),
            integrity="diagnostic",
        )
        self._store.append(
            ContextEventDraft(
                event_type="tool.failed",
                turn_id=turn_id,
                capability=capability,
                payload=diagnostic_payload,
            ),
            integrity="diagnostic",
        )

    def _append_missing_baselines(
        self,
        capability: str,
        result: Mapping[str, Any],
        context_artifacts: Iterable[VerifiedArtifact],
        *,
        turn_id: str,
    ) -> None:
        for artifact in sorted(context_artifacts, key=lambda item: item.reference):
            if artifact.reference in self._store.snapshot.baselines:
                continue
            payload = _baseline_payload(artifact, self._verifier.workspace_root)
            if capability == "context.open":
                if isinstance(result.get("revision_ref"), str):
                    payload["revision_ref"] = result["revision_ref"]
                payload["network"] = {
                    **payload["network"],
                    **_network_summary_from_mapping(result),
                }
            self._store.append(
                ContextEventDraft(
                    event_type="simulator.context.opened",
                    turn_id=turn_id,
                    capability="context.open",
                    payload=payload,
                )
            )

    def _append_observation(
        self,
        capability: str,
        result: Mapping[str, Any],
        event: Mapping[str, Any],
        *,
        start: Mapping[str, Any],
        turn_id: str,
        call_id: str | None,
        consume_dependencies: bool = True,
        trace_sequence: int | None = None,
    ) -> str:
        args = _start_args(start)
        observation_ref = _stable_ref("observation", capability, turn_id, call_id, args, _projection_summary(capability, result, event))
        consumed_refs = _consumed_refs(capability, args) if consume_dependencies else []
        result_path = self._tool_result_path(turn_id, call_id or observation_ref)
        _write_json_atomic(result_path, {"capability": capability, "ok": event.get("ok") is True, "result": result, "error": event.get("error"), "evidence_refs": event.get("evidence_refs", [])})
        self._store.append(
            ContextEventDraft(
                event_type="tool.observation.recorded",
                turn_id=turn_id,
                capability=capability,
                trace_sequence=trace_sequence,
                payload={
                    "observation_ref": observation_ref,
                    "path": _relative_path(result_path, self._verifier.workspace_root),
                    "summary": _projection_summary(capability, result, event),
                    "producer_observation": _producer_observation(capability, start, call_id),
                    "consumed_refs": consumed_refs,
                    "produced_refs": _produced_refs(capability, result, event),
                },
            )
        )
        return observation_ref

    def _tool_result_path(self, turn_id: str, call_id: str) -> Path:
        return (
            self._verifier.workspace_root
            / "tool-results"
            / turn_id
            / "compatibility"
            / f"{call_id}.json"
        )

    def _append_results(
        self,
        capability: str,
        result_artifacts: Iterable[VerifiedArtifact],
        event_evidence_refs: list[str],
        observation_ref: str,
        *,
        turn_id: str,
        start: Mapping[str, Any],
    ) -> None:
        for artifact in sorted(result_artifacts, key=lambda item: item.reference):
            # A result_ref identifies one immutable simulator artifact.  Later
            # reads of its evidence may rediscover it, but that is a reuse in a
            # different tool observation, not a conflicting new result.
            if artifact.reference in self._store.snapshot.results:
                continue
            document = artifact.document
            registered_capability = _registered_result_capability(capability, document)
            evidence_refs = _dedupe([*_string_items(document.get("evidence_refs")), *event_evidence_refs])
            self._store.append(
                ContextEventDraft(
                    event_type="result.registered",
                    turn_id=turn_id,
                    capability=registered_capability,
                    payload={
                        "result_ref": artifact.reference,
                        "revision_ref": str(document["revision_ref"]),
                        "path": _relative_path(artifact.path, self._verifier.workspace_root),
                        "evidence_refs": evidence_refs,
                        "solver_summary": _solver_summary(document),
                        "producer_observation": {
                            **_producer_observation(capability, start, _tool_call_id(start)),
                            "observation_ref": observation_ref,
                        },
                    },
                )
            )

    def _append_evidence(
        self,
        capability: str,
        evidence_artifacts: Iterable[VerifiedArtifact],
        *,
        turn_id: str,
    ) -> None:
        for artifact in sorted(evidence_artifacts, key=lambda item: item.reference):
            document = artifact.document
            refs = _evidence_record_refs(document)
            self._store.append(
                ContextEventDraft(
                    event_type="evidence.registered",
                    payload={
                        "evidence_ref": artifact.reference,
                        "path": _relative_path(artifact.path, self._verifier.workspace_root),
                        "kind": "simulator",
                        "refs": refs,
                        "summary": {
                            "provenance": "gridctl",
                            "evidence_type": document.get("evidence_type"),
                            "capability_id": document.get("capability_id"),
                        },
                    },
                )
            )

    def _append_facts(
        self,
        capability: str,
        result: Mapping[str, Any],
        result_artifacts: tuple[VerifiedArtifact, ...],
        evidence_artifacts: tuple[VerifiedArtifact, ...],
        ranking_source_artifact: VerifiedArtifact | None,
        observation_ref: str,
        *,
        turn_id: str,
        start: Mapping[str, Any],
        evidence_refs: list[str],
    ) -> None:
        if capability not in PROMOTED_FACT_FIELDS:
            return
        facts = _promoted_fact_payloads(
            capability,
            result,
            result_artifacts,
            evidence_artifacts,
            ranking_source_artifact,
            self._store.snapshot.results,
            observation_ref,
            turn_id=turn_id,
            start=start,
            evidence_refs=evidence_refs,
        )
        for fact in facts:
            self._store.append(
                ContextEventDraft(
                    event_type="fact.verified",
                    turn_id=turn_id,
                    capability=capability,
                    payload={
                        "fact_ref": _stable_ref("fact", fact),
                        "statement": _canonical_json(fact),
                        "evidence_refs": fact["evidence_refs"],
                        "authored_by": "gridctl",
                    },
                )
            )

    def _verified_ranking_source(self, start: Mapping[str, Any]) -> VerifiedArtifact:
        result_ref = _start_args(start).get("result_ref")
        if not isinstance(result_ref, str):
            raise SimulatorIntegrityError("result.branches.rank requires started result_ref")
        if result_ref not in self._store.snapshot.results:
            raise SimulatorIntegrityError(f"result.branches.rank references unregistered result: {result_ref}")
        return self._verifier.verify_result(result_ref)

    def _verify_result_consumers(
        self,
        capability: str,
        start: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        args = _start_args(start)
        requested = [
            value
            for key in ("result_ref", "base_result_ref", "candidate_result_ref")
            if isinstance((value := args.get(key)), str)
        ]
        if not requested:
            raise SimulatorIntegrityError(f"{capability} requires a source result reference")
        artifacts: dict[str, VerifiedArtifact] = {}
        for result_ref in requested:
            if result_ref not in self._store.snapshot.results:
                raise SimulatorIntegrityError(f"{capability} references unregistered result: {result_ref}")
            artifacts[result_ref] = self._verifier.verify_result(result_ref)
        single_ref = args.get("result_ref")
        if isinstance(single_ref, str):
            returned_ref = result.get("result_ref")
            if isinstance(returned_ref, str) and returned_ref != single_ref:
                raise SimulatorIntegrityError(
                    f"{capability} returned result_ref {returned_ref} for requested {single_ref}"
                )
            source = artifacts[single_ref].document
            for field in ("context_ref", "revision_ref"):
                returned = result.get(field)
                if isinstance(returned, str) and returned != source.get(field):
                    raise SimulatorIntegrityError(f"{capability} returned mismatched {field}")
        for prefix in ("base", "candidate"):
            result_ref = args.get(f"{prefix}_result_ref")
            returned_context = result.get(f"{prefix}_context_ref")
            if isinstance(result_ref, str) and isinstance(returned_context, str):
                if artifacts[result_ref].document.get("context_ref") != returned_context:
                    raise SimulatorIntegrityError(f"{capability} returned mismatched {prefix}_context_ref")

    def _assert_result_matches_started_inputs(
        self,
        capability: str,
        result: Mapping[str, Any],
        start: Mapping[str, Any],
    ) -> None:
        args = _start_args(start)
        started_tool_name = _tool_name(start)
        if started_tool_name is not None:
            expected_capability = _TOOL_NAME_TO_CAPABILITY.get(started_tool_name)
            if expected_capability is not None and expected_capability != capability:
                raise SimulatorIntegrityError(
                    f"tool call {started_tool_name} returned {capability}, expected {expected_capability}"
                )
        requested_context_ref = args.get("context_ref")
        returned_context_ref = result.get("context_ref")
        if (
            isinstance(requested_context_ref, str)
            and isinstance(returned_context_ref, str)
            and requested_context_ref != returned_context_ref
        ):
            parent_context_ref = result.get("parent_context_ref")
            creates_child = capability in {"model.revision.derive", "model.equivalent.derive"}
            if not creates_child or parent_context_ref != requested_context_ref:
                raise SimulatorIntegrityError(
                    f"{capability} returned context_ref {returned_context_ref} for requested {requested_context_ref}"
                )
        requested_result_ref = args.get("result_ref")
        returned_result_ref = result.get("source_result_ref")
        if (
            capability == "result.branches.rank"
            and isinstance(requested_result_ref, str)
            and isinstance(returned_result_ref, str)
            and requested_result_ref != returned_result_ref
        ):
            raise SimulatorIntegrityError(
                f"{capability} returned source_result_ref {returned_result_ref} for requested {requested_result_ref}"
            )


def _baseline_payload(artifact: VerifiedArtifact, workspace_root: Path) -> dict[str, Any]:
    document = artifact.document
    revision_ref = document.get("revision_ref")
    if not isinstance(revision_ref, str):
        raise SimulatorIntegrityError(f"context document is missing revision_ref: {artifact.reference}")
    return {
        "context_ref": artifact.reference,
        "revision_ref": revision_ref,
        "path": _relative_path(artifact.path, workspace_root),
        "source": {
            "capability": "context.open",
            "grid_capability_protocol": "1.0",
            "pandapower_version": str(document.get("pandapower_version", "3.4.0")),
        },
        "network": _network_summary_from_mapping(document),
    }


def _network_summary_from_mapping(document: Mapping[str, Any]) -> dict[str, Any]:
    counts = document.get("counts")
    if not isinstance(counts, Mapping):
        counts = {}
    return {
        "name": str(document.get("model_id") or document.get("model") or "unknown"),
        "bus_count": _int_value(counts.get("bus"), default=0),
        "line_count": _int_value(counts.get("line"), default=0),
        "trafo_count": _int_value(counts.get("trafo"), default=0),
    }


def _projection_summary(capability: str, result: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "ok": event.get("ok") is True,
    }
    for key in ("context_ref", "revision_ref", "result_ref", "evidence_ref", "status", "converged", "total_active_loss"):
        value = result.get(key)
        if _is_scalar(value):
            summary[key] = value
    if capability == "result.branches.rank":
        branches = result.get("branches")
        if isinstance(branches, list):
            summary["branch_count"] = len(branches)
    if capability == "analysis.contingency.n_minus_one.run":
        scenarios = result.get("scenarios")
        if isinstance(scenarios, list):
            summary["scenario_count"] = len(scenarios)
    error = event.get("error")
    if isinstance(error, Mapping):
        summary["error_code"] = error.get("code")
    return summary


def _solver_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    existing = document.get("solver_summary")
    if isinstance(existing, Mapping):
        return dict(existing)
    summary: dict[str, Any] = {}
    for key in ("result_type", "status", "converged", "total_active_loss"):
        value = document.get(key)
        if _is_scalar(value):
            summary[key] = value
    scenarios = document.get("scenarios")
    if isinstance(scenarios, list):
        summary["scenario_count"] = len(scenarios)
    return summary


def _registered_result_capability(parent_capability: str, document: Mapping[str, Any]) -> str:
    """Give linked child results their own semantic producer identity."""
    if parent_capability != "analysis.contingency.n_minus_one.run":
        return parent_capability
    result_type = document.get("result_type")
    operation = document.get("operation")
    if result_type == "analysis.contingency.n_minus_one.scenario" or operation == "contingency.n_minus_one.scenario":
        return "analysis.contingency.n_minus_one.scenario"
    return parent_capability


def _promoted_fact_payloads(
    capability: str,
    result: Mapping[str, Any],
    result_artifacts: tuple[VerifiedArtifact, ...],
    evidence_artifacts: tuple[VerifiedArtifact, ...],
    ranking_source_artifact: VerifiedArtifact | None,
    registered_results: Mapping[str, ResultRecord],
    observation_ref: str,
    *,
    turn_id: str,
    start: Mapping[str, Any],
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    source = _fact_source(
        capability,
        result,
        result_artifacts,
        ranking_source_artifact,
        registered_results,
        evidence_refs,
        start,
    )
    if not source["evidence_refs"]:
        return []
    common = {
        "context_ref": source.get("context_ref"),
        "revision_ref": source.get("revision_ref"),
        "turn_id": turn_id,
        "source_observation_id": observation_ref,
        "producer_observation": _producer_observation(capability, start, _tool_call_id(start)),
        "source_ref": source.get("source_ref"),
        "evidence_refs": source["evidence_refs"],
    }
    facts: list[dict[str, Any]] = []
    if capability == "topology.branch.endpoints.get":
        evidence_facts = _verified_evidence_facts(capability, evidence_artifacts)
        branch_ref = _first_string(
            evidence_facts.get("branch_ref"),
            result.get("branch_ref"),
            _nested(result, "branch", "branch_ref"),
        )
        for field, predicate in (("from_bus", "topology.branch.from_bus"), ("to_bus", "topology.branch.to_bus")):
            value = _verified_evidence_value(capability, evidence_facts, result, field)
            if value is not None:
                facts.append({**common, "predicate": predicate, "branch_ref": branch_ref, "value": value})
    elif capability == "analysis.powerflow.ac.run":
        document = _single_result_document(capability, result_artifacts)
        for field, predicate in (
            ("converged", "powerflow.converged"),
            ("total_active_loss", "powerflow.total_active_loss"),
        ):
            value = _verified_result_value(capability, document, result, field)
            if value is not None:
                fact = {**common, "predicate": predicate, "value": value}
                if field == "total_active_loss":
                    fact["unit"] = str(result.get("total_active_loss_unit", "MW"))
                facts.append(fact)
    elif capability == "result.branches.rank":
        branches = result.get("branches")
        metric = _start_args(start).get("metric")
        if isinstance(branches, list):
            for index, branch in enumerate(branches, start=1):
                if not isinstance(branch, Mapping):
                    continue
                branch_metric = branch.get("metric") if isinstance(branch.get("metric"), str) else metric
                value = branch.get("value")
                if isinstance(branch_metric, str) and _is_scalar(value):
                    facts.append(
                        {
                            **common,
                            "predicate": f"branch.{branch_metric}",
                            "branch_ref": branch.get("branch_ref"),
                            "rank": index,
                            "value": value,
                            "unit": branch.get("unit"),
                        }
                    )
    elif capability == "analysis.contingency.n_minus_one.run":
        document = _single_result_document(capability, result_artifacts)
        scenarios = document.get("scenarios")
        scenario_count = len(scenarios) if isinstance(scenarios, list) else 0
        max_loading = _max_scenario_loading(scenarios)
        violation_count = _violation_count(scenarios)
        for predicate, value in (
            ("n1.status", _verified_result_value(capability, document, result, "status")),
            ("n1.scenario_count", scenario_count),
            ("n1.max_loading_percent", max_loading),
            ("n1.violation_count", violation_count),
        ):
            if value is not None:
                fact = {**common, "predicate": predicate, "value": value}
                if predicate == "n1.max_loading_percent":
                    fact["unit"] = "%"
                facts.append(fact)
    return facts


def _fact_source(
    capability: str,
    result: Mapping[str, Any],
    result_artifacts: tuple[VerifiedArtifact, ...],
    ranking_source_artifact: VerifiedArtifact | None,
    registered_results: Mapping[str, ResultRecord],
    evidence_refs: list[str],
    start: Mapping[str, Any],
) -> dict[str, Any]:
    if capability == "result.branches.rank":
        consumed_result_ref = _start_args(start).get("result_ref")
        if isinstance(consumed_result_ref, str) and consumed_result_ref in registered_results:
            registered = registered_results[consumed_result_ref]
            document = ranking_source_artifact.document if ranking_source_artifact is not None else {}
            return {
                "context_ref": document.get("context_ref"),
                "revision_ref": document.get("revision_ref") or registered.revision_ref,
                "source_ref": consumed_result_ref,
                "evidence_refs": registered.evidence_refs,
            }
        return {"source_ref": consumed_result_ref, "evidence_refs": []}

    artifact = result_artifacts[0] if result_artifacts else None
    document = artifact.document if artifact is not None else result
    source_ref = artifact.reference if artifact is not None else result.get("evidence_ref")
    return {
        "context_ref": document.get("context_ref") or result.get("context_ref"),
        "revision_ref": document.get("revision_ref") or result.get("revision_ref"),
        "source_ref": source_ref,
        "evidence_refs": evidence_refs,
    }


def _single_result_document(capability: str, result_artifacts: tuple[VerifiedArtifact, ...]) -> Mapping[str, Any]:
    if not result_artifacts:
        raise SimulatorIntegrityError(f"{capability} has no verified result artifact for fact projection")
    return result_artifacts[0].document


def _verified_result_value(
    capability: str,
    document: Mapping[str, Any],
    inline_result: Mapping[str, Any],
    field: str,
) -> object:
    if field not in document:
        return None
    verified = document[field]
    inline = inline_result.get(field)
    if _is_scalar(inline) and inline != verified:
        raise SimulatorIntegrityError(f"{capability} inline {field} does not match verified result artifact")
    return verified


def _verified_evidence_facts(
    capability: str,
    evidence_artifacts: tuple[VerifiedArtifact, ...],
) -> Mapping[str, Any]:
    for artifact in evidence_artifacts:
        if artifact.document.get("capability_id") != capability:
            continue
        facts = artifact.document.get("facts")
        if isinstance(facts, Mapping):
            return facts
    raise SimulatorIntegrityError(f"{capability} has no verified evidence facts for fact projection")


def _verified_evidence_value(
    capability: str,
    evidence_facts: Mapping[str, Any],
    inline_result: Mapping[str, Any],
    field: str,
) -> object:
    if field not in evidence_facts:
        return None
    verified = evidence_facts[field]
    inline = inline_result.get(field)
    if _is_scalar(inline) and inline != verified:
        raise SimulatorIntegrityError(f"{capability} inline {field} does not match verified evidence artifact")
    return verified


def _event_evidence_refs(event: Mapping[str, Any], result: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    refs.extend(_string_items(event.get("evidence_refs")))
    evidence_ref = result.get("evidence_ref")
    if isinstance(evidence_ref, str):
        refs.append(evidence_ref)
    refs.extend(_string_items(result.get("evidence_refs")))
    return _dedupe(refs)


def _evidence_record_refs(document: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    result_ref = document.get("result_ref")
    if isinstance(result_ref, str):
        refs.append(result_ref)
    context_ref = document.get("context_ref")
    if isinstance(context_ref, str):
        refs.append(context_ref)
    return _dedupe(refs)


def _consumed_refs(capability: str, args: Mapping[str, Any]) -> list[str]:
    if capability == "context.open":
        return []
    refs: list[str] = []
    for key in ("context_ref", "result_ref", "base_result_ref", "candidate_result_ref", "evidence_ref"):
        value = args.get(key)
        if isinstance(value, str):
            refs.append(value)
    refs.extend(_string_items(args.get("result_refs")))
    refs.extend(_string_items(args.get("evidence_refs")))
    return _dedupe(refs)


def _produced_refs(capability: str, result: Mapping[str, Any], event: Mapping[str, Any]) -> list[str]:
    if capability.startswith("result."):
        return []
    refs: list[str] = []
    context_ref = result.get("context_ref")
    if capability in {
        "context.open",
        "model.create",
        "model.revision.derive",
        "model.equivalent.derive",
    } and isinstance(context_ref, str):
        refs.append(context_ref)
    result_ref = result.get("result_ref")
    if isinstance(result_ref, str):
        refs.append(result_ref)
    refs.extend(_string_items(result.get("result_refs")))
    refs.extend(_event_evidence_refs(event, result))
    return _dedupe(refs)


def _producer_observation(capability: str, start: Mapping[str, Any], call_id: str | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "capability": capability,
            "tool_call_id": call_id,
            "tool_name": _tool_name(start),
            "args": _start_args(start),
            "grid_capability_protocol": "1.0",
            "pandapower_version": "3.4.0",
        }.items()
        if value is not None
    }


def _tool_call_id(event: Mapping[str, Any]) -> str | None:
    for key in ("tool_call_id", "toolCallId", "id"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return None


def _tool_name(event: Mapping[str, Any]) -> str | None:
    for key in ("tool_name", "toolName"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return None


def _start_args(start: Mapping[str, Any]) -> Mapping[str, Any]:
    args = start.get("args")
    return args if isinstance(args, Mapping) else {}


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _stable_ref(kind: str, *parts: object) -> str:
    digest = sha256(_canonical_json(parts).encode("utf-8")).hexdigest()
    return f"{kind}:sha256:{digest}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = _canonical_json(payload).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _dedupe(refs: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            deduped.append(ref)
    return deduped


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _int_value(value: object, *, default: int) -> int:
    return value if isinstance(value, int) else default


def _nested(mapping: Mapping[str, Any], outer: str, inner: str) -> object:
    nested = mapping.get(outer)
    if isinstance(nested, Mapping):
        return nested.get(inner)
    return None


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str):
            return value
    return None


def _first_present(keyed_result: Mapping[str, Any], key: str, result_artifacts: tuple[VerifiedArtifact, ...]) -> object:
    value = keyed_result.get(key)
    if value is not None:
        return value
    for artifact in result_artifacts:
        value = artifact.document.get(key)
        if value is not None:
            return value
    return None


def _max_scenario_loading(scenarios: object) -> float | int | None:
    if not isinstance(scenarios, list):
        return None
    values: list[float | int] = []
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            continue
        value = scenario.get("max_loading_percent")
        if isinstance(value, int | float):
            values.append(value)
    return max(values) if values else None


def _violation_count(scenarios: object) -> int | None:
    if not isinstance(scenarios, list):
        return None
    count = 0
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            continue
        violations = scenario.get("violations")
        if isinstance(violations, list):
            count += len(violations)
    return count
