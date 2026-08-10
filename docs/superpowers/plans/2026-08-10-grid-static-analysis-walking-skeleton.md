# Grid Static Analysis Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest complete `grid-agent run` path that resolves one of five LLM providers, drives a pinned Pi RPC runtime, composes an isolated pandapower 3.4.0 `gridctl` environment, and always returns an auditable answer envelope.

**Architecture:** `grid-agent` is a lightweight Python CLI and controller that never imports pandapower. Separately locked `grid-simulator` exposes a versioned JSONL process protocol and writes evidence into the run workspace. Pi remains the model/tool loop; one tiny JavaScript extension replaces built-in Bash only to strip provider secrets from tool subprocesses.

**Tech Stack:** Python 3.12, uv, Pydantic 2, Typer, pytest, pandapower 3.4.0, Node.js 22.19+, npm, `@earendil-works/pi-coding-agent` 0.80.6, JSON/JSONL, subprocess stdio.

## Global Constraints

- Implement only design Section 18.1. Sections 18.2–18.4 are excluded.
- No first-party source, test, build command, or runtime command may import from or refer to `3th-party/`.
- `grid-agent` remains free of pandapower, NumPy, pandas, and SciPy.
- `grid-simulator` pins `pandapower==3.4.0` in its own environment and lock.
- Pin Pi source commit `2b3fda9921b5590f285165287bd442a25817f17b`, package `0.80.6`, and Node.js minimum `22.19.0`.
- Support exactly `openai`, `openrouter`, `deepseek`, `openai-codex`, and `minimax` in this release profile.
- Resolve configurable LLM fields as CLI > process environment > current-directory `.env` > built-in default; invalid winning values fail without fallback.
- API keys are environment-only and never command arguments, files, traces, simulator input, or Bash-tool child environment.
- `openai-codex` uses only project-owned OAuth state under `var/pi/agent/auth.json`; ordinary commands never read ambient Pi state.
- `grid-agent run` stdout is one JSON object with exactly `question_id` and `answer_output`; progress and diagnostics use stderr.
- Every run creates append-only JSONL trace data and evidence under `var/runs/<run_id>/` without a service or database.
- Numerical values come from simulator receipts. The LLM may interpret and cite them but may not invent or hand-calculate network results.
- Default tests are offline and non-billable. Live checks require `--probe-llm` or `GRID_AGENT_E2E_LIVE=1`.
- Apply red-green-refactor discipline and make the focused commit named by each task.

---

## Planned File Map

| Path | Responsibility |
|---|---|
| `.env.example`, `.gitignore` | Portable configuration example and secret/runtime exclusions. |
| `packages/grid-agent/` | Lightweight CLI, configuration, auth, Pi RPC, tracing, simulator client, and controller. |
| `packages/grid-simulator/` | Independent pandapower 3.4.0 protocol, operations, and evidence process. |
| `packages/pi-grid-tools/` | Pi Bash environment hardening only; native grid tools are excluded. |
| `runtime/pi-runtime.lock.json` | Pi repository, commit, package, executable, engine, and SRI identity. |
| `configs/llm-providers.json` | Versioned five-provider release catalog. |
| `configs/prompts/grid-agent-system.md` | Capability-first execution and evidence rules. |
| `configs/policies/static-analysis-v1.json` | Versioned voltage/loading limits. |
| `knowledge/` | Short concept, analysis, and policy cards copied into each workspace. |
| `tests/e2e/` | Offline scripted-Pi smoke and explicitly opted-in live smoke. |

---

### Task 1: Establish Independent Package and Lock Boundaries

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Modify: `pyproject.toml`
- Create: `packages/grid-agent/pyproject.toml`
- Create: `packages/grid-agent/src/grid_agent/__init__.py`
- Create: `packages/grid-agent/tests/contract/test_repository_boundaries.py`
- Create: `packages/grid-simulator/pyproject.toml`
- Create: `packages/grid-simulator/src/grid_simulator/__init__.py`
- Create: `packages/grid-simulator/tests/test_package.py`
- Create: `packages/pi-grid-tools/package.json`
- Create: `packages/pi-grid-tools/test/package.test.mjs`
- Create: `packages/grid-agent/uv.lock`
- Create: `packages/grid-simulator/uv.lock`
- Create: `packages/pi-grid-tools/package-lock.json`

**Interfaces:**
- Consumes: approved repository boundaries and Python `>=3.12`.
- Produces: commands `grid-agent` and `gridctl`, import roots `grid_agent` and `grid_simulator`, and three independent locks.

- [ ] **Step 1: Write failing boundary tests**

```python
# packages/grid-agent/tests/contract/test_repository_boundaries.py
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[4]

def test_agent_has_no_scientific_simulator_dependencies() -> None:
    data = tomllib.loads((ROOT / "packages/grid-agent/pyproject.toml").read_text())
    dependencies = " ".join(data["project"]["dependencies"]).lower()
    for forbidden in ("pandapower", "numpy", "pandas", "scipy"):
        assert forbidden not in dependencies

def test_runtime_sources_have_no_research_checkout_reference() -> None:
    roots = [ROOT / "packages", ROOT / "runtime", ROOT / "configs", ROOT / "knowledge"]
    checked = []
    for base in roots:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".toml", ".json", ".mjs", ".md"}:
                checked.append(path)
                assert "3th-party/" not in path.read_text(encoding="utf-8")
    assert checked
```

```python
# packages/grid-simulator/tests/test_package.py
import grid_simulator

def test_package_version() -> None:
    assert grid_simulator.__version__ == "0.1.0"
```

```javascript
// packages/pi-grid-tools/test/package.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import packageJson from "../package.json" with { type: "json" };

test("package pins the validated Pi API", () => {
  assert.equal(packageJson.dependencies["@earendil-works/pi-coding-agent"], "0.80.6");
});
```

- [ ] **Step 2: Run tests and verify package files are absent**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/contract/test_repository_boundaries.py -v
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_package.py -v
npm test --prefix packages/pi-grid-tools
```

Expected: each command fails because its manifest or import does not exist.

- [ ] **Step 3: Create minimal manifests and package roots**

```toml
# packages/grid-agent/pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "grid-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "filelock>=3.20,<4",
  "pydantic>=2.12,<3",
  "python-dotenv>=1.2,<2",
  "typer>=0.20,<1",
]

[project.scripts]
grid-agent = "grid_agent.cli.app:main"

[dependency-groups]
dev = ["pytest>=9,<10", "pytest-cov>=7,<8"]

[tool.hatch.build.targets.wheel]
packages = ["src/grid_agent"]
```

```toml
# packages/grid-simulator/pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "grid-simulator"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pandapower==3.4.0", "pydantic>=2.12,<3"]

[project.scripts]
gridctl = "grid_simulator.cli:main"

[dependency-groups]
dev = ["pytest>=9,<10"]

