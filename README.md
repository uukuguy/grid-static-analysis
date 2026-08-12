## Grid Static Analysis

`grid-agent run` writes exactly one JSON object to stdout: `question_id` and `answer_output`. Diagnostics stay on stderr.

```sh
make setup
make doctor
make run QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
make test
make validate
```

The simulator is separately pinned to pandapower 3.4.0. API keys are environment-only; never put them in command arguments or files. Each numeric answer is produced through the isolated `gridctl` JSONL process and leaves evidence under `runs/<question_id>/`.

`runs/` is the ignored operator-visible evidence area. `.grid-agent/` is ignored internal Pi auth/runtime/session state. Pure informational answers, such as voltage-range or N-1 policy explanations, do not create a run directory.

`make run` is explicitly offline. For an LLM backend, copy `.env.example` to the Git-ignored `.env`, set one provider key and `GRID_AGENT_PI_COMMAND` (or install the managed Pi runtime under `.grid-agent/runtime/pi`), then run `make run-llm QUESTION="问题"`. `openai-codex` OAuth credentials are imported or created under `.grid-agent/auth/pi`. An optional `PROVIDER=<...>` overrides the `.env` provider for that invocation. The CLI resolves the provider, materializes a secret-free Pi configuration, and starts Pi RPC.

`make validate` runs the mandatory WP-A deterministic offline and scripted-Pi suites. `make validate-provider PROVIDER=<id> [MODEL=<id>]` is optional and may call a billed provider only when explicit credentials are configured.

See [运行操作指南](docs/RUNBOOK.md) for setup, execution, Pi RPC, evidence, and verification details.
