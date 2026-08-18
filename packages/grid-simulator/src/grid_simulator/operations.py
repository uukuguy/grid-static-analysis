from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import networkx as nx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError as JsonSchemaSchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pandapower.topology import create_nxgraph
from pandapower.auxiliary import LoadflowNotConverged

from grid_simulator.analyses import (
    RECOVERY_ACTIONS_NON_CONVERGENCE,
    PowerflowExecutionError,
    ResultIntegrityError,
    UnknownBranchError,
    UnknownResultError,
    evidence_path,
    persist_non_convergence_diagnostics,
    rank_branches,
    run_ac_powerflow,
    run_n_minus_one,
)
from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.capabilities.families import CAPABILITY_FAMILIES
from grid_simulator.capabilities.schema import CapabilityContract
from grid_simulator.constraints import describe_model_constraints
from grid_simulator.creators import (
    CreatorArgumentsError,
    CreatorRegistry,
    UnknownCreatorError,
    UnknownElementReferenceError,
)
from grid_simulator.engine import Pandapower340Engine
from grid_simulator.evidence import canonical_json, fingerprint, write_json
from grid_simulator.models import (
    ContextIntegrityError,
    ContextNotFoundError,
    ContextStore,
    InvalidContextRef,
    ModelNotFoundError,
    ModelRegistry,
)
from grid_simulator.protocol import CapabilityError, GridCapabilityRequest, GridCapabilityResponse
from grid_simulator.queries import (
    BranchRecord,
    BusRecord,
    allowed_field_names,
    asset_ref,
    dataset_names,
    dataset_ref,
    field_metadata,
    find_branch,
    find_bus,
    find_element,
    records_for_dataset,
)
from grid_simulator.workspace import SimulatorWorkspace
from grid_simulator.revisions import (
    PatchFieldError,
    PatchKindError,
    PatchSelectorError,
    RevisionStore,
)


EXECUTABLE_CAPABILITIES = frozenset(
    {
        "environment.describe",
        "model.list",
        "model.creator.list",
        "model.creator.describe",
        "model.create",
        "model.revision.derive",
        "context.open",
        "context.get",
        "model.constraints.describe",
        "model.element.get",
        "model.dataset.list",
        "model.dataset.describe",
        "model.dataset.query",
        "topology.branch.endpoints.get",
        "topology.components.get",
        "evidence.get",
        "analysis.powerflow.ac.run",
        "result.branches.rank",
        "analysis.contingency.n_minus_one.run",
    }
)
MODEL_VIEW_LIMIT = 50
_EVIDENCE_REF_PATTERN = re.compile(r"^evidence:sha256:([0-9a-f]{64})$")


@dataclass(frozen=True)
class OperationServices:
    engine: Pandapower340Engine
    capability_registry: CapabilityRegistry


def dispatch(
    request: GridCapabilityRequest, workspace_path: Path, services: OperationServices | None = None
) -> GridCapabilityResponse:
    active_services = services or OperationServices(Pandapower340Engine(), CapabilityRegistry.load_packaged())
    try:
        if request.capability not in EXECUTABLE_CAPABILITIES:
            raise _unsupported_capability(request.capability)
        contract = _require_contract(active_services.capability_registry, request.capability)
        _validate_arguments(contract, request.arguments)
        result = _dispatch(request, SimulatorWorkspace(workspace_path), active_services)
        _validate_result(contract, result)
    except _OperationFailure as exc:
        return GridCapabilityResponse(request_id=request.request_id, ok=False, error=exc.error)
    return GridCapabilityResponse(request_id=request.request_id, ok=True, result=result)