[tool.hatch.build.targets.wheel]
packages = ["src/grid_simulator"]
```

```json
{
  "name": "@grid-static-analysis/pi-grid-tools",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {"check": "node --check src/hardened-bash.mjs", "test": "node --test"},
  "dependencies": {"@earendil-works/pi-coding-agent": "0.80.6"},
  "engines": {"node": ">=22.19.0"}
}
```

Both `__init__.py` files contain `__version__ = "0.1.0"`. Keep the root project dependency-free and change only its description to `Capability-first grid static-analysis agent`.

- [ ] **Step 4: Add ignores and the non-secret environment template**

```gitignore
.env
.env.*
!.env.example
**/.venv/
**/node_modules/
**/__pycache__/
**/.pytest_cache/
**/.coverage
var/
```

```dotenv
GRID_AGENT_LLM_PROVIDER=openai
GRID_AGENT_LLM_MODEL=
GRID_AGENT_LLM_BASE_URL=
GRID_AGENT_LLM_API_KEY_ENV=
GRID_AGENT_LLM_TIMEOUT_SECONDS=180
GRID_AGENT_LLM_MAX_RETRIES=2
OPENAI_API_KEY=
OPENROUTER_API_KEY=
DEEPSEEK_API_KEY=
MINIMAX_API_KEY=
GRID_AGENT_OPENAI_ORGANIZATION=
GRID_AGENT_OPENAI_PROJECT=
GRID_AGENT_OPENROUTER_HTTP_REFERER=
GRID_AGENT_OPENROUTER_APP_NAME=
GRID_AGENT_PI_COMMAND=
GRID_AGENT_GRIDCTL_EXECUTABLE=
```

- [ ] **Step 5: Generate locks and run boundary tests**

```bash
uv lock --project packages/grid-agent
uv lock --project packages/grid-simulator
npm install --prefix packages/pi-grid-tools --package-lock-only
uv run --project packages/grid-agent pytest packages/grid-agent/tests/contract/test_repository_boundaries.py -v
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_package.py -v
npm test --prefix packages/pi-grid-tools
```

Expected: all tests pass and all three locks exist.

- [ ] **Step 6: Commit**

```bash
git add .gitignore .env.example pyproject.toml packages/grid-agent packages/grid-simulator packages/pi-grid-tools
git commit -m "build: establish isolated package boundaries"
```

---

### Task 2: Define Answer, Workspace, and Trace Contracts

**Files:**
- Create: `packages/grid-agent/src/grid_agent/contracts.py`
- Create: `packages/grid-agent/src/grid_agent/application/workspace.py`
- Create: `packages/grid-agent/src/grid_agent/observability/trace.py`
- Create: `packages/grid-agent/tests/test_contracts.py`
- Create: `packages/grid-agent/tests/test_trace.py`

**Interfaces:**
- Consumes: package from Task 1.
- Produces: `AnswerEnvelope`, `RunRequest`, `AttemptStatus`, `RunWorkspace.create()`, and `JsonlTraceWriter.append()`.

- [ ] **Step 1: Write failing public-shape and redaction tests**

```python
from grid_agent.contracts import AnswerEnvelope, AttemptStatus, RunRequest

def test_answer_envelope_has_exact_public_shape() -> None:
    envelope = AnswerEnvelope(question_id="q-1", answer_output="ok")
    assert envelope.model_dump() == {"question_id": "q-1", "answer_output": "ok"}

def test_plain_question_gets_id() -> None:
    request = RunRequest.from_text("run AC power flow")
    assert request.question_id.startswith("q-")
    assert AttemptStatus.EXECUTION_FAILED.value == "execution_failed"
```

```python
import json
from grid_agent.application.workspace import RunWorkspace
from grid_agent.observability.trace import JsonlTraceWriter

def test_trace_is_append_only_and_redacted(tmp_path) -> None:
    workspace = RunWorkspace.create(tmp_path, run_id="run-1")
    writer = JsonlTraceWriter(workspace.events_path, secret_values={"sk-secret"})
    writer.append("run_started", {"key": "sk-secret"})
    writer.append("run_finished", {"status": "answered_with_evidence"})
    records = [json.loads(line) for line in workspace.events_path.read_text().splitlines()]
    assert [record["sequence"] for record in records] == [1, 2]
    assert records[0]["payload"]["key"] == "[REDACTED]"
```

- [ ] **Step 2: Run tests and verify import failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/test_contracts.py packages/grid-agent/tests/test_trace.py -v`

Expected: FAIL because these modules do not exist.

- [ ] **Step 3: Implement exact contracts**

```python
from enum import StrEnum
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field

class AttemptStatus(StrEnum):
    ANSWERED_WITH_EVIDENCE = "answered_with_evidence"
    ANSWERED_FROM_GENERAL_KNOWLEDGE = "answered_from_general_knowledge"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    EXECUTION_FAILED = "execution_failed"

class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)

    @classmethod
    def from_text(cls, question: str) -> "RunRequest":
        return cls(question_id=f"q-{uuid4().hex}", question=question.strip())

class AnswerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    answer_output: str
```

Implement `RunWorkspace.create(root: Path, run_id: str | None = None)` with paths for `input.json`, `run.json`, `events.jsonl`, `answer.json`, `pi/`, `evidence/`, `corpus/`, and `bin/`. Implement `JsonlTraceWriter.append()` with sequence, UTC timestamp, recursive secret-substring redaction inside every string, one LF-terminated object, flush, and `os.fsync()`.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/test_contracts.py packages/grid-agent/tests/test_trace.py -v`

Expected: PASS with no secret text on disk.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent packages/grid-agent/tests
git commit -m "feat: add run and trace contracts"
```

---

### Task 3: Implement the Five-Provider Resolver

**Files:**
- Create: `configs/llm-providers.json`
- Create: `packages/grid-agent/src/grid_agent/config/models.py`
- Create: `packages/grid-agent/src/grid_agent/config/catalog.py`
- Create: `packages/grid-agent/src/grid_agent/config/resolver.py`
- Create: `packages/grid-agent/tests/config/test_resolver.py`
- Create: `packages/grid-agent/tests/config/test_catalog.py`

**Interfaces:**
- Consumes: `.env.example` and project OAuth status callback.
- Produces: `ProviderCatalog.load()`, `CliLLMOptions`, `ResolvedLLMConfig`, `ResolvedLLM`, and `resolve_llm()`.

- [ ] **Step 1: Write failing precedence/authentication tests**

