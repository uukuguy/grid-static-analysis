# WP-A Semantic Foundation and Validation Baseline Implementation Plan

> **For agentic workers:** Use `subagent-driven-development` (recommended) or execute inline task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Design reference:** [`2026-08-12-pandapower-semantic-capability-redesign.md`](../specs/2026-08-12-pandapower-semantic-capability-redesign.md)

**Goal:** Rebuild the v0.1 vertical slice around one domain-semantic capability protocol, registered read-only networks, precise topology/data/AC/N-1 tools, a complete initial Skill, and executable validation cases while removing the legacy prompt, protocol, and `grid_query` path.

**Architecture:** Start an isolated implementation worktree from tag `v0.1`, then cherry-pick the approved redesign specification. `grid-agent` drives Pi with a controlled Skill guide and contract-derived domain tools; `gridctl` owns registered pandapower 3.4.0 models, immutable run contexts, deterministic analyses, typed errors, results, and evidence. WP-A supports IEEE-39 as its registered execution model and preserves the useful AC/ranking/N-1 slice under the new contracts; multiple registered networks, DC power flow, richer policy/risk analysis, and broader pandapower packages belong to WP-B.

**Tech Stack:** Python >=3.12, uv, Pydantic >=2.12,<3, pandapower==3.4.0, pytest >=9,<10, Node.js >=22.19.0, Pi 0.80.6, JSON Schema 2020-12, JSONL, Markdown Skill resources.

## Global Constraints

- Begin implementation from annotated tag `v0.1` (`5cf2e2d`), not from the current GSE main implementation.
- Preserve `stdout`: exactly one JSON object containing only `question_id` and `answer_output`.
- Keep pandapower, pandas, NumPy, and SciPy out of `packages/grid-agent`.
- Pi receives no arbitrary `read`, shell, Python, filesystem, DataFrame, or `pandapowerNet` capability.
- Use one public protocol: `protocol="grid-capability"`, `protocol_version="1.0"`.
- A pure informational answer creates neither `runs/<question_id>/` nor simulator evidence.
- A simulator-backed network fact or calculation persists complete current-run evidence before the model sees the result.
- Tool descriptions must be independently usable; Skill guidance does not compensate for incomplete schemas.
- The initial Skill must be complete for every capability advertised by WP-A.
- Do not retain protocol 1.0 compatibility aliases, `grid_query`, `hardened-bash.mjs`, or `configs/prompts/grid-agent-system.md` after the cutover task.
- Do not touch the user's uncommitted `Makefile` in the current main worktree; all implementation occurs in the isolated v0.1-based worktree.

---

## Dependency and Delivery Boundary

This is plan 1 of 4 from the approved redesign. It must leave a working CLI and new-domain tool path. Later plans consume these stable outputs:

- WP-B consumes the capability contract, registered-model/context API, dataset API, Skill packaging, and validation case format to add multiple networks, DC flow, richer queries, policy/risk, and broader static analysis.
- WP-C consumes result/evidence references and run layout to add durable DCI plans, budgets, checkpoints, compaction, continuous sessions, and resume.
- WP-D consumes capability contracts to rebuild MCP and finish transport conformance, cleanup, and release packaging.

## File Map

### Versioned configuration and runtime state

- Create `packages/grid-agent/src/grid_agent/application/paths.py`: one typed source for repository, configuration, internal-state, and run-output locations.
- Move `runtime/pi-runtime.lock.json` to `configs/runtime/pi-runtime.lock.json`.
- Move `runtime/licenses/PI-NOTICE.md` to `third-party-notices/PI.md`.
- Create `configs/agent/system-policy.md`: stable safety, evidence, and answer invariants only.
- Modify `.gitignore`: ignore `.grid-agent/` and `runs/`; stop naming `var/` as the active layout.

### Simulator domain and capabilities

- Replace `packages/grid-simulator/src/grid_simulator/protocol.py`: grid-capability request, response, and actionable error models.
- Replace `packages/grid-simulator/src/grid_simulator/capabilities.py` with package `packages/grid-simulator/src/grid_simulator/capabilities/`.
- Create `packages/grid-simulator/src/grid_simulator/capabilities/schema.py`: semantic capability model.
- Create `packages/grid-simulator/src/grid_simulator/capabilities/registry.py`: packaged-contract loader and validator.
- Create `packages/grid-simulator/src/grid_simulator/capabilities/definitions/*.json`: canonical WP-A contracts.
- Create `packages/grid-simulator/src/grid_simulator/models.py`: registered model, revision, context, asset reference, and context store.
- Create `packages/grid-simulator/src/grid_simulator/queries.py`: typed element, dataset, and topology queries.
- Create `packages/grid-simulator/src/grid_simulator/analyses.py`: AC, line ranking, and N-1 execution using stable references.
- Modify `packages/grid-simulator/src/grid_simulator/engine.py`: registered-model loading and normalized pandapower access.
- Replace `packages/grid-simulator/src/grid_simulator/operations.py`: dispatch only grid-capability operations.
- Modify `packages/grid-simulator/src/grid_simulator/evidence.py` and `workspace.py`: atomic result/evidence persistence under the new run layout.
- Modify `packages/grid-simulator/src/grid_simulator/cli.py`: accept and return only the new public envelope.

### Agent, Skill, and Pi tools

- Create `skills/grid-static-analysis/SKILL.md` and the complete WP-A references.
- Create `packages/grid-agent/src/grid_agent/knowledge/offline.py`: reviewed informational answers without simulator workspaces.
- Create `packages/grid-agent/src/grid_agent/tools/catalog.py`: materialize model-facing tools from semantic contracts.
- Replace `packages/grid-agent/src/grid_agent/simulator/client.py`: invoke capabilities and preserve typed errors.
- Modify `packages/grid-agent/src/grid_agent/runtime/environment.py`: pass only catalog, Skill, answer, and workspace paths to Pi.
- Replace `packages/pi-grid-tools/src/hardened-bash.mjs` with `packages/pi-grid-tools/src/domain-tools.mjs`.
- Modify `packages/grid-agent/src/grid_agent/cli/app.py`: remove `_answer`, legacy prompt wiring, and legacy directories.

### Validation and documentation

- Create `validation/manifest.json`, `validation/suites/task-required/*.json`, and `validation/suites/static-analysis-core/*.json`.
- Create `validation/run.py`: deterministic case runner and evaluator dispatch.
- Create `packages/grid-agent/tests/validation/`: case-schema, oracle, trajectory, and CLI tests.
- Update `Makefile`, `README.md`, `docs/RUNBOOK.md`, and `AGENTS.md` to the new paths and commands.
- Delete legacy knowledge workflow cards after their reviewed content is incorporated into the Skill.

---

### Task 1: Create the v0.1 implementation worktree and establish the baseline

**Files:**
- No source edits.
- Worktree: `.worktrees/pandapower-semantic-capabilities`
- Branch: `feature/pandapower-semantic-capabilities`

**Interfaces:**
- Consumes: tag `v0.1`, approved design commit `dce24a5`.
- Produces: isolated clean implementation branch with the approved design available locally.

- [ ] **Step 1: Create the worktree through the required worktree skill**

Run from the current main worktree:

```bash
git worktree add .worktrees/pandapower-semantic-capabilities -b feature/pandapower-semantic-capabilities v0.1
```

Expected: Git reports a new branch at `5cf2e2d`; the current main worktree and its modified `Makefile` remain unchanged.

- [ ] **Step 2: Bring the approved design into the implementation branch**

```bash
git -C .worktrees/pandapower-semantic-capabilities cherry-pick dce24a5
```

Expected: one clean documentation commit; no GSE implementation commits appear in the branch history.

- [ ] **Step 3: Install and verify the v0.1 baseline**

```bash
make setup
make test
make test-e2e
```

Run from `.worktrees/pandapower-semantic-capabilities`.

Expected: all v0.1 agent, simulator, Node, and scripted end-to-end tests pass. If a test fails because the local environment is missing a prerequisite, fix environment setup only; do not change product behavior in this task.

- [ ] **Step 4: Record the baseline without creating a source commit**

```bash
git status --short
git log --oneline -3
```

Expected: clean status and the cherry-picked design above `5cf2e2d`.

