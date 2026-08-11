from __future__ import annotations

import pandapower as pp
import pandapower.networks as pn

from grid_simulator.evidence import fingerprint


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

    def open_ieee39(self):
        return pn.case39()

    def serialize(self, net) -> str:
        return pp.to_json(net)

    def network_ref(self, net) -> str:
        return f"network:ieee39:{fingerprint(self.serialize(net))}"

    def run_ac(self, net) -> None:
        pp.runpp(net, **self.ac_options)