```python
def test_cli_wins_over_process_and_dotenv(tmp_path, catalog) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GRID_AGENT_LLM_PROVIDER=deepseek\nDEEPSEEK_API_KEY=dotenv-key\n")
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="openai", model="gpt-5.5"),
        environ={"GRID_AGENT_LLM_PROVIDER": "openrouter", "OPENAI_API_KEY": "process-key"},
        env_file=env_file,
    )
    assert resolved.config.provider == "openai"
    assert resolved.config.field_sources["provider"] == "cli"
    assert resolved.secret.value == "process-key"

def test_codex_rejects_base_url_override(catalog) -> None:
    with pytest.raises(ConfigurationError, match="base URL"):
        resolve_llm(
            catalog=catalog,
            cli=CliLLMOptions(provider="openai-codex", base_url="https://proxy.invalid"),
            environ={},
            oauth_configured=lambda _: True,
        )

def test_minimax_uses_own_key_and_transport(catalog) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="minimax"),
        environ={"MINIMAX_API_KEY": "secret"},
    )
    assert resolved.config.credential_reference == "MINIMAX_API_KEY"
    assert resolved.config.compatibility_profile == "anthropic-messages"
```

- [ ] **Step 2: Run tests and verify missing catalog**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/config -v`

Expected: FAIL because catalog and resolver modules do not exist.

- [ ] **Step 3: Add exact release catalog**

```json
{
  "schema_version": 1,
  "descriptor_version": "2026-08-10.pi-0.80.6",
  "default_provider": "openai",
  "providers": {
    "openai": {"default_model":"gpt-5.5","base_url":"https://api.openai.com/v1","base_url_policy":"override_allowed","auth":{"kind":"api_key_env","default_env":"OPENAI_API_KEY"},"pi_provider":"openai","compatibility_profile":"openai-responses","supports_tools":true},
    "openrouter": {"default_model":"moonshotai/kimi-k2.6","base_url":"https://openrouter.ai/api/v1","base_url_policy":"override_allowed","auth":{"kind":"api_key_env","default_env":"OPENROUTER_API_KEY"},"pi_provider":"openrouter","compatibility_profile":"pi-built-in","supports_tools":true},
    "deepseek": {"default_model":"deepseek-v4-pro","base_url":"https://api.deepseek.com","base_url_policy":"override_allowed","auth":{"kind":"api_key_env","default_env":"DEEPSEEK_API_KEY"},"pi_provider":"deepseek","compatibility_profile":"pi-built-in","supports_tools":true},
    "openai-codex": {"default_model":"gpt-5.5","base_url":"https://chatgpt.com/backend-api","base_url_policy":"fixed","auth":{"kind":"pi_oauth","profile":"openai-codex"},"pi_provider":"openai-codex","compatibility_profile":"openai-codex-responses","supports_tools":true},
    "minimax": {"default_model":"MiniMax-M2.7","base_url":"https://api.minimax.io/anthropic","base_url_policy":"override_allowed","auth":{"kind":"api_key_env","default_env":"MINIMAX_API_KEY"},"pi_provider":"minimax","compatibility_profile":"anthropic-messages","supports_tools":true}
  }
}
```

- [ ] **Step 4: Implement field-by-field resolution**

Define frozen `CliLLMOptions`, `ResolvedLLMConfig`, `SecretValue(repr=False)`, and `ResolvedLLM`, and use the exact signature `resolve_llm(*, catalog, cli, environ, env_file=None, dotenv_values=None, oauth_configured=None)`. `ResolvedLLMConfig` contains provider, model, base URL, auth kind, credential reference, timeout, retries, Pi provider, compatibility profile, descriptor version, public headers, and per-field source map. Load `.env` without mutating `os.environ`; normalize empty optional values to unset. Map only the approved OpenAI organization/project and OpenRouter referer/title variables into public headers. Validate provider/model, absolute URL, loopback-only HTTP, positive timeout, nonnegative retries, auth presence, tool support, and fixed Codex URL. Never infer provider from keys.

- [ ] **Step 5: Run the complete resolver matrix**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/config -v`

Expected: PASS for five providers, four layers, custom key names, invalid winners, URLs, and Codex separation.

- [ ] **Step 6: Commit**

```bash
git add configs/llm-providers.json packages/grid-agent/src/grid_agent/config packages/grid-agent/tests/config
git commit -m "feat: resolve five LLM providers deterministically"
```

---

### Task 4: Pin, Install, Locate, and Diagnose the Pi Runtime

**Files:**
- Create: `runtime/pi-runtime.lock.json`
- Create: `runtime/licenses/PI-NOTICE.md`
- Create: `packages/grid-agent/src/grid_agent/runtime/lock.py`
- Create: `packages/grid-agent/src/grid_agent/runtime/installer.py`
- Create: `packages/grid-agent/src/grid_agent/runtime/locator.py`
- Create: `packages/grid-agent/tests/runtime/test_installer.py`
- Create: `packages/grid-agent/tests/runtime/test_locator.py`

**Interfaces:**
- Consumes: state directory and injected subprocess runner.
- Produces: `PiRuntimeLock.load()`, `PiRuntimeInstaller.install()`, `PiCommand(argv, identity)`, `PiOAuthHelper(argv, identity)`, and `PiRuntimeLocator.resolve()`.

- [ ] **Step 1: Write failing deterministic-installer tests**

```python
def test_installer_uses_detached_pinned_commit(tmp_path, fake_runner, runtime_lock) -> None:
    command = PiRuntimeInstaller(runtime_lock, tmp_path, runner=fake_runner).install()
    assert ["git", "fetch", "--depth", "1", "origin", runtime_lock.commit] in fake_runner.calls
    assert ["git", "checkout", "--detach", runtime_lock.commit] in fake_runner.calls
    assert ["npm", "ci"] in fake_runner.calls
    assert ["npm", "run", "build"] in fake_runner.calls
    assert command.identity.commit == "2b3fda9921b5590f285165287bd442a25817f17b"

def test_locator_marks_explicit_command_unmanaged(tmp_path) -> None:
    command = PiRuntimeLocator(tmp_path, {"GRID_AGENT_PI_COMMAND": "/opt/homebrew/bin/pi"}).resolve()
    assert command.argv == ("/opt/homebrew/bin/pi",)
    assert command.identity.source == "explicit_override"
```