---

### Task 2: Establish explicit project paths and the new state layout

**Files:**
- Create: `packages/grid-agent/src/grid_agent/application/paths.py`
- Create: `packages/grid-agent/tests/application/test_paths.py`
- Modify: `packages/grid-agent/src/grid_agent/application/workspace.py`
- Modify: `packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/lock.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/installer.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/locator.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/pi_config.py`
- Modify: `packages/grid-agent/src/grid_agent/auth/store.py`
- Move: `runtime/pi-runtime.lock.json` -> `configs/runtime/pi-runtime.lock.json`
- Move: `runtime/licenses/PI-NOTICE.md` -> `third-party-notices/PI.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: repository root `Path`.
- Produces: `ProjectPaths.from_root(root)`, `ProjectPaths.runs_dir`, `internal_dir`, `pi_runtime_dir`, `pi_agent_dir`, and `sessions_dir`.

- [ ] **Step 1: Write failing path and workspace tests**

```python
# packages/grid-agent/tests/application/test_paths.py
from pathlib import Path

from grid_agent.application.paths import ProjectPaths
from grid_agent.application.workspace import RunWorkspace


def test_project_paths_separate_internal_state_from_auditable_runs(tmp_path: Path) -> None:
    paths = ProjectPaths.from_root(tmp_path)

    assert paths.runs_dir == tmp_path / "runs"
    assert paths.internal_dir == tmp_path / ".grid-agent"
    assert paths.pi_runtime_dir == tmp_path / ".grid-agent/runtime/pi"
    assert paths.pi_agent_dir == tmp_path / ".grid-agent/auth/pi"
    assert paths.sessions_dir == tmp_path / ".grid-agent/sessions"
    assert paths.runtime_lock == tmp_path / "configs/runtime/pi-runtime.lock.json"


