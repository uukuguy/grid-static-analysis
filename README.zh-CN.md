# 电网静态分析

[English](README.md) | 简体中文

`grid-agent` 是一个能力优先、证据闭环的命令行代理，用于对已登记的电力系统网络执行静态分析。LLM 负责理解请求并组合项目定义的工具；`gridctl` 与固定版本的 pandapower 模拟器负责全部确定性网络计算。

`v1.0.0` 是声明的静态分析产品范围内首个稳定版本。当前覆盖情况始终以可执行能力矩阵为准。

## 功能范围

- 发现已登记网络，并通过受控声明式接口创建模型。
- 派生不可变网络修订和分析场景。
- 执行拓扑、AC/DC/三相潮流、AC/DC 最优潮流、IEC 60909 短路、状态估计、诊断、故障分析、风险评估、网络等值和静态保护分析。
- 查询、聚合、比较和排序由模拟器管理的结果数据集。
- 在多步骤分析和连续报告中复用经过验证的上下文。
- 记录原生执行轨迹，并提供只读调查工作台。
- 将最终数值结论绑定到当前运行的结果和证据引用。

项目覆盖的是声明的 pandapower 静态分析产品范围，而不是 pandapower 的全部公开 API。时序/控制工作流、绘图、任意文件或数据库转换，以及未固定的外部求解器运行时不属于模型能力边界。详见[能力架构](docs/architecture/pandapower-capability-composition.md)和[可执行覆盖矩阵](configs/capabilities/pandapower-3.4.0-static-analysis.json)。

## 系统架构

```text
自然语言请求
      |
      v
grid-agent + Pi/LLM       意图理解、工具组合、上下文、答案封装
      |
      v  grid-capability/1.0
gridctl + grid-simulator  契约、登记模型、结果、证据
      |
      v
pandapower                确定性电力系统计算
      |
      v
runs/<question_id>/       操作者可见的当前运行证据
```

LLM 只能选择已登记的语义工具，不能获得 shell、任意 Python、原始 pandapower 对象、DataFrame 或通用文件系统访问权。所有数值和网络特定结论都必须跨越模拟器边界返回。

## 快速开始

前置条件为 Python 3.12+、Node.js 22.19+、`uv` 和 `npm`。Provider 支持的分析还需要配置相应的 LLM 凭据；离线冒烟检查不需要 Provider。

```sh
git clone https://github.com/uukuguy/grid-static-analysis.git
cd grid-static-analysis
make setup
make doctor
```

执行确定性离线冒烟检查：

```sh
make run QUESTION="IEEE-39 节点系统中线路 11 连接哪两个母线？"
```

执行主要的自然语言代理路径：

```sh
cp .env.example .env
# 在 Git 忽略的 .env 文件中配置一个受支持的 Provider 凭据。
make install-pi
make run-llm QUESTION="对 IEEE-39 节点系统运行交流潮流，并报告有功网损。"
```

如需使用项目自有的 OpenAI Codex OAuth 而不是 API key，请先在 `.env` 中设置 `GRID_AGENT_LLM_PROVIDER=openai-codex`，再执行 `make auth-login`；该登录命令不会自动选择 Provider。也可以在单次调用中使用 `make run-llm PROVIDER=openai-codex QUESTION="..."` 指定 Provider。Provider 配置、认证优先级、运行时安装和失败诊断详见[运行操作指南](docs/RUNBOOK.md)。

## 主要工作流

| 目标 | 命令 |
| --- | --- |
| 检查运行环境 | `make doctor` |
| 离线确定性冒烟检查 | `make run QUESTION="..."` |
| LLM 驱动的单题分析 | `make run-llm QUESTION="..."` |
| 连续多题分析 | `make analysis INSTRUCTIONS=path/to/instructions.txt` |
| 连续分析兼容别名 | `make report INSTRUCTIONS=path/to/instructions.txt` |
| 构建并启动只读工作台 | `make trajectory PORT=8765` |

`grid-agent run` 向 stdout 精确写入一个 JSON 对象：

```json
{"question_id":"...","answer_output":"..."}
```

进度、诊断和工具事件只写入 stderr。连续分析同样只输出一个最终答案封装，其 `answer_output` 指向生成的报告。

## 结果、证据与工作台

模拟器支持的运行将操作者可见工件写入 `runs/<question_id>/`。最终结论只能引用当前运行已经接纳的结果和证据。纯信息类离线回答不会创建仿真证据。

内部认证、托管 Pi 运行时、缓存和会话状态位于 Git 忽略的 `.grid-agent/` 目录；版本化运行配置位于 `configs/runtime/`。

启动本地只读轨迹工作台：

```sh
make trajectory PORT=8765
```

UI 和 API 默认位于 `http://127.0.0.1:8765`。工作台只投影已记录事实用于调查，不能修改运行记录，也不能替代模拟器事实。

## 验证

```sh
make doctor
make test
make test-e2e
make validate
```

`make validate-provider PROVIDER=<id> [MODEL=<id>]` 是可选命令，需要显式凭据，并可能产生 Provider 费用。

## 仓库结构

| 路径 | 职责 |
| --- | --- |
| `packages/grid-agent/` | CLI、Pi/LLM 运行时、上下文、轨迹、报告和答案封装 |
| `packages/grid-simulator/` | `gridctl`、登记模型、pandapower 执行、结果和证据 |
| `packages/pi-grid-tools/` | 项目限定的 Pi 工具、指南、请求捕获和答案提交 |
| `packages/trajectory-workbench/` | 只读 React/TypeScript 轨迹调查 UI |
| `configs/` | 版本化能力、策略、Provider 目录和运行配置 |
| `validation/` | 离线、脚本 Pi、语义和可选 Provider 验证套件 |
| `docs/` | 操作指南、架构、设计历史、计划和持久项目状态 |

## 文档索引

- [运行操作指南](docs/RUNBOOK.md) — 初始化、认证、执行、证据与故障排查。
- [人工验证手册](docs/MANUAL-VALIDATION.md) — 可复现的人工验收流程。
- [能力注册与组合推理](docs/architecture/pandapower-capability-composition.md) — 能力范围和 LLM 工具编排边界。
- [分析上下文架构](docs/architecture/analysis-context.md) — 经过验证的多步骤上下文模型。
- [轨迹事件架构](docs/architecture/trajectory-events.md) — 权威原生执行时间线。
- [当前项目状态](docs/status/CURRENT-STATE.md) — 结构快照与实现入口。
- [仓库 Agent 契约](AGENTS.md) — 稳定的 Codex/Claude Code 规则与事实来源。

## 安全与贡献边界

凭据只能存放在环境变量或 Git 忽略的项目认证状态中，不能进入命令参数、提交文件、日志、模拟器环境或证据。新增模型能力必须可复用、由契约定义、经过白名单，并由模拟器执行；禁止逐题捷径和任意执行面。
