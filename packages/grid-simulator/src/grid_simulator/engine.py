from __future__ import annotations

import pandapower as pp
import pandapower.networks as pn

from grid_simulator.evidence import fingerprint


class Pandapower340Engine:
    name = "pandapower"
    version = pp.__version__

    def open_ieee39(self):
        return pn.case39()

    def serialize(self, net) -> str:
        return pp.to_json(net)

    def network_ref(self, net) -> str:
        return f"network:ieee39:{fingerprint(self.serialize(net))}"
