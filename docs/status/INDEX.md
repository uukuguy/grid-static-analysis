# docs/status INDEX

## Active

| File | Purpose |
| --- | --- |
| `CURRENT-STATE.md` | Structural project snapshot. |
| `JOURNAL.md` | Append-only durable event log. |
| `RESUME-NEXT-SESSION.md` | Current recovery baton. |
| `INDEX.md` | This discovery index. |
| `DECISIONS.md` | Active architectural decision ledger. |
| `climb/research-tree.md` | Generated full-capability hypothesis and scoring summary; resume-load. |
| `climb/session-state.json` | Active climb cycle and next action. |

## Climb storage and configuration

| Path | Purpose |
| --- | --- |
| `climb/config.yaml` | Project-specific climb adapter configuration. |
| `climb/session-target.md` | Machine-readable 100% static-analysis coverage target. |
| `climb/hypotheses.yaml` | Append-only capability architecture hypothesis state. |
| `climb/runs.csv` | Append-only local coverage experiment ledger. |
| `climb/calibration.json` | Local/online calibration state. |
| `climb/pending-lb.json` | Pending external score state; empty for local-gate mode. |
| `climb/adjudicator-log.md` | Append-only hypothesis decision record. |
| `climb/research-tree.json` | Machine-readable generated research tree. |
