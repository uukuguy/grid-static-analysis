from __future__ import annotations

from typing import Any

import pandapower as pp
from pandapower.grid_equivalents import get_equivalent

from grid_simulator.models import ContextStore, ModelRegistry
from grid_simulator.queries import list_bus_records
from grid_simulator.revisions import RevisionStore
from grid_simulator.workspace import SimulatorWorkspace


class EquivalentDerivationError(ValueError):
    pass


def derive_equivalent(
    workspace: SimulatorWorkspace, engine: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    context_ref = str(arguments["context_ref"])
    context_store = ContextStore(workspace, ModelRegistry(engine))
    context = context_store.require(context_ref)
    net = context_store.load_network(context_ref)
    by_ref = {record.asset_ref: record.index for record in list_bus_records(net, context.revision_ref)}
    boundary_refs = [str(ref) for ref in arguments["boundary_bus_refs"]]
    internal_refs = [str(ref) for ref in arguments["internal_bus_refs"]]
    unknown = sorted(set(boundary_refs + internal_refs) - set(by_ref))
    if unknown:
        raise EquivalentDerivationError(f"unknown bus refs: {unknown}")
    pp.runpp(net, calculate_voltage_angles=bool(arguments.get("calculate_voltage_angles", True)))
    equivalent = get_equivalent(
        net,
        eq_type=str(arguments["equivalent_type"]),
        boundary_buses=[by_ref[ref] for ref in boundary_refs],
        internal_buses=[by_ref[ref] for ref in internal_refs],
        return_internal=bool(arguments.get("return_internal", True)),
        show_computing_time=False,
        ward_type=str(arguments.get("ward_type", "ward_injection")),
        adapt_va_degree=bool(arguments.get("adapt_va_degree", False)),
        calculate_voltage_angles=bool(arguments.get("calculate_voltage_angles", True)),
        allow_net_change_for_convergence=bool(
            arguments.get("allow_net_change_for_convergence", False)
        ),
    )
    if equivalent is None:
        raise EquivalentDerivationError(
            "the boundary/internal selection leaves no external network to reduce"
        )
    operation = {
        "equivalent_type": arguments["equivalent_type"],
        "boundary_bus_refs": boundary_refs,
        "internal_bus_refs": internal_refs,
        "return_internal": bool(arguments.get("return_internal", True)),
        "ward_type": str(arguments.get("ward_type", "ward_injection")),
    }
    derived = RevisionStore(workspace, engine).persist_derived_network(
        parent_context=context,
        net=equivalent,
        operation={"equivalent": operation},
    )
    return {
        "model": derived.context.model_id,
        "source": "derived-equivalent",
        "context_ref": derived.context.context_ref,
        "revision_ref": derived.context.revision_ref,
        "lineage_ref": derived.context.lineage_ref,
        "parent_context_ref": context.context_ref,
        "equivalent_type": arguments["equivalent_type"],
        "boundary_bus_refs": boundary_refs,
        "internal_bus_refs": internal_refs,
        "counts": derived.counts,
    }
