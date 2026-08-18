#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "configs" / "capabilities" / "pandapower-3.4.0-static-analysis.json"
REQUIRED_ROW_FIELDS = frozenset({"id", "package", "scope", "binding", "status", "evidence"})
SCOPES = frozenset({"in_scope", "excluded"})


class MatrixValidationError(ValueError):
    pass


class CapabilityMatrix(NamedTuple):
    schema_version: str
    engine: str
    engine_version: str
    release_threshold: float
    status_values: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


class CoverageScore(NamedTuple):
    total_in_scope: int
    published: int
    partial: int
    missing: int
    coverage_percent: float
    release_ready: bool
    per_package: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return self._asdict()


def load_matrix(path: Path) -> CapabilityMatrix:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixValidationError(f"matrix is unreadable: {exc}") from exc
    if not isinstance(document, dict):
        raise MatrixValidationError("matrix must be a JSON object")
    for field in ("schema_version", "engine", "engine_version", "release_threshold", "status_values", "rows"):
        if field not in document:
            raise MatrixValidationError(f"matrix missing {field}")
    statuses = document["status_values"]
    if not isinstance(statuses, list) or not statuses or not all(isinstance(item, str) for item in statuses):
        raise MatrixValidationError("status_values must be a non-empty string list")
    rows = document["rows"]
    if not isinstance(rows, list) or not rows:
        raise MatrixValidationError("rows must be a non-empty list")
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict) or set(raw) != REQUIRED_ROW_FIELDS:
            raise MatrixValidationError(f"row {index} fields must be {sorted(REQUIRED_ROW_FIELDS)}")
        if not all(isinstance(value, str) for value in raw.values()):
            raise MatrixValidationError(f"row {index} values must be strings")
        row = {field: raw[field].strip() for field in REQUIRED_ROW_FIELDS}
        if not row["id"]:
            raise MatrixValidationError(f"row {index} id is empty")
        if row["id"] in seen:
            raise MatrixValidationError(f"duplicate capability id: {row['id']}")
        seen.add(row["id"])
        if row["scope"] not in SCOPES:
            raise MatrixValidationError(f"row {row['id']} has unknown scope: {row['scope']}")
        if row["status"] not in statuses:
            raise MatrixValidationError(f"row {row['id']} has unknown status: {row['status']}")
        if row["scope"] == "excluded" and row["status"] != "excluded":
            raise MatrixValidationError(f"excluded row {row['id']} must have excluded status")
        if row["scope"] == "in_scope" and row["status"] == "excluded":
            raise MatrixValidationError(f"in-scope row {row['id']} cannot have excluded status")
        for field in ("package", "binding", "evidence"):
            if not row[field]:
                raise MatrixValidationError(f"row {row['id']} {field} is empty")
        normalized.append(row)
    threshold = float(document["release_threshold"])
    if not 0.0 < threshold <= 1.0:
        raise MatrixValidationError("release_threshold must be in (0, 1]")
    return CapabilityMatrix(
        schema_version=str(document["schema_version"]),
        engine=str(document["engine"]),
        engine_version=str(document["engine_version"]),
        release_threshold=threshold,
        status_values=tuple(statuses),
        rows=tuple(normalized),
    )


def score_matrix(matrix: CapabilityMatrix) -> CoverageScore:
    rows = [row for row in matrix.rows if row["scope"] == "in_scope"]
    if not rows:
        raise MatrixValidationError("matrix must contain at least one in-scope row")
    counts = {status: sum(row["status"] == status for row in rows) for status in matrix.status_values}
    published = counts.get("published", 0)
    coverage = 100.0 * published / len(rows)
    package_counts: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        package_counts[row["package"]].append(row["status"] == "published")
    per_package = {
        package: 100.0 * sum(values) / len(values)
        for package, values in sorted(package_counts.items())
    }
    return CoverageScore(
        total_in_scope=len(rows),
        published=published,
        partial=counts.get("partial", 0),
        missing=counts.get("missing", 0),
        coverage_percent=coverage,
        release_ready=coverage / 100.0 >= matrix.release_threshold,
        per_package=per_package,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and score the pandapower static-analysis capability matrix")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--json", action="store_true", help="print machine-readable score")
    parser.add_argument("--check", action="store_true", help="fail unless the release threshold is met")
    args = parser.parse_args()
    try:
        matrix = load_matrix(args.matrix)
        score = score_matrix(matrix)
    except MatrixValidationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    payload = {
        "ok": True,
        "engine": matrix.engine,
        "engine_version": matrix.engine_version,
        **score.as_dict(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"pandapower {matrix.engine_version} static-analysis coverage: "
            f"{score.published}/{score.total_in_scope} ({score.coverage_percent:.2f}%) "
            f"partial={score.partial} missing={score.missing} release_ready={score.release_ready}"
        )
    return 1 if args.check and not score.release_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
