# Bilingual Repository Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish aligned English and Simplified Chinese repository entry points, a single stable Codex/Claude Code contract, and verified GitHub About/Topics metadata.

**Architecture:** `README.md` and `README.zh-CN.md` form the bilingual user/developer entry layer. `AGENTS.md` is the only mutable coding-agent contract, with `CLAUDE.md` as a relative symbolic link; volatile facts stay in versioned authoritative references. GitHub metadata is applied only after local documentation verification and is read back from GitHub before completion is claimed.

**Tech Stack:** Markdown, POSIX symbolic links, Make, Git, GitHub CLI (`gh`).

## Global Constraints

- `README.md` is the default English entry point; `README.zh-CN.md` is a section-aligned Simplified Chinese edition.
- `CLAUDE.md` must be the relative symbolic link `CLAUDE.md -> AGENTS.md`, never a copied file.
- `AGENTS.md` contains stable repository-wide rules only; mutable capability, version, runtime, and state details are referenced from authoritative files.
- Preserve the single JSON stdout envelope and the `grid-capability/1.0` simulator boundary in all descriptions.
- Do not change runtime behavior, repository visibility, homepage URL, provider credentials, or the `v1.0.0` tag.
- Do not stage or delete unrelated PDF, ZIP, test-script, user-manual, or validation-question artifacts. Preserve JOURNAL append-only semantics and rewrite RESUME only through the project-state checkpoint workflow after durable events.
- GitHub About must be exactly: `Capability-first CLI agent for evidence-backed power-system static analysis with pandapower.`
- GitHub Topics must be exactly the 14 approved topics listed in Task 4.

## File Structure

- Modify `AGENTS.md` — stable, tool-neutral repository contract for Codex and Claude Code.
- Create `CLAUDE.md` — relative symbolic link to `AGENTS.md`.
- Modify `README.md` — default English product and developer entry point.
- Create `README.zh-CN.md` — section-aligned Simplified Chinese entry point.
- Modify GitHub repository metadata — About description and Topics only; no local file represents this state.

---

### Task 1: Stable Cross-Agent Repository Contract

**Files:**
- Modify: `AGENTS.md`
- Create: `CLAUDE.md` as a symbolic link

**Interfaces:**
- Consumes: repository contracts in `configs/agent/system-policy.md`, `docs/RUNBOOK.md`, and `docs/architecture/pandapower-capability-composition.md`.
- Produces: one agent-instruction byte stream reachable as both `AGENTS.md` and `CLAUDE.md`.

- [ ] **Step 1: Verify the symlink acceptance check fails before implementation**

Run:

```sh
test -L CLAUDE.md && test "$(readlink CLAUDE.md)" = "AGENTS.md"
```

Expected: non-zero exit because `CLAUDE.md` does not exist yet.

- [ ] **Step 2: Replace `AGENTS.md` with the stable contract**

Use `apply_patch` to make `AGENTS.md` exactly:

```markdown
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
```

- [ ] **Step 3: Create the relative Claude Code link**

Run:

```sh
ln -s AGENTS.md CLAUDE.md
```

Expected: `CLAUDE.md` is a symbolic link whose stored target is exactly
`AGENTS.md`.

- [ ] **Step 4: Verify both tools receive identical instructions**

Run:

```sh
test -L CLAUDE.md
test "$(readlink CLAUDE.md)" = "AGENTS.md"
cmp -s AGENTS.md CLAUDE.md
git diff --check -- AGENTS.md CLAUDE.md
```

Expected: every command exits `0` with no output.

- [ ] **Step 5: Commit the cross-agent contract**

Run:

```sh
git add AGENTS.md CLAUDE.md
git diff --cached --check
git diff --cached --name-status
git commit -m "docs: unify coding agent instructions"
```

Expected staged paths: only `AGENTS.md` and `CLAUDE.md`.

---

### Task 2: Aligned English and Simplified Chinese README Pair

