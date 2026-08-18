from __future__ import annotations

from typing import Any

from pandapower.shortcircuit import calc_sc

from grid_simulator.bindings.base import AnalysisOperation, AnalysisOutcome, closed_schema, effective, enum, number


DEFAULTS = {
    "bus": None,
    "fault": "3ph",
    "case": "max",
    "lv_tol_percent": 10,
    "topology": "auto",
    "ip": False,
    "ith": False,
    "tk_s": 1.0,
    "kappa_method": "C",
    "r_fault_ohm": 0.0,
    "x_fault_ohm": 0.0,
    "branch_results": False,
    "check_connectivity": True,
    "return_all_currents": False,
    "inverse_y": True,
    "use_pre_fault_voltage": False,
}
SCHEMA = closed_schema(
    {
        "bus": {
            "anyOf": [
                {"type": "null"},
                {"type": "integer", "minimum": 0},
                {"type": "array", "minItems": 1, "maxItems": 10000, "items": {"type": "integer", "minimum": 0}},
            ]
        },
        "fault": enum("3ph", "2ph", "1ph"),
        "case": enum("max", "min"),
        "lv_tol_percent": {"type": "integer", "enum": [6, 10]},
        "topology": enum("auto", "meshed", "radial"),
        "ip": {"type": "boolean"},
        "ith": {"type": "boolean"},
        "tk_s": number(exclusive_minimum=0),
        "kappa_method": enum("B", "C"),
        "r_fault_ohm": number(minimum=0),
        "x_fault_ohm": number(minimum=0),
        "branch_results": {"type": "boolean"},
        "check_connectivity": {"type": "boolean"},
        "return_all_currents": {"type": "boolean"},
        "inverse_y": {"type": "boolean"},
        "use_pre_fault_voltage": {"type": "boolean"},
    }
)


def run(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    selected = effective(DEFAULTS, options)
    calc_sc(net, **selected)
    return AnalysisOutcome(
        "short_circuit.iec60909",
        "succeeded",
        selected,
        {"fault": selected["fault"], "case": selected["case"]},
    )


OPERATIONS = (
    AnalysisOperation(
        "short_circuit.iec60909",
        "IEC 60909 short-circuit calculation",
        "calc_sc",
        SCHEMA,
        run,
    ),
)
