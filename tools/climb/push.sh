#!/usr/bin/env bash
set -euo pipefail

RUN_DIR=${1:?usage: push.sh RUN_DIR}
printf '{"mode":"local-gate","run_dir":"%s","external_submission":false}\n' "$RUN_DIR"
