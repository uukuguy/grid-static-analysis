# Agent Instructions

## Project Contract

This repository builds `grid-agent`, a command-line static-analysis agent for registered power-system networks. The CLI writes exactly one JSON object to stdout with `question_id` and `answer_output`; diagnostics go to stderr.

Numerical or network-specific claims must cross the project simulator boundary through `gridctl` using `grid-capability` protocol version `1.0`. The simulator environment is pinned to pandapower 3.4.0. Do not guess losses, voltages, rankings, contingency outcomes, or evidence.

## Boundaries

- `grid-agent` owns question handling, answer composition, tracing, Pi/LLM runtime setup, and the final answer envelope.
- `gridctl` owns simulator-side operations and deterministic calculations.
- Pi/LLM may use only project-defined grid tools, `grid_guide_open`, and `grid_submit_answer`.
- Do not expose shell, generic file read/write/edit, raw pandapower objects, arbitrary Python, or legacy query aliases as model capabilities.
- Offline informational answers may not create run evidence.
- Simulator-backed answers write current-run evidence under `runs/<question_id>/`.

## Runtime Layout

- `runs/` is ignored operator-visible run evidence and validation report storage.
- `.grid-agent/` is ignored internal auth/runtime/session state.
- Versioned runtime configuration lives under `configs/runtime/`.
- Do not delete or migrate a user's existing main-worktree `var/` data as part of source cleanup.

## Verification

Prefer Makefile targets:

```sh
make doctor
make test
make test-e2e
make validate
```

`make validate-provider PROVIDER=<id> [MODEL=<id>]` is optional and may be billed; use it only with explicit provider credentials.

For behavior changes, run the smallest focused tests first, then the broader gate. Preserve the stdout envelope contract and current-run evidence checks.
