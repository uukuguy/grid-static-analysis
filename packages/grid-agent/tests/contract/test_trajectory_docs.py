from pathlib import Path


def test_trajectory_docs_publish_fail_closed_contract() -> None:
    root = Path(__file__).resolve().parents[4]
    text = (root / "docs/architecture/trajectory-events.md").read_text(encoding="utf-8")

    for phrase in ("grid-run-event/1.0", "run-events.jsonl", "unknown required event", "last valid sequence"):
        assert phrase in text
