from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from grid_agent.application.workspace import RunWorkspace
from grid_agent.cli.app import _verify_evidence_refs
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
