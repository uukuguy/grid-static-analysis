from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4


class GridctlClientError(RuntimeError):
    pass


class SimulatorOperationError(GridctlClientError):
    pass


class SimulatorCapabilityError(GridctlClientError):
    def __init__(self, error: dict[str, object]) -> None:
        super().__init__(str(error.get("message", "Grid capability failed")))
        self.error = error


class GridctlClient:
    def __init__(self, *, executable: Path, workspace: Path, timeout_seconds: float = 60) -> None:
        self.executable = Path(executable)
        self.workspace = Path(workspace)
        self.timeout_seconds = timeout_seconds
        self.last_diagnostics = ""

    def invoke(self, capability: str, arguments: dict[str, object]) -> dict[str, object]:
        request_id = f"sim-{uuid4().hex}"
        request = {
            "protocol": "grid-capability",
            "protocol_version": "1.0",
            "request_id": request_id,
            "capability": capability,
            "arguments": arguments,
        }
        try:
            completed = subprocess.run(
                [str(self.executable), "request", "--workspace", str(self.workspace)],
                input=json.dumps(request, separators=(",", ":")) + "\n",
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GridctlClientError("Grid simulator process could not complete") from exc
        self.last_diagnostics = completed.stderr
        lines = completed.stdout.splitlines()
        if len(lines) != 1:
            raise GridctlClientError("Grid simulator returned an invalid stdout protocol")
        try:
            response = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise GridctlClientError("Grid simulator returned non-JSON stdout") from exc
        if (
            response.get("protocol") != "grid-capability"
            or response.get("protocol_version") != "1.0"
            or response.get("request_id") != request_id
        ):
            raise GridctlClientError("Grid simulator response does not match its request")
        if response.get("ok") is not True:
            error = response.get("error") or {}
            if isinstance(error, dict):
                raise SimulatorCapabilityError(error)
            raise SimulatorOperationError("Grid simulator operation failed")
        result = response.get("result")
        if not isinstance(result, dict):
            raise GridctlClientError("Grid simulator response has no result object")
        return result

    def call(self, capability: str, arguments: dict[str, object]) -> dict[str, object]:
        return self.invoke(capability, arguments)
