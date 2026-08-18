# Repository Agent Contract

This file is the repository-wide instruction source for coding agents. Keep it
compatible with both Codex and Claude Code. `CLAUDE.md` must remain a relative
symbolic link to this file so the two tools read identical instructions.

## Product Contract

This repository builds `grid-agent`, a capability-first command-line agent for
static analysis of registered power-system networks.

- The default CLI contract writes exactly one JSON object to stdout with
  `question_id` and `answer_output`.
- Progress, diagnostics, tool events, and warnings go to stderr.
- Numerical and network-specific claims must cross the simulator boundary
  through `gridctl` using `grid-capability/1.0`.
- Never guess losses, voltages, rankings, topology, contingency outcomes, or
  evidence. Use simulator results from the current run.

## Ownership and Trust Boundaries

- `grid-agent` owns question handling, answer composition, Pi/LLM runtime setup,
  continuous context, tracing, reporting, and the final answer envelope.
- `gridctl` and `grid-simulator` own registered network access, deterministic
  calculations, model revisions, result datasets, and evidence.
- pandapower objects, DataFrames, callable names, and raw simulator internals
  stay behind the simulator boundary.
- Observation, projection, validation, and reporting may diagnose execution but
  must not replace simulator truth or block an otherwise valid primary answer.

## Model Capability Boundary

Pi/LLM may use only project-defined grid tools, `grid_guide_open`, bounded
context/decision tools published by the project, and `grid_submit_answer`.

Do not expose or add model capabilities for:

- shell commands or arbitrary subprocesses;
- generic file read, write, or edit operations;
- arbitrary Python or pandapower function execution;
- raw `pandapowerNet` objects or DataFrames;
- legacy query aliases;
- question-, fixture-, network-, or expected-answer-specific shortcuts.

New capabilities must be semantic, reusable across questions, contract-defined,
allowlisted, and executed through `gridctl`.

## Evidence and Runtime State

- Offline informational answers do not create run evidence.
- Simulator-backed answers persist current-run results and evidence under
  `runs/<question_id>/`; final claims may cite only references admitted for that
  run.
- `runs/` is ignored operator-visible evidence and validation-report storage.
- `.grid-agent/` is ignored internal authentication, runtime, cache, and session
  state.
- Versioned runtime configuration belongs under `configs/runtime/`.
- Provider credentials stay in environment variables or project-owned ignored
  authentication state. Never place secrets in arguments, logs, committed files,
  simulator environments, or answer artifacts.
- Do not delete or migrate a user's existing main-worktree `var/` data during
  source cleanup.

## Authoritative References

Do not duplicate frequently changing facts in this file. Read the owning source:

| Information | Source of truth |
| --- | --- |
| Published capability coverage | `configs/capabilities/pandapower-3.4.0-static-analysis.json` |
| Simulator package and version pin | `packages/grid-simulator/pyproject.toml` |
| Runtime setup, authentication, commands, and evidence inspection | `docs/RUNBOOK.md` |
| Capability registration and LLM composition architecture | `docs/architecture/pandapower-capability-composition.md` |
| Model-facing execution policy | `configs/agent/system-policy.md` |
| Structural project state | `docs/status/CURRENT-STATE.md` |
| Active recovery baton | `docs/status/RESUME-NEXT-SESSION.md` |

## Working Rules

- Preserve unrelated tracked and untracked user changes; stage only task-owned
  paths.
- Prefer `rg` and `rg --files` for repository discovery.
- Use `apply_patch` for text edits and explicit non-destructive commands for
  filesystem operations such as creating the approved symbolic link.
- Keep `README.md` and `README.zh-CN.md` aligned whenever shared product facts,
  commands, headings, or references change.
- Keep stable rules here and route volatile details to the authoritative
  references above.

## Verification

For behavior changes, run the smallest focused test first and then the supported
repository gates:

```sh
make doctor
make test
make test-e2e
make validate
```

`make validate-provider PROVIDER=<id> [MODEL=<id>]` is optional, requires
explicit provider credentials, and may be billed. Do not run it without that
authorization.

Documentation-only changes must at minimum pass link/symlink checks,
`git diff --check`, and `make doctor`. Preserve the stdout envelope,
simulator-boundary, and current-run evidence contracts in every change.
