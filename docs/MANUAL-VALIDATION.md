# 人工验证手册

本手册用于在 WP-A 分支或已合并的 `main` 上人工复核 Grid Static Analysis 的可运行边界。所有命令均从仓库根目录执行，且只使用 [Makefile](../Makefile) 已发布的入口。

## 验证范围与原则

- 仿真器固定为 pandapower 3.4.0；电气数值只能由隔离的 `gridctl` 计算。
- `stdout` 只能有一个 JSON 答案对象：`question_id` 与 `answer_output`；进度和诊断在 `stderr`。
- 离线知识问答不应创建运行目录。拓扑、潮流、排序和 N-1 等 simulator-backed 问题应在 `runs/<question_id>/` 留下当前运行的证据。
- 在线 Pi/LLM 只能使用 `grid_*` domain tools、`grid_guide_open` 与 `grid_submit_answer`，不能使用 shell、read、write 或通用查询工具。
- 验证器只核对工具结果、`result_refs` 和 `claim_evidence_refs`，绝不从 `answer_output` 文本反推电网事实。

## Makefile 入口对照

| 目的 | 命令 | 成功判据 |
| --- | --- | --- |
| 安装依赖 | `make setup` | agent、simulator、Pi tools 三套依赖均完成安装。 |
| 本机健康检查 | `make doctor` | 输出 JSON；不发送模型请求。 |
| 主产品/评测路径 | `make run-llm QUESTION="..."` | Pi/LLM 解释自然语言并组合 domain tools；stdout 是单个答案 JSON，stderr 有 Pi 工具轨迹。 |
| 批量系统仿真分析 | `make report [QUESTIONS=...] [OUTPUT=...]` | 缺省运行 TASK 问题集，实时显示分步日志，并写入易读报告；`OUTPUT` 可选 JSONL 标准结果。 |
| 离线冒烟 | `make run QUESTION="..."` | 只验证确定性离线知识/诊断路由；不代替智能体能力验证。 |
| Pi 安装/认证 | `make install-pi`、`make auth-import-pi`、`make auth-login` | 仅在使用托管 Pi 或 `openai-codex` OAuth 时需要。 |
| 单元与契约测试 | `make test` | Python agent、pandapower simulator 和 Node tools 全部通过。 |
| 端到端测试 | `make test-e2e` | 离线 CLI 与 scripted Pi → gridctl 路径全部通过。 |
| 必需验证集 | `make validate` | `runs/validation-offline.json` 和 `runs/validation-scripted.json` 均显示 `failed: 0`。 |
| 付费 provider 抽检 | `make validate-provider PROVIDER=<id> [MODEL=<id>]` | 仅在凭证已配置时运行；报告写入 `runs/validation-provider.json`。 |

`make validate-provider` 可能实际调用计费模型，不能把它当作本地常规检查；缺少对应 provider 凭证时应失败且不得输出密钥。

## 1. 初始化与边界检查

```sh
make setup
make doctor
```

检查 `make doctor` 的 JSON 是否报告可定位的 `gridctl`、pandapower 3.4.0 与所需运行时。它不应创建某个问题的 `runs/<question_id>/` 目录，也不应发起 provider 请求。

## 2. 主产品路径：Pi/LLM 自然语言分析

人工验收任务理解、实体识别和多步工具组合时，所有 TASK 示例都应首先走 `make run-llm`，而不是 `make run`：

```sh
make run-llm QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
make run-llm QUESTION="对IEEE-39节点系统运行交流潮流，并输出有功网损;"
make run-llm QUESTION="筛选负载率最高的5条线路;"
```

先按 RUNBOOK 配置 provider/Pi。检查 stdout 的单一 JSON 外壳、stderr 的受控工具轨迹，以及 `runs/<question_id>/` 下的当前运行证据。不要把离线固定路由的成功当成模型理解或工具编排成功。

## 批量“系统仿真分析报告”

不带参数即可运行版本化的 TASK 示例问题集：

```sh
make report
```

输入文件每行一个问题；可指定自己的文件和供评测/后处理读取的标准结果：

```sh
make report QUESTIONS=questions.txt OUTPUT=answers.jsonl
```

终端用 `========== 问题 N/总数 开始/结束 ==========` 分隔每题，并在边界内实时显示模型推理摘要、工具开始/完成/失败和本题摘要。每题结束时立即原子刷新 Markdown 报告；如指定 `OUTPUT`，立即追加并刷新一行标准 JSONL。因此中断批次时，已完成题目的报告和 JSONL 均可直接查看和使用。Markdown 报告在 `runs/reports/`，每题以问题本身为标题并先给最终回答；随后记录本题实际打开的**仿真环境上下文**（模型来源、pandapower 版本、网络规模和只读快照）、可观察的分析动作与时长，以及可读的证据说明。报告中的“查看冻结上下文快照”“查看证据工件”和“打开本题运行目录”均可直接打开对应文件；不会把 SHA-256 或内部 asset/context/result ID 当作说明文字展示。这个上下文是问题分析和仿真结果的共同边界，不是由回答文字推断的标签。它只记录可审计的执行信息，不展示模型隐藏推理。`OUTPUT` 文件每行严格只含 `question_id` 与 `answer_output`，答案同样不包含内部 ID。