- [ ] **Step 2: Run tests and verify runtime modules are absent**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -v`

Expected: FAIL because runtime lock and locator types do not exist.

- [ ] **Step 3: Add exact runtime identity**

```json
{
  "schema_version": 1,
  "source": {"repository": "https://github.com/earendil-works/pi.git", "commit": "2b3fda9921b5590f285165287bd442a25817f17b"},
  "package": {
    "name": "@earendil-works/pi-coding-agent",
    "version": "0.80.6",
    "directory": "packages/coding-agent",
    "executable": "dist/cli.js",
    "oauth_helper": "packages/ai/dist/cli.js",
    "npm_integrity": "sha512-vcfD6tOk402isLl3Cm/qbn2O10TvgroMp1+/fEGM24ZdvETFCdOYv5VZ7m59EI5fPsjfSJh+CpQ5bhBrhfOg7g=="
  },
  "runtime": {"node_minimum": "22.19.0"}
}
```

`PI-NOTICE.md` names the package, repository, commit, MIT license, and states that runtime acquisition is independent of research checkouts.

- [ ] **Step 4: Implement command-array installation and location**

Create `var/runtime/pi/source`, initialize Git if absent, set the exact origin, fetch the commit, checkout detached, run `npm ci`, run root `npm run build`, verify `packages/coding-agent/dist/cli.js`, then run `node <cli> --version`. Use argument arrays, explicit cwd, bounded timeouts, captured stderr, and no `shell=True`. A failed build never becomes active.

Locator order is explicit `GRID_AGENT_PI_COMMAND`, then the managed executable. It never searches research checkouts or ambient Pi configuration. Record path, source kind, version, commit, and lock SHA-256. Also resolve a same-release OAuth helper: managed source uses `<source>/packages/ai/dist/cli.js`; an explicit installed coding-agent command uses its sibling `node_modules/@earendil-works/pi-ai/dist/cli.js` and fails clearly if that pinned helper is unavailable.

- [ ] **Step 5: Run offline tests and local non-billable probe**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -v
GRID_AGENT_PI_COMMAND=/opt/homebrew/bin/pi uv run --project packages/grid-agent python -c 'from grid_agent.runtime.locator import PiRuntimeLocator; assert PiRuntimeLocator.from_cwd().probe().version == "0.80.6"'
```

Expected: tests pass without network and the local command reports `0.80.6` without model generation.

- [ ] **Step 6: Commit**

```bash
git add runtime packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime
git commit -m "feat: manage pinned Pi runtime"
```

---

### Task 5: Harden Pi Bash Without Replacing the Harness

**Files:**
- Create: `packages/pi-grid-tools/src/hardened-bash.mjs`
- Create: `packages/pi-grid-tools/test/hardened-bash.test.mjs`

**Interfaces:**
- Consumes: Pi extension API 0.80.6 and `GRID_AGENT_SECRET_ENV_NAMES`.
- Produces: default extension and pure `sanitizeEnvironment(env, names)` helper.

- [ ] **Step 1: Write failing secret-isolation tests**

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { sanitizeEnvironment } from "../src/hardened-bash.mjs";

test("removes canonical and resolver-selected secrets", () => {
  const clean = sanitizeEnvironment({
    PATH: "/safe/bin",
    OPENAI_API_KEY: "openai-secret",
    CUSTOM_PROVIDER_TOKEN: "custom-secret",
    GRID_AGENT_SECRET_ENV_NAMES: "CUSTOM_PROVIDER_TOKEN"
  }, ["OPENAI_API_KEY", "CUSTOM_PROVIDER_TOKEN"]);
  assert.deepEqual(clean, { PATH: "/safe/bin" });
});

test("does not mutate the Pi environment object", () => {
  const source = { PATH: "/bin", MINIMAX_API_KEY: "secret" };
  sanitizeEnvironment(source, ["MINIMAX_API_KEY"]);
  assert.equal(source.MINIMAX_API_KEY, "secret");
});
```

- [ ] **Step 2: Run tests and verify extension absence**

Run: `npm test --prefix packages/pi-grid-tools`

Expected: FAIL because `hardened-bash.mjs` does not exist.

- [ ] **Step 3: Implement same-name Bash override**

```javascript
import { createBashTool } from "@earendil-works/pi-coding-agent";

const CANONICAL_SECRET_NAMES = [
  "OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY"
];

export function sanitizeEnvironment(env, selectedNames = []) {
  const blocked = new Set([...CANONICAL_SECRET_NAMES, ...selectedNames, "GRID_AGENT_SECRET_ENV_NAMES"]);
  return Object.fromEntries(Object.entries(env).filter(([name]) => !blocked.has(name)));
}

export default function hardenedBashExtension(pi) {
  const selectedNames = (process.env.GRID_AGENT_SECRET_ENV_NAMES ?? "")
    .split(",").map((name) => name.trim()).filter(Boolean);
  const bashTool = createBashTool(process.cwd(), {
    spawnHook: ({ command, cwd, env }) => ({command, cwd, env: sanitizeEnvironment(env, selectedNames)})
  });
  pi.registerTool({...bashTool});
}
```

- [ ] **Step 4: Run Node checks**

```bash
npm ci --prefix packages/pi-grid-tools
npm run check --prefix packages/pi-grid-tools
npm test --prefix packages/pi-grid-tools
```

Expected: PASS; PATH remains while canonical and custom credentials are absent.

- [ ] **Step 5: Commit**

```bash
git add packages/pi-grid-tools
git commit -m "feat: isolate provider secrets from Pi bash"
```

---

### Task 6: Add Project-Owned OpenAI Codex OAuth Commands

**Files:**
- Create: `packages/grid-agent/src/grid_agent/auth/store.py`
- Create: `packages/grid-agent/src/grid_agent/auth/service.py`
- Create: `packages/grid-agent/tests/auth/test_store.py`
- Create: `packages/grid-agent/tests/auth/test_service.py`

**Interfaces:**
- Consumes: `PiOAuthHelper`, project state directory, and filelock.
- Produces: `ProjectAuthStore`, `AuthStatus`, and `AuthService.login/import_from_pi/status/logout`.

- [ ] **Step 1: Write failing selected-entry and redaction tests**

```python
import json

def test_import_copies_only_codex_oauth_entry(tmp_path) -> None:
    source = tmp_path / "global-auth.json"
    source.write_text('{"openai-codex":{"type":"oauth","access":"secret"},"openai":{"type":"api_key","key":"forbidden"}}')
    store = ProjectAuthStore(tmp_path / "project" / "auth.json")
    status = store.import_provider(source, "openai-codex")
    assert status.configured is True
    assert store.read_redacted() == {"openai-codex": {"type": "oauth", "configured": True}}
    assert set(json.loads(store.path.read_text())) == {"openai-codex"}
    assert (store.path.stat().st_mode & 0o777) == 0o600

def test_logout_never_changes_source(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"openai-codex":{"type":"oauth","access":"secret"}}')
    store = ProjectAuthStore(tmp_path / "project" / "auth.json")
    store.import_provider(source, "openai-codex")
    store.logout("openai-codex")
    assert "secret" in source.read_text()
    assert store.status("openai-codex").configured is False
```

- [ ] **Step 2: Run tests and verify auth modules are absent**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/auth -v`

Expected: FAIL because auth store and service do not exist.

- [ ] **Step 3: Implement project auth store**

Reject providers other than `openai-codex`, malformed JSON, non-object entries, non-OAuth credentials, and source symlinks. Use `auth.json.grid-agent.lock`, a temporary file in the destination directory plus `os.replace()`, directory mode `0700`, and file mode `0600`. `AuthStatus` contains only provider, auth kind, configured state, and numeric expiry when present. No token-bearing value appears in repr, logs, errors, or return values.

- [ ] **Step 4: Implement auth service over pinned Pi**

`login("openai-codex")` creates the project directory/file with `0700`/`0600`, holds the project lock, and invokes the same-release Pi OAuth helper:

