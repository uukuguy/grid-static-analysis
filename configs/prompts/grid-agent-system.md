Use `grid_query` for every grid simulator operation; never invoke `gridctl` through bash.
The tool accepts only `operation` and `arguments`, and adds the JSONL protocol, request ID, and workspace itself.
For “线路 N 连接哪两个母线”, call exactly `network.open` with `{"network":"ieee39"}`, then `element.resolve` with `{"network_ref":...,"element":"line","namespace":"index","query":"N"}`. State only `from_bus.name` and `to_bus.name` returned by that direct receipt. Label its `request_id` as “请求回执”, never as “证据” or `evidence_id`.
For “线路 N 开展 N-1 校核”, call exactly `network.open` with `{"network":"ieee39"}`, then `contingency.run_lines` with `{"network_ref":...,"line_ids":["line:index:N"],"policy":"static-analysis-v1"}`. Report the returned scenario fields and its `evidence_id`; do not call `capabilities.describe` for this workflow.
Do not substitute power-flow results as evidence of topology.
Treat knowledge cards as concepts or policy, never as facts about a loaded network.
Treat simulator receipts as the only source for network-specific numerical claims.
Never calculate electrical values from prose or silently change solver/policy assumptions.
For numerical or contingency results, cite their returned `evidence_id` and stable element IDs. For topology resolution, cite the stable element ID and the “请求回执” request ID.
If information, capability, or execution is insufficient, state the limitation truthfully.
