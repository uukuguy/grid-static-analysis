from __future__ import annotations

import contextlib
import io
from typing import Any

import pandas as pd
import pandapower as pp
from pandapower.optimal_powerflow import OPFNotConverged

from grid_simulator.bindings.base import AnalysisOperation, AnalysisOutcome, closed_schema, effective, enum, number


AC_DEFAULTS = {
    "verbose": False,
    "calculate_voltage_angles": True,
    "check_connectivity": True,
    "suppress_warnings": True,
    "switch_rx_ratio": 2.0,
    "delta": 1e-10,
    "init": "flat",
    "numba": True,
    "trafo3w_losses": "hv",
    "consider_line_temperature": False,
}
AC_SCHEMA = closed_schema(
    {
        "verbose": {"type": "boolean"},
        "calculate_voltage_angles": {"type": "boolean"},
        "check_connectivity": {"type": "boolean"},
        "suppress_warnings": {"type": "boolean"},
        "switch_rx_ratio": number(exclusive_minimum=0),
        "delta": number(exclusive_minimum=0),
        "init": enum("flat", "pf", "results"),
        "numba": {"type": "boolean"},
        "trafo3w_losses": enum("hv", "mv", "lv", "star"),
        "consider_line_temperature": {"type": "boolean"},
    }
)

DC_DEFAULTS = {
    "verbose": False,
    "check_connectivity": True,
    "suppress_warnings": True,
    "switch_rx_ratio": 0.5,
    "delta": 1e-10,
    "trafo3w_losses": "hv",
}
DC_SCHEMA = closed_schema(
    {
        "verbose": {"type": "boolean"},
        "check_connectivity": {"type": "boolean"},
        "suppress_warnings": {"type": "boolean"},
        "switch_rx_ratio": number(exclusive_minimum=0),
        "delta": number(exclusive_minimum=0),
        "trafo3w_losses": enum("hv", "mv", "lv", "star"),
    }
)


def _run(net: Any, operation: str, options: dict[str, Any]) -> AnalysisOutcome:
    function = pp.runopp if operation == "opf.ac" else pp.rundcopp
    status = "succeeded"
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            function(net, **options)
        except OPFNotConverged:
            status = "non_converged"
    converged = bool(getattr(net, "OPF_converged", False))
    if status == "succeeded" and not converged:
        status = "non_converged"
    objective = getattr(net, "res_cost", None)
    if objective is not None:
        net["res_objective"] = pd.DataFrame([{"objective": float(objective)}])
    return AnalysisOutcome(operation, status, options, {"converged": converged, "objective": objective})


def run_ac(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    return _run(net, "opf.ac", effective(AC_DEFAULTS, options))


def run_dc(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    return _run(net, "opf.dc", effective(DC_DEFAULTS, options))


OPERATIONS = (
    AnalysisOperation("opf.ac", "AC optimal power flow", "runopp", AC_SCHEMA, run_ac),
    AnalysisOperation("opf.dc", "DC optimal power flow", "rundcopp", DC_SCHEMA, run_dc),
)