```text
node <PiOAuthHelper> login openai-codex
```

Run it with cwd `<state>/pi/agent` so its `auth.json` is project-owned, and inherit the terminal for browser/device selection. Verify and chmod the project entry after success. `import_from_pi()` defaults to `~/.pi/agent/auth.json` but reads it only after explicit invocation. `logout()` edits only the project file.

- [ ] **Step 5: Run auth tests with fake Pi**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/auth -v`

Expected: PASS; fake login receives the project directory and exact login command, with no token in returned text.

- [ ] **Step 6: Commit**

```bash
git add packages/grid-agent/src/grid_agent/auth packages/grid-agent/tests/auth
git commit -m "feat: isolate Codex OAuth state"
```

---

### Task 7: Implement Simulator Protocol, Capability Registry, and Network Evidence

**Files:**
- Create: `packages/grid-simulator/src/grid_simulator/protocol.py`
- Create: `packages/grid-simulator/src/grid_simulator/capabilities.py`
- Create: `packages/grid-simulator/src/grid_simulator/workspace.py`
- Create: `packages/grid-simulator/src/grid_simulator/evidence.py`
- Create: `packages/grid-simulator/src/grid_simulator/engine.py`
- Create: `packages/grid-simulator/src/grid_simulator/operations.py`
- Create: `packages/grid-simulator/src/grid_simulator/cli.py`
- Create: `packages/grid-simulator/tests/test_protocol.py`
- Create: `packages/grid-simulator/tests/test_network_operations.py`

**Interfaces:**
- Consumes: pandapower 3.4.0 and caller-provided workspace.
- Produces: `SimulatorRequest`, `SimulatorResponse`, `OperationError`, `CapabilityRegistry`, `Pandapower340Engine`, and `dispatch()`.

- [ ] **Step 1: Write failing protocol and generic network tests**

```python
def request(operation: str, arguments: dict) -> SimulatorRequest:
    return SimulatorRequest(protocol_version="1.0", request_id="req-1", operation=operation, arguments=arguments)

def test_registry_is_discoverable(tmp_path) -> None:
    response = dispatch(request("capabilities.list", {}), tmp_path)
    ids = {item["id"] for item in response.result["capabilities"]}
    assert {"network.open", "element.resolve", "powerflow.run_ac", "results.lines", "contingency.run_lines"} <= ids

def test_line_index_11_resolves_user_bus_names(tmp_path) -> None:
    opened = dispatch(request("network.open", {"network": "ieee39"}), tmp_path)
    resolved = dispatch(request("element.resolve", {
        "network_ref": opened.result["network_ref"], "element": "line", "namespace": "index", "query": "11"
    }), tmp_path)
    assert resolved.result["element_id"] == "line:index:11"
    assert resolved.result["from_bus"]["name"] == "6"
    assert resolved.result["to_bus"]["name"] == "11"
```

- [ ] **Step 2: Run tests and verify protocol imports fail**

Run: `uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_protocol.py packages/grid-simulator/tests/test_network_operations.py -v`

Expected: FAIL because simulator protocol and operations do not exist.

- [ ] **Step 3: Implement strict schemas and transport**

```python
class SimulatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Literal["1.0"]
    request_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    arguments: dict[str, JsonValue]

class OperationError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, JsonValue] = Field(default_factory=dict)

class SimulatorResponse(BaseModel):
    protocol_version: Literal["1.0"] = "1.0"
    request_id: str
    ok: bool
    result: dict[str, JsonValue] | None = None
    error: OperationError | None = None
```

`gridctl request --workspace PATH` reads one JSON object from stdin, writes one compact JSON response plus LF to stdout, and sends diagnostics to stderr. Operation failures return `ok=false` with exit `0`; malformed transport returns a structured `invalid_request` response and exit `2`.

- [ ] **Step 4: Implement content-addressed network operations**

Allow only `ieee39`. `network.open` loads `case39()`, records engine/version/source, stable semantic SHA-256, counts, and `network_ref`, then stores pandapower JSON under `workspace/evidence/networks/<sha>.json`. Implement `capabilities.list`, `capabilities.describe`, `network.open`, `network.describe`, and `element.resolve`. Stable IDs are `<element>:index:<integer>`; bus responses include internal index and user-facing `name`. Return typed errors for unknown or ambiguous requests.

- [ ] **Step 5: Run protocol/network tests**

Run: `uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_protocol.py packages/grid-simulator/tests/test_network_operations.py -v`

Expected: PASS; line 11 resolves names 6 and 11 and no incidental logs reach stdout.

- [ ] **Step 6: Commit**

```bash
git add packages/grid-simulator/src packages/grid-simulator/tests
git commit -m "feat: expose capability-first simulator protocol"
```

---

### Task 8: Add AC, Result Query, Contingency, and Golden Receipts

**Files:**
- Create: `configs/policies/static-analysis-v1.json`
- Modify: `packages/grid-simulator/src/grid_simulator/engine.py`
- Modify: `packages/grid-simulator/src/grid_simulator/operations.py`
- Modify: `packages/grid-simulator/src/grid_simulator/evidence.py`
- Create: `packages/grid-simulator/tests/golden/ieee39-pandapower-3.4.0.json`
- Create: `packages/grid-simulator/tests/test_powerflow.py`
- Create: `packages/grid-simulator/tests/test_contingency.py`

**Interfaces:**
- Consumes: `network_ref`, policy `static-analysis-v1`, and explicit solver options.
- Produces: `powerflow.run_ac`, `results.lines`, and `contingency.run_lines` receipts with evidence IDs.

- [ ] **Step 1: Write failing numerical golden tests**

```python
def test_ieee39_ac_golden(dispatch_request) -> None:
    network_ref = dispatch_request("network.open", {"network": "ieee39"})["network_ref"]
    result = dispatch_request("powerflow.run_ac", {"network_ref": network_ref})
    assert result["converged"] is True
    assert result["total_active_loss_mw"] == pytest.approx(43.64112576084923, abs=1e-8)
    ranked = dispatch_request("results.lines", {"result_ref": result["result_ref"], "sort": "loading_percent", "limit": 5})
    assert [line["index"] for line in ranked["lines"]] == [21, 11, 26, 2, 29]

def test_line_11_outage_has_full_receipt(dispatch_request) -> None:
    network_ref = dispatch_request("network.open", {"network": "ieee39"})["network_ref"]
    result = dispatch_request("contingency.run_lines", {
        "network_ref": network_ref, "line_ids": ["line:index:11"], "policy": "static-analysis-v1"
    })
    scenario = result["scenarios"][0]
    assert scenario["converged"] is True
    assert scenario["max_line_loading_percent"] == pytest.approx(105.97543088358476, abs=1e-8)
    assert [item["index"] for item in scenario["overloaded_lines"]] == [7, 16, 17]
    assert scenario["evidence_id"]
