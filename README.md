## Grid Static Analysis

`grid-agent run` writes exactly one JSON object to stdout: `question_id` and `answer_output`. Diagnostics stay on stderr.

```sh
uv sync --project packages/grid-agent
uv sync --project packages/grid-simulator
npm ci --prefix packages/pi-grid-tools
uv run --project packages/grid-agent grid-agent doctor --json
uv run --project packages/grid-agent grid-agent run "IEEE-39节点系统中线路11连接哪两个母线?"
```

The simulator is separately pinned to pandapower 3.4.0. API keys are environment-only; never put them in command arguments or files. Each numeric answer is produced through the isolated `gridctl` JSONL process and leaves evidence under `var/runs/`.