def _dispatch(
    request: GridCapabilityRequest, workspace: SimulatorWorkspace, services: OperationServices
) -> dict[str, Any]:
    if request.capability == "environment.describe":
        return _environment_describe(services.capability_registry)
    if request.capability == "model.list":
        return _model_list(services.engine)
    if request.capability == "model.creator.list":
        return _model_creator_list(services.engine)
    if request.capability == "model.creator.describe":
        return _model_creator_describe(services.engine, request.arguments)
    if request.capability == "model.create":
        return _model_create(workspace, services.engine, request.arguments)
    if request.capability == "model.revision.derive":
        return _model_revision_derive(workspace, services.engine, request.arguments)
    if request.capability == "context.open":
        return _context_open(workspace, services.engine, request.arguments)
    if request.capability == "context.get":
        return _context_get(workspace, services.engine, request.arguments)
    if request.capability == "model.constraints.describe":
        return _model_constraints_describe(workspace, services.engine, request.arguments)
    if request.capability == "model.element.get":
        return _model_element_get(workspace, services.engine, request.arguments)
    if request.capability == "model.dataset.list":
        return _model_dataset_list(workspace, services.engine, request.arguments)
    if request.capability == "model.dataset.describe":
        return _model_dataset_describe(workspace, services.engine, request.arguments)
    if request.capability == "model.dataset.query":
        return _model_dataset_query(workspace, services.engine, request.arguments)
    if request.capability == "topology.branch.endpoints.get":
        return _topology_branch_endpoints_get(workspace, services.engine, request.arguments)
    if request.capability == "topology.components.get":
        return _topology_components_get(workspace, services.engine, request.arguments)
    if request.capability == "evidence.get":
        return _evidence_get(workspace, request.arguments)
    if request.capability == "analysis.powerflow.ac.run":
        return _analysis_powerflow_ac_run(workspace, services.engine, request.arguments)
    if request.capability == "result.branches.rank":
        return _result_branches_rank(workspace, request.arguments)
    if request.capability == "analysis.contingency.n_minus_one.run":
        return _analysis_contingency_n_minus_one_run(workspace, services.engine, request.arguments)
    raise _unsupported_capability(request.capability)


def _environment_describe(registry: CapabilityRegistry) -> dict[str, Any]:
    return {
        "protocol": "grid-capability",
        "protocol_version": "1.0",
        "simulator": "grid-simulator",
        "pandapower_version": "3.4.0",
        "executable_capabilities": [
            {
                "id": contract.id,
                "tool_name": contract.tool_name,
                "title": contract.title,
                "risk": contract.risk,
                "availability": contract.availability,
                "context_effect": contract.context_effect.model_dump(mode="json"),
            }
            for contract in registry.list()
            if contract.id in EXECUTABLE_CAPABILITIES
        ],
        "capability_families": [family.model_dump(mode="json") for family in CAPABILITY_FAMILIES],
    }


def _model_list(engine: Pandapower340Engine) -> dict[str, Any]:
    return {
        "models": [
            {"model": model.model_id, "source": model.source, "pandapower_version": model.engine_version}
            for model in ModelRegistry(engine).list()
        ]
    }


def _model_creator_list(engine: Pandapower340Engine) -> dict[str, Any]:
    registry = CreatorRegistry()
    return {
        "pandapower_version": engine.version,
        "registry_version": registry.version,
        "creators": registry.summaries(),
    }


