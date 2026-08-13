from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from grid_agent.application.workspace import RunWorkspace
from grid_agent.cli.app import _load_submitted_answer, _load_verified_answer_draft, _verify_evidence_refs
from grid_agent.simulator.client import GridctlClient
from grid_agent.simulator.locator import GridctlLocator


ROOT = Path(__file__).resolve().parents[4]


def _canonical_json(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _write_document(path: Path, document: object) -> str:
    payload = _canonical_json(document)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return f"evidence:sha256:{digest}"


def _write_evidence_document(path: Path, document: object) -> str:
    evidence_ref = _write_document(path, document)
    digest = evidence_ref.removeprefix("evidence:sha256:")
    path.rename(path.with_name(path.name.replace("placeholder", digest)))
    return evidence_ref


def _write_result_document(workspace: RunWorkspace, prefix: str, document: dict[str, object]) -> str:
    payload = _canonical_json(document)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    result_ref = f"result:sha256:{digest}"
    path = workspace.evidence_path / "results" / f"{prefix}-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json({"result_ref": result_ref, **document}), encoding="utf-8")
    return result_ref


def _write_answer_draft(
    workspace: RunWorkspace,
    *,
    answer_output: str = "answer",
    claim_evidence_refs: list[str],
    result_refs: list[str] | None = None,
) -> None:
    payload: dict[str, object] = {
        "answer_output": answer_output,
        "claim_evidence_refs": claim_evidence_refs,
    }
    if result_refs is not None:
        payload["result_refs"] = result_refs
    (workspace.root_path / "answer-draft.json").write_text(json.dumps(payload), encoding="utf-8")


def test_verify_evidence_refs_accepts_network_fact_and_analysis_documents(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
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

    network_ref = _write_document(workspace.evidence_path / "network-facts" / "network-fact-placeholder.json", network_fact)
    analysis_ref = _write_document(workspace.evidence_path / "analysis" / "analysis-evidence-placeholder.json", analysis_result)
    (workspace.evidence_path / "network-facts" / "network-fact-placeholder.json").rename(
        workspace.evidence_path / "network-facts" / f"network-fact-{network_ref.removeprefix('evidence:sha256:')}.json"
    )
    (workspace.evidence_path / "analysis" / "analysis-evidence-placeholder.json").rename(
        workspace.evidence_path / "analysis" / f"analysis-evidence-{analysis_ref.removeprefix('evidence:sha256:')}.json"
    )

    _verify_evidence_refs(workspace, (network_ref, analysis_ref))


def test_verify_evidence_refs_accepts_generated_ac_and_n1_evidence(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    client = GridctlClient(
        executable=GridctlLocator(ROOT).resolve(),
        workspace=workspace.root_path,
        timeout_seconds=60,
    )
    opened = client.invoke("context.open", {"model_id": "ieee39"})
    context_ref = str(opened["context_ref"])
    powerflow = client.invoke("analysis.powerflow.ac.run", {"context_ref": context_ref})
    element = client.invoke(
        "model.element.get",
        {
            "context_ref": context_ref,
            "kind": "line",
            "namespace": "pandapower_index",
            "identifier": "11",
        },
    )
    contingency = client.invoke(
        "analysis.contingency.n_minus_one.run",
        {
            "context_ref": context_ref,
            "branch_refs": [str(dict(element["element"])["asset_ref"])],
            "policy": "static-analysis-v1",
        },
    )

    _verify_evidence_refs(
        workspace,
        tuple(str(ref) for ref in powerflow["evidence_refs"])
        + tuple(str(ref) for ref in contingency["evidence_refs"]),
    )


@pytest.mark.parametrize(
    "directory,prefix",
    [
        ("results", "powerflow"),
        ("artifacts", "dataset-query"),
    ],
)
def test_verify_evidence_refs_rejects_result_and_artifact_documents(
    tmp_path: Path, directory: str, prefix: str
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    document = {"evidence_type": "analysis_result", "capability_id": "analysis.powerflow.ac.run"}
    evidence_ref = _write_document(workspace.evidence_path / directory / "placeholder.json", document)
    digest = evidence_ref.removeprefix("evidence:sha256:")
    (workspace.evidence_path / directory / "placeholder.json").rename(
        workspace.evidence_path / directory / f"{prefix}-{digest}.json"
    )

    with pytest.raises(RuntimeError, match="not in the current run"):
        _verify_evidence_refs(workspace, (evidence_ref,))


def test_verify_evidence_refs_rejects_tampered_allowed_document(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    document = {"evidence_type": "contingency_scenario", "capability_id": "analysis.contingency.n_minus_one.run"}
    evidence_ref = _write_document(workspace.evidence_path / "analysis" / "placeholder.json", document)
    digest = evidence_ref.removeprefix("evidence:sha256:")
    path = workspace.evidence_path / "analysis" / f"analysis-evidence-{digest}.json"
    (workspace.evidence_path / "analysis" / "placeholder.json").rename(path)
    path.write_text('{"evidence_type":"contingency_scenario","tampered":true}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="content does not match"):
        _verify_evidence_refs(workspace, (evidence_ref,))


def test_answer_draft_accepts_topology_evidence_without_result_refs(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    network_fact = {
        "evidence_type": "network_fact",
        "capability_id": "topology.branch.endpoints.get",
        "facts": {"from_bus_ref": "asset:bus:sha256:" + "1" * 64},
    }
    evidence_ref = _write_evidence_document(
        workspace.evidence_path / "network-facts" / "network-fact-placeholder.json",
        network_fact,
    )
    _write_answer_draft(workspace, claim_evidence_refs=[evidence_ref], result_refs=[])

    assert _load_verified_answer_draft(workspace) == "answer"


def test_answer_draft_requires_declared_result_refs_field(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    _write_answer_draft(workspace, claim_evidence_refs=[])

    with pytest.raises(RuntimeError, match="must include result_refs"):
        _load_verified_answer_draft(workspace)


def test_answer_draft_derives_and_verifies_result_ref_linked_by_analysis_evidence(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    result_ref = _write_result_document(
        workspace,
        "powerflow",
        {
            "result_type": "analysis.powerflow.ac",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "branch_results": [],
        },
    )
    evidence_ref = _write_evidence_document(
        workspace.evidence_path / "analysis" / "analysis-evidence-placeholder.json",
        {
            "evidence_type": "analysis_result",
            "capability_id": "analysis.powerflow.ac.run",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "result_ref": result_ref,
            "facts": {"converged": True},
        },
    )
    _write_answer_draft(workspace, claim_evidence_refs=[evidence_ref], result_refs=[])

    assert _load_verified_answer_draft(workspace) == "answer"


def test_answer_draft_accepts_result_ref_linked_to_current_run_analysis_evidence(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    result_ref = _write_result_document(
        workspace,
        "powerflow",
        {
            "result_type": "analysis.powerflow.ac",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "branch_results": [],
        },
    )
    evidence_ref = _write_evidence_document(
        workspace.evidence_path / "analysis" / "analysis-evidence-placeholder.json",
        {
            "evidence_type": "analysis_result",
            "capability_id": "analysis.powerflow.ac.run",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "result_ref": result_ref,
            "facts": {"converged": True},
        },
    )
    _write_answer_draft(workspace, claim_evidence_refs=[evidence_ref], result_refs=[result_ref])

    assert _load_verified_answer_draft(workspace) == "answer"


def test_answer_draft_accepts_declared_result_with_unclaimed_current_run_analysis_evidence(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    result_ref = _write_result_document(
        workspace,
        "contingency",
        {
            "result_type": "analysis.contingency.n_minus_one.aggregate",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "scenarios": [],
        },
    )
    _write_evidence_document(
        workspace.evidence_path / "analysis" / "analysis-evidence-placeholder.json",
        {
            "evidence_type": "contingency_scenario",
            "capability_id": "analysis.contingency.n_minus_one.run",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "result_ref": result_ref,
            "facts": {"status": "succeeded"},
        },
    )
    _write_answer_draft(workspace, claim_evidence_refs=[], result_refs=[result_ref])

    assert _load_verified_answer_draft(workspace) == "answer"


def test_answer_draft_accepts_contingency_aggregate_with_unclaimed_scenario_evidence(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    scenario_ref = _write_result_document(
        workspace,
        "contingency-scenario",
        {
            "result_type": "analysis.contingency.n_minus_one.scenario",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
        },
    )
    evidence_ref = _write_evidence_document(
        workspace.evidence_path / "analysis" / "analysis-evidence-placeholder.json",
        {
            "evidence_type": "contingency_scenario",
            "capability_id": "analysis.contingency.n_minus_one.run",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "result_ref": scenario_ref,
            "facts": {"status": "succeeded"},
        },
    )
    aggregate_ref = _write_result_document(
        workspace,
        "contingency",
        {
            "result_type": "analysis.contingency.n_minus_one.aggregate",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "evidence_refs": [evidence_ref],
            "scenarios": [{"scenario_result_ref": scenario_ref}],
        },
    )
    _write_answer_draft(workspace, claim_evidence_refs=[], result_refs=[aggregate_ref])

    assert _load_verified_answer_draft(workspace) == "answer"


def test_answer_draft_rejects_tampered_result_document(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    result_ref = _write_result_document(
        workspace,
        "powerflow",
        {
            "result_type": "analysis.powerflow.ac",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "branch_results": [],
        },
    )
    digest = result_ref.removeprefix("result:sha256:")
    (workspace.evidence_path / "results" / f"powerflow-{digest}.json").write_text(
        '{"result_ref":"' + result_ref + '","tampered":true}',
        encoding="utf-8",
    )
    _write_answer_draft(workspace, claim_evidence_refs=[], result_refs=[result_ref])

    with pytest.raises(RuntimeError, match="content does not match"):
        _load_verified_answer_draft(workspace)


def test_answer_draft_rejects_result_ref_not_linked_to_claimed_evidence(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    result_ref = _write_result_document(
        workspace,
        "powerflow",
        {
            "result_type": "analysis.powerflow.ac",
            "context_ref": "context:sha256:" + "1" * 64,
            "revision_ref": "revision:sha256:" + "2" * 64,
            "branch_results": [],
        },
    )
    _write_answer_draft(workspace, claim_evidence_refs=[], result_refs=[result_ref])

    with pytest.raises(RuntimeError, match="declared result_ref is not linked to claimed evidence"):
        _load_verified_answer_draft(workspace)


def test_submitted_topology_answer_keeps_answer_and_reports_non_result_references(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    network_fact = {
        "evidence_type": "network_fact",
        "capability_id": "topology.branch.endpoints.get",
        "facts": {"from_bus_ref": "asset:bus:sha256:" + "1" * 64},
    }
    evidence_ref = _write_evidence_document(
        workspace.evidence_path / "network-facts" / "network-fact-placeholder.json",
        network_fact,
    )
    _write_answer_draft(
        workspace,
        answer_output="线路 11 连接母线 6 与 11。",
        claim_evidence_refs=[evidence_ref],
        result_refs=["context:sha256:" + "2" * 64, "asset:line:sha256:" + "3" * 64],
    )

    submitted = _load_submitted_answer(workspace)

    assert submitted.answer_output == "线路 11 连接母线 6 与 11。"
    assert len(submitted.diagnostics) == 2
    assert all(diagnostic.severity == "warning" for diagnostic in submitted.diagnostics)
    audit = json.loads((workspace.root_path / "answer-audit.json").read_text(encoding="utf-8"))
    assert audit == {
        "diagnostics": [
            {
                "severity": diagnostic.severity,
                "finding": diagnostic.finding,
                "impact": diagnostic.impact,
                "remediation": diagnostic.remediation,
            }
            for diagnostic in submitted.diagnostics
        ]
    }


def test_submitted_answer_keeps_answer_when_claim_evidence_is_foreign(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", run_id="q")
    _write_answer_draft(
        workspace,
        answer_output="模型已提交的答案",
        claim_evidence_refs=["evidence:sha256:" + "f" * 64],
        result_refs=[],
    )

    submitted = _load_submitted_answer(workspace)

    assert submitted.answer_output == "模型已提交的答案"
    assert len(submitted.diagnostics) == 1
    assert submitted.diagnostics[0].severity == "error"
