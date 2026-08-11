.DEFAULT_GOAL := help

.PHONY: help setup setup-agent setup-simulator setup-tools install-pi doctor run run-llm test test-agent test-simulator test-tools test-e2e

help:
	@echo "Grid Static Analysis commands"
	@echo "  make setup                 Install all local dependencies"
	@echo "  make doctor                Inspect local runtime readiness"
	@echo "  make run QUESTION='...'    Run one offline grid-analysis question"
	@echo "  make run-llm PROVIDER=openai QUESTION='...'  Run through configured Pi/LLM"
	@echo "  make install-pi            Install the pinned Pi runtime"
	@echo "  make test                  Run all offline verification"
	@echo "  make test-e2e              Run offline command-line scenarios"

setup: setup-agent setup-simulator setup-tools

setup-agent:
	uv sync --project packages/grid-agent

setup-simulator:
	uv sync --project packages/grid-simulator

setup-tools:
	npm ci --prefix packages/pi-grid-tools

install-pi:
	uv run --project packages/grid-agent grid-agent install-pi

doctor:
	uv run --project packages/grid-agent grid-agent doctor --json

run:
	@test -n "$(QUESTION)" || (echo "Usage: make run QUESTION='IEEE-39节点系统中线路11连接哪两个母线?'" >&2; exit 2)
	uv run --project packages/grid-agent grid-agent run --offline "$(QUESTION)"

run-llm:
	@test -n "$(QUESTION)" || (echo "Usage: make run-llm PROVIDER=openai QUESTION='...'" >&2; exit 2)
	@test -n "$(PROVIDER)" || (echo "Set PROVIDER=openai|openrouter|deepseek|minimax" >&2; exit 2)
	uv run --project packages/grid-agent grid-agent run --provider "$(PROVIDER)" "$(QUESTION)"

test: test-agent test-simulator test-tools

test-agent:
	uv run --project packages/grid-agent pytest packages/grid-agent/tests -q

test-simulator:
	uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -q

test-tools:
	npm run check --prefix packages/pi-grid-tools
	npm test --prefix packages/pi-grid-tools

test-e2e:
	uv run --project packages/grid-agent pytest packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py -q