def _model_creator_describe(
    engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    registry = CreatorRegistry()
    creator = str(arguments["creator"])
    try:
        description = registry.describe(creator)
    except UnknownCreatorError as exc:
        raise _failure(
            "unknown_creator",
            f"Creator {exc.creator!r} is not in the pandapower 3.4.0 creator registry",
            phase="resolve",
            allowed_recovery_actions=("list_creators",),
            details={"creator": exc.creator, "allowed_creators": list(exc.allowed)},
        ) from exc
    return {
        "pandapower_version": engine.version,
        "registry_version": registry.version,
        **description,
    }


def _model_create(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    try:
        created = RevisionStore(workspace, engine).create(
            name=str(arguments["name"]),
            sn_mva=float(arguments.get("sn_mva", 1.0)),
            f_hz=float(arguments.get("f_hz", 50.0)),
            elements=list(arguments["elements"]),
        )
    except UnknownCreatorError as exc:
        raise _failure(
            "unknown_creator",
            f"Creator {exc.creator!r} is not in the pandapower 3.4.0 creator registry",
            phase="resolve",
            allowed_recovery_actions=("list_creators",),
            details={"creator": exc.creator, "allowed_creators": list(exc.allowed)},
        ) from exc
    except UnknownElementReferenceError as exc:
        raise _failure(
            "unknown_local_element_ref",
            "Element arguments reference an ID that has not been created earlier in the transaction",
            phase="validate",
            allowed_recovery_actions=("order_elements_by_dependency",),
        ) from exc
    except CreatorArgumentsError as exc:
        raise _failure(
            "creator_arguments_invalid",
            str(exc),
            phase="validate",
            allowed_recovery_actions=("describe_creator",),
        ) from exc
    except OSError as exc:
        raise _failure("persist_failed", "Created model could not be persisted", phase="persist") from exc
    return _revision_result(created)


def _model_revision_derive(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    parent, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    try:
        derived = RevisionStore(workspace, engine).derive(
            parent_context=parent,
            parent_net=net,
            patches=list(arguments["patches"]),
        )
    except UnknownCreatorError as exc:
        raise _failure(
            "unknown_creator",
            f"Creator {exc.creator!r} is not in the pandapower 3.4.0 creator registry",
            phase="resolve",
            allowed_recovery_actions=("list_creators",),
            details={"creator": exc.creator, "allowed_creators": list(exc.allowed)},
        ) from exc
    except UnknownElementReferenceError as exc:
        raise _failure(
            "unknown_local_element_ref",
            "Create patch references an ID not created by an earlier patch",
            phase="validate",
            allowed_recovery_actions=("order_create_patches_by_dependency",),
        ) from exc
    except CreatorArgumentsError as exc:
        raise _failure(
            "creator_arguments_invalid",
            str(exc),
            phase="validate",
            allowed_recovery_actions=("describe_creator",),
        ) from exc
    except PatchFieldError as exc:
        raise _failure(
            "patch_field_unavailable",
            "Patch references fields unavailable for the selected element kind",
            phase="validate",
            allowed_recovery_actions=("describe_dataset",),
            details={"kind": exc.kind, "fields": exc.fields, "allowed_fields": exc.allowed},
        ) from exc
    except PatchSelectorError as exc:
        raise _failure(
            "patch_selector_invalid",
            str(exc),
            phase="validate",
            allowed_recovery_actions=("query_dataset",),
        ) from exc
    except PatchKindError as exc:
        raise _failure(
            "patch_operation_unavailable",
            "Patch element kind or operation is not supported by this revision",
            phase="validate",
            allowed_recovery_actions=("list_datasets",),
        ) from exc
    except OSError as exc:
        raise _failure("persist_failed", "Derived model could not be persisted", phase="persist") from exc
    result = _revision_result(derived)
    result["parent_context_ref"] = parent.context_ref
    result["parent_revision_ref"] = parent.revision_ref
    return result


def _revision_result(revision: Any) -> dict[str, Any]:
    return {
        "context_ref": revision.context.context_ref,
        "revision_ref": revision.context.revision_ref,
        "lineage_ref": revision.context.lineage_ref,
        "model": revision.context.model_id,
        "origin": revision.context.origin,
        "counts": revision.counts,
    }


def _context_open(workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]) -> dict[str, Any]:
    registry = ModelRegistry(engine)
    store = ContextStore(workspace, registry)
    model_id = str(arguments["model_id"])
    try:
        context = store.create(model_id)
    except ModelNotFoundError as exc:
        raise _failure(
            "model_not_found",
            f"Model {exc.model_id!r} is not registered",
            phase="resolve",
            allowed_recovery_actions=("call_model_list",),
        ) from exc
    except OSError as exc:
        raise _failure("persist_failed", "Context evidence could not be persisted", phase="persist") from exc
    model = registry.get(context.model_id)
    net = store.load_network(context.context_ref)
    return {
        "context_ref": context.context_ref,
        "model": context.model_id,
        "engine": engine.name,
        "pandapower_version": engine.version,
        "source": model.source,
        "semantic_sha256": context.revision_ref.removeprefix("revision:sha256:"),
        "counts": {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo))},
    }


def _context_get(workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]) -> dict[str, Any]:
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    return {
        "context_ref": context.context_ref,
        "model": context.model_id,
        "counts": {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo))},
    }


