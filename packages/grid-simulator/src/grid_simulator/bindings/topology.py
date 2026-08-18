from __future__ import annotations

from typing import Any

import networkx as nx
import pandas as pd
from pandapower.topology import create_nxgraph, unsupplied_buses

from grid_simulator.bindings.base import (
    AnalysisOperation,
    AnalysisOutcome,
    AnalysisPrerequisiteError,
    closed_schema,
    integer,
)
from grid_simulator.queries import asset_ref


GRAPH_OPTIONS = {
    "respect_switches": {"type": "boolean"},
    "include_lines": {"type": "boolean"},
    "include_trafos": {"type": "boolean"},
    "include_trafo3ws": {"type": "boolean"},
    "include_impedances": {"type": "boolean"},
    "include_dclines": {"type": "boolean"},
}


def _graph(net: Any, options: dict[str, Any]) -> Any:
    return create_nxgraph(
        net,
        respect_switches=bool(options.get("respect_switches", True)),
        include_lines=bool(options.get("include_lines", True)),
        include_trafos=bool(options.get("include_trafos", True)),
        include_trafo3ws=bool(options.get("include_trafo3ws", True)),
        include_impedances=bool(options.get("include_impedances", True)),
        include_dclines=bool(options.get("include_dclines", True)),
    )


def _bus_ref(net: Any, index: int) -> str:
    return asset_ref(str(net._grid_agent_revision_ref), "bus", index)


def run_path(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    source = int(options["source_bus"])
    target = int(options["target_bus"])
    graph = _graph(net, options)
    if source not in graph or target not in graph:
        raise AnalysisPrerequisiteError(
            "topology path references an unavailable bus", source_bus=source, target_bus=target
        )
    try:
        path = nx.shortest_path(graph, source=source, target=target)
    except nx.NetworkXNoPath as exc:
        raise AnalysisPrerequisiteError(
            "no topology path exists between the requested buses",
            source_bus=source,
            target_bus=target,
        ) from exc
    net["res_topology_path"] = pd.DataFrame(
        [
            {"order": order, "bus_index": int(bus), "bus_ref": _bus_ref(net, int(bus))}
            for order, bus in enumerate(path)
        ]
    )
    return AnalysisOutcome(
        "topology.path",
        "succeeded",
        options,
        {"source_bus": source, "target_bus": target, "hop_count": max(len(path) - 1, 0)},
    )


def run_neighbors(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    source = int(options["source_bus"])
    max_depth = int(options.get("max_depth", 1))
    graph = _graph(net, options)
    if source not in graph:
        raise AnalysisPrerequisiteError("topology neighbors references an unavailable bus", source_bus=source)
    distances = nx.single_source_shortest_path_length(graph, source, cutoff=max_depth)
    net["res_topology_neighbor"] = pd.DataFrame(
        [
            {"bus_index": int(bus), "bus_ref": _bus_ref(net, int(bus)), "depth": int(depth)}
            for bus, depth in sorted(distances.items(), key=lambda item: (item[1], item[0]))
        ]
    )
    return AnalysisOutcome(
        "topology.neighbors",
        "succeeded",
        options,
        {"source_bus": source, "max_depth": max_depth, "bus_count": len(distances)},
    )


def run_unsupplied(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    graph = _graph(net, options)
    buses = sorted(int(bus) for bus in unsupplied_buses(net, mg=graph))
    net["res_unsupplied_bus"] = pd.DataFrame(
        [{"bus_index": bus, "bus_ref": _bus_ref(net, bus)} for bus in buses],
        columns=["bus_index", "bus_ref"],
    )
    return AnalysisOutcome(
        "topology.unsupplied",
        "succeeded",
        options,
        {"unsupplied_bus_count": len(buses)},
    )


OPERATIONS = (
    AnalysisOperation(
        "topology.path",
        "Shortest topology path",
        "topology.create_nxgraph+networkx.shortest_path",
        closed_schema(
            {
                "source_bus": {"type": "integer", "minimum": 0},
                "target_bus": {"type": "integer", "minimum": 0},
                **GRAPH_OPTIONS,
            }
        ) | {"required": ["source_bus", "target_bus"]},
        run_path,
    ),
    AnalysisOperation(
        "topology.neighbors",
        "Topology neighbors",
        "topology.create_nxgraph+networkx.single_source_shortest_path_length",
        closed_schema(
            {
                "source_bus": {"type": "integer", "minimum": 0},
                "max_depth": integer(minimum=1, maximum=20),
                **GRAPH_OPTIONS,
            }
        ) | {"required": ["source_bus"]},
        run_neighbors,
    ),
    AnalysisOperation(
        "topology.unsupplied",
        "Unsupplied buses",
        "topology.unsupplied_buses",
        closed_schema(GRAPH_OPTIONS),
        run_unsupplied,
    ),
)
