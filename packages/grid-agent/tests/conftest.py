import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def capability_documents() -> tuple[dict[str, object], ...]:
    definition_root = (
        ROOT / "packages/grid-simulator/src/grid_simulator/capabilities/definitions"
    )
    return tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(definition_root.glob("*.json"))
    )
