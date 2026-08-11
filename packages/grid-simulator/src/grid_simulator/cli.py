from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from grid_simulator.operations import dispatch
from grid_simulator.protocol import OperationError, SimulatorRequest, SimulatorResponse


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gridctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    request_parser = subparsers.add_parser("request")
    request_parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command != "request":
        return 2

    try:
        raw = json.loads(sys.stdin.read())
        request = SimulatorRequest.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        response = SimulatorResponse(
            request_id="invalid-request",
            ok=False,
            error=OperationError(code="invalid_request", message="Request must be a valid protocol 1.0 JSON object"),
        )
        _write_response(response)
        print(f"gridctl: invalid request: {exc}", file=sys.stderr)
        return 2

    _write_response(dispatch(request, args.workspace))
    return 0


def _write_response(response: SimulatorResponse) -> None:
    sys.stdout.write(json.dumps(response.model_dump(mode="json"), separators=(",", ":")) + "\n")