若最终答案审计不通过，报告不会只给出截断日志或悄悄把草稿当作成功答案：它会明确写出发现、对最终结果的影响和复核建议，并在其下保留“模型草稿（未采纳）”。标准 JSONL 仍只输出受控的最终结果，避免把未经证据校验的草稿交给下游系统。

## 3. 离线知识与确定性诊断

先运行纯知识问题：

```sh
make run QUESTION="母线电压正常运行范围是多少?"
```

确认 stdout 可被 `json.loads` 解析，且只含 `question_id`、`answer_output`；该问题不应新建 `runs/<question_id>/`。

再运行当前离线支持的确定性拓扑诊断：

```sh
make run QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
```

预期答案说明线路 11 的端点为母线 6 与母线 11。确认该次运行对应的目录包含 `evidence/network-facts/`，其中 network-fact 文档的摘要与引用的 `evidence:sha256:*` 一致。不要只凭答案文字判断正确性，应打开该 JSON 文档核对 `capability_id` 为 `topology.branch.endpoints.get` 及端点字段。

## 4. 潮流、排序和 N-1 的证据复核

以下每条均应通过 `gridctl` 执行 pandapower，而非由模型计算数值：

```sh
make run-llm QUESTION="对IEEE-39节点系统运行交流潮流，并输出有功网损;"
make run-llm QUESTION="筛选负载率最高的5条线路;"
make run-llm QUESTION="对线路11开展N-1校核;"
```

对每个新运行目录，检查：

1. `evidence/analysis/` 和 `evidence/results/` 存在对应文档；
2. 结果文档含 `result_ref`、`context_ref`、`revision_ref`；
3. 分析证据引用相同的 `result_ref`，且其文件内容摘要与引用的 SHA-256 匹配；
4. 排序读取已有结果时不会再次运行潮流；N-1 可以报告部分场景不收敛，但必须保留该限制及证据。

具体答案数值取决于注册模型与 pandapower 固定版本；人工验收以当前运行中的结构化结果/证据为准，不以手工抄录的数字为准。

## 5. 在线 Pi/LLM 工具边界复核

将 `.env.example` 复制为 Git 忽略的 `.env`，仅配置一个 provider 的凭证；详见 [RUNBOOK](RUNBOOK.md#llm-配置与-pi-rpc-路径)。随后执行：

```sh
make run-llm QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
```

检查 stderr 中有 `grid_guide_open`、`context.open`、`topology.branch.endpoints.get` 和 `grid_submit_answer` 等事件。然后检查 `runs/<question_id>/events.jsonl`：领域工具完成事件必须以规范化的 `tool_result` 保存，包含 capability、`ok`、typed `result` 和 `evidence_refs`。不得出现 `read`、`shell`、`bash`、`grid_query` 或模型直接调用 pandapower 的轨迹。

最后打开 `answer-draft.json`：它应有 `answer_output`、`result_refs`、`claim_evidence_refs`。`result_refs` 是支撑最终结论的主结果；分析证据中已关联的场景结果由运行时自动校验，不要求模型机械重复每一个场景引用。拓扑事实允许空 `result_refs`；AC/排序/N-1 结论必须有当前运行的主结果或与其相连的分析证据。引用缺失、过期、跨上下文或摘要不匹配时 CLI 必须拒绝草稿，而不是照样输出答案。

## 6. 回归与验证集

```sh
make test
make test-e2e
make validate
```

`make validate` 的两个报告是人工验收的最小证据：

```sh
sed -n '1,160p' runs/validation-offline.json
sed -n '1,160p' runs/validation-scripted.json
```

每个报告的 `summary.failed` 必须为 `0`。同时检查各 case 的 `checks`：`envelope` 验证 stdout 外壳；`capability_constraints` 验证工具边界；`oracle` 对拓扑、潮流、排序和 N-1 读取结构化工具结果；`evidence` 验证引用确实位于当前 run。知识说明和限制说明的文字检查只适用于这两类非电气事实用例。

## 常见失败判读

| 症状 | 排查方向 |
| --- | --- |
| `make doctor` 找不到 `gridctl` | 运行 `make setup`，确认 simulator 环境可创建。 |
| `401 authentication_error` | 更新 `.env` 中与 provider 匹配的密钥；密钥不要写入命令行。 |
| `Request timed out` | 检查 stderr 首行的超时/重试配置，再检查 `runs/<question_id>/events.jsonl`。 |
| 草稿被拒绝 | 核对 `answer-draft.json` 的 refs 是否属于当前 run、SHA 是否匹配、分析证据是否链接结果。 |
| `verification_*` 或 `structured_oracle_mismatch` | 检查 events 中是否有规范化 `tool_result` 以及真实 evidence 文档；不要通过修改答案文字来规避。 |
| `powerflow_non_converged` 或 N-1 partial | 这是可报告的受控限制，前提是 typed error/证据完整且答案不编造数值。 |