**Files:**
- Modify: `README.md`
- Create: `README.zh-CN.md`

**Interfaces:**
- Consumes: Makefile command names and the authoritative references listed in `AGENTS.md`.
- Produces: two section-aligned repository entry points with reciprocal language links.

- [ ] **Step 1: Verify bilingual acceptance checks fail before implementation**

Run:

```sh
test -f README.zh-CN.md
rg -q 'README\.zh-CN\.md' README.md
```

Expected: non-zero exit because the Chinese README does not exist and the
English README has no language switch.

- [ ] **Step 2: Replace the default English README**

Use `apply_patch` to make `README.md` exactly:

````markdown
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
make run QUESTION="Which buses are connected by line 11 in the IEEE 39-bus network?"
```

Run the primary natural-language agent path:

```sh
cp .env.example .env
# Configure one supported provider credential in the ignored .env file.
make install-pi
make run-llm QUESTION="Run an AC power flow on the IEEE 39-bus network and report active power losses."
```

For project-owned OpenAI Codex OAuth instead of an API key, use
`make auth-login`. See the [runbook](docs/RUNBOOK.md) for provider setup,
authentication precedence, runtime installation, and failure diagnosis.

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
````

- [ ] **Step 3: Add the aligned Simplified Chinese README**

Use `apply_patch` to create `README.zh-CN.md` exactly:

````markdown
# 电网静态分析

[English](README.md) | 简体中文

`grid-agent` 是一个能力优先、证据闭环的命令行代理，用于对已登记的电力系统网络执行静态分析。LLM 负责理解请求并组合项目定义的工具；`gridctl` 与固定版本的 pandapower 模拟器负责全部确定性网络计算。

`v1.0.0` 是声明的静态分析产品范围内首个稳定版本。当前覆盖情况始终以可执行能力矩阵为准。

## 功能范围

- 发现已登记网络，并通过受控声明式接口创建模型。
- 派生不可变网络修订和分析场景。
- 执行拓扑、AC/DC/三相潮流、AC/DC 最优潮流、IEC 60909 短路、状态估计、诊断、故障分析、风险评估、网络等值和静态保护分析。
- 查询、聚合、比较和排序由模拟器管理的结果数据集。
- 在多步骤分析和连续报告中复用经过验证的上下文。
- 记录原生执行轨迹，并提供只读调查工作台。
- 将最终数值结论绑定到当前运行的结果和证据引用。

项目覆盖的是声明的 pandapower 静态分析产品范围，而不是 pandapower 的全部公开 API。时序/控制工作流、绘图、任意文件或数据库转换，以及未固定的外部求解器运行时不属于模型能力边界。详见[能力架构](docs/architecture/pandapower-capability-composition.md)和[可执行覆盖矩阵](configs/capabilities/pandapower-3.4.0-static-analysis.json)。

## 系统架构

```text
自然语言请求
      |
      v
grid-agent + Pi/LLM       意图理解、工具组合、上下文、答案封装
      |
      v  grid-capability/1.0
gridctl + grid-simulator  契约、登记模型、结果、证据
      |
      v
pandapower                确定性电力系统计算
      |
      v