```

- [ ] **Step 2: Run tests and verify operations are unsupported**

Run: `uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_powerflow.py packages/grid-simulator/tests/test_contingency.py -v`

Expected: FAIL with unsupported operation errors.

- [ ] **Step 3: Add policy and explicit solver options**

```json
{
  "schema_version": 1,
  "policy_id": "static-analysis-v1",
  "bus_voltage_pu": {"minimum": 0.95, "maximum": 1.05},
  "branch_loading_percent": {"maximum": 100.0}
}
```

```python
AC_OPTIONS = {
    "algorithm": "nr", "calculate_voltage_angles": True, "init": "dc",
    "max_iteration": 10, "tolerance_mva": 1e-8, "trafo_model": "t",
    "trafo_loading": "current", "enforce_q_lims": False, "check_connectivity": True,
}
```

- [ ] **Step 4: Implement deterministic evidence**

`powerflow.run_ac` loads a fresh artifact, calls `runpp` once with `AC_OPTIONS`, fails closed on non-convergence, and stores all bus/line/trafo rows plus summary. Total active loss is `sum(res_line.pl_mw) + sum(res_trafo.pl_mw) + sum(res_trafo3w.pl_mw)`. Receipts include solver options, version, network fingerprint, convergence, units, and policy.

`results.lines` allows sort keys `loading_percent`, `p_from_mw`, `p_to_mw`, and `pl_mw`, limit `1..100`, and deterministic descending value/index ordering. `contingency.run_lines` accepts at most 32 unique stable line IDs, deep-copies the clean network per scenario, outages exactly one line, runs identical AC options, captures complete violations/evidence, and continues after a typed non-convergence receipt.

- [ ] **Step 5: Commit exact golden fixture and run simulator suite**

```json
{
  "engine": "pandapower",
  "version": "3.4.0",
  "ieee39": {
    "line_11_end_bus_names": ["6", "11"],
    "total_active_loss_mw": 43.64112576084923,
    "top5_line_indices": [21, 11, 26, 2, 29],
    "line_11_outage_max_loading_percent": 105.97543088358476,
    "line_11_outage_overloaded_line_indices": [7, 16, 17]
  }
}
```

Run: `uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -v`

Expected: PASS against `pandapower==3.4.0`.

- [ ] **Step 6: Commit**

```bash
git add configs/policies packages/grid-simulator
git commit -m "feat: compute auditable static-analysis evidence"
```

---

### Task 9: Add Isolated Simulator Client and Concise Knowledge Corpus

**Files:**
- Create: `packages/grid-agent/src/grid_agent/simulator/locator.py`
- Create: `packages/grid-agent/src/grid_agent/simulator/client.py`
- Create: `packages/grid-agent/tests/simulator/test_client.py`
- Create: `knowledge/index.json`
- Create: `knowledge/concepts/per-unit-and-evidence.md`
- Create: `knowledge/analyses/ac-power-flow.md`
- Create: `knowledge/analyses/n-minus-one.md`
- Create: `knowledge/policies/static-analysis-v1.md`
- Create: `configs/prompts/grid-agent-system.md`

**Interfaces:**
- Consumes: workspace, executable path, and simulator JSON protocol.
- Produces: `GridctlLocator.resolve()`, `GridctlClient.call()`, copied corpus, and system prompt.

- [ ] **Step 1: Write failing subprocess-isolation tests**

```python
def test_client_uses_json_stdin_and_clean_stdout(tmp_path, fake_gridctl) -> None:
    client = GridctlClient(executable=fake_gridctl.executable, workspace=tmp_path, timeout_seconds=5)
    result = client.call("capabilities.list", {})
    assert result["capabilities"]
    sent = fake_gridctl.requests[0]
    assert sent["protocol_version"] == "1.0"
    assert sent["operation"] == "capabilities.list"

def test_agent_source_never_imports_pandapower() -> None:
    for path in Path("packages/grid-agent/src").rglob("*.py"):
        assert "import pandapower" not in path.read_text()
```

- [ ] **Step 2: Run tests and verify client imports fail**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/simulator -v`

Expected: FAIL because locator and client do not exist.

- [ ] **Step 3: Implement strict executable discovery and exchange**

Locator order is explicit `GRID_AGENT_GRIDCTL_EXECUTABLE`, then `<repo>/packages/grid-simulator/.venv/bin/gridctl` or Windows `Scripts/gridctl.exe`. Accept one executable path, not a shell command.

`GridctlClient.call()` creates a request UUID, runs `[executable, "request", "--workspace", workspace]`, sends one compact LF JSON record, captures streams separately, enforces timeout, rejects multiple/non-JSON stdout, validates version/request ID, converts `ok=false` into `SimulatorOperationError`, and records stderr only as diagnostics. It never imports simulator code.

- [ ] **Step 4: Write four short cards and operating prompt**

The index lists stable ID, kind, path, and version. Cards cover units/per-unit, evidence versus policy, AC inputs/options, N-1 violation classes, and configurable `0.95–1.05 pu` / `100%` release policy in fewer than 1,200 words total.

The system prompt contains these exact rules:

```text
Discover operations with capabilities.list/capabilities.describe before guessing parameters.
Use gridctl request with strict JSON and the workspace from GRID_AGENT_WORKSPACE.
Treat knowledge cards as concepts or policy, never as facts about a loaded network.
Treat simulator receipts as the only source for network-specific numerical claims.
Never calculate electrical values from prose or silently change solver/policy assumptions.
Cite evidence_id and stable element IDs in the final answer when simulation was used.
If information, capability, or execution is insufficient, state the limitation truthfully.
```

- [ ] **Step 5: Run client and corpus tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/simulator -v`

Expected: PASS; stdout is parsed once, stderr stays diagnostic, and all indexed cards exist.

- [ ] **Step 6: Commit**

```bash
git add packages/grid-agent/src/grid_agent/simulator packages/grid-agent/tests/simulator knowledge configs/prompts
git commit -m "feat: connect isolated simulator corpus"
```

---

### Task 10: Implement Pi Configuration Materialization and RPC Capture

**Files:**
- Create: `packages/grid-agent/src/grid_agent/runtime/pi_config.py`
- Create: `packages/grid-agent/src/grid_agent/runtime/rpc.py`
- Create: `packages/grid-agent/src/grid_agent/runtime/environment.py`
- Create: `packages/grid-agent/tests/fixtures/fake_pi_rpc.py`
- Create: `packages/grid-agent/tests/runtime/test_pi_config.py`
- Create: `packages/grid-agent/tests/runtime/test_rpc.py`
- Create: `packages/grid-agent/tests/runtime/test_provider_adapters.py`

**Interfaces:**
- Consumes: `ResolvedLLM`, `PiCommand`, workspace, trace writer, hardened extension, and gridctl PATH.
- Produces: `PiConfigMaterializer.materialize()`, `build_pi_environment()`, `build_pi_launch()`, and `PiRpcClient`.

- [ ] **Step 1: Write failing framing and five-provider tests**

```python
def test_rpc_requires_ack_before_agent_end(fake_pi_command, workspace, trace) -> None:
    client = PiRpcClient(fake_pi_command("agent_end_before_ack"), workspace, trace)
    client.start()
    with pytest.raises(PiProtocolError, match="before prompt acknowledgement"):
        client.prompt_and_wait("question")
    client.stop()

