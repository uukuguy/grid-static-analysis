from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools" / "capability_matrix.py"
MATRIX_PATH = ROOT / "configs" / "capabilities" / "pandapower-3.4.0-static-analysis.json"


def _module():
    spec = importlib.util.spec_from_file_location("capability_matrix", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_matrix(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    path = tmp_path / "matrix.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "engine": "pandapower",
                "engine_version": "3.4.0",
                "release_threshold": 1.0,
                "status_values": ["published", "partial", "missing", "excluded"],
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    return path


def _row(identifier: str, *, scope: str = "in_scope", status: str = "published") -> dict[str, str]:
    return {
        "id": identifier,
        "package": "test-package",
        "scope": scope,
        "binding": "test.binding",
        "status": status,
        "evidence": "test evidence",
    }


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([_row("duplicate"), _row("duplicate")], "duplicate capability id"),
        ([_row("bad-status", status="unknown")], "unknown status"),
        ([_row("bad-exclusion", scope="excluded", status="published")], "excluded row"),
        ([_row("missing-evidence") | {"evidence": ""}], "evidence"),
    ],
)
def test_load_matrix_rejects_invalid_documents(tmp_path: Path, rows, message: str) -> None:
    matrix = _module()

    with pytest.raises(matrix.MatrixValidationError, match=message):
        matrix.load_matrix(_write_matrix(tmp_path, rows))


def test_score_reports_truthful_in_scope_coverage() -> None:
    matrix_module = _module()
    matrix = matrix_module.load_matrix(MATRIX_PATH)

    score = matrix_module.score_matrix(matrix)

    assert score.total_in_scope == 24
    assert score.published == 24
    assert score.partial == 0
    assert score.missing == 0
    assert score.coverage_percent == 100.0
    assert score.release_ready is True
    assert score.per_package["model-lifecycle"] == 100.0
    assert score.per_package["model-data"] == 100.0
    assert score.per_package["result-analysis"] == 100.0
    assert score.per_package["power-flow"] == 100.0
    assert score.per_package["opf"] == 100.0
    assert score.per_package["short-circuit"] == 100.0
    assert score.per_package["state-estimation"] == 100.0
    assert score.per_package["diagnostic"] == 100.0
    assert score.per_package["topology"] == 100.0
    assert score.per_package["contingency"] == 100.0
    assert score.per_package["policy-risk"] == 100.0
    assert score.per_package["protection"] == 100.0


def test_score_requires_all_in_scope_rows_for_release(tmp_path: Path) -> None:
    matrix_module = _module()
    matrix = matrix_module.load_matrix(
        _write_matrix(tmp_path, [_row("one"), _row("two"), _row("outside", scope="excluded", status="excluded")])
    )

    score = matrix_module.score_matrix(matrix)

    assert score.coverage_percent == 100.0
    assert score.release_ready is True
    assert score.total_in_scope == 2
