from pathlib import Path

import pytest

from grid_agent.tools.guide import GuideIndex, GuideNotFound


ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = ROOT / "skills/grid-static-analysis"


def test_skill_has_guidance_for_every_advertised_capability(
    capability_documents: tuple[dict[str, object], ...],
) -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in SKILL_ROOT.rglob("*.md"))

    missing = [
        document["id"] for document in capability_documents if str(document["id"]) not in text
    ]

    assert missing == []


def test_agent_tests_read_capabilities_as_documents() -> None:
    tests_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "packages/grid-agent/tests").rglob("*.py"))
    )

    forbidden_import = "grid_simulator" + ".capabilities"
    assert forbidden_import not in tests_text
    assert "definitions" in tests_text


def test_skill_limits_evidence_get_to_topology_network_fact_documents() -> None:
    required_paths = (
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "references/result-query.md",
        SKILL_ROOT / "references/evidence-and-recovery.md",
    )
    texts = {
        path.relative_to(SKILL_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in required_paths
    }
    combined = "\n".join(texts.values()).lower()

    for resource_id, text in texts.items():
        lowered = text.lower()
        assert "evidence.get" in lowered, resource_id
        assert "topology" in lowered and "network_fact" in lowered, resource_id

    required_note = "`evidence.get` is topology/network-fact-only"
    assert required_note.lower() in combined
    assert (
        "ac, ranking, and n-1 results must cite returned `result_ref` and `evidence_refs`"
        in combined
    )

    forbidden_guidance = (
        "retrieve supporting evidence when the answer needs the evidence document",
        "retrieve supporting evidence with `evidence.get` when a final answer needs the evidence document",
        "show the evidence for this endpoint result",
        "evidence body",
        "analysis result body",
        "contingency body",
        "retrieve result body",
        "retrieve contingency body",
    )
    offenders = [phrase for phrase in forbidden_guidance if phrase in combined]
    assert offenders == []


def test_guide_index_opens_only_published_resources() -> None:
    guide = GuideIndex.load(SKILL_ROOT)

    assert "topology.branch.endpoints.get" in guide.open("topology-analysis").text

    with pytest.raises(GuideNotFound):
        guide.open("../../.env")

    with pytest.raises(GuideNotFound):
        guide.open("topology%2Fanalysis")
