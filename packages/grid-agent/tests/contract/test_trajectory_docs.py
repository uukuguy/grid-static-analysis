from pathlib import Path


def test_trajectory_docs_publish_fail_closed_contract() -> None:
    root = Path(__file__).resolve().parents[4]
    text = (root / "docs/architecture/trajectory-events.md").read_text(encoding="utf-8")

    for phrase in ("grid-run-event/1.0", "run-events.jsonl", "unknown required event", "last valid sequence"):
        assert phrase in text


def test_trajectory_docs_describe_only_implemented_replay_rejections() -> None:
    root = Path(__file__).resolve().parents[4]
    text = (root / "docs/architecture/trajectory-events.md").read_text(encoding="utf-8")

    assert "impossible transition" not in text


def test_trajectory_docs_allow_unknown_context_revisions() -> None:
    root = Path(__file__).resolve().parents[4]
    text = (root / "docs/architecture/trajectory-events.md").read_text(encoding="utf-8")

    assert "null/unknown" in text
    assert "authoritative surrounding state" in text
