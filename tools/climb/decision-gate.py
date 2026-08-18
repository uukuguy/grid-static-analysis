#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-eval-json", required=True, type=Path)
    args = parser.parse_args()
    score = json.loads(args.local_eval_json.read_text(encoding="utf-8"))
    ready = bool(score["release_ready"])
    print(json.dumps({
        "decision": "PUSH" if ready else "CONTINUE",
        "reason": "100% release gate met" if ready else "matrix incomplete; advance next implementation hypothesis",
        "local_total": score["total"],
        "action_next": "run release closure" if ready else "advance hypothesis pool",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
