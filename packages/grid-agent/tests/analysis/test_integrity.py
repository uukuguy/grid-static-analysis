from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from grid_agent.analysis.integrity import ContentReferenceVerifier, SimulatorIntegrityError
from grid_agent.application.workspace import RunWorkspace
from grid_agent.simulator.client import GridctlClient
from grid_agent.simulator.locator import GridctlLocator


ROOT = Path(__file__).resolve().parents[4]
CONTEXT_REF = "context:sha256:" + "1" * 64
REVISION_REF = "revision:sha256:" + "2" * 64


def _canonical_json(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _write_document(path: Path, document: object) -> str:
    payload = _canonical_json(document)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return "evidence:sha256:" + digest


def _write_evidence_document(path: Path, document: object) -> str:
    evidence_ref = _write_document(path, document)
    digest = evidence_ref.removeprefix("evidence:sha256:")
    path.rename(path.with_name(path.name.replace("placeholder", digest)))
    return evidence_ref


def _write_result_document(workspace_root: Path, prefix: str, document: dict[str, object]) -> str:
    payload = _canonical_json(document)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    result_ref = "result:sha256:" + digest
    path = result_path(workspace_root, result_ref, prefix=prefix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json({"result_ref": result_ref, **document}), encoding="utf-8")
    return result_ref


def write_valid_result(
    workspace_root: Path,
    *,
    context_ref: str = CONTEXT_REF,
    revision_ref: str = REVISION_REF,
    prefix: str = "powerflow",
) -> str:
    return _write_result_document(
        workspace_root,
        prefix,
        {
            "result_type": "analysis.powerflow.ac",
            "context_ref": context_ref,
            "revision_ref": revision_ref,
            "branch_results": [],
        },
    )


def result_path(workspace_root: Path, result_ref: str, *, prefix: str = "powerflow") -> Path:
    digest = result_ref.removeprefix("result:sha256:")
    return workspace_root / "evidence" / "results" / f"{prefix}-{digest}.json"


def test_answer_audit_reports_bad_reference_without_raising(tmp_path: Path) -> None:
    verifier = ContentReferenceVerifier(tmp_path)

    diagnostics = verifier.audit_answer_references(
        claim_evidence_refs=("evidence:sha256:" + "a" * 64,),
        result_refs=("context:sha256:" + "b" * 64,),
    )

    assert {item.category for item in diagnostics} == {"missing_evidence", "misclassified_result_ref"}


def test_successful_gridctl_result_with_tampered_artifact_is_terminal(tmp_path: Path) -> None:
    result_ref = write_valid_result(tmp_path, context_ref=CONTEXT_REF, revision_ref=REVISION_REF)
    result_path(tmp_path, result_ref).write_text('{"tampered":true}', encoding="utf-8")
    verifier = ContentReferenceVerifier(tmp_path)

    with pytest.raises(SimulatorIntegrityError, match="digest"):
        verifier.admit_successful_tool_references(
            capability="analysis.powerflow.ac.run",
            result={"context_ref": CONTEXT_REF, "revision_ref": REVISION_REF, "result_ref": result_ref},
            evidence_refs=(),
        )


def test_verify_evidence_accepts_network_fact_and_analysis_documents(tmp_path: Path) -> None:
    network_fact = {
        "evidence_type": "network_fact",
        "capability_id": "topology.branch.endpoints.get",
        "facts": {"from_bus_ref": "asset:bus:sha256:" + "1" * 64},
    }
    analysis_result = {
        "evidence_type": "analysis_result",
        "capability_id": "analysis.powerflow.ac.run",
        "result_ref": "result:sha256:" + "2" * 64,
        "facts": {"converged": True},
    }
    model_constraints = {
        "evidence_type": "network_fact",
        "capability_id": "model.constraints.describe",
        "facts": {"constraints": [{"quantity": "bus.vm_pu", "lower": 0.94, "upper": 1.06}]},
    }
    network_ref = _write_evidence_document(
        tmp_path / "evidence" / "network-facts" / "network-fact-placeholder.json",
        network_fact,
    )
    analysis_ref = _write_evidence_document(
        tmp_path / "evidence" / "analysis" / "analysis-evidence-placeholder.json",
        analysis_result,
    )
    constraints_ref = _write_evidence_document(
        tmp_path / "evidence" / "network-facts" / "network-fact-placeholder.json",
        model_constraints,
    )

    verifier = ContentReferenceVerifier(tmp_path)
    assert verifier.verify_evidence(network_ref).document == network_fact
    assert verifier.verify_evidence(analysis_ref).document == analysis_result
    assert verifier.verify_evidence(constraints_ref).document == model_constraints


def test_verify_evidence_accepts_generated_ac_and_n1_evidence(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    client = GridctlClient(
        executable=GridctlLocator(ROOT).resolve(),
        workspace=workspace.root_path,
        timeout_seconds=60,
    )
    opened = client.invoke("context.open", {"model_id": "ieee39"})
    context_ref = opened.get("context_ref")
    assert isinstance(context_ref, str)
    powerflow = client.invoke("analysis.powerflow.ac.run", {"context_ref": context_ref})
    powerflow_evidence_refs = powerflow.get("evidence_refs")
    assert isinstance(powerflow_evidence_refs, list)
    element = client.invoke(
        "model.element.get",
        {
            "context_ref": context_ref,
            "kind": "line",
            "namespace": "pandapower_index",
            "identifier": "11",
        },
    )
    element_document = element.get("element")
    assert isinstance(element_document, Mapping)
    branch_ref = element_document.get("asset_ref")
    assert isinstance(branch_ref, str)
    contingency = client.invoke(
        "analysis.contingency.n_minus_one.run",
        {
            "context_ref": context_ref,
            "branch_refs": [branch_ref],
        },
    )
    contingency_evidence_refs = contingency.get("evidence_refs")
    assert isinstance(contingency_evidence_refs, list)

    verifier = ContentReferenceVerifier(workspace.root_path)
    for evidence_ref in tuple(str(ref) for ref in powerflow_evidence_refs) + tuple(
        str(ref) for ref in contingency_evidence_refs
    ):
        assert verifier.verify_evidence(evidence_ref).reference == evidence_ref


@pytest.mark.parametrize(
    "directory,prefix",
    [
        ("results", "powerflow"),
        ("artifacts", "dataset-query"),
    ],
)
def test_verify_evidence_rejects_result_and_artifact_documents(
    tmp_path: Path, directory: str, prefix: str
) -> None:
    document = {"evidence_type": "analysis_result", "capability_id": "analysis.powerflow.ac.run"}
    evidence_ref = _write_document(tmp_path / "evidence" / directory / "placeholder.json", document)
    digest = evidence_ref.removeprefix("evidence:sha256:")
    (tmp_path / "evidence" / directory / "placeholder.json").rename(
        tmp_path / "evidence" / directory / f"{prefix}-{digest}.json"
    )

    with pytest.raises(RuntimeError, match="not in the current run"):
        ContentReferenceVerifier(tmp_path).verify_evidence(evidence_ref)


def test_verify_evidence_rejects_tampered_allowed_document(tmp_path: Path) -> None:
    document = {"evidence_type": "contingency_scenario", "capability_id": "analysis.contingency.n_minus_one.run"}
    evidence_ref = _write_document(tmp_path / "evidence" / "analysis" / "placeholder.json", document)
    digest = evidence_ref.removeprefix("evidence:sha256:")
    path = tmp_path / "evidence" / "analysis" / f"analysis-evidence-{digest}.json"
    (tmp_path / "evidence" / "analysis" / "placeholder.json").rename(path)
    path.write_text('{"evidence_type":"contingency_scenario","tampered":true}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="content does not match"):
        ContentReferenceVerifier(tmp_path).verify_evidence(evidence_ref)


def test_answer_audit_accepts_topology_evidence_without_result_refs(tmp_path: Path) -> None:
    evidence_ref = _write_evidence_document(
        tmp_path / "evidence" / "network-facts" / "network-fact-placeholder.json",
        {
            "evidence_type": "network_fact",
            "capability_id": "topology.branch.endpoints.get",
            "facts": {"from_bus_ref": "asset:bus:sha256:" + "1" * 64},
        },
    )

    diagnostics = ContentReferenceVerifier(tmp_path).audit_answer_references((evidence_ref,), ())

    assert diagnostics == ()


def test_answer_audit_accepts_result_ref_linked_by_analysis_evidence(tmp_path: Path) -> None:
    result_ref = write_valid_result(tmp_path)
    evidence_ref = _write_evidence_document(
        tmp_path / "evidence" / "analysis" / "analysis-evidence-placeholder.json",
        {
            "evidence_type": "analysis_result",
            "capability_id": "analysis.powerflow.ac.run",
            "context_ref": CONTEXT_REF,
            "revision_ref": REVISION_REF,
            "result_ref": result_ref,
            "facts": {"converged": True},
        },
    )

    diagnostics = ContentReferenceVerifier(tmp_path).audit_answer_references((evidence_ref,), (result_ref,))

    assert diagnostics == ()


def test_answer_audit_accepts_declared_result_with_unclaimed_current_run_analysis_evidence(tmp_path: Path) -> None:
    result_ref = _write_result_document(
        tmp_path,
        "contingency",
        {
            "result_type": "analysis.contingency.n_minus_one.aggregate",
            "context_ref": CONTEXT_REF,
            "revision_ref": REVISION_REF,
            "scenarios": [],
        },
    )
    _write_evidence_document(
        tmp_path / "evidence" / "analysis" / "analysis-evidence-placeholder.json",
        {
            "evidence_type": "contingency_scenario",
            "capability_id": "analysis.contingency.n_minus_one.run",
            "context_ref": CONTEXT_REF,
            "revision_ref": REVISION_REF,
            "result_ref": result_ref,
            "facts": {"status": "succeeded"},
        },
    )

    diagnostics = ContentReferenceVerifier(tmp_path).audit_answer_references((), (result_ref,))

    assert diagnostics == ()


def test_answer_audit_accepts_contingency_aggregate_with_unclaimed_scenario_evidence(tmp_path: Path) -> None:
    scenario_ref = _write_result_document(
        tmp_path,
        "contingency-scenario",
        {
            "result_type": "analysis.contingency.n_minus_one.scenario",
            "context_ref": CONTEXT_REF,
            "revision_ref": REVISION_REF,
        },
    )
    evidence_ref = _write_evidence_document(
        tmp_path / "evidence" / "analysis" / "analysis-evidence-placeholder.json",
        {
            "evidence_type": "contingency_scenario",
            "capability_id": "analysis.contingency.n_minus_one.run",
            "context_ref": CONTEXT_REF,
            "revision_ref": REVISION_REF,
            "result_ref": scenario_ref,
            "facts": {"status": "succeeded"},
        },
    )
    aggregate_ref = _write_result_document(
        tmp_path,
        "contingency",
        {
            "result_type": "analysis.contingency.n_minus_one.aggregate",
            "context_ref": CONTEXT_REF,
            "revision_ref": REVISION_REF,
            "evidence_refs": [evidence_ref],
            "scenarios": [{"scenario_result_ref": scenario_ref}],
        },
    )

    diagnostics = ContentReferenceVerifier(tmp_path).audit_answer_references((), (aggregate_ref,))

    assert diagnostics == ()


def test_answer_audit_reports_tampered_result_without_raising(tmp_path: Path) -> None:
    result_ref = write_valid_result(tmp_path)
    result_path(tmp_path, result_ref).write_text(
        '{"result_ref":"' + result_ref + '","tampered":true}',
        encoding="utf-8",
    )

    diagnostics = ContentReferenceVerifier(tmp_path).audit_answer_references((), (result_ref,))

    assert {item.category for item in diagnostics} == {"invalid_result"}


def test_answer_audit_reports_unlinked_result_without_raising(tmp_path: Path) -> None:
    result_ref = write_valid_result(tmp_path)

    diagnostics = ContentReferenceVerifier(tmp_path).audit_answer_references((), (result_ref,))

    assert {item.category for item in diagnostics} == {"unlinked_result"}
