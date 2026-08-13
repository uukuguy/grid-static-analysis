.DEFAULT_GOAL := help

.PHONY: help setup setup-agent setup-simulator setup-tools install-pi auth-import-pi auth-login doctor run run-llm analysis report test test-agent test-simulator test-tools test-e2e validate validate-provider

help:
	@echo "Grid Static Analysis commands"
	@echo "  make setup                 Install all local dependencies"
	@echo "  make doctor                Inspect local runtime readiness"
	@echo "  make run QUESTION='...'    Run a local deterministic smoke/offline check"
	@echo "  make run-llm QUESTION='...'  Primary natural-language agent path via Pi/LLM"
	@echo "  make analysis [INSTRUCTIONS=...]  Continuous analysis report; default TASK instruction set"
	@echo "  make report [INSTRUCTIONS=...]  Compatibility alias for make analysis"
	@echo "  make install-pi            Install the pinned Pi runtime"
	@echo "  make auth-import-pi        Import local Pi Codex OAuth to this project"
	@echo "  make auth-login            Log in to Pi Codex OAuth for this project"
	@echo "  make test                  Run all offline verification"
	@echo "  make test-e2e              Run offline CLI and scripted Pi-to-gridctl scenarios"
	@echo "  make validate              Run deterministic WP-A validation"
	@echo "  make validate-provider PROVIDER=... [MODEL=...]  Run optional billed provider validation"
	@echo "  Manual: docs/MANUAL-VALIDATION.md (human verification for every entry above)"

setup: setup-agent setup-simulator setup-tools

setup-agent:
	uv sync --project packages/grid-agent

setup-simulator:
	uv sync --project packages/grid-simulator

setup-tools:
	npm ci --prefix packages/pi-grid-tools

install-pi:
	uv run --project packages/grid-agent grid-agent install-pi

auth-import-pi:
	uv run --project packages/grid-agent grid-agent auth-import-pi

auth-login:
	uv run --project packages/grid-agent grid-agent auth-login

doctor:
	uv run --project packages/grid-agent grid-agent doctor --json

QUESTION ?= IEEE-39节点系统中线路11连接哪两个母线?
# QUESTION ?= 母线电压正常运行范围是多少?
# QUESTION ?= N-1静态安全校核需要检查哪些越限类型?
# QUESTION ?= ‘潮流计算工具（pandapower runpp）需要输入哪些参数？’
# QUESTION ?= 对IEEE-39节点系统运行交流潮流，并输出有功网损;
# QUESTION ?= 筛选负载率最高的5条线路
# QUESTION ?= 对线路17开展N-1校核
# QUESTION ?= 母线低电压、线路过载等风险及证据（仿真结果）
#
run:
	@test -n "$(QUESTION)" || (echo "Usage: make run QUESTION='IEEE-39节点系统中线路11连接哪两个母线?'" >&2; exit 2)
	uv run --project packages/grid-agent grid-agent run --offline "$(QUESTION)"

run-llm:
	@test -n "$(QUESTION)" || (echo "Usage: make run-llm QUESTION='...' [PROVIDER=openai]" >&2; exit 2)
	uv run --project packages/grid-agent grid-agent run $(if $(PROVIDER),--provider "$(PROVIDER)") "$(QUESTION)"

INSTRUCTIONS ?= validation/questions/task.md.txt

analysis:
	@test -f "$(INSTRUCTIONS)" || (echo "Instruction file not found: $(INSTRUCTIONS)" >&2; exit 2)
	uv run --project packages/grid-agent grid-agent analysis --instructions "$(INSTRUCTIONS)" $(if $(PROVIDER),--provider "$(PROVIDER)") $(if $(MODEL),--model "$(MODEL)")

report: analysis

test: test-agent test-simulator test-tools

test-agent:
	uv run --project packages/grid-agent pytest packages/grid-agent/tests -q

test-simulator:
	uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -q

test-tools:
	npm run check --prefix packages/pi-grid-tools
	npm test --prefix packages/pi-grid-tools

test-e2e:
	uv run --project packages/grid-agent pytest packages/grid-agent/tests/e2e -q

validate:
	uv run --project packages/grid-agent python validation/run.py --mode offline --suite task-required --report runs/validation-offline.json
	uv run --project packages/grid-agent python validation/run.py --mode scripted-pi --suite static-analysis-core --report runs/validation-scripted.json

validate-provider:
	uv run --project packages/grid-agent python validation/run.py --mode provider --suite task-required --provider "$(PROVIDER)" $(if $(MODEL),--model "$(MODEL)") --report runs/validation-provider.json
