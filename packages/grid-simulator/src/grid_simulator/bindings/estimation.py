from __future__ import annotations

from typing import Any

from pandapower.estimation import chi2_analysis, estimate, remove_bad_data

from grid_simulator.bindings.base import AnalysisOperation, AnalysisOutcome, closed_schema, effective, enum, integer, nullable, number


BUS_SELECTION = nullable(
    {
        "anyOf": [
            enum("aux_bus", "no_inj_bus", "zero_pwr_bus"),
            {"type": "array", "maxItems": 10000, "items": {"type": "integer", "minimum": 0}},
        ]
    }
)
FUSE_SELECTION = nullable(
    {
        "anyOf": [
            {"const": "all"},
            {"type": "array", "maxItems": 10000, "items": {"type": "integer", "minimum": 0}},
        ]
    }
)
ESTIMATE_DEFAULTS = {
    "algorithm": "wls",
    "init": "flat",
    "tolerance": 1e-6,
    "maximum_iterations": 50,
    "zero_injection": "aux_bus",
    "fuse_buses_with_bb_switch": "all",
    "debug_mode": False,
}
ESTIMATE_SCHEMA = closed_schema(
    {
        "algorithm": enum("wls", "wls_with_zero_constraint", "opt", "irwls", "lp", "af-wls"),
        "init": enum("flat", "results", "slack"),
        "tolerance": number(exclusive_minimum=0),
        "maximum_iterations": integer(maximum=10000),
        "zero_injection": BUS_SELECTION,
        "fuse_buses_with_bb_switch": FUSE_SELECTION,
        "debug_mode": {"type": "boolean"},
        "a": number(exclusive_minimum=0),
        "opt_method": enum("Newton-CG", "BFGS", "SLSQP", "trust-constr"),
        "estimator": enum("wls", "lav", "shgm", "ql", "qc", "qmc", "gm", "rr"),
    }
)
CHI2_DEFAULTS = {
    "init": "flat",
    "tolerance": 1e-6,
    "maximum_iterations": 10,
    "calculate_voltage_angles": True,
    "chi2_prob_false": 0.05,
}
CHI2_SCHEMA = closed_schema(
    {
        "init": enum("flat", "results", "slack"),
        "tolerance": number(exclusive_minimum=0),
        "maximum_iterations": integer(maximum=10000),
        "calculate_voltage_angles": {"type": "boolean"},
        "chi2_prob_false": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
    }
)
REMOVE_DEFAULTS = {
    "init": "flat",
    "tolerance": 1e-6,
    "maximum_iterations": 10,
    "calculate_voltage_angles": True,
    "rn_max_threshold": 3.0,
}
REMOVE_SCHEMA = closed_schema(
    {
        "init": enum("flat", "results", "slack"),
        "tolerance": number(exclusive_minimum=0),
        "maximum_iterations": integer(maximum=10000),
        "calculate_voltage_angles": {"type": "boolean"},
        "rn_max_threshold": number(exclusive_minimum=0),
    }
)


def run_estimate(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    selected = effective(ESTIMATE_DEFAULTS, options)
    raw = estimate(net, **selected)
    if isinstance(raw, dict):
        success = bool(raw.get("success"))
        metadata = {
            "success": success,
            "num_iterations": raw.get("num_iterations"),
            "objective_function_value": raw.get("objective_function_value"),
        }
    else:
        success = bool(raw)
        metadata = {"success": success}
    return AnalysisOutcome(
        "state_estimation.estimate", "succeeded" if success else "failed", selected, metadata
    )


def run_chi2(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    selected = effective(CHI2_DEFAULTS, options)
    detected = bool(chi2_analysis(net, **selected))
    return AnalysisOutcome(
        "state_estimation.chi2", "succeeded", selected, {"bad_data_detected": detected}
    )


def run_remove(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    selected = effective(REMOVE_DEFAULTS, options)
    success = bool(remove_bad_data(net, **selected))
    return AnalysisOutcome(
        "state_estimation.remove_bad_data",
        "succeeded" if success else "failed",
        selected,
        {"success": success},
    )


OPERATIONS = (
    AnalysisOperation(
        "state_estimation.estimate", "State estimation", "estimate", ESTIMATE_SCHEMA, run_estimate
    ),
    AnalysisOperation(
        "state_estimation.chi2", "State-estimation chi-square analysis", "chi2_analysis", CHI2_SCHEMA, run_chi2
    ),
    AnalysisOperation(
        "state_estimation.remove_bad_data",
        "State-estimation bad-data removal",
        "remove_bad_data",
        REMOVE_SCHEMA,
        run_remove,
    ),
)