def test_run_workspace_uses_operator_visible_layout(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(ProjectPaths.from_root(tmp_path).runs_dir, "q-test")

    assert workspace.root_path == tmp_path / "runs/q-test"
    assert workspace.tool_results_path == tmp_path / "runs/q-test/tool-results"
    assert workspace.evidence_path == tmp_path / "runs/q-test/evidence"
    assert workspace.answer_path == tmp_path / "runs/q-test/answer.json"
```

- [ ] **Step 2: Run the tests and verify the new path API is absent**

Run:

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/application/test_paths.py -v
```

Expected: FAIL importing `grid_agent.application.paths` or accessing `tool_results_path`.

- [ ] **Step 3: Implement `ProjectPaths` and update `RunWorkspace`**

```python
# packages/grid-agent/src/grid_agent/application/paths.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path

    @classmethod
    def from_root(cls, root: Path) -> "ProjectPaths":
        return cls(Path(root).resolve())

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def internal_dir(self) -> Path:
        return self.root / ".grid-agent"

    @property
    def pi_runtime_dir(self) -> Path:
        return self.internal_dir / "runtime/pi"

    @property
    def pi_agent_dir(self) -> Path:
        return self.internal_dir / "auth/pi"

    @property
    def sessions_dir(self) -> Path:
        return self.internal_dir / "sessions"

    @property
    def runtime_lock(self) -> Path:
        return self.root / "configs/runtime/pi-runtime.lock.json"
```

Update `RunWorkspace` to replace `corpus_path` with these fields and create exactly these run directories:

```python
tool_results_path = root_path / "tool-results"
evidence_path = root_path / "evidence"
pi_path = root_path / "pi"
bin_path = root_path / "bin"
for path in (tool_results_path, evidence_path, pi_path, bin_path):
    path.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Move versioned runtime files and redirect internal paths**

```bash
mkdir -p configs/runtime third-party-notices
git mv runtime/pi-runtime.lock.json configs/runtime/pi-runtime.lock.json
git mv runtime/licenses/PI-NOTICE.md third-party-notices/PI.md
```

Update runtime lock loading to resolve `configs/runtime/pi-runtime.lock.json`. Update installer, locator, Pi configuration, and auth storage call sites to receive `ProjectPaths` values rather than concatenate `var/...` locally. Add these exact ignore entries:

```gitignore
/.grid-agent/
/runs/
```

- [ ] **Step 5: Run focused and existing runtime tests**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/application/test_paths.py packages/grid-agent/tests/runtime packages/grid-agent/tests/auth -v
```

Expected: PASS; assertions use `.grid-agent/runtime/pi`, `.grid-agent/auth/pi`, and `runs/`.

- [ ] **Step 6: Commit the state-layout boundary**

```bash
git add .gitignore configs/runtime third-party-notices packages/grid-agent
git commit -m "refactor(paths): separate internal state from run evidence"
```

---

### Task 3: Define the validation case contract and deterministic harness

**Files:**
- Create: `validation/manifest.json`
- Create: `validation/run.py`
- Create: `validation/suites/task-required/topology-line-endpoints-001.json`
- Create: `validation/suites/task-required/knowledge-voltage-range-001.json`
- Create: `validation/suites/static-analysis-core/unknown-line-001.json`
- Create: `packages/grid-agent/src/grid_agent/validation/__init__.py`
- Create: `packages/grid-agent/src/grid_agent/validation/cases.py`
- Create: `packages/grid-agent/src/grid_agent/validation/oracles.py`
- Create: `packages/grid-agent/tests/validation/test_case_contract.py`
- Create: `packages/grid-agent/tests/validation/test_oracles.py`

**Interfaces:**
- Consumes: CLI command template and JSON case documents.
- Produces: `ValidationCase`, `CaseRequirements`, `OracleSpec`, `load_cases(root)`, and deterministic evaluator results.
- Structured topology facts are verified only from successful canonical `tool_result` trace events; `topology_branch_endpoints(event, arguments)` compares typed `branch`, `from_bus`, and `to_bus` fields from the event result. answer_output is never parsed for electrical entities, relationships, values, or units.

- [ ] **Step 1: Write failing validation-schema tests**

```python
# packages/grid-agent/tests/validation/test_case_contract.py
from pathlib import Path

from grid_agent.validation.cases import load_cases


ROOT = Path(__file__).resolve().parents[4]


def test_validation_cases_have_unique_ids_and_deterministic_oracles() -> None:
    cases = load_cases(ROOT / "validation")

    assert len(cases) == 3
    assert len({case.id for case in cases}) == len(cases)
    assert all(case.oracle.kind in {"structured", "knowledge", "limitation"} for case in cases)


def test_topology_case_forbids_unnecessary_powerflow() -> None:
    case = next(item for item in load_cases(ROOT / "validation") if item.id == "topology-line-endpoints-001")

    assert case.requirements.required_capabilities == ("topology.branch.endpoints.get",)
    assert case.requirements.forbidden_capabilities == ("analysis.powerflow.ac.run",)
    assert case.requirements.max_tool_calls == 4
    assert case.requirements.requires_evidence is True
```

- [ ] **Step 2: Run and verify the validation package is absent**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation/test_case_contract.py -v
```

Expected: FAIL importing `grid_agent.validation.cases`.

- [ ] **Step 3: Implement the strict case models and loader**

Create `packages/grid-agent/src/grid_agent/validation/cases.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseRequirements(StrictModel):
    required_capabilities: tuple[str, ...] = ()
    forbidden_capabilities: tuple[str, ...] = ()
    max_tool_calls: int = Field(ge=0)
    requires_evidence: bool


class OracleSpec(StrictModel):
    kind: Literal["structured", "knowledge", "limitation"]
    evaluator: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ValidationCase(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    question: str = Field(min_length=1)
    suites: tuple[str, ...]
    model: str | None = None
    requirements: CaseRequirements
    oracle: OracleSpec


def load_cases(root: Path) -> tuple[ValidationCase, ...]:
    paths = sorted((Path(root) / "suites").glob("*/*.json"))
    cases = tuple(ValidationCase.model_validate(json.loads(path.read_text(encoding="utf-8"))) for path in paths)
    identifiers = [case.id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("validation case ids must be unique")
    return cases
```

- [ ] **Step 4: Add the first three executable case documents**

`validation/manifest.json` is versioned and names the supported suites explicitly:

```json
{
  "schema_version": "1.0",
  "suites": {
    "task-required": {"description": "docs/TASK.md mandatory questions and truthful boundary cases"},
    "static-analysis-core": {"description": "growing semantic capability, recovery, and evidence regression set"}
  }
}
```

`topology-line-endpoints-001.json`:

```json
{
  "id": "topology-line-endpoints-001",
  "question": "IEEE-39节点系统中线路11连接哪两个母线？",
  "suites": ["task-required", "static-analysis-core"],
  "model": "ieee39",
  "requirements": {
    "required_capabilities": ["topology.branch.endpoints.get"],
    "forbidden_capabilities": ["analysis.powerflow.ac.run"],
    "max_tool_calls": 4,
    "requires_evidence": true
  },
  "oracle": {
    "kind": "structured",
    "evaluator": "topology_branch_endpoints",
    "arguments": {
      "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
      "from_bus": {"name": "6"},
      "to_bus": {"name": "11"}
    }
  }
}
```

`knowledge-voltage-range-001.json` uses evaluator `contains_all`, arguments `{"values":["0.95","1.05","pu"]}`, no required capability, forbids `analysis.powerflow.ac.run`, max calls 0, and requires no evidence. `unknown-line-001.json` uses evaluator `truthful_limitation`, model `ieee39`, required capability `model.element.get`, max calls 4, and identifier `171`.

- [ ] **Step 5: Implement deterministic oracle functions and their tests**

```python
# packages/grid-agent/src/grid_agent/validation/oracles.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue


@dataclass(frozen=True)
class ToolResultEvent:
    capability: str
    result: Mapping[str, JsonValue]
    evidence_refs: tuple[str, ...]


def contains_all(answer: str, arguments: Mapping[str, object]) -> bool:
    values = arguments.get("values", [])
    return isinstance(values, Sequence) and all(str(value).casefold() in answer.casefold() for value in values)


def truthful_limitation(answer: str, arguments: Mapping[str, object]) -> bool:
    lowered = answer.casefold()
    return any(term in lowered for term in ("不存在", "未找到", "不支持", "limitation", "not found"))


def declared_fields_match(actual: JsonValue, expected: JsonValue) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and declared_fields_match(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def topology_branch_endpoints(event: ToolResultEvent, arguments: Mapping[str, JsonValue]) -> bool:
    return event.capability == "topology.branch.endpoints.get" and declared_fields_match(
        event.result, dict(arguments)
    )


ORACLES = {
    "contains_all": contains_all,
    "truthful_limitation": truthful_limitation,
    "topology_branch_endpoints": topology_branch_endpoints,
}
```

Tests call informational evaluators with answer prose and call `topology_branch_endpoints` with `ToolResultEvent` instances. `validation/run.py` loads cases, executes a supplied CLI command, parses the answer envelope, parses canonical successful `tool_result` trace events, checks evidence references, applies the selected structured oracle to typed result fields, checks capability constraints, and emits one JSON record per case plus a final summary record. Structured topology validation has these deterministic failure classes: `verification_trace_missing`, `verification_result_missing`, `verification_evidence_missing`, and `structured_oracle_mismatch`; no text fallback exists.

- [ ] **Step 6: Run validation unit tests and commit**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation -v
git add validation packages/grid-agent/src/grid_agent/validation packages/grid-agent/tests/validation
git commit -m "test(validation): establish growing question corpus"
```

Expected: validation tests PASS; product cases are not yet run against the legacy CLI.

---

### Task 4: Replace the legacy operation envelope with grid-capability 1.0

**Files:**
- Replace: `packages/grid-simulator/src/grid_simulator/protocol.py`
- Delete: `packages/grid-simulator/src/grid_simulator/capabilities.py`
- Create: `packages/grid-simulator/src/grid_simulator/capabilities/__init__.py`
- Create: `packages/grid-simulator/src/grid_simulator/capabilities/schema.py`
- Create: `packages/grid-simulator/src/grid_simulator/capabilities/registry.py`
- Create: `packages/grid-simulator/src/grid_simulator/capabilities/definitions/__init__.py`
- Create: `packages/grid-simulator/src/grid_simulator/capabilities/definitions/*.json`
- Replace: `packages/grid-simulator/tests/test_protocol.py`
- Create: `packages/grid-simulator/tests/test_capability_contracts.py`
- Modify: `packages/grid-simulator/pyproject.toml`

**Interfaces:**
- Consumes: packaged JSON capability documents.
- Produces: `GridCapabilityRequest`, `GridCapabilityResponse`, `CapabilityError`, `CapabilityContract`, and `CapabilityRegistry.require(identifier)`.

- [ ] **Step 1: Write failing protocol and semantic-contract tests**

```python
from pydantic import ValidationError
import pytest

from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.protocol import GridCapabilityRequest, GridCapabilityResponse


def test_request_uses_named_grid_capability_protocol() -> None:
    request = GridCapabilityRequest(
        protocol="grid-capability",
        protocol_version="1.0",
        request_id="req-1",
        capability="topology.branch.endpoints.get",
        arguments={"context_ref": "context:sha256:" + "a" * 64, "branch_ref": "asset:line:sha256:" + "b" * 64},
    )
    assert request.capability == "topology.branch.endpoints.get"


def test_response_requires_exactly_one_result_or_error() -> None:
    with pytest.raises(ValidationError):
        GridCapabilityResponse(request_id="req-1", ok=True, result=None, error=None)


def test_contracts_express_composition_and_pandapower_binding() -> None:
    contract = CapabilityRegistry.load_packaged().require("topology.branch.endpoints.get")
    assert contract.tool_name == "grid_topology_branch_endpoints"
    assert "network.branch" in contract.consumes
    assert "topology.endpoints" in contract.produces
    assert contract.pandapower.version == "3.4.0"
    assert contract.terms["zh"]
    assert contract.not_for
```

- [ ] **Step 2: Run and verify the new types are absent**

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_protocol.py packages/grid-simulator/tests/test_capability_contracts.py -v
```

Expected: FAIL importing the new models.

- [ ] **Step 3: Implement the new envelope and actionable error**

```python
# packages/grid-simulator/src/grid_simulator/protocol.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GridCapabilityRequest(StrictModel):
    protocol: Literal["grid-capability"] = "grid-capability"
    protocol_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    capability: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    arguments: dict[str, JsonValue]


class CapabilityError(StrictModel):
    code: str
    phase: Literal["parse", "resolve", "validate", "execute", "persist"]
    message: str
    retryable: bool = False
    state_effect: Literal["none", "committed"] = "none"
    allowed_recovery_actions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    details: dict[str, JsonValue] = Field(default_factory=dict)


class GridCapabilityResponse(StrictModel):
    protocol: Literal["grid-capability"] = "grid-capability"
    protocol_version: Literal["1.0"] = "1.0"
    request_id: str
    ok: bool
    result: dict[str, JsonValue] | None = None
    error: CapabilityError | None = None

    @model_validator(mode="after")
    def check_payload(self) -> "GridCapabilityResponse":
        if self.ok and (self.result is None or self.error is not None):
            raise ValueError("successful response requires only result")
        if not self.ok and (self.error is None or self.result is not None):
            raise ValueError("failed response requires only error")
        return self
```

- [ ] **Step 4: Implement the complete semantic contract model**

`CapabilityContract` contains these exact required fields:

```python
class PandapowerBinding(StrictModel):
    version: Literal["3.4.0"]
    operation: str
    limitations: tuple[str, ...] = ()


class CapabilityContract(StrictModel):
    id: str
    version: str
    package: str
    tool_name: str
    title: str
    purpose: str
    applies_to: tuple[str, ...]
    not_for: tuple[str, ...]
    terms: dict[Literal["zh", "en"], tuple[str, ...]]
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    requires: tuple[str, ...]
    consumes: tuple[str, ...]
    produces: tuple[str, ...]
    common_next: tuple[str, ...]
    errors: tuple[str, ...]
    recovery: dict[str, tuple[str, ...]]
    state_effect: Literal["none", "creates_context", "creates_result"]
    evidence_required: bool
    risk: Literal["catalog", "read_only_model", "read_only_analysis"]
    pandapower: PandapowerBinding | None
```

The registry imports `CapabilityContract` from `capabilities.schema`, uses `importlib.resources.files("grid_simulator.capabilities.definitions")`, validates every JSON file, rejects duplicate IDs and tool names, and returns contracts sorted by ID. `capabilities.__init__` exports only `CapabilityContract` and `CapabilityRegistry`.

- [ ] **Step 5: Add all WP-A contract documents**

Create complete contracts for:

```text
environment.describe
model.list
context.open
context.get
model.element.get
model.dataset.describe
model.dataset.query
topology.branch.endpoints.get
topology.components.get
analysis.powerflow.ac.run
result.branches.rank
analysis.contingency.n_minus_one.run
evidence.get
```

Every schema sets `additionalProperties: false`; every reference field has its exact prefix pattern; all enum-like fields use JSON Schema `enum` rather than free strings. `model.dataset.query` uses `oneOf` branches for `network.buses` and `network.branches`, each with its own selectable-field enum. Do not add a generic `fields: string[]` schema.

- [ ] **Step 6: Package the JSON resources and run contract tests**

Add this Hatch inclusion:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/grid_simulator/capabilities/definitions" = "grid_simulator/capabilities/definitions"
```

Run:

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_protocol.py packages/grid-simulator/tests/test_capability_contracts.py -v
```

Expected: PASS for envelope exclusivity, duplicate checks, schema completeness, terms, composition types, and pandapower binding.

- [ ] **Step 7: Commit the semantic protocol**

```bash
git add packages/grid-simulator
git commit -m "feat(protocol): define semantic grid capability contracts"
```

---

### Task 5: Add registered models, immutable revisions, and run contexts

**Files:**
- Create: `packages/grid-simulator/src/grid_simulator/models.py`
- Modify: `packages/grid-simulator/src/grid_simulator/engine.py`
- Modify: `packages/grid-simulator/src/grid_simulator/workspace.py`
- Modify: `packages/grid-simulator/src/grid_simulator/evidence.py`
- Create: `packages/grid-simulator/tests/test_models.py`
- Create: `packages/grid-simulator/tests/test_contexts.py`

**Interfaces:**
- Consumes: registered model ID `ieee39`, run workspace.
- Produces: `RegisteredModel`, `OpenedContext`, `ModelRegistry.list()`, `ModelRegistry.open(model_id)`, `ContextStore.create(model_id)`, and `ContextStore.require(context_ref)`.

- [ ] **Step 1: Write failing registration and immutability tests**

```python
from pathlib import Path

from grid_simulator.engine import Pandapower340Engine
from grid_simulator.models import ContextStore, ModelRegistry
from grid_simulator.workspace import SimulatorWorkspace


def test_registry_lists_ieee39_with_domain_aliases() -> None:
    model = ModelRegistry(Pandapower340Engine()).list()[0]
    assert model.model_id == "ieee39"
    assert "IEEE-39节点系统" in model.aliases
    assert model.source == "pandapower.networks.case39"


def test_open_context_persists_immutable_revision(tmp_path: Path) -> None:
    workspace = SimulatorWorkspace(tmp_path)
    context = ContextStore(workspace, ModelRegistry(Pandapower340Engine())).create("ieee39")
    loaded = ContextStore(workspace, ModelRegistry(Pandapower340Engine())).require(context.context_ref)

    assert loaded == context
    assert context.revision_ref.startswith("revision:sha256:")
    assert workspace.model_artifact(context.revision_ref).is_file()
```

- [ ] **Step 2: Run and verify model/context types are absent**

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_models.py packages/grid-simulator/tests/test_contexts.py -v
```

Expected: FAIL importing `grid_simulator.models`.

- [ ] **Step 3: Implement registered model loading**

Use immutable Pydantic models:

```python
class RegisteredModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_id: str
    title: str
    aliases: tuple[str, ...]
    source: str
    engine: Literal["pandapower"] = "pandapower"
    engine_version: Literal["3.4.0"] = "3.4.0"


class OpenedContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    context_ref: str
    model_id: str
    revision_ref: str
    engine: Literal["pandapower"]
    engine_version: Literal["3.4.0"]
```

`Pandapower340Engine.open_registered("ieee39")` returns `pandapower.networks.case39()` and rejects every other ID with typed `model_not_found` at the operation boundary. Add `serialize(net) -> str` using `pandapower.to_json(net)` and `deserialize(payload: str)` using `pandapower.from_json_string(payload)`; no operation receives an arbitrary filesystem path. `ModelRegistry` contains exactly one WP-A entry and never evaluates a function name from input.

- [ ] **Step 4: Implement content-addressed context persistence**

`ContextStore.create()` serializes the loaded network, hashes the exact serialized bytes, writes the model artifact atomically, and hashes this canonical context document:

```json
{
  "model_id": "ieee39",
  "revision_ref": "revision:sha256:<digest>",
  "engine": "pandapower",
  "engine_version": "3.4.0"
}
```

The context reference is `context:sha256:<digest>`. `require()` accepts only that exact pattern, verifies the stored document hash and the model-artifact digest, and never silently opens a new model for an unknown reference. `load_network(context_ref)` calls `require()`, deserializes only the verified artifact bytes, and confirms the resulting engine/version metadata before returning the network.

- [ ] **Step 5: Run tests and commit**

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_models.py packages/grid-simulator/tests/test_contexts.py -v
git add packages/grid-simulator
git commit -m "feat(models): register immutable pandapower contexts"
```

Expected: PASS; reopening the same registered model produces the same revision ref and a verifiable context document.

---

### Task 6: Implement typed element, dataset, and topology capabilities

**Files:**
- Create: `packages/grid-simulator/tests/conftest.py`
- Create: `packages/grid-simulator/src/grid_simulator/queries.py`
- Replace: `packages/grid-simulator/src/grid_simulator/operations.py`
- Replace: `packages/grid-simulator/tests/test_network_operations.py`
- Create: `packages/grid-simulator/tests/test_datasets.py`
- Create: `packages/grid-simulator/tests/test_topology.py`
- Create: `packages/grid-simulator/tests/test_network_evidence.py`

**Interfaces:**
- Consumes: `context_ref`, registered asset identifier, typed dataset query.
- Produces: stable `asset_ref`, `model.element`, `network.buses`, `network.branches`, `topology.endpoints`, and `evidence.network_fact` results.

- [ ] **Step 1: Define the dispatch test boundary and write failing direct-topology tests**

The tests require `dispatch(request: GridCapabilityRequest, workspace_path: Path, services: OperationServices | None = None) -> GridCapabilityResponse`, which Step 7 implements without changing the JSONL public boundary. `OperationServices` is a frozen dataclass containing `engine: Pandapower340Engine` and `capability_registry: CapabilityRegistry`; production creates those defaults when `services` is `None`.

Create `packages/grid-simulator/tests/conftest.py` with a `GridTestClient`. It owns a `SimulatorWorkspace`, one `OperationServices` instance, and these exact helpers:

```python
class ControllablePandapowerEngine(Pandapower340Engine):
    def __init__(self) -> None:
        self.force_non_convergence = False
        self.non_convergent_outages: set[int] = set()

    def run_ac(self, net, *args, **kwargs) -> None:
        outaged = {int(index) for index in net.line.index if not bool(net.line.at[index, "in_service"])}
        if self.force_non_convergence or outaged & self.non_convergent_outages:
            raise LoadflowNotConverged("injected test non-convergence")
        super().run_ac(net, *args, **kwargs)


class GridTestClient:
    def __init__(self, root: Path) -> None:
        self.workspace = SimulatorWorkspace(root)
        self.engine = ControllablePandapowerEngine()
        self.services = OperationServices(self.engine, CapabilityRegistry.load_packaged())
        self._request_number = 0

    def _invoke(self, capability: str, arguments: dict[str, JsonValue]) -> GridCapabilityResponse:
        self._request_number += 1
        request = GridCapabilityRequest(
            request_id=f"test-{self._request_number}",
            capability=capability,
            arguments=arguments,
        )
        return dispatch(request, self.workspace.root, self.services)

    def call(self, capability: str, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]:
        response = self._invoke(capability, arguments)
        assert response.ok is True and response.result is not None
        return response.result

    def call_error(self, capability: str, arguments: dict[str, JsonValue]) -> CapabilityError:
        response = self._invoke(capability, arguments)
        assert response.ok is False and response.error is not None
        return response.error


@pytest.fixture
def grid(tmp_path: Path) -> GridTestClient:
    return GridTestClient(tmp_path)


@pytest.fixture
def context_ref(grid: GridTestClient) -> str:
    return str(grid.call("context.open", {"model_id": "ieee39"})["context_ref"])
```

`call()` must assert a successful correlated `GridCapabilityResponse`; `call_error()` must assert a failed correlated response and return its typed error. This fixture is the only test helper used by Tasks 6 and 7.

Then add the capability tests:

```python
def test_line_11_returns_endpoints_without_powerflow(grid, context_ref: str) -> None:
    response = grid.call(
        "topology.branch.endpoints.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    )
    assert response["branch"]["alias"] == "pandapower:line:11"
    assert response["from_bus"]["name"] == "6"
    assert response["to_bus"]["name"] == "11"
    assert response["evidence_ref"].startswith("evidence:sha256:")
    assert not list(grid.workspace.results_dir.glob("powerflow-*.json"))


def test_branch_dataset_schema_enumerates_every_queryable_field(grid, context_ref: str) -> None:
    description = grid.call("model.dataset.describe", {"context_ref": context_ref, "dataset": "network.branches"})
    fields = {item["name"] for item in description["fields"]}
    assert {"asset_ref", "kind", "name", "from_bus_ref", "to_bus_ref", "in_service"} <= fields


def test_unknown_query_field_returns_allowed_fields(grid, context_ref: str) -> None:
    error = grid.call_error(
        "model.dataset.query",
        {"context_ref": context_ref, "dataset": "network.branches", "select": ["mystery"]},
    )
    assert error.code == "field_unavailable"
    assert "allowed_fields" in error.details
    assert error.allowed_recovery_actions == ("describe_dataset",)
```

- [ ] **Step 2: Run and verify the new operations fail**

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_network_operations.py packages/grid-simulator/tests/test_datasets.py packages/grid-simulator/tests/test_topology.py -v
```

Expected: FAIL because dispatch still accepts legacy operations and direct capabilities do not exist.

- [ ] **Step 3: Implement stable model elements**

`queries.py` defines domain records for `BusRecord` and `BranchRecord`. Asset refs are hashes of the canonical tuple `(revision_ref, kind, pandapower_index)`:

```python
def asset_ref(revision_ref: str, kind: str, index: int) -> str:
    payload = json.dumps([revision_ref, kind, index], separators=(",", ":"), ensure_ascii=False)
    return f"asset:{kind}:sha256:{sha256(payload.encode()).hexdigest()}"
```

Line records expose `from_bus_ref` and `to_bus_ref`; transformer records expose their corresponding domain endpoint fields. The record includes `alias="pandapower:<kind>:<index>"` and never treats `from_bus` as power-flow direction.

- [ ] **Step 4: Implement typed dataset descriptions and bounded query**

Define constant field metadata for `network.buses` and `network.branches`, including type, unit, meaning, and provenance. Query supports only:

```text
select: 1..16 declared fields
where: equality against kind, in_service, name, alias, or asset_ref
sort: one declared selected field plus ascending/descending
limit: 1..200
```

Reject unknown fields before accessing a DataFrame. Return compact records and an artifact ref when the complete result is larger than the model-view limit.

- [ ] **Step 5: Implement topology endpoints and connected components**

Endpoints use the normalized branch record. Components use `pandapower.topology.create_nxgraph(net, respect_switches=True, include_out_of_service=False)` internally and return stable bus refs grouped by component. Neither operation runs `pp.runpp`.

- [ ] **Step 6: Persist network-fact evidence before returning**

The evidence document contains:

```json
{
  "evidence_type": "network_fact",
  "capability_id": "topology.branch.endpoints.get",
  "context_ref": "context:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "revision_ref": "revision:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "subject_ref": "asset:line:sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "facts": {
    "from_bus_ref": "asset:bus:sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "to_bus_ref": "asset:bus:sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  },
  "provenance": {
    "engine": "pandapower",
    "engine_version": "3.4.0",
    "source_alias": "pandapower:line:11"
  }
}
```

Write atomically, then return the evidence ref. Injected persistence failure must return `evidence_persist_failed` and no successful result.

- [ ] **Step 7: Replace dispatch with capability-only routing**

`operations.dispatch(request, workspace)` validates the contract schema with `Draft202012Validator`, routes by capability ID, converts domain failures into `CapabilityError`, and returns `unsupported_capability` for unknown IDs. Do not translate old operation names.

- [ ] **Step 8: Run tests and commit**

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_network_operations.py packages/grid-simulator/tests/test_datasets.py packages/grid-simulator/tests/test_topology.py packages/grid-simulator/tests/test_network_evidence.py -v
git add packages/grid-simulator
git commit -m "feat(topology): expose typed network facts and datasets"
```

---

### Task 7: Port AC power flow, result ranking, and N-1 to the new contracts

**Files:**
- Create: `packages/grid-simulator/src/grid_simulator/analyses.py`
- Modify: `packages/grid-simulator/src/grid_simulator/operations.py`
- Modify: `packages/grid-simulator/tests/conftest.py`
- Replace: `packages/grid-simulator/tests/test_powerflow.py`
- Replace: `packages/grid-simulator/tests/test_contingency.py`
- Create: `packages/grid-simulator/tests/test_analysis_errors.py`

**Interfaces:**
- Consumes: immutable `context_ref`, explicit solver profile, stable line asset refs.
- Produces: `result_ref`, `evidence_refs`, normalized branch results, actionable non-convergence, and partial N-1 outcomes.

- [ ] **Step 1: Write failing analysis and typed-error tests**

Use the shared `ControllablePandapowerEngine`: its normal path delegates to the real engine, `force_non_convergence=True` raises `LoadflowNotConverged`, and any line index in `non_convergent_outages` raises the same exception when that line is out of service. Add this fixture so scenario ordering is explicit:

```python
@pytest.fixture
def line_refs(grid: GridTestClient, context_ref: str) -> list[str]:
    references = []
    for identifier in ("0", "1"):
        result = grid.call(
            "model.element.get",
            {
                "context_ref": context_ref,
                "kind": "line",
                "namespace": "pandapower_index",
                "identifier": identifier,
            },
        )
        references.append(str(result["element"]["asset_ref"]))
    return references
```

```python
def test_ac_powerflow_records_effective_solver_and_evidence(grid, context_ref: str) -> None:
    result = grid.call("analysis.powerflow.ac.run", {"context_ref": context_ref})
    assert result["converged"] is True
    assert result["solver"]["algorithm"] == "nr"
    assert result["total_active_loss"]["unit"] == "MW"
    assert result["result_ref"].startswith("result:sha256:")
    assert result["evidence_refs"]


def test_n_minus_one_preserves_partial_scenario_failure(grid, context_ref: str, line_refs: list[str]) -> None:
    grid.engine.non_convergent_outages.add(1)
    result = grid.call(
        "analysis.contingency.n_minus_one.run",
        {"context_ref": context_ref, "branch_refs": line_refs[:2], "policy": "static-analysis-v1"},
    )
    assert result["status"] == "partial"
    assert [item["status"] for item in result["scenarios"]] == ["succeeded", "non_converged"]


def test_non_convergence_is_not_marked_retryable(grid, context_ref: str) -> None:
    grid.engine.force_non_convergence = True
    error = grid.call_error("analysis.powerflow.ac.run", {"context_ref": context_ref})
    assert error.code == "powerflow_non_converged"
    assert error.retryable is False
    assert "change_solver_profile" in error.allowed_recovery_actions
```

- [ ] **Step 2: Run and verify the new analysis surface fails**

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_powerflow.py packages/grid-simulator/tests/test_contingency.py packages/grid-simulator/tests/test_analysis_errors.py -v
```

Expected: FAIL until analysis calls consume `context_ref` and stable branch refs.

- [ ] **Step 3: Implement AC analysis with explicit defaults**

Use the v0.1 tested solver defaults as the named `ac-default-v1` profile. Accept only the contract-enumerated override values and bounds. Persist a complete normalized result containing bus, line, transformer, generator, load, external-grid, convergence, and loss records. Return a bounded summary plus `result_ref` and evidence refs.

Catch `pandapower.LoadflowNotConverged` separately. Return an actionable non-convergence error with diagnostics artifact and these legal recovery actions:

```text
inspect_network_diagnostics
change_solver_profile
report_non_convergence
```

- [ ] **Step 4: Implement branch ranking over persisted results**

`result.branches.rank` requires a current-run `result_ref`, accepts enum sort fields `loading_percent`, `p_from_mw`, `p_to_mw`, or `pl_mw`, explicit direction, and limit 1..100. It returns stable asset refs and units. It does not reload or rerun power flow.

- [ ] **Step 5: Implement N-1 with independent scenarios**

Resolve every stable branch ref against the context revision. Deep-copy the base network for each outage, mark only the selected line or transformer out of service, run AC, and discard the copy. Persist one scenario result/evidence document per branch before aggregating. A scenario failure does not roll back other scenarios; the aggregate status is `succeeded`, `partial`, or `failed`.

- [ ] **Step 6: Run numerical goldens and commit**

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -v
git add packages/grid-simulator
git commit -m "feat(analysis): port AC and N-1 to semantic capabilities"
```

Expected: IEEE-39 total active loss and ranked-line fixtures remain within their existing pandapower 3.4.0 tolerances; all new typed-error tests pass.

---

### Task 8: Write the complete WP-A Skill and controlled guide index

**Files:**
- Create: `skills/grid-static-analysis/SKILL.md`
- Create: `skills/grid-static-analysis/references/capability-map.md`
- Create: `skills/grid-static-analysis/references/model-and-context.md`
- Create: `skills/grid-static-analysis/references/network-elements.md`
- Create: `skills/grid-static-analysis/references/topology-analysis.md`
- Create: `skills/grid-static-analysis/references/ac-powerflow.md`
- Create: `skills/grid-static-analysis/references/contingency-analysis.md`
- Create: `skills/grid-static-analysis/references/result-query.md`
- Create: `skills/grid-static-analysis/references/evidence-and-recovery.md`
- Create: `skills/grid-static-analysis/references/future-capabilities.md`
- Create: `packages/grid-agent/src/grid_agent/tools/guide.py`
- Create: `packages/grid-agent/tests/tools/test_guide.py`
- Create: `packages/grid-agent/tests/conftest.py`
- Create: `packages/grid-agent/tests/contract/test_skill.py`

**Interfaces:**
- Consumes: published Skill resource ID, capability registry.
- Produces: `GuideIndex.open(resource_id) -> GuideDocument` and complete operational guidance for every advertised WP-A capability.

- [ ] **Step 1: Write failing Skill completeness and traversal tests**

The contract tests read the simulator's versioned JSON definitions as documents; the agent package never imports simulator Python:

```python
# packages/grid-agent/tests/conftest.py
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def capability_documents() -> tuple[dict[str, object], ...]:
    definition_root = ROOT / "packages/grid-simulator/src/grid_simulator/capabilities/definitions"
    return tuple(json.loads(path.read_text(encoding="utf-8")) for path in sorted(definition_root.glob("*.json")))
```

Then write the Skill tests:

```python
from pathlib import Path

import pytest

from grid_agent.tools.guide import GuideIndex, GuideNotFound


ROOT = Path(__file__).resolve().parents[4]


def test_skill_has_guidance_for_every_advertised_capability(capability_documents) -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "skills/grid-static-analysis").rglob("*.md"))
    missing = [document["id"] for document in capability_documents if str(document["id"]) not in text]
    assert missing == []


def test_guide_index_opens_only_published_resources() -> None:
    guide = GuideIndex.load(ROOT / "skills/grid-static-analysis")
    assert "topology.branch.endpoints.get" in guide.open("topology-analysis").text
    with pytest.raises(GuideNotFound):
        guide.open("../../.env")
```

- [ ] **Step 2: Run and verify Skill resources are absent**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/tools/test_guide.py packages/grid-agent/tests/contract/test_skill.py -v
```

Expected: FAIL because the Skill and guide index do not exist.

- [ ] **Step 3: Write the root Skill as an operational navigation contract**

The root file contains exactly these sections with direct links to the references:

```markdown
---
name: grid-static-analysis
description: Analyze registered power-system networks with pandapower 3.4.0 domain tools. Use for network data, topology, AC power flow, branch ranking, N-1 contingencies, result interpretation, and evidence-backed grid conclusions.
---

# Grid Static Analysis

## Operating Rules
## Choose the Analysis Domain
## Context and Evidence Discipline
## Simple Questions
## Multi-step Analysis
## Failure Recovery
## Capability Status
```

Operating rules distinguish knowledge, network facts, and calculation results; forbid invented values; require explicit contexts; and require current-run evidence for network-specific claims.

- [ ] **Step 4: Write complete WP-A domain references**

Each implemented reference contains these sections:

```markdown
# <Domain>
## Use This For
## Do Not Use This For
## Concepts and Terminology
## Available Capabilities
## Parameters and Defaults
## Result Fields and Units
## Single-step Examples
## Multi-step Examples
## Failures and Legal Recovery
## Evidence Requirements
## Common Mistakes
```

Required guidance includes:

- topology endpoints are source topology and not real-time flow direction;
- source aliases such as `pandapower:line:11` are resolvable identifiers, while stable refs are used for composition;
- AC requires a context, an explicit/default solver profile, and convergence checking;
- ranking consumes a prior result and must not rerun power flow;
- N-1 starts from the same base revision, isolates each scenario, reports non-convergence and partial success, and never mutates the base network;
- non-convergence is not blindly retried;
- evidence refs are required for topology and numerical claims;
- `future-capabilities.md` explicitly lists DC flow, OPF, short circuit, state estimation, time series, model import/create/modify, richer policy/risk, and multiple registered networks as unavailable in WP-A.

Use the Datathings pandapower Skill only as a coverage reference. Rewrite every Python/DataFrame workflow into the WP-A domain capabilities and verify facts against pandapower 3.4.0 documentation.

- [ ] **Step 5: Implement the allowlisted guide index**

`GuideIndex.load(skill_root)` indexes `SKILL.md` as `overview` and each file directly under `references/` by filename stem. `open()` accepts `^[a-z0-9][a-z0-9-]+$`, rejects separators and percent-encoded separators, resolves the indexed absolute path, and returns title plus full text.

- [ ] **Step 6: Run Skill checks and commit**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/tools/test_guide.py packages/grid-agent/tests/contract/test_skill.py -v
git add skills packages/grid-agent/src/grid_agent/tools packages/grid-agent/tests/tools packages/grid-agent/tests/contract
git commit -m "docs(skill): publish complete static-analysis guidance"
```

Expected: every WP-A capability ID occurs in meaningful guidance; no missing resource or traversal is accepted.

---

### Task 9: Generate precise Pi domain tools and remove shell/read exposure

**Files:**
- Create: `packages/grid-agent/src/grid_agent/tools/catalog.py`
- Create: `packages/grid-agent/tests/tools/test_catalog.py`
- Create: `packages/pi-grid-tools/src/domain-tools.mjs`
- Create: `packages/pi-grid-tools/test/domain-tools.test.mjs`
- Delete: `packages/pi-grid-tools/src/hardened-bash.mjs`
- Delete: `packages/pi-grid-tools/test/hardened-bash.test.mjs`
- Modify: `packages/pi-grid-tools/package.json`
- Modify: `packages/grid-agent/src/grid_agent/runtime/environment.py`
- Modify: `packages/grid-agent/tests/runtime/test_pi_config.py`

**Interfaces:**
- Consumes: semantic capability list, published Skill index, run workspace.
- Produces: `ToolCatalog.materialize(path)`, direct `grid_*` Pi tools, `grid_guide_open`, and `grid_submit_answer` with no builtin filesystem or shell tools.

- [ ] **Step 1: Write failing catalog and Pi launch tests**

```python
def test_catalog_preserves_semantic_tool_description(capability_documents) -> None:
    catalog = ToolCatalog.from_documents(capability_documents)
    tool = catalog.require("grid_topology_branch_endpoints")
    assert "连接" in tool.description
    assert "不表示实时功率方向" in tool.description
    assert tool.input_schema["additionalProperties"] is False


def test_pi_launch_exposes_only_project_tools(resolved, runtime_paths) -> None:
    launch = build_pi_launch(resolved, runtime_paths)
    joined = " ".join(launch.argv)
    assert "domain-tools.mjs" in joined
    assert "hardened-bash.mjs" not in joined
    assert "grid_query" not in joined
    assert "--no-builtin-tools" in launch.argv
```

Node tests assert catalog schema passthrough, secret removal, request correlation, guide traversal rejection, answer-draft writing, and absence of registered `bash`, `read`, `write`, or `edit` tools.

- [ ] **Step 2: Run and verify the new tool materialization is absent**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/tools/test_catalog.py packages/grid-agent/tests/runtime/test_pi_config.py -v
npm test --prefix packages/pi-grid-tools
```

Expected: FAIL until the catalog and new extension exist.

- [ ] **Step 3: Implement model-facing descriptions from contracts**

`ToolCatalog.from_documents()` validates each document against the agent-side materialization schema and builds descriptions in this exact order:

```text
Purpose: <purpose>
Use for: <applies_to>
Do not use for: <not_for>
Requires: <requires>
Produces: <produces>
Common next capabilities: <common_next>
Recovery: <error -> actions>
```

It preserves the exact input schema and writes a deterministic sorted JSON catalog with a SHA-256 fingerprint.

- [ ] **Step 4: Implement `domain-tools.mjs`**

The extension:

1. reads only paths passed through `GRID_AGENT_TOOL_CATALOG`, `GRID_AGENT_GUIDE_INDEX`, `GRID_AGENT_WORKSPACE`, and `GRID_AGENT_ANSWER_DRAFT`;
2. validates each resolved path is inside its configured root;
3. registers one `defineTool` per contract using `Type.Unsafe(input_schema)`;
4. sends `{protocol:"grid-capability",protocol_version:"1.0",request_id,capability,arguments}` to `gridctl` by argument-array `spawn`;
5. validates correlation and maps failed responses to `isError: true` without discarding the typed error;
6. registers `grid_guide_open` over the published guide index;
7. registers `grid_submit_answer`, which atomically writes `{answer_output, claim_evidence_refs}` to the configured draft path.

Sanitize all provider credential variables from the `gridctl` child environment. Do not register a generic Bash tool.

- [ ] **Step 5: Cut Pi launch over to the new extension**

Replace prompt-path input in `RuntimePaths` with:

```python
tool_catalog_path: Path
guide_index_path: Path
answer_draft_path: Path
system_policy_path: Path
```

Launch Pi with the stable system policy, the new extension, and `--no-builtin-tools`. Do not pass any built-in tool list.

- [ ] **Step 6: Run Python and Node tests and commit**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/tools packages/grid-agent/tests/runtime/test_pi_config.py -v
npm run check --prefix packages/pi-grid-tools
npm test --prefix packages/pi-grid-tools
git add packages/grid-agent packages/pi-grid-tools
git commit -m "feat(tools): expose semantic grid tools to Pi"
```

---

### Task 10: Cut the agent and gridctl clients over to the new domain path

**Files:**
- Replace: `packages/grid-agent/src/grid_agent/simulator/client.py`
- Create: `packages/grid-agent/src/grid_agent/knowledge/__init__.py`
- Create: `packages/grid-agent/src/grid_agent/knowledge/offline.py`
- Create: `packages/grid-agent/tests/knowledge/test_offline.py`
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py`
- Modify: `packages/grid-agent/tests/simulator/test_client.py`
- Modify: `packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py`
- Create: `configs/agent/system-policy.md`
- Delete: `configs/prompts/grid-agent-system.md`
- Modify: `packages/grid-simulator/src/grid_simulator/cli.py`

**Interfaces:**
- Consumes: `GridctlClient.invoke(capability, arguments)`, reviewed offline knowledge, tool catalog, answer draft.
- Produces: strict answer envelope, no-run informational answers, simulator-backed runs under `runs/`, and typed limitation envelopes.

- [ ] **Step 1: Write failing client and route tests**

```python
def test_client_invokes_named_capability(fake_gridctl, tmp_path) -> None:
    result = GridctlClient(executable=fake_gridctl, workspace=tmp_path).invoke("model.list", {})
    assert result["models"][0]["model_id"] == "ieee39"
    assert fake_gridctl.last_request()["protocol"] == "grid-capability"
    assert "operation" not in fake_gridctl.last_request()


def test_information_answer_creates_no_run_directory(cli_runner, tmp_path) -> None:
    result = cli_runner(tmp_path, "母线电压正常运行范围是多少?", offline=True)
    assert result.returncode == 0
    assert not (tmp_path / "runs").exists()
    assert "0.95" in result.answer and "1.05" in result.answer


def test_topology_answer_uses_current_run_evidence(cli_runner, tmp_path) -> None:
    result = cli_runner(tmp_path, "IEEE-39节点系统中线路11连接哪两个母线?", offline=True)
    assert result.returncode == 0
    evidence = list((tmp_path / "runs" / result.question_id / "evidence").glob("*.json"))
    assert evidence
    assert "6" in result.answer and "11" in result.answer
```

- [ ] **Step 2: Run and verify legacy client/routing fails the new contract**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/simulator/test_client.py packages/grid-agent/tests/knowledge/test_offline.py packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py -v
```

Expected: FAIL because the client still sends `operation`, `_answer` still owns hard-coded routing, and paths still create legacy workspaces.

- [ ] **Step 3: Implement typed simulator client errors**

```python
class SimulatorCapabilityError(GridctlClientError):
    def __init__(self, error: dict[str, object]) -> None:
        super().__init__(str(error.get("message", "Grid capability failed")))
        self.error = error


def invoke(self, capability: str, arguments: dict[str, object]) -> dict[str, object]:
    request = {
        "protocol": "grid-capability",
        "protocol_version": "1.0",
        "request_id": f"sim-{uuid4().hex}",
        "capability": capability,
        "arguments": arguments,
    }
    # Existing strict one-line subprocess and correlation checks remain.
```

Preserve the complete typed error payload on failure.

- [ ] **Step 4: Implement reviewed offline knowledge without simulator state**

`offline.py` defines three versioned knowledge entries for voltage policy meaning, N-1 violation types, and AC tool inputs. Each entry records the source policy or Skill resource ID. `answer_information(question)` returns a string only when the question unambiguously asks one of these concepts; otherwise it returns `None`. It never creates a workspace or imports simulator code.

- [ ] **Step 5: Replace `_answer` with capability-based offline execution**

The offline path performs this order:

1. call `answer_information`; return directly when non-`None`;
2. create `runs/<question_id>` only now;
3. invoke `context.open` for the explicitly recognized registered model;
4. for the WP-A offline smoke grammar, resolve topology, AC, ranking, or N-1 into direct named capabilities;
5. answer only from returned structured results and evidence;
6. return a truthful limitation for unsupported language or capabilities.

This small offline grammar is a deterministic diagnostic path and is not used as the real-provider intent resolver. Put it in `grid_agent/knowledge/offline.py`, not in the CLI function.

- [ ] **Step 6: Wire the online Pi path**

For online runs:

- create the run workspace;
- invoke `environment.describe` and materialize all WP-A tools without lexical pre-filtering;
- materialize the Skill guide index;
- start Pi with `configs/agent/system-policy.md`;
- require `grid_submit_answer` to create the draft;
- verify every submitted evidence ref exists under the current run;
- emit the strict final envelope.

The system policy contains only safety, evidence, context, truthful-limitation, and answer-submission invariants. It contains no network IDs, question patterns, operation sequences, or current capability list.

- [ ] **Step 7: Replace the gridctl CLI parser**

Parse `GridCapabilityRequest`, return `GridCapabilityResponse`, and use this exact invalid-input error:

```python
CapabilityError(
    code="invalid_request",
    phase="parse",
    message="Request must be a valid grid-capability 1.0 JSON object",
    retryable=False,
    allowed_recovery_actions=("correct_request",),
)
```

- [ ] **Step 8: Run focused end-to-end tests and commit**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/simulator packages/grid-agent/tests/knowledge packages/grid-agent/tests/e2e -v
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -v
git add configs/agent packages/grid-agent packages/grid-simulator configs/prompts
git commit -m "feat(agent): cut over to semantic capability execution"
```

Expected: informational answers create no `runs/`; topology and numerical answers create current-run evidence; legacy prompt file is deleted.

---

### Task 11: Make validation executable, remove legacy artifacts, and close WP-A

**Files:**
- Modify: `validation/run.py`
- Add: remaining `validation/suites/task-required/*.json`
- Add: `validation/suites/static-analysis-core/*.json`
- Create: `packages/grid-agent/tests/e2e/test_semantic_pi_path.py`
- Create: `packages/grid-agent/tests/contract/test_repository_boundary.py`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `docs/RUNBOOK.md`
- Modify: `AGENTS.md`
- Delete: `knowledge/analyses/ac-power-flow.md`
- Delete: `knowledge/analyses/n-minus-one.md`
- Delete: `knowledge/concepts/per-unit-and-evidence.md` after reviewed content moves into Skill
- Delete: `knowledge/policies/static-analysis-v1.md` after policy explanation moves into Skill
- Delete: `knowledge/index.json`
- Delete: empty `runtime/` and `configs/prompts/` directories

**Interfaces:**
- Consumes: strict CLI envelope, run traces, capability contracts, Skill resources, deterministic oracles.
- Produces: `make validate`, WP-A coverage report, cleaned source tree, and documented operator workflow.

- [ ] **Step 1: Add the complete WP-A validation cases**

Add TASK cases for:

- line 11 endpoints;
- voltage range knowledge;
- N-1 violation-type knowledge;
- AC tool input knowledge;
- IEEE-39 AC loss;
- top-five line loading;
- line 171 truthful limitation in IEEE-39;
- critical-line outage ordering using the WP-A supported policy;
- voltage/overload risk request reported as partial capability when WP-B risk evaluation is unavailable.

Add static-core cases for line lookup by alias, bus listing, branch dataset schema, components, invalid field recovery, AC non-convergence injection, N-1 partial failure, stale result ref, and evidence mismatch.

Each case names a deterministic oracle, required/forbidden capabilities, max tool calls, and evidence requirement. Unsupported WP-B capability cases require an explicit limitation and never accept invented output.

- [ ] **Step 2: Complete the validation runner**

Support these exact modes:

```text
--mode offline
--mode scripted-pi
--mode provider --provider <id> --model <id>
--suite <name>
--report <path>
```

Offline and scripted-Pi modes are mandatory CI. Provider mode requires explicit credentials and records provider/model, tool trace, token/latency when available, and cost metadata without storing secrets. The report separates oracle pass, capability-constraint pass, evidence pass, and envelope pass.

- [ ] **Step 3: Write the scripted Pi semantic-path test**

The fake Pi must call the real `gridctl` using the catalog-defined capability IDs, not hard-coded legacy operations. It opens the Skill topology guide, opens IEEE-39 context, calls `topology.branch.endpoints.get`, emits a canonical successful `tool_result` trace event containing the tool's typed result and `evidence_refs`, submits the answer with the returned evidence ref, and exits. Assert:

- no built-in `read` or shell event;
- no `grid_query` event;
- no power-flow call;
- the `tool_result` event result contains the oracle input fields `branch`, `from_bus`, and `to_bus`;
- the `tool_result` event contains non-empty `evidence_refs`;
- submitted evidence exists in the current run.

- [ ] **Step 4: Add supported Make targets**

```make
.PHONY: validate validate-provider

validate:
	uv run --project packages/grid-agent python validation/run.py --mode offline --suite task-required --report runs/validation-offline.json
	uv run --project packages/grid-agent python validation/run.py --mode scripted-pi --suite static-analysis-core --report runs/validation-scripted.json

validate-provider:
	uv run --project packages/grid-agent python validation/run.py --mode provider --suite task-required --provider "$(PROVIDER)" $(if $(MODEL),--model "$(MODEL)") --report runs/validation-provider.json
```

Include grid-mcp only in WP-D; do not add an empty MCP target in WP-A.

- [ ] **Step 5: Remove legacy source and assert it stays removed**

Delete the listed legacy knowledge files after verifying every retained concept appears in the Skill. Add a repository-boundary test:

```python
def test_legacy_runtime_paths_are_absent() -> None:
    root = Path(__file__).resolve().parents[4]
    forbidden = [
        root / "configs/prompts/grid-agent-system.md",
        root / "packages/pi-grid-tools/src/hardened-bash.mjs",
        root / "runtime/pi-runtime.lock.json",
        root / "knowledge/index.json",
    ]
    assert [str(path) for path in forbidden if path.exists()] == []
    source = "\n".join(path.read_text(encoding="utf-8") for path in (root / "packages").rglob("*.*") if path.suffix in {".py", ".mjs", ".json"})
    assert "class SimulatorRequest" not in source
    assert "request.operation" not in source
    assert "grid_query" not in source
```

- [ ] **Step 6: Update operator documentation**

Document:

- `runs/` versus `.grid-agent/`;
- pure informational answers create no run evidence;
- all model facts and calculations go through gridctl/pandapower 3.4.0;
- Skill role versus tool descriptions;
- `make validate` and optional billed `make validate-provider`;
- WP-A capability coverage and explicit WP-B limitations;
- how to inspect `events.jsonl`, `tool-results/`, evidence, and `answer.json`;
- no migration-time deletion of the user's existing main-worktree `var/` data.

- [ ] **Step 7: Run the complete WP-A gate**

```bash
make test
make test-e2e
make validate
git status --short
```

Expected:

- all Python and Node tests pass;
- every supported WP-A deterministic case passes;
- planned WP-B questions return truthful limitations rather than fabricated results;
- line 11 topology uses no power-flow capability and completes within four tool calls;
- stdout remains one strict answer envelope;
- status contains only the intended documentation/report exclusions, with reports under ignored `runs/`.

- [ ] **Step 8: Commit WP-A closure**

```bash
git add Makefile README.md AGENTS.md docs/RUNBOOK.md validation packages skills configs third-party-notices .gitignore
git commit -m "feat: complete semantic capability foundation"
```

After committing, journal the verification results and update the managed worklist to mark WP-A complete and WP-B ready for planning. Do not begin WP-B without its own reviewed implementation plan.

---

## WP-A Acceptance Gate

WP-A is accepted only when all of the following are demonstrated:

1. The implementation branch descends from `v0.1` and contains no current-main GSE implementation merge.
2. Only `grid-capability` 1.0 is public; old `operation` requests are rejected.
3. Line 11 resolves directly to buses 6 and 11 with current-run topology evidence and no power flow.
4. Dataset fields are discoverable and schema-enumerated; unknown fields return allowed fields and legal recovery.
5. AC, branch ranking, and N-1 produce the same pandapower 3.4.0 numerical results as v0.1 under the new context/result/evidence contracts.
6. Non-convergence is typed, non-retryable by default, and actionable; N-1 partial failures preserve successful scenario evidence.
7. The Skill is complete for every advertised WP-A capability and inaccessible outside its published resource index.
8. Pi exposes project domain tools, guide access, and answer submission only; no generic read, shell, or legacy `grid_query` exists.
9. Informational answers create no run workspace; simulator-backed answers write under `runs/<question_id>/`.
10. `.grid-agent/` contains only ignored internal auth/runtime/session state; versioned runtime configuration is under `configs/runtime/`.
11. TASK-required and static-core deterministic WP-A validation pass; unsupported WP-B requests produce truthful limitations.
12. Legacy prompts, protocol aliases, tools, knowledge duplicates, and misleading runtime/var path documentation are removed from the new branch.

## Follow-on Planning Triggers

Write the separate WP-B plan only after WP-A acceptance fixes the actual capability, dataset, Skill, and validation interfaces. WP-B then expands breadth across multiple registered networks, DC power flow, richer result operations, executable policy/risk, and the remaining `docs/TASK.md` static-security behavior. WP-C and WP-D remain dependent on those accepted interfaces.