runs/<question_id>/       操作者可见的当前运行证据
```

LLM 只能选择已登记的语义工具，不能获得 shell、任意 Python、原始 pandapower 对象、DataFrame 或通用文件系统访问权。所有数值和网络特定结论都必须跨越模拟器边界返回。

## 快速开始

前置条件为 Python 3.12+、Node.js 22.19+、`uv` 和 `npm`。Provider 支持的分析还需要配置相应的 LLM 凭据；离线冒烟检查不需要 Provider。

```sh
git clone https://github.com/uukuguy/grid-static-analysis.git
cd grid-static-analysis
make setup
make doctor
```

执行确定性离线冒烟检查：

```sh
make run QUESTION="IEEE-39 节点系统中线路 11 连接哪两个母线？"
```

执行主要的自然语言代理路径：

```sh
cp .env.example .env
# 在 Git 忽略的 .env 文件中配置一个受支持的 Provider 凭据。
make install-pi
make run-llm QUESTION="对 IEEE-39 节点系统运行交流潮流，并报告有功网损。"
```

如需使用项目自有的 OpenAI Codex OAuth 而不是 API key，执行 `make auth-login`。Provider 配置、认证优先级、运行时安装和失败诊断详见[运行操作指南](docs/RUNBOOK.md)。

## 主要工作流

| 目标 | 命令 |
| --- | --- |
| 检查运行环境 | `make doctor` |
| 离线确定性冒烟检查 | `make run QUESTION="..."` |
| LLM 驱动的单题分析 | `make run-llm QUESTION="..."` |
| 连续多题分析 | `make analysis INSTRUCTIONS=path/to/instructions.txt` |
| 连续分析兼容别名 | `make report INSTRUCTIONS=path/to/instructions.txt` |
| 构建并启动只读工作台 | `make trajectory PORT=8765` |

`grid-agent run` 向 stdout 精确写入一个 JSON 对象：

```json
{"question_id":"...","answer_output":"..."}
```

进度、诊断和工具事件只写入 stderr。连续分析同样只输出一个最终答案封装，其 `answer_output` 指向生成的报告。

## 结果、证据与工作台

模拟器支持的运行将操作者可见工件写入 `runs/<question_id>/`。最终结论只能引用当前运行已经接纳的结果和证据。纯信息类离线回答不会创建仿真证据。

内部认证、托管 Pi 运行时、缓存和会话状态位于 Git 忽略的 `.grid-agent/` 目录；版本化运行配置位于 `configs/runtime/`。

启动本地只读轨迹工作台：

```sh
make trajectory PORT=8765
```

UI 和 API 默认位于 `http://127.0.0.1:8765`。工作台只投影已记录事实用于调查，不能修改运行记录，也不能替代模拟器事实。

## 验证

```sh
make doctor
make test
make test-e2e
make validate
```

`make validate-provider PROVIDER=<id> [MODEL=<id>]` 是可选命令，需要显式凭据，并可能产生 Provider 费用。

## 仓库结构

| 路径 | 职责 |
| --- | --- |
| `packages/grid-agent/` | CLI、Pi/LLM 运行时、上下文、轨迹、报告和答案封装 |
| `packages/grid-simulator/` | `gridctl`、登记模型、pandapower 执行、结果和证据 |
| `packages/pi-grid-tools/` | 项目限定的 Pi 工具、指南、请求捕获和答案提交 |
| `packages/trajectory-workbench/` | 只读 React/TypeScript 轨迹调查 UI |
| `configs/` | 版本化能力、策略、Provider 目录和运行配置 |
| `validation/` | 离线、脚本 Pi、语义和可选 Provider 验证套件 |
| `docs/` | 操作指南、架构、设计历史、计划和持久项目状态 |

## 文档索引

- [运行操作指南](docs/RUNBOOK.md) — 初始化、认证、执行、证据与故障排查。
- [人工验证手册](docs/MANUAL-VALIDATION.md) — 可复现的人工验收流程。
- [能力注册与组合推理](docs/architecture/pandapower-capability-composition.md) — 能力范围和 LLM 工具编排边界。
- [分析上下文架构](docs/architecture/analysis-context.md) — 经过验证的多步骤上下文模型。
- [轨迹事件架构](docs/architecture/trajectory-events.md) — 权威原生执行时间线。
- [当前项目状态](docs/status/CURRENT-STATE.md) — 结构快照与实现入口。
- [仓库 Agent 契约](AGENTS.md) — 稳定的 Codex/Claude Code 规则与事实来源。

## 安全与贡献边界

凭据只能存放在环境变量或 Git 忽略的项目认证状态中，不能进入命令参数、提交文件、日志、模拟器环境或证据。新增模型能力必须可复用、由契约定义、经过白名单，并由模拟器执行；禁止逐题捷径和任意执行面。
````

