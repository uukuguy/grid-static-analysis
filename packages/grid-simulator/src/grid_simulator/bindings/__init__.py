"""Pinned, schema-validated pandapower analysis bindings."""

from grid_simulator.bindings.diagnostic import OPERATIONS as DIAGNOSTIC_OPERATIONS
from grid_simulator.bindings.estimation import OPERATIONS as ESTIMATION_OPERATIONS
from grid_simulator.bindings.opf import OPERATIONS as OPF_OPERATIONS
from grid_simulator.bindings.powerflow import OPERATIONS as POWERFLOW_OPERATIONS
from grid_simulator.bindings.short_circuit import OPERATIONS as SHORT_CIRCUIT_OPERATIONS


OPERATIONS = (
    *POWERFLOW_OPERATIONS,
    *OPF_OPERATIONS,
    *SHORT_CIRCUIT_OPERATIONS,
    *ESTIMATION_OPERATIONS,
    *DIAGNOSTIC_OPERATIONS,
)
