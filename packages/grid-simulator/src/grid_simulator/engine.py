from __future__ import annotations

import pandapower as pp
import pandapower.networks as pn

from grid_simulator.evidence import fingerprint
from grid_simulator.model_catalog import allowed_network_factories
from grid_simulator.models import ModelNotFoundError


def _network_factory_bindings():
    bindings = {}
    for factory_id in allowed_network_factories():
        factory = getattr(pn, factory_id, None)
        if not callable(factory) or not getattr(factory, "__module__", "").startswith("pandapower.networks."):
            raise RuntimeError(f"trusted network factory {factory_id!r} is unavailable in pandapower 3.4.0")
        bindings[factory_id] = factory
    return bindings


_NETWORK_FACTORIES = _network_factory_bindings()


class Pandapower340Engine:
    name = "pandapower"
    version = pp.__version__

    ac_options = {
        "algorithm": "nr",
        "calculate_voltage_angles": True,
        "init": "dc",
        "max_iteration": 10,
        "tolerance_mva": 1e-8,
        "trafo_model": "t",
        "trafo_loading": "current",
        "enforce_q_lims": False,
        "check_connectivity": True,
    }

    def open_registered(self, factory_id: str):
        factory = _NETWORK_FACTORIES.get(factory_id)
        if factory is None:
            raise ModelNotFoundError(factory_id)
        return factory()

    def serialize(self, net) -> str:
        return pp.to_json(net)

    def deserialize(self, payload: str):
        return pp.from_json_string(payload)

    def network_ref(self, net) -> str:
        return f"network:ieee39:{fingerprint(self.serialize(net))}"

    def run_ac(self, net, options: dict | None = None) -> None:
        pp.runpp(net, **(options or self.ac_options))