- [ ] **Step 4: Verify bilingual structure, reciprocal links, and local references**

Run:

```sh
test -f README.zh-CN.md
rg -q '\[简体中文\]\(README\.zh-CN\.md\)' README.md
rg -q '\[English\]\(README\.md\)' README.zh-CN.md
diff -u \
  <(sed -n 's/^\(##\+\).*/\1/p' README.md) \
  <(sed -n 's/^\(##\+\).*/\1/p' README.zh-CN.md)

for doc in README.md README.zh-CN.md AGENTS.md; do
  base_dir=$(dirname "$doc")
  while IFS= read -r target; do
    case "$target" in
      http:*|https:*|mailto:*|'#'*) continue ;;
    esac
    clean_target=${target%%#*}
    test -z "$clean_target" || test -e "$base_dir/$clean_target" || {
      echo "Missing link in $doc: $target" >&2
      exit 1
    }
  done < <(perl -ne 'while (/\]\(([^)]+)\)/g) { print "$1\n" }' "$doc")
done

git diff --check -- README.md README.zh-CN.md AGENTS.md CLAUDE.md
```

Expected: every command exits `0`; `diff` and link checking print nothing.

- [ ] **Step 5: Verify documented commands exist in the Makefile**

Run:

```sh
for target in setup doctor run run-llm install-pi auth-login analysis report trajectory test test-e2e validate validate-provider; do
  rg -q "^${target}:" Makefile || {
    echo "Missing Make target: $target" >&2
    exit 1
  }
done
```

Expected: exit `0` with no output.

- [ ] **Step 6: Commit the bilingual README pair**

Run:

```sh
git add README.md README.zh-CN.md
git diff --cached --check
git diff --cached --name-status
git commit -m "docs: publish bilingual project readme"
```

Expected staged paths: only `README.md` and `README.zh-CN.md`.

---

### Task 3: Local Documentation Acceptance Gate

**Files:**
- Verify: `AGENTS.md`
- Verify: `CLAUDE.md`
- Verify: `README.md`
- Verify: `README.zh-CN.md`

**Interfaces:**
- Consumes: committed outputs of Tasks 1 and 2.
- Produces: fresh local evidence that documentation, commands, and the agent link satisfy the approved design.

- [ ] **Step 1: Re-run the complete documentation contract**

Run:

```sh
test -L CLAUDE.md
test "$(readlink CLAUDE.md)" = "AGENTS.md"
cmp -s AGENTS.md CLAUDE.md
test -f README.zh-CN.md
rg -q '\[简体中文\]\(README\.zh-CN\.md\)' README.md
rg -q '\[English\]\(README\.md\)' README.zh-CN.md
diff -u \
  <(sed -n 's/^\(##\+\).*/\1/p' README.md) \
  <(sed -n 's/^\(##\+\).*/\1/p' README.zh-CN.md)
git diff --check
```

Expected: every command exits `0` with no output.

- [ ] **Step 2: Verify repository runtime discovery remains healthy**

Run:

```sh
make doctor
```

Expected: exit `0` and one JSON object containing a resolved `gridctl` path and
`"live_probe": false`.

- [ ] **Step 3: Confirm only unrelated pre-existing workspace changes remain**

Run:

```sh
git status --short --branch
git log -3 --oneline
```

Expected: README/AGENTS/CLAUDE paths are clean and committed. Existing
`docs/status/JOURNAL.md`, `docs/status/RESUME-NEXT-SESSION.md`, PDF, ZIP,
test-script, user-manual, and validation-question changes may remain and must not
be altered.

---

### Task 4: GitHub About and Topics Synchronization

**Files:**
- External state only: `uukuguy/grid-static-analysis` repository metadata

**Interfaces:**
- Consumes: approved About/Topics copy and successful Task 3 local gate.
- Produces: GitHub metadata verified by API read-back without changing visibility or homepage.

