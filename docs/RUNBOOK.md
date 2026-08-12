# 运行操作指南

## 前置条件

- Python 3.12 或更高版本与 `uv`
- Node.js 22.19 或更高版本与 `npm`

## 初始化

在仓库根目录执行：

```sh
make setup
make doctor
```

`make setup` 分别创建 agent 与 simulator 的隔离环境，并安装 Pi grid domain tools 扩展依赖。`make doctor` 不发送模型请求。

## 执行分析问题

```sh
make run QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
make run QUESTION="对IEEE-39节点系统运行交流潮流，并输出有功网损;"
make run QUESTION="筛选负载率最高的5条线路;"
```

标准输出始终是一个 JSON 对象，仅含 `question_id` 与 `answer_output`。数值计算和模型事实通过独立的 `gridctl` JSONL 进程完成，仿真边界固定为 pandapower 3.4.0；运行证据写入当前目录的 `runs/<question_id>/`。纯信息回答不会创建运行目录，也不会声称仿真证据。

`runs/` 是操作者可检查的运行记录，已被 Git 忽略。`.grid-agent/` 只存放项目内部 Pi OAuth、托管 Pi runtime、会话状态等内部状态，同样被 Git 忽略。版本化运行配置位于 `configs/runtime/`，例如 `configs/runtime/pi-runtime.lock.json`。

## LLM 配置与 Pi RPC 路径

配置写在仓库根目录的 `.env`：它已被 Git 忽略。先复制模板，再只填写一个实际使用的密钥：

```sh
cp .env.example .env
# 编辑 .env：例如保留 GRID_AGENT_LLM_PROVIDER=openai，填写 OPENAI_API_KEY=...
```

可选的非密钥参数也写在 `.env`：`GRID_AGENT_LLM_MODEL`、`GRID_AGENT_LLM_BASE_URL`、`GRID_AGENT_LLM_TIMEOUT_SECONDS` 与 `GRID_AGENT_LLM_MAX_RETRIES`。后两项分别是单次 provider 请求的秒数和重试次数（`0` 禁用重试）；每次 `make run-llm` 都会写入项目私有的 Pi `settings.json`，同时作用于 Pi 的 HTTP 空闲时限、SDK 请求时限和自动重试。命令行参数优先于 `.env`，进程环境变量优先于 `.env`。支持的 provider 与默认密钥变量为：`openai`/`OPENAI_API_KEY`、`openrouter`/`OPENROUTER_API_KEY`、`deepseek`/`DEEPSEEK_API_KEY`、`minimax`/`MINIMAX_API_KEY`。`openai-codex` 使用 Pi OAuth，而不是 API key。

DeepSeek 官方 OpenAI API 的 V4 model 参数为 `deepseek-v4-flash` 或 `deepseek-v4-pro`，不要填发行日期后缀；项目会在启动 Pi 前拒绝其他 DeepSeek model id。

Pi 运行时按以下顺序发现：`GRID_AGENT_PI_COMMAND`、项目托管版本、`PATH` 中的 `pi`。因此 Pi 已在 `PATH` 时无需配置 `GRID_AGENT_PI_COMMAND`；否则可在 `.env` 设置该绝对路径，或在仓库根目录执行 `make install-pi` 安装本项目锁定版本到 `.grid-agent/runtime/pi`。模型密钥会仅在启动 Pi 子进程时通过环境变量传递，不写入 `.grid-agent/auth/pi` 的配置文件或命令行。

当 `GRID_AGENT_LLM_PROVIDER=openai-codex` 时，不填写 API key。先从已经登录的本地 Pi 导入 OAuth 凭证，或登录到项目自己的 Pi OAuth 配置：

```sh
make auth-import-pi
# 若尚未有本地 Pi 登录态：先 make install-pi，再 make auth-login
```

```sh
# 默认读取 .env 中的 GRID_AGENT_LLM_PROVIDER
make run-llm QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"

# 临时覆盖 .env 中的 provider
make run-llm PROVIDER=deepseek QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
```

`make run` 始终是本地、非计费的离线 gridctl 路径；`make run-llm` 才会调用配置的 LLM，并把受控的 `gridctl` 放入 Pi 的受限 PATH。Pi 只暴露项目生成的 `grid_*` domain tools、`grid_guide_open` 和 `grid_submit_answer`；不会启用通用 shell/read/write/edit 内置工具。

`make run-llm` 的 stdout 仍只输出最终 JSON；实时进度写到 stderr，包括运行耗时、provider/model、生效的超时与重试参数、输入与输出前 200 字摘要、Pi 工具事件、重试事件，以及超过 10 秒无事件时的等待提示。密钥字段会被隐藏。

若日志出现 `401 ... authentication_error`，表示当前 provider 的 API key 无效、过期或与所选 provider 不匹配；更新 `.env` 中对应的密钥后重新运行。该错误不会重试。若出现 `Request timed out`，先确认日志首行的超时和重试参数，再检查 provider 服务状态或提高 `GRID_AGENT_LLM_TIMEOUT_SECONDS`；运行原始事件保存在 `runs/<question_id>/events.jsonl`，可用于进一步诊断。

## Skill 与工具边界

Pi 只能访问项目发布的 grid domain tools、`grid_guide_open` 和 `grid_submit_answer`。工具描述说明某个 capability 如何调用；`skills/grid-static-analysis/` 是操作手册，说明何时使用 capability、如何组合上下文、结果和证据，以及哪些请求属于 WP-B 或后续范围。

WP-A 可执行能力包括：运行时/模型发现、打开 IEEE-39 上下文、数据集描述与查询、元素解析、线路端点、拓扑连通分量、交流潮流、有功网损、支路负载率排序、`static-analysis-v1` 单支路 N-1 校核，以及拓扑证据读取。WP-B 范围包括多注册网络、DC 潮流、更丰富的策略/风险引擎和更广泛结果查询；当前请求触及这些范围时必须返回明确限制，不能编造输出。

## 证据检查

每个 simulator-backed run 可检查：

- `runs/<question_id>/events.jsonl`：Pi 事件、工具调用和结果 trace。
- `runs/<question_id>/tool-results/`：工具侧结果暂存目录。
- `runs/<question_id>/evidence/`：当前运行的 context、model、network-fact、analysis 和 result 证据。
- `runs/<question_id>/answer.json` 或 `answer-draft.json`：最终或提交草稿。

最终答案只能引用当前运行中实际存在的 `evidence:sha256:*` 或 `result:sha256:*`。迁移和清理不会删除用户主工作树中的既有 `var/` 数据；本分支只使用新的 ignored `runs/` 和 `.grid-agent/` 布局。

## 验证

```sh
make test
make test-e2e
make validate
```

`make test` 运行 agent、pandapower simulator 和 Node 扩展测试；`make test-e2e` 运行离线命令行样例及脚本化 Pi → gridctl 路径。
`make validate` 运行 WP-A 必需的 deterministic validation：offline `task-required` 和 scripted-Pi `static-analysis-core`，报告写入 ignored `runs/validation-offline.json` 与 `runs/validation-scripted.json`。

可选 provider validation 会产生真实模型调用，必须显式给出 provider 且环境中已有对应凭证：

```sh
make validate-provider PROVIDER=openai MODEL=gpt-5.5
```

报告写入 `runs/validation-provider.json`，记录 provider/model、trace、延迟以及可用的 token/cost 元数据，不写入密钥。