@pytest.mark.parametrize(("provider", "secret_name"), [
    ("openai", "OPENAI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"), ("openai-codex", None),
    ("minimax", "MINIMAX_API_KEY"),
])
def test_provider_launch(provider, secret_name, resolved_factory, runtime_paths) -> None:
    launch = build_pi_launch(resolved_factory(provider), runtime_paths)
    assert launch.argv[launch.argv.index("--provider") + 1] == provider
    assert "--api-key" not in launch.argv
    assert launch.environment["PI_CODING_AGENT_DIR"].endswith("var/pi/agent")
    assert launch.argv[launch.argv.index("--extension") + 1].endswith("hardened-bash.mjs")
    if secret_name:
        assert launch.environment["GRID_AGENT_SECRET_ENV_NAMES"] == secret_name
```

- [ ] **Step 2: Run tests and verify RPC modules are absent**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_pi_config.py packages/grid-agent/tests/runtime/test_rpc.py packages/grid-agent/tests/runtime/test_provider_adapters.py -v`

Expected: FAIL because configuration and RPC modules do not exist.

- [ ] **Step 3: Generate secret-free project Pi configuration**

Write project `settings.json` and `models.json` beneath `var/pi/agent/`, preserving an OAuth-only `auth.json`. `models.json` is `{}` for official URLs without public headers; otherwise it contains only:

```json
{"providers":{"<pi_provider>":{"baseUrl":"<validated override>","headers":{"<public-header>":"<public-value>"}}}}
```

Never write `apiKey`. Reject any API-key entry in project `auth.json`. Apply `0700`/`0600` where supported.

- [ ] **Step 4: Build minimal Pi environment and argv**

Allowlist PATH, HOME, platform temp and locale variables, explicitly approved certificate/proxy variables, `PI_CODING_AGENT_DIR`, `PI_CODING_AGENT_SESSION_DIR`, `PI_OFFLINE`, `GRID_AGENT_WORKSPACE`, and the selected API-key variable. Set `GRID_AGENT_SECRET_ENV_NAMES` to that variable. No LLM variable enters `GridctlClient`.

Launch:

```text
<PiCommand> --mode rpc --provider <pi_provider> --model <model>
--session-dir <run>/pi --system-prompt <prompt-file>
--no-extensions --no-skills --no-prompt-templates --no-context-files
--extension <pi-grid-tools>/src/hardened-bash.mjs --tools read,bash
```

Prepend run `bin/` to PATH so `gridctl` is callable.

- [ ] **Step 5: Implement strict LF JSONL lifecycle**

Use binary pipes, write one compact LF request, strip only trailing CR/LF, record every response/event before interpreting it, collect `message_update.assistantMessageEvent.type == "text_delta"`, require matching successful prompt acknowledgement before `agent_end`, handle early EOF with redacted stderr, and terminate then kill after two seconds. Never stream assistant text to stdout.

The fake Pi fixture implements success, prompt rejection, early EOF, end-before-ack, tool events, and secret-bearing stderr. When provider is `openai-codex`, `PiRpcClient` holds the same project auth lock for its full process lifetime so token refresh cannot race import, logout, or another project run.

