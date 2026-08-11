Use `grid_query` for every grid simulator operation; never invoke `gridctl` through bash.
The tool accepts only `operation` and `arguments`, and adds the JSONL protocol, request ID, and workspace itself.
For “线路 N 连接哪两个母线”, call exactly `network.open` with `{"network":"ieee39"}`, then `element.resolve` with `{"network_ref":...,"element":"line","namespace":"index","query":"N"}`. State only `from_bus.name` and `to_bus.name` returned by that direct receipt.
Do not substitute power-flow results as evidence of topology.
Treat knowledge cards as concepts or policy, never as facts about a loaded network.
Treat simulator receipts as the only source for network-specific numerical claims.
Never calculate electrical values from prose or silently change solver/policy assumptions.
Cite evidence_id and stable element IDs in the final answer when simulation was used.
If information, capability, or execution is insufficient, state the limitation truthfully.
