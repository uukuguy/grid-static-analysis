from __future__ import annotations


class CapabilityRegistry:
    _CAPABILITIES = (
        ("capabilities.list", "List available simulator operations."),
        ("capabilities.describe", "Describe one simulator operation."),
        ("network.open", "Open a supported grid model."),
        ("network.describe", "Describe an opened grid model."),
        ("element.resolve", "Resolve a stable network element identifier."),
        ("powerflow.run_ac", "Run deterministic AC power flow."),
        ("results.lines", "Query ranked AC line results."),
        ("contingency.run_lines", "Run single-line contingencies."),
    )

    def list(self) -> list[dict[str, str]]:
        return [{"id": identifier, "description": description} for identifier, description in self._CAPABILITIES]

    def describe(self, identifier: str) -> dict[str, str] | None:
        return next((item for item in self.list() if item["id"] == identifier), None)