- [ ] **Step 6: Run runtime/provider tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime -v`

Expected: PASS for five mappings, framing, cleanup, trace capture, and secret-free artifacts.

- [ ] **Step 7: Commit**

```bash
git add packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime packages/grid-agent/tests/fixtures
git commit -m "feat: drive Pi through audited RPC"
```

---

### Task 11: Compose `doctor`, `auth`, `runtime`, and Always-Answer `run`

**Files:**
- Create: `packages/grid-agent/src/grid_agent/application/controller.py`
- Create: `packages/grid-agent/src/grid_agent/application/bootstrap.py`
- Create: `packages/grid-agent/src/grid_agent/cli/app.py`
- Create: `packages/grid-agent/src/grid_agent/cli/input.py`
- Create: `packages/grid-agent/tests/cli/test_doctor.py`
- Create: `packages/grid-agent/tests/cli/test_auth.py`
- Create: `packages/grid-agent/tests/cli/test_run.py`
- Create: `packages/grid-agent/tests/application/test_controller.py`

**Interfaces:**
- Consumes: Tasks 2–10.
- Produces: `grid-agent doctor`, `runtime install`, `auth login/import/status/logout`, and `run`.

- [ ] **Step 1: Write failing CLI outcome tests**

```python
def test_run_stdout_is_exact_envelope(cli_runner, fake_controller) -> None:
    result = cli_runner.invoke(app, ["run", "What is N-1 checking?"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "question_id": fake_controller.question_id,
        "answer_output": fake_controller.answer,
    }

def test_configuration_failure_still_returns_envelope(cli_runner, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = cli_runner.invoke(app, ["run", "question", "--provider", "openai", "--no-env-file"])
    assert result.exit_code != 0
    output = json.loads(result.stdout)
    assert set(output) == {"question_id", "answer_output"}
    assert "configuration" in output["answer_output"].lower()

def test_doctor_is_non_billable_by_default(cli_runner, fake_pi_rpc) -> None:
    result = cli_runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    assert fake_pi_rpc.prompt_count == 0
    assert "secret" not in result.stdout
```

- [ ] **Step 2: Run tests and verify application wiring is absent**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli packages/grid-agent/tests/application -v`

Expected: FAIL because controller and CLI app do not exist.

- [ ] **Step 3: Implement bootstrap and one-question controller**

Bootstrap creates workspace, writes `input.json`, copies knowledge into `corpus/knowledge`, writes capability descriptors to `corpus/capabilities.json`, creates run `bin/gridctl` symlink to the resolved executable, materializes the prompt, and starts tracing before fallible provider/runtime work.

`GridSessionController.run(request, llm)` starts Pi, sends one prompt, wraps returned text, writes `answer.json` and `run.json`, and closes processes in `finally`. Convert configuration, auth, runtime, simulator, Pi protocol, timeout, and unexpected failures into a truthful Chinese-and-English-readable limitation in the same envelope and nonzero exit category. Redacted technical detail remains only in trace.

- [ ] **Step 4: Implement Typer commands and input forms**

`run` accepts one positional question, `--input-json JSON`, or `--input-file PATH` as mutually exclusive sources. Preserve supplied `question_id`; generate one for plain or malformed machine input. Add shared `--provider`, `--model`, `--base-url`, `--api-key-env`, `--timeout-seconds`, `--max-retries`, and `--env-file/--no-env-file`.

Wire approved auth/runtime commands. `doctor --json` reports catalog, redacted credential reference, auth state, runtime identity, gridctl version, extension path, state-directory writability, and source map without a prompt. `doctor --probe-llm` warns on stderr and sends `Reply READY without tools` through the normal adapter.

- [ ] **Step 5: Run CLI/application failure-envelope tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli packages/grid-agent/tests/application -v`

Expected: PASS; every recognized run emits one envelope, stderr is diagnostic-only, and default doctor sends zero prompts.

- [ ] **Step 6: Commit**

```bash
git add packages/grid-agent/src/grid_agent/application packages/grid-agent/src/grid_agent/cli packages/grid-agent/tests/cli packages/grid-agent/tests/application
git commit -m "feat: deliver always-answer grid-agent CLI"
```

---

### Task 12: Verify Full Offline/Live Paths and Operator UX

**Files:**
- Create: `tests/e2e/test_offline_walking_skeleton.py`
- Create: `tests/e2e/test_live_walking_skeleton.py`
- Create: `tests/e2e/conftest.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: package environments, scripted Pi RPC, real gridctl, and optional configured provider.
- Produces: reproducible setup/run/test commands and acceptance evidence.

- [ ] **Step 1: Write failing offline E2E test**

```python
def test_offline_question_traverses_cli_pi_gridctl_evidence(
    grid_agent_command, scripted_pi_command, gridctl_executable, tmp_path
) -> None:
    env = {
        "GRID_AGENT_PI_COMMAND": scripted_pi_command,
        "GRID_AGENT_GRIDCTL_EXECUTABLE": str(gridctl_executable),
        "GRID_AGENT_LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "test-only-secret",
    }
    completed = subprocess.run(
        [*grid_agent_command, "run", "Run IEEE-39 AC power flow and report total active loss", "--no-env-file"],
        cwd=tmp_path, env={**minimal_test_os_env(), **env}, text=True, capture_output=True, timeout=60,
    )
    envelope = json.loads(completed.stdout)
    run_dir = only_run_dir(tmp_path / "var/runs")
    assert set(envelope) == {"question_id", "answer_output"}
    assert "43.64112576084923" in envelope["answer_output"]
    assert (run_dir / "events.jsonl").exists()
    assert list((run_dir / "evidence").rglob("*.json"))
    assert "test-only-secret" not in all_text_artifacts(run_dir)
```

The scripted Pi process must invoke real `gridctl request` from its received workspace; it may not embed the golden number.

- [ ] **Step 2: Run offline test and verify missing fixture path**

Run: `uv run --project packages/grid-agent pytest tests/e2e/test_offline_walking_skeleton.py -v`

Expected: FAIL until the fixture connects built CLI, fake Pi RPC, and separately installed gridctl.

- [ ] **Step 3: Implement offline trajectories and failures**

Scripted Pi reads the prompt, removes every name from `GRID_AGENT_SECRET_ENV_NAMES` before spawning gridctl, invokes real `capabilities.list`, `network.open {"network":"ieee39"}`, and `powerflow.run_ac`, then emits tool and text-delta events. Add general knowledge, line resolution, AC, line-11 contingency, unsupported operation, simulator crash, and Pi early-exit cases. Assert exact envelope shape, evidence when applicable, truthful limitations, clean stdout, and no secret artifact.

- [ ] **Step 4: Add explicit live smoke**

```python
@pytest.mark.skipif(os.getenv("GRID_AGENT_E2E_LIVE") != "1", reason="explicit live opt-in required")
def test_live_provider_answers_ieee39_line_question(grid_agent_command) -> None:
    completed = subprocess.run(
        [*grid_agent_command, "run", "IEEE-39节点系统中线路11连接哪两个母线?"],
        text=True, capture_output=True, timeout=300, check=True,
    )
    output = json.loads(completed.stdout)
    assert "6" in output["answer_output"] and "11" in output["answer_output"]
```

CI never sets live opt-in; provider/model and credentials come only from the normal resolver.

- [ ] **Step 5: Write exact operator commands in README**

```bash
uv sync --project packages/grid-agent
uv sync --project packages/grid-simulator
npm ci --prefix packages/pi-grid-tools
uv run --project packages/grid-agent grid-agent runtime install
uv run --project packages/grid-agent grid-agent doctor --json
uv run --project packages/grid-agent grid-agent auth import openai-codex --from-pi
uv run --project packages/grid-agent grid-agent run "IEEE-39节点系统中线路11连接哪两个母线?" --provider openai-codex
```

Document API-key and MiniMax examples, precedence, probe billing warning, stdout/stderr, run artifacts, independent lock updates, and the local-development Bash boundary. Never instruct installation from research checkouts. Verify the design header remains `Approved` and that its security section records the Bash child-secret override.

- [ ] **Step 6: Run full non-billable verification**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests tests/e2e/test_offline_walking_skeleton.py -v
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -v
npm run check --prefix packages/pi-grid-tools
npm test --prefix packages/pi-grid-tools
git grep -n "3th-party/" -- ':!docs/**' ':!findings.md' ':!progress.md' ':!task_plan.md'
git diff --check
```

Expected: Python/Node suites pass; live E2E is skipped; grep returns no matches; diff check emits nothing.

- [ ] **Step 7: Run one approved live acceptance when credentials are intentionally selected**

Run: `GRID_AGENT_E2E_LIVE=1 uv run --project packages/grid-agent pytest tests/e2e/test_live_walking_skeleton.py -v -s`

Expected: one real question traverses Pi and gridctl, returns the envelope, and produces trace/evidence with fingerprints and request IDs but no secrets.

- [ ] **Step 8: Commit**

```bash
git add README.md tests/e2e
git commit -m "test: verify walking skeleton end to end"
```

---

## Out-of-Scope Guardrail

Do not add continuous chat, session resume UI, persistent simulator service, native grid tools, SQLite, HTML reports, replay, experiments, external telemetry, OPF, short circuit, state estimation, time series, converters, vector search, or broad knowledge authoring. Their contracts remain valid, but implementation begins only after Task 12 passes.

## Final Acceptance Checklist

- [ ] Three packages build and test from independent locks.
- [ ] No first-party runtime/build/test path uses research checkouts.
- [ ] Agent environment has no pandapower/scientific stack.
- [ ] Five providers resolve deterministically with provider-specific auth.
- [ ] OAuth is project-owned; API keys remain environment-only and are stripped from Bash children.
- [ ] Default doctor is non-billable and redacted.
- [ ] Pi RPC framing, events, failures, and cleanup are contract-tested.
- [ ] Gridctl performs real pandapower 3.4.0 calculations in a separate process.
- [ ] Golden loss, ranking, identifier, and contingency checks pass within declared tolerances.
- [ ] Every run outcome returns exactly `question_id` and `answer_output` on stdout.
- [ ] Evidence-backed runs cite stable evidence IDs; failures never fabricate numerical evidence.
- [ ] Offline E2E passes and live E2E stays explicit and auditable.
