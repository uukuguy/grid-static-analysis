from __future__ import annotations

from pathlib import Path

import pytest
from pandapower.auxiliary import LoadflowNotConverged
from pydantic import JsonValue

from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.engine import Pandapower340Engine
from grid_simulator.operations import OperationServices, dispatch
from grid_simulator.protocol import CapabilityError, GridCapabilityRequest, GridCapabilityResponse
from grid_simulator.workspace import SimulatorWorkspace


class ControllablePandapowerEngine(Pandapower340Engine):
    def __init__(self) -> None:
        self.force_non_convergence = False
        self.non_convergent_outages: set[int] = set()

    def run_ac(self, net, *args, **kwargs) -> None:
        outaged = {int(index) for index in net.line.index if not bool(net.line.at[index, "in_service"])}
        if self.force_non_convergence or outaged & self.non_convergent_outages:
            raise LoadflowNotConverged("injected test non-convergence")
        super().run_ac(net, *args, **kwargs)


class GridTestClient:
    def __init__(self, root: Path) -> None:
        self.workspace = SimulatorWorkspace(root)
        self.engine = ControllablePandapowerEngine()
        self.services = OperationServices(self.engine, CapabilityRegistry.load_packaged())
        self._request_number = 0

    def _invoke(self, capability: str, arguments: dict[str, JsonValue]) -> GridCapabilityResponse:
        self._request_number += 1
        request = GridCapabilityRequest(
            request_id=f"test-{self._request_number}",
            capability=capability,
            arguments=arguments,
        )
        response = dispatch(request, self.workspace.root, self.services)
        assert response.request_id == request.request_id
        return response

    def call(self, capability: str, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]:
        response = self._invoke(capability, arguments)
        assert response.ok is True and response.result is not None
        return response.result

    def call_error(self, capability: str, arguments: dict[str, JsonValue]) -> CapabilityError:
        response = self._invoke(capability, arguments)
        assert response.ok is False and response.error is not None
        return response.error


@pytest.fixture
def grid(tmp_path: Path) -> GridTestClient:
    return GridTestClient(tmp_path)


@pytest.fixture
def context_ref(grid: GridTestClient) -> str:
    return str(grid.call("context.open", {"model_id": "ieee39"})["context_ref"])
