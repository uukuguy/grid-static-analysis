# Grid Static Analysis

English | [简体中文](README.zh-CN.md)

`grid-agent` is a capability-first command-line agent for evidence-backed static
analysis of registered power-system networks. An LLM interprets the request and
composes project-defined tools; `gridctl` and the pinned pandapower simulator
perform every deterministic network calculation.

`v1.0.0` is the first stable release of the declared static-analysis product
scope. The executable capability matrix remains the authority for current
coverage.

## What It Does

- Discovers registered networks and creates controlled declarative models.
- Derives immutable network revisions and analysis scenarios.
- Runs topology, AC/DC/three-phase power flow, AC/DC optimal power flow,
  IEC 60909 short-circuit, state estimation, diagnostics, contingency, risk,
  equivalent-network, and static protection analyses.
- Queries, aggregates, compares, and ranks simulator-owned result datasets.
- Carries verified context across multi-step analysis and continuous reports.
- Records native trajectories and serves a read-only investigation workbench.
- Binds final numerical claims to current-run result and evidence references.

The project covers its declared pandapower static-analysis scope, not every
public pandapower API. Time-series/control workflows, plotting, arbitrary
file/database conversion, and unpinned external solver runtimes remain outside
the model capability boundary. See the
[capability architecture](docs/architecture/pandapower-capability-composition.md)
and the
[executable coverage matrix](configs/capabilities/pandapower-3.4.0-static-analysis.json).

## Architecture

```text
Natural-language request
        |
        v
grid-agent + Pi/LLM       intent, tool composition, context, answer envelope
        |
        v  grid-capability/1.0
gridctl + grid-simulator  contracts, registered models, results, evidence
        |
        v
pandapower                deterministic power-system calculations
        |
        v
runs/<question_id>/       operator-visible current-run evidence
```

The LLM chooses from registered semantic tools; it never receives shell,
arbitrary Python, raw pandapower objects, DataFrames, or generic filesystem
access. Numerical and network-specific claims must come back through the
simulator boundary.

## Quick Start

Prerequisites are Python 3.12+, Node.js 22.19+, `uv`, and `npm`. Provider-backed
analysis additionally needs a supported LLM credential; offline smoke checks do
not.

```sh
git clone https://github.com/uukuguy/grid-static-analysis.git
cd grid-static-analysis
make setup
make doctor
```

Run a deterministic offline smoke check:

```sh
make run QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
```

Run the primary natural-language agent path:

```sh
cp .env.example .env
# Configure one supported provider credential in the ignored .env file.
make install-pi
make run-llm QUESTION="Run an AC power flow on the IEEE 39-bus network and report active power losses."
```

For project-owned OpenAI Codex OAuth instead of an API key, set
`GRID_AGENT_LLM_PROVIDER=openai-codex` in `.env` before using `make auth-login`;
the login command does not select the provider. You can also select it per
invocation with `make run-llm PROVIDER=openai-codex QUESTION="..."`. See the
[runbook](docs/RUNBOOK.md) for provider setup, authentication precedence,
runtime installation, and failure diagnosis.

## Primary Workflows

| Goal | Command |
| --- | --- |
| Inspect runtime readiness | `make doctor` |
| Offline deterministic smoke check | `make run QUESTION="..."` |
| LLM-led single question | `make run-llm QUESTION="..."` |
| Continuous multi-question analysis | `make analysis INSTRUCTIONS=path/to/instructions.txt` |
| Compatibility alias for continuous analysis | `make report INSTRUCTIONS=path/to/instructions.txt` |
| Build and serve the read-only workbench | `make trajectory PORT=8765` |

`grid-agent run` writes exactly one JSON object to stdout:

```json
{"question_id":"...","answer_output":"..."}
```

Progress, diagnostics, and tool events stay on stderr. Continuous analysis also
emits one final answer envelope whose `answer_output` points to the generated
report.

## Results, Evidence, and Workbench

Simulator-backed runs store operator-visible artifacts under
`runs/<question_id>/`. Final claims can cite only result and evidence references
admitted for the current run. Pure informational offline answers do not create
simulation evidence.

Internal authentication, managed Pi runtime files, caches, and session state
stay under the ignored `.grid-agent/` directory. Versioned runtime configuration
stays under `configs/runtime/`.

Start the local read-only trajectory workbench with:

```sh
make trajectory PORT=8765
```

It serves the UI and API on `http://127.0.0.1:8765`. The workbench projects
recorded facts for investigation; it cannot mutate runs or replace simulator
truth.

## Verification

```sh
make doctor
make test
make test-e2e
make validate
```

`make validate-provider PROVIDER=<id> [MODEL=<id>]` is optional, requires
explicit credentials, and may incur provider charges.

## Repository Layout

| Path | Responsibility |
| --- | --- |
| `packages/grid-agent/` | CLI, Pi/LLM runtime, context, trajectory, reports, and answer envelope |
| `packages/grid-simulator/` | `gridctl`, registered models, pandapower execution, results, and evidence |
| `packages/pi-grid-tools/` | Project-scoped Pi tools, guides, request capture, and answer submission |
| `packages/trajectory-workbench/` | Read-only React/TypeScript trajectory investigation UI |
| `configs/` | Versioned capabilities, policies, provider catalog, and runtime configuration |
| `validation/` | Offline, scripted-Pi, semantic, and optional provider validation suites |
| `docs/` | Runbooks, architecture, design history, plans, and durable project state |

## Documentation

- [Runbook](docs/RUNBOOK.md) — setup, authentication, execution, evidence, and troubleshooting.
- [Manual validation guide](docs/MANUAL-VALIDATION.md) — reproducible human acceptance procedure.
- [Capability registration and composition](docs/architecture/pandapower-capability-composition.md) — scope and LLM tool orchestration boundaries.
- [Analysis context architecture](docs/architecture/analysis-context.md) — verified multi-step context model.
- [Trajectory event architecture](docs/architecture/trajectory-events.md) — authoritative native execution chronology.
- [Current project state](docs/status/CURRENT-STATE.md) — structural snapshot and implementation entry points.
- [Repository agent contract](AGENTS.md) — stable Codex/Claude Code rules and sources of truth.

## Security and Contribution Boundaries

Keep credentials in environment variables or ignored project-owned auth state.
Do not place secrets in command arguments, committed files, logs, simulator
environments, or evidence. New model capabilities must remain reusable,
contract-defined, allowlisted, and simulator-backed—never question-specific
shortcuts or arbitrary execution surfaces.
