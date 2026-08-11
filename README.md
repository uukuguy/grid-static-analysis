## Grid Static Analysis

`grid-agent run` writes exactly one JSON object to stdout: `question_id` and `answer_output`. Diagnostics stay on stderr.

```sh
make setup
make doctor
make run QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
make test
```

The simulator is separately pinned to pandapower 3.4.0. API keys are environment-only; never put them in command arguments or files. Each numeric answer is produced through the isolated `gridctl` JSONL process and leaves evidence under `var/runs/`.

See [运行操作指南](docs/RUNBOOK.md) for setup, execution, Pi RPC, evidence, and verification details.