- [ ] **Step 1: Capture current GitHub state and authentication**

Run:

```sh
gh auth status
gh repo view uukuguy/grid-static-analysis \
  --json nameWithOwner,description,homepageUrl,repositoryTopics,isPrivate
```

Expected: authenticated access to `uukuguy/grid-static-analysis`; current
visibility and homepage are recorded before mutation.

- [ ] **Step 2: Set the approved About description and Topics**

Run:

```sh
gh repo edit uukuguy/grid-static-analysis \
  --description "Capability-first CLI agent for evidence-backed power-system static analysis with pandapower." \
  --add-topic "power-systems,power-grid,pandapower,static-analysis,power-flow,optimal-power-flow,short-circuit,contingency-analysis,state-estimation,llm-agent,ai-agent,python,cli,electrical-engineering"
```

Expected: exit `0`. Do not pass `--visibility` or `--homepage`.

- [ ] **Step 3: Read back and compare exact GitHub metadata**

Run:

```sh
gh repo view uukuguy/grid-static-analysis \
  --json description --jq '.description'
gh repo view uukuguy/grid-static-analysis \
  --json repositoryTopics --jq '.repositoryTopics[].name' | sort
gh repo view uukuguy/grid-static-analysis \
  --json homepageUrl,isPrivate --jq '{homepageUrl, isPrivate}'
```

Expected description:

```text
Capability-first CLI agent for evidence-backed power-system static analysis with pandapower.
```

Expected sorted Topics:

```text
ai-agent
cli
contingency-analysis
electrical-engineering
llm-agent
optimal-power-flow
pandapower
power-flow
power-grid
power-systems
python
short-circuit
state-estimation
static-analysis
```

Expected: `homepageUrl` and `isPrivate` match the values captured in Step 1.
If authentication, permission, or network access fails, stop and report GitHub
metadata as incomplete without changing local documentation claims.

- [ ] **Step 4: Record the external metadata event without creating a release commit**

Append this project-state fact with the current timestamp:

```text
GitHub About 与 14 个 Topics 已回读确认，与 v1.0 双语文档一致
```

Refresh the active checkpoint because the task's recovery boundary has changed.
Do not move or recreate `v1.0.0`.

---

### Task 5: Final Scope and Completion Verification

**Files:**
- Verify all task-owned paths and external metadata

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: final completion evidence and a concise handoff.

- [ ] **Step 1: Verify final local file identities**

Run:

```sh
git ls-files -s AGENTS.md CLAUDE.md README.md README.zh-CN.md
test "$(git ls-files -s CLAUDE.md | awk '{print $1}')" = "120000"
test "$(readlink CLAUDE.md)" = "AGENTS.md"
cmp -s AGENTS.md CLAUDE.md
git diff --check
make doctor
```

Expected: `CLAUDE.md` has Git mode `120000`; every test exits `0`; `make doctor`
prints valid JSON.

- [ ] **Step 2: Verify recent commits and untouched workspace artifacts**

Run:

```sh
git log -5 --oneline --decorate
git status --short --branch
```

Expected: the cross-agent contract and bilingual README commits are present.
Unrelated pre-existing status and untracked artifacts are unchanged.

- [ ] **Step 3: Read GitHub metadata one final time**

Run:

```sh
gh repo view uukuguy/grid-static-analysis \
  --json description,homepageUrl,repositoryTopics,isPrivate,url
```

Expected: About and all 14 Topics match Task 4; repository visibility and
homepage remain unchanged.

- [ ] **Step 4: Report completion**

Report:

- committed local documentation paths and commit hashes;
- `CLAUDE.md -> AGENTS.md` verification;
- English-default and Chinese README parity;
- `make doctor` and documentation-validation results;
- GitHub About/Topics read-back;
- unchanged unrelated working-tree artifacts;
- whether commits need pushing, without pushing unless explicitly authorized.