def _model_constraints_describe(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    described = describe_model_constraints(net, context.revision_ref)
    evidence_ref = _persist_constraint_fact(workspace, engine, context, described["constraints"])
    return {
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "constraints": described["constraints"],
        "evidence_refs": [evidence_ref],
    }


def _model_element_get(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    kind = str(arguments["kind"])
    namespace = str(arguments["namespace"])
    identifier = str(arguments["identifier"])
    available_kinds = {name.removeprefix("network.") for name in dataset_names(net) if name not in {"network.buses", "network.branches"}}
    if kind not in available_kinds:
        raise _failure(
            "unknown_element_kind",
            f"Element kind {kind!r} is not available in this network revision",
            phase="resolve",
            allowed_recovery_actions=("list_datasets",),
            details={"allowed_kinds": sorted(available_kinds)},
        )
    record = find_element(net, context.revision_ref, kind, namespace, identifier)
    if record is None:
        raise _failure(
            "unknown_element",
            f"No {kind!r} element matches {namespace!r}={identifier!r}",
            phase="resolve",
            allowed_recovery_actions=("query_dataset",),
        )
    return {
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "asset_ref": record.asset_ref,
        "element": record.as_dict(),
    }


def _model_dataset_describe(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    dataset = str(arguments["dataset"])
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    _require_dataset(net, dataset)
    return {
        "dataset_ref": dataset_ref(context.revision_ref, dataset),
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "dataset": dataset,
        "row_count": len(records_for_dataset(net, context.revision_ref, dataset)),
        "fields": field_metadata(dataset, net),
    }


def _model_dataset_list(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    return {
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "datasets": [
            {
                "dataset": name,
                "dataset_ref": dataset_ref(context.revision_ref, name),
                "row_count": len(records_for_dataset(net, context.revision_ref, name)),
            }
            for name in dataset_names(net)
        ],
    }


def _model_dataset_query(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    dataset = str(arguments["dataset"])
    select = [str(field) for field in arguments["select"]]
    where = dict(arguments.get("where", {}))
    filters = list(arguments.get("filters", []))
    sort = arguments.get("sort")
    limit = int(arguments.get("limit", 100))
    offset = int(arguments.get("offset", 0))
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    _require_dataset(net, dataset)
    _validate_dataset_query(net, dataset, select, where, filters, sort)
    try:
        rows = [record.as_dict() for record in records_for_dataset(net, context.revision_ref, dataset)]
    except ValueError as exc:
        raise _failure(
            "dataset_value_unavailable",
            "Dataset contains a value that cannot cross the typed boundary",
            phase="execute",
            allowed_recovery_actions=("choose_another_dataset",),
        ) from exc
    filtered_rows = _filter_rows(rows, where, filters)
    sorted_rows = _sort_rows(filtered_rows, sort)
    selected_rows = [{field: row[field] for field in select} for row in sorted_rows]
    page_limit = min(limit, MODEL_VIEW_LIMIT)
    returned_rows = selected_rows[offset : offset + page_limit]
    next_offset = offset + len(returned_rows) if offset + len(returned_rows) < len(selected_rows) else None
    result: dict[str, Any] = {
        "dataset_ref": dataset_ref(context.revision_ref, dataset),
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "dataset": dataset,
        "row_count": len(selected_rows),
        "returned_row_count": len(returned_rows),
        "offset": offset,
        "next_offset": next_offset,
        "rows": returned_rows,
    }
    if len(selected_rows) > MODEL_VIEW_LIMIT:
        artifact = {
            "artifact_type": "dataset_query",
            "dataset": dataset,
            "context_ref": context.context_ref,
            "revision_ref": context.revision_ref,
            "row_count": len(selected_rows),
            "rows": selected_rows,
        }
        digest = fingerprint(canonical_json(artifact))
        path = workspace.root / "evidence" / "artifacts" / f"dataset-query-{digest}.json"
        write_json(path, artifact)
        result["artifact_ref"] = f"artifact:sha256:{digest}"
    return result


def _topology_branch_endpoints_get(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    branch = _resolve_branch_argument(net, context.revision_ref, arguments)
    if branch is None:
        raise _failure(
            "unknown_branch",
            "Branch reference does not resolve to a model branch",
            phase="resolve",
            allowed_recovery_actions=("resolve_element",),
        )
    from_bus = find_bus(net, context.revision_ref, "asset_ref", branch.from_bus_ref)
    to_bus = find_bus(net, context.revision_ref, "asset_ref", branch.to_bus_ref)
    if from_bus is None or to_bus is None:
        raise _failure("topology_unavailable", "Branch endpoints could not be resolved", phase="execute")
    evidence_ref = _persist_network_fact(workspace, engine, context, branch)
    return {
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "branch": branch.summary(),
        "from_bus": _bus_endpoint(from_bus),
        "to_bus": _bus_endpoint(to_bus),
        "evidence_ref": evidence_ref,
    }


def _topology_components_get(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    try:
        graph = create_nxgraph(net, respect_switches=True, include_out_of_service=False)
    except Exception as exc:
        raise _failure("topology_unavailable", "Topology graph could not be derived", phase="execute") from exc
    components = []
    for component_id, nodes in enumerate(sorted(nx.connected_components(graph), key=lambda item: min(int(node) for node in item))):
        bus_indices = sorted(int(node) for node in nodes)
        subgraph = graph.subgraph(bus_indices)
        components.append(
            {
                "component_id": f"component:{component_id}",
                "bus_count": len(bus_indices),
                "branch_count": int(subgraph.number_of_edges()),
                "bus_refs": [asset_ref(context.revision_ref, "bus", index) for index in bus_indices[:200]],
            }
        )
    return {
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "component_count": len(components),
        "components": components,
    }


def _evidence_get(workspace: SimulatorWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    evidence_ref = str(arguments["evidence_ref"])
    digest = _parse_evidence_ref(evidence_ref)
    path = evidence_path(workspace, evidence_ref) or workspace.root / "evidence" / "network-facts" / f"network-fact-{digest}.json"
    if not path.is_file():
        raise _failure(
            "unknown_evidence",
            "Evidence reference is unavailable in this workspace",
            phase="resolve",
            allowed_recovery_actions=("rerun_producing_capability",),
        )
    payload = path.read_text(encoding="utf-8")
    if fingerprint(payload) != digest:
        raise _failure("artifact_unreadable", "Evidence content does not match its reference", phase="resolve")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise _failure("artifact_unreadable", "Evidence content is not valid JSON", phase="resolve") from exc
    return {"evidence_ref": evidence_ref, "document": document}


def _analysis_powerflow_ac_run(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    try:
        return run_ac_powerflow(workspace=workspace, engine=engine, context=context, net=net, arguments=arguments)
    except LoadflowNotConverged:
        diagnostics = persist_non_convergence_diagnostics(
            workspace=workspace,
            engine=engine,
            context=context,
            capability_id="analysis.powerflow.ac.run",
        )
        raise _failure(
            "powerflow_non_converged",
            "Pandapower AC power flow did not converge",
            phase="execute",
            allowed_recovery_actions=RECOVERY_ACTIONS_NON_CONVERGENCE,
            evidence_refs=(diagnostics.evidence_ref,),
            artifact_refs=(diagnostics.artifact_ref,),
        )
    except PowerflowExecutionError as exc:
        raise _failure(
            "powerflow_failed",
            "Pandapower AC power flow failed before producing a valid result",
            phase="execute",
            allowed_recovery_actions=("inspect_network_diagnostics", "report_failure"),
        ) from exc
    except OSError as exc:
        raise _failure(
            "persist_failed",
            "Power-flow result evidence could not be persisted",
            phase="persist",
            allowed_recovery_actions=("retry",),
        ) from exc


def _result_branches_rank(workspace: SimulatorWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return rank_branches(workspace=workspace, arguments=arguments)
    except ResultIntegrityError as exc:
        raise _failure(
            "result_integrity_failed",
            "Power-flow result evidence failed integrity verification",
            phase="resolve",
            allowed_recovery_actions=("rerun_powerflow",),
        ) from exc
    except UnknownResultError as exc:
        raise _failure(
            "unknown_result",
            "Power-flow result reference is unavailable in this workspace",
            phase="resolve",
            allowed_recovery_actions=("run_powerflow",),
        ) from exc


def _analysis_contingency_n_minus_one_run(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, arguments: dict[str, Any]
) -> dict[str, Any]:
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    try:
        return run_n_minus_one(workspace=workspace, engine=engine, context=context, net=net, arguments=arguments)
    except UnknownBranchError as exc:
        raise _failure(
            "unknown_branch",
            "Branch reference does not resolve to a model branch in this context revision",
            phase="resolve",
            allowed_recovery_actions=("resolve_element",),
        ) from exc
    except PowerflowExecutionError as exc:
        raise _failure(
            "powerflow_failed",
            "N-1 contingency execution failed before producing a valid aggregate result",
            phase="execute",
            allowed_recovery_actions=("inspect_network_diagnostics", "report_failure"),
        ) from exc
    except OSError as exc:
        raise _failure(
            "persist_failed",
            "N-1 contingency evidence could not be persisted",
            phase="persist",
            allowed_recovery_actions=("retry",),
        ) from exc


def _load_context_and_network(workspace: SimulatorWorkspace, engine: Pandapower340Engine, context_ref: str):
    store = ContextStore(workspace, ModelRegistry(engine))
    try:
        context = store.require(context_ref)
        net = store.load_network(context.context_ref)
    except (InvalidContextRef, ContextNotFoundError, ContextIntegrityError) as exc:
        raise _failure(
            "unknown_context",
            "Context reference is not available or failed verification",
            phase="resolve",
            allowed_recovery_actions=("call_context_open",),
        ) from exc
    return context, net


def _require_dataset(net: Any, dataset: str) -> None:
    if dataset not in dataset_names(net):
        raise _failure(
            "unsupported_dataset",
            "Dataset is not available in this network revision",
            phase="resolve",
            allowed_recovery_actions=("list_datasets",),
            details={"dataset": dataset, "available_datasets": list(dataset_names(net))},
        )


def _validate_dataset_query(
    net: Any,
    dataset: str,
    select: list[str],
    where: dict[str, Any],
    filters: list[object],
    sort: object,
) -> None:
    allowed_fields = allowed_field_names(dataset, net)
    unavailable = [field for field in select if field not in allowed_fields]
    if unavailable:
        raise _failure(
            "field_unavailable",
            "Select contains fields unavailable for this dataset",
            phase="validate",
            allowed_recovery_actions=("describe_dataset",),
            details={"fields": unavailable, "allowed_fields": list(allowed_fields)},
        )
    invalid_where = [field for field in where if field not in allowed_fields]
    if invalid_where:
        raise _failure(
            "where_field_unavailable",
            "Where contains fields unavailable for equality filtering",
            phase="validate",
            allowed_recovery_actions=("describe_dataset",),
            details={"fields": invalid_where, "allowed_where_fields": list(allowed_fields)},
        )
    invalid_filters = [
        str(dict(item).get("field", ""))
        for item in filters
        if str(dict(item).get("field", "")) not in allowed_fields
    ]
    if invalid_filters:
        raise _failure(
            "where_field_unavailable",
            "Filters contain fields unavailable for this dataset",
            phase="validate",
            allowed_recovery_actions=("describe_dataset",),
            details={"fields": invalid_filters, "allowed_where_fields": list(allowed_fields)},
        )
    if sort is None:
        return
    sort_field = str(dict(sort)["field"])
    if sort_field not in allowed_fields:
        raise _failure(
            "field_unavailable",
            "Sort field is unavailable for this dataset",
            phase="validate",
            allowed_recovery_actions=("describe_dataset",),
            details={"fields": [sort_field], "allowed_fields": list(allowed_fields)},
        )
    if sort_field not in select:
        raise _failure(
            "sort_field_unselected",
            "Sort field must also be selected",
            phase="validate",
            allowed_recovery_actions=("select_sort_field",),
        )


def _filter_rows(
    rows: list[dict[str, Any]], where: dict[str, Any], filters: list[object]
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if all(row[field] == value for field, value in where.items())
        and all(_predicate_matches(row, dict(predicate)) for predicate in filters)
    ]


def _predicate_matches(row: dict[str, Any], predicate: dict[str, Any]) -> bool:
    actual = row[str(predicate["field"])]
    expected = predicate.get("value")
    operator = str(predicate["operator"])
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        return actual in expected
    if actual is None or expected is None:
        return False
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    return False


def _sort_rows(rows: list[dict[str, Any]], sort: object) -> list[dict[str, Any]]:
    if sort is None:
        return rows
    sort_dict = dict(sort)
    reverse = sort_dict["direction"] == "descending"
    field = str(sort_dict["field"])
    return sorted(rows, key=lambda row: (row[field] is None, row[field]), reverse=reverse)


def _resolve_branch_argument(net: Any, revision_ref: str, arguments: dict[str, Any]) -> BranchRecord | None:
    if "branch_ref" in arguments:
        branch_ref = str(arguments["branch_ref"])
        match = re.fullmatch(r"asset:(line|trafo|trafo3w):sha256:[0-9a-f]{64}", branch_ref)
        if match is None:
            return None
        return find_branch(net, revision_ref, match.group(1), "asset_ref", branch_ref)
    return find_branch(
        net,
        revision_ref,
        str(arguments["kind"]),
        str(arguments["namespace"]),
        str(arguments["identifier"]),
    )


def _bus_endpoint(bus: BusRecord) -> dict[str, Any]:
    return {"asset_ref": bus.asset_ref, "index": bus.index, "name": bus.name, "alias": bus.alias}


def _persist_network_fact(
    workspace: SimulatorWorkspace, engine: Pandapower340Engine, context: Any, branch: BranchRecord
) -> str:
    document = {
        "evidence_type": "network_fact",
        "capability_id": "topology.branch.endpoints.get",
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "subject_ref": branch.asset_ref,
        "facts": {"from_bus_ref": branch.from_bus_ref, "to_bus_ref": branch.to_bus_ref},
        "provenance": {
            "engine": engine.name,
            "engine_version": engine.version,
            "source_alias": branch.alias,
        },
    }
    digest = fingerprint(canonical_json(document))
    evidence_ref = f"evidence:sha256:{digest}"
    path = workspace.root / "evidence" / "network-facts" / f"network-fact-{digest}.json"
    try:
        write_json(path, document)
    except OSError as exc:
        raise _failure(
            "evidence_persist_failed",
            "Network-fact evidence could not be persisted",
            phase="persist",
            allowed_recovery_actions=("retry",),
        ) from exc
    return evidence_ref


def _persist_constraint_fact(
    workspace: SimulatorWorkspace,
    engine: Pandapower340Engine,
    context: Any,
    constraints: list[dict[str, Any]],
) -> str:
    document = {
        "evidence_type": "network_fact",
        "capability_id": "model.constraints.describe",
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "facts": {"constraints": constraints},
        "provenance": {
            "engine": engine.name,
            "engine_version": engine.version,
            "source": "pandapower model tables",
        },
    }
    digest = fingerprint(canonical_json(document))
    evidence_ref = f"evidence:sha256:{digest}"
    path = workspace.root / "evidence" / "network-facts" / f"network-fact-{digest}.json"
    try:
        write_json(path, document)
    except OSError as exc:
        raise _failure(
            "evidence_persist_failed",
            "Model-constraint evidence could not be persisted",
            phase="persist",
            allowed_recovery_actions=("retry",),
        ) from exc
    return evidence_ref


def _parse_evidence_ref(evidence_ref: str) -> str:
    match = _EVIDENCE_REF_PATTERN.fullmatch(evidence_ref)
    if match is None:
        raise _failure("unknown_evidence", "Evidence reference is malformed", phase="resolve")
    return match.group(1)


def _require_contract(registry: CapabilityRegistry, capability: str) -> CapabilityContract:
    try:
        return registry.require(capability)
    except KeyError as exc:
        raise _failure(
            "capability_contract_unavailable",
            f"Capability {capability!r} contract is unavailable",
            phase="resolve",
        ) from exc


def _validate_arguments(contract: CapabilityContract, arguments: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(contract.input_schema)
        Draft202012Validator(contract.input_schema).validate(arguments)
    except JsonSchemaSchemaError as exc:
        raise _failure(
            "capability_input_schema_invalid",
            f"Capability {contract.id!r} has an invalid input contract",
            phase="resolve",
        ) from exc
    except JsonSchemaValidationError as exc:
        raise _failure(
            "invalid_arguments",
            "Capability arguments do not match the input contract",
            phase="validate",
            allowed_recovery_actions=("correct_arguments",),
        ) from exc
def _validate_result(contract: CapabilityContract, result: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(contract.output_schema)
        Draft202012Validator(contract.output_schema).validate(result)
    except JsonSchemaSchemaError as exc:
        raise _failure(
            "capability_output_schema_invalid",
            f"Capability {contract.id!r} has an invalid output contract",
            phase="resolve",
        ) from exc
    except JsonSchemaValidationError as exc:
        raise _failure(
            "contract_output_invalid",
            f"Capability {contract.id!r} produced a result that does not match its output contract",
        ) from exc


class _OperationFailure(Exception):
    def __init__(self, error: CapabilityError) -> None:
        self.error = error


def _unsupported_capability(capability: str) -> _OperationFailure:
    return _failure("unsupported_capability", f"Capability {capability!r} is not implemented")


def _failure(
    code: str,
    message: str,
    *,
    phase: Literal["parse", "resolve", "validate", "execute", "persist"] = "execute",
    allowed_recovery_actions: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    artifact_refs: tuple[str, ...] = (),
    details: dict[str, Any] | None = None,
) -> _OperationFailure:
    return _OperationFailure(
        CapabilityError(
            code=code,
            phase=phase,
            message=message,
            allowed_recovery_actions=allowed_recovery_actions,
            evidence_refs=evidence_refs,
            artifact_refs=artifact_refs,
            details=details or {},
        )
    )
