from __future__ import annotations

from typing import Any

import pandapower as pp

from grid_simulator.bindings.base import (
    AnalysisOperation,
    AnalysisOutcome,
    bool_or_auto,
    closed_schema,
    effective,
    enum,
    int_or_auto,
    nullable,
    number,
    recycle_schema,
)


AC_DEFAULTS = {
    "algorithm": "nr",
    "calculate_voltage_angles": True,
    "init": "auto",
    "max_iteration": "auto",
    "tolerance_mva": 1e-8,
    "trafo_model": "t",
    "trafo_loading": "current",
    "enforce_p_lims": False,
    "enforce_q_lims": False,
    "check_connectivity": True,
    "voltage_depend_loads": True,
    "consider_line_temperature": False,
    "run_control": False,
    "distributed_slack": False,
    "tdpf": False,
    "tdpf_delay_s": None,
}
AC_SCHEMA = closed_schema(
    {
        "algorithm": enum("nr", "iwamoto_nr", "bfsw", "gs", "fdbx", "fdxb"),
        "calculate_voltage_angles": bool_or_auto(),
        "init": enum("auto", "flat", "dc", "results"),
        "max_iteration": int_or_auto(),
        "tolerance_mva": number(exclusive_minimum=0),
        "trafo_model": enum("t", "pi"),
        "trafo_loading": enum("current", "power"),
        "enforce_p_lims": {"type": "boolean"},
        "enforce_q_lims": {"type": "boolean"},
        "check_connectivity": {"type": "boolean"},
        "voltage_depend_loads": {"type": "boolean"},
        "consider_line_temperature": {"type": "boolean"},
        "run_control": {"type": "boolean"},
        "distributed_slack": {"type": "boolean"},
        "tdpf": {"type": "boolean"},
        "tdpf_delay_s": nullable(number(minimum=0)),
    }
)

DC_DEFAULTS = {
    "trafo_model": "t",
    "trafo_loading": "current",
    "recycle": None,
    "check_connectivity": True,
    "switch_rx_ratio": 2.0,
    "trafo3w_losses": "hv",
}
DC_SCHEMA = closed_schema(
    {
        "trafo_model": enum("t", "pi"),
        "trafo_loading": enum("current", "power"),
        "recycle": recycle_schema(),
        "check_connectivity": {"type": "boolean"},
        "switch_rx_ratio": number(exclusive_minimum=0),
        "trafo3w_losses": enum("hv", "mv", "lv", "star"),
    }
)

THREE_PHASE_DEFAULTS = {
    "calculate_voltage_angles": True,
    "init": "auto",
    "max_iteration": "auto",
    "tolerance_mva": 1e-8,
    "trafo_model": "t",
    "trafo_loading": "current",
    "enforce_q_lims": False,
    "numba": True,
    "recycle": None,
    "check_connectivity": True,
    "switch_rx_ratio": 2.0,
    "v_debug": False,
}
THREE_PHASE_SCHEMA = closed_schema(
    {
        "algorithm": {"const": "nr"},
        "calculate_voltage_angles": bool_or_auto(),
        "init": enum("auto", "flat", "dc", "results"),
        "max_iteration": int_or_auto(),
        "tolerance_mva": number(exclusive_minimum=0),
        "trafo_model": {"const": "t"},
        "trafo_loading": enum("current", "power"),
        "enforce_q_lims": {"type": "boolean"},
        "numba": {"type": "boolean"},
        "recycle": recycle_schema(),
        "check_connectivity": {"type": "boolean"},
        "switch_rx_ratio": number(exclusive_minimum=0),
        "v_debug": {"type": "boolean"},
    }
)


def run_ac(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    selected = effective(AC_DEFAULTS, options)
    engine.run_ac(net, selected)
    return AnalysisOutcome("powerflow.ac", "succeeded", selected, {"converged": bool(net.converged)})


def run_dc(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    selected = effective(DC_DEFAULTS, options)
    pp.rundcpp(net, **selected)
    return AnalysisOutcome("powerflow.dc", "succeeded", selected, {"converged": bool(net.converged)})


def run_three_phase(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    selected = effective(THREE_PHASE_DEFAULTS, options)
    algorithm = selected.pop("algorithm", None)
    pp.runpp_3ph(net, **selected)
    if algorithm is not None:
        selected = {"algorithm": algorithm, **selected}
    return AnalysisOutcome(
        "powerflow.three_phase", "succeeded", selected, {"converged": bool(net.converged)}
    )


OPERATIONS = (
    AnalysisOperation("powerflow.ac", "AC power flow", "runpp", AC_SCHEMA, run_ac),
    AnalysisOperation("powerflow.dc", "DC power flow", "rundcpp", DC_SCHEMA, run_dc),
    AnalysisOperation(
        "powerflow.three_phase",
        "Unbalanced three-phase power flow",
        "runpp_3ph",
        THREE_PHASE_SCHEMA,
        run_three_phase,
    ),
)
