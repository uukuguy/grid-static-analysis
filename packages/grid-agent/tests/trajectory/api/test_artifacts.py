from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from grid_agent.trajectory.api.artifacts import ArtifactAccessError, ArtifactGateway
from grid_agent.trajectory.projection_models import ArtifactIndex, ArtifactIndexRecord


def artifact_fixture(tmp_path: Path) -> tuple[Path, ArtifactIndex, str]:
    run_root = tmp_path / "runs" / "analysis-test"
    path = run_root / "evidence" / "network-facts" / "network-fact.json"
    value = b'{"fact":"verified"}\n'
    path.parent.mkdir(parents=True)
    path.write_bytes(value)
    reference = "evidence:sha256:" + sha256(value).hexdigest()
    record = ArtifactIndexRecord(
        id=f"artifact:analysis-test:{reference}",
        source_sequences=(1,),
        reference=reference,
        kind="evidence",
        relative_path="evidence/network-facts/network-fact.json",
        sha256=sha256(value).hexdigest(),
        verification_status="verified",
    )
    return run_root, ArtifactIndex(analysis_id="analysis-test", records={reference: record}), reference


def test_gateway_opens_only_verified_indexed_artifact(tmp_path: Path) -> None:
    run_root, index, evidence_ref = artifact_fixture(tmp_path)

    response = ArtifactGateway(run_root, index).open(evidence_ref)

    assert response.media_type == "application/json; charset=utf-8"
    assert response.filename == "network-fact.json"
    assert response.sha256 == index.records[evidence_ref].sha256
    assert response.size_bytes == len(response.content)
    assert response.content.startswith(b"{")


def test_gateway_returns_the_verified_bytes_after_the_file_changes(tmp_path: Path) -> None:
    run_root, index, evidence_ref = artifact_fixture(tmp_path)
    path = run_root / index.records[evidence_ref].relative_path

    response = ArtifactGateway(run_root, index).open(evidence_ref)
    path.write_bytes(b'{"fact":"swapped after verification"}\n')

    assert response.content == b'{"fact":"verified"}\n'
    assert response.size_bytes == len(response.content)


def test_gateway_reads_verified_bytes_from_a_nofollow_file_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root, index, evidence_ref = artifact_fixture(tmp_path)

    def read_by_path_is_forbidden(_: Path) -> bytes:
        pytest.fail("artifact gateway must read from its verified file descriptor")

    monkeypatch.setattr(Path, "read_bytes", read_by_path_is_forbidden)

    response = ArtifactGateway(run_root, index).open(evidence_ref)

    assert response.content == b'{"fact":"verified"}\n'


@pytest.mark.parametrize(
    "reference",
    [
        "../manifest.json",
        "/etc/passwd",
        "pi/session.jsonl",
        "pi%2fsession.jsonl",
        "pi%5csession.jsonl",
        "evidence:sha256:" + "f" * 64,
    ],
)
def test_gateway_rejects_unregistered_reference(tmp_path: Path, reference: str) -> None:
    run_root, index, _ = artifact_fixture(tmp_path)

    with pytest.raises(ArtifactAccessError, match="not registered|invalid artifact reference"):
        ArtifactGateway(run_root, index).open(reference)


def test_gateway_rejects_symlink_swap_after_projection(tmp_path: Path) -> None:
    run_root, index, evidence_ref = artifact_fixture(tmp_path)
    path = run_root / index.records[evidence_ref].relative_path
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    path.unlink()
    path.symlink_to(outside)

    with pytest.raises(ArtifactAccessError, match="safe run path"):
        ArtifactGateway(run_root, index).open(evidence_ref)


def test_gateway_rejects_indexed_path_that_escapes_run_root(tmp_path: Path) -> None:
    run_root, index, evidence_ref = artifact_fixture(tmp_path)
    record = index.records[evidence_ref].model_copy(update={"relative_path": "../outside.json"})
    unsafe_index = index.model_copy(update={"records": {evidence_ref: record}})

    with pytest.raises(ArtifactAccessError, match="safe run path"):
        ArtifactGateway(run_root, unsafe_index).open(evidence_ref)


def test_gateway_rejects_post_projection_content_change(tmp_path: Path) -> None:
    run_root, index, evidence_ref = artifact_fixture(tmp_path)
    path = run_root / index.records[evidence_ref].relative_path
    path.write_bytes(b'{"fact":"changed"}\n')

    with pytest.raises(ArtifactAccessError, match="integrity mismatch"):
        ArtifactGateway(run_root, index).open(evidence_ref)
