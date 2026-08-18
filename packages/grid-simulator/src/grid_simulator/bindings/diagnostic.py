from __future__ import annotations

import contextlib
import io
import json
from typing import Any

import pandas as pd
import pandapower as pp

from grid_simulator.bindings.base import AnalysisOperation, AnalysisOutcome, closed_schema, effective, enum, number


DEFAULTS = {
    "report_style": None,
    "warnings_only": False,
    "return_result_dict": True,
    "overload_scaling_factor": 0.001,
    "lines_min_length_km": 0.0,
    "lines_min_z_ohm": 0.0,
    "nom_voltage_tolerance": 0.3,
}
SCHEMA = closed_schema(
    {
        "report_style": {"anyOf": [{"type": "null"}, enum("compact", "detailed")]},
        "warnings_only": {"type": "boolean"},
        "return_result_dict": {"const": True},
        "overload_scaling_factor": number(exclusive_minimum=0),
        "lines_min_length_km": number(minimum=0),
        "lines_min_z_ohm": number(minimum=0),
        "nom_voltage_tolerance": number(minimum=0),
    }
)


def _json_default(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def run(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    selected = effective(DEFAULTS, options)
    with contextlib.redirect_stdout(io.StringIO()):
        findings = pp.diagnostic(net, **selected)
    rows = []
    for check, details in sorted((findings or {}).items()):
        count = len(details) if isinstance(details, list) else int(bool(details))
        rows.append(
            {
                "check": str(check),
                "finding_count": count,
                "details_json": json.dumps(details, default=_json_default, sort_keys=True, separators=(",", ":")),
            }
        )
    net["res_diagnostic"] = pd.DataFrame(rows, columns=["check", "finding_count", "details_json"])
    return AnalysisOutcome(
        "diagnostic.run",
        "succeeded",
        selected,
        {"check_count": len(rows), "finding_count": sum(row["finding_count"] for row in rows)},
    )


OPERATIONS = (
    AnalysisOperation("diagnostic.run", "Network diagnostics", "diagnostic", SCHEMA, run),
)
