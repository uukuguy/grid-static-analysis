from __future__ import annotations

import math
from typing import Any

import pandapower as pp
from pandapower.protection.run_protection import calculate_protection_times
from pandapower.shortcircuit import calc_sc

from grid_simulator.bindings.base import (
    AnalysisOperation,
    AnalysisOutcome,
    AnalysisPrerequisiteError,
    closed_schema,
    enum,
)


SCHEMA = closed_schema(
    {
        "scenario": enum("pp", "sc"),
        "fault": enum("3ph", "2ph", "1ph"),
        "case": enum("max", "min"),
    }
)


def run(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    if "protection" not in net or not len(net.protection):
        raise AnalysisPrerequisiteError(
            "the model has no protection devices",
            required_dataset="network.protection",
            recovery="create a supported protection device in an immutable model revision",
        )
    scenario = str(options.get("scenario", "pp"))
    if scenario == "pp":
        pp.runpp(net)
    else:
        calc_sc(
            net,
            fault=str(options.get("fault", "3ph")),
            case=str(options.get("case", "max")),
            branch_results=True,
            return_all_currents=True,
        )
    results = calculate_protection_times(net, scenario=scenario).copy()
    for column in results.columns:
        results[column] = results[column].map(
            lambda value: None if isinstance(value, float) and not math.isfinite(value) else value
        )
    net["res_protection"] = results
    tripped = int(results["trip_melt"].fillna(False).astype(bool).sum()) if "trip_melt" in results else 0
    return AnalysisOutcome(
        "protection.static",
        "succeeded",
        {"scenario": scenario, **{key: value for key, value in options.items() if key != "scenario"}},
        {"device_count": len(results), "tripped_device_count": tripped, "scenario": scenario},
    )


OPERATIONS = (
    AnalysisOperation(
        "protection.static",
        "Static protection evaluation",
        "protection.calculate_protection_times",
        SCHEMA,
        run,
    ),
)
