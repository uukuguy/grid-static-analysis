# Pandapower 能力注册与组合推理架构

- **日期：** 2026-08-18
- **状态：** 当前实现说明
- **适用范围：** `grid-agent`、Pi/LLM 工具层、`gridctl` 与 pandapower 3.4.0 静态分析

## 1. 文档目的

本文回答以下三个问题：

1. “统一能力目录动态注册工具”是否覆盖了 pandapower 的全部能力？
2. `grid-agent` 是否能够根据问题动态组合多个注册工具完成推理和计算？
3. LLM、`grid-agent`、`gridctl`、pandapower、分析上下文和证据系统在这个过程中分别负责什么？

核心结论是：

> 当前实现完整覆盖项目声明的 pandapower 3.4.0 **静态分析产品范围**，但不等于暴露 pandapower 的全部公开 Python API。框架具备目录驱动的 LLM 工具组合能力：LLM 负责理解问题和规划工具链，`gridctl` 与 pandapower 负责确定性计算，分析上下文负责跨步骤状态传递，结果与证据系统负责事实闭环。

这套能力面向问题类型和分析语义，不面向某一道验证题。验证题用于检查能力，不用于定义能力，也不允许通过题目文本分支或逐题专用函数凑出答案。

## 2. “完整覆盖”的准确含义

### 2.1 当前覆盖的是静态分析产品范围

版本化能力矩阵是
[`configs/capabilities/pandapower-3.4.0-static-analysis.json`](../../configs/capabilities/pandapower-3.4.0-static-analysis.json)。当前矩阵包含 24 项 `in_scope` 能力，24 项均为 `published`，即声明范围内覆盖率为 100%。

主要能力族包括：

- 注册网络模型的发现与打开；
- 声明式网络创建和元素创建器发现；
- 不可变模型修订与场景派生；
- 网络元素表的描述、查询和实体解析；
- 拓扑端点、连通分量、邻居、路径和失电区域分析；
- AC、DC 和三相潮流；
- AC 和 DC 最优潮流；
- IEC 60909 短路计算；
- 状态估计、卡方分析和坏数据移除；
- pandapower diagnostic；
- N-1 故障分析；
- 模型约束、越限评估和风险排序；
- Ward、XWard、REI 网络等值；
- pandapower 支持的静态保护分析；
- 全部已生成 `res_*` 结果表的保存、描述、查询、聚合和比较；
- 当前运行结果与证据的持久化和引用校验。

当前模型目录登记 60 个 pandapower 3.4.0 网络模型，并保留稳定的 `ieee39` 别名。声明式创建器从固定版本 pandapower 中发现首参数为 `net` 的 `create_*` 函数，再以受控 Schema 暴露；模型不能提交任意 Python 函数名。

### 2.2 不覆盖 pandapower 的全部公开 API

能力矩阵明确排除了以下四类能力：

| 能力族 | 排除原因 |
| --- | --- |
| `pandapower.timeseries` 与 `control` | 属于准静态时序或控制器工作流，不属于当前静态分析产品 |
| plotting | 属于展示能力，不是分析计算能力 |
| 任意文件、数据库与 converter I/O | 会突破模型的文件系统和原始对象边界 |
| `runpm`、`runpp_pgm` 等外部求解器 | 依赖没有随项目固定的 Julia 或其他外部运行时 |

因此应当使用两个不同的判断标准：

- 如果“全部能力”指 pandapower 命名空间中的每一个公开函数，答案是**没有覆盖**。
- 如果“全部能力”指本项目声明的电网静态分析产品范围，当前能力矩阵是 **24/24 全部发布**。

未注册能力不会因为 pandapower 已经安装就自动成为 LLM 工具。这个限制保证模型不能取得 shell、任意 Python、文件系统、原始 `pandapowerNet` 或 DataFrame 访问权。

## 3. 分层职责

```text
路径 A：推理期间的注册工具调用

自然语言问题
      |
      v
grid-agent / Pi / LLM
  - 理解问题与分析意图
  - 读取工具 Schema 和语义说明
  - 规划并调用注册工具
      |
      v  grid-capability/1.0
gridctl / grid-simulator
  - 校验 capability 和输入 Schema
  - 管理模型、修订、结果和证据
  - 调度确定性分析操作
      |
      v
pandapower 3.4.0
  - 电网模型和算法实现
  - 潮流、OPF、短路、估计、拓扑等计算
      |
      v
result/evidence 返回给 LLM 继续推理


路径 B：终端最终文本与答案工件

grid-agent / Pi / LLM
  - 返回面向读者的普通最终文本
      |
      v
grid-agent controller
  - 单题 run：发布 stdout AnswerEnvelope，保留事件和工具证据
  - 连续 analysis：绑定当前回合结果/证据 lineage
  - 连续 analysis：写入 turns/NNN/answer-draft.json 与 answer.json
```

职责边界如下：

- **LLM** 负责语义推理和下一步选择，不负责猜测潮流、损耗、电压、排序或故障结果。
- **`grid-agent`** 负责问题编排、统一工具目录、Pi 运行、连续上下文、轨迹、当前回合结果/证据绑定和最终答案封装。
- **`gridctl` / `grid-simulator`** 负责所有网络事实和确定性计算，以及模型、结果和证据的内容寻址。
- **pandapower 3.4.0** 负责具体电力系统算法；其对象始终留在模拟器边界内。
- **观察、投影和完整性诊断层** 负责记录和解释执行过程，不应替代或改写成功的主计算结果。

## 4. 统一能力目录如何动态注册工具

### 4.1 能力定义

模拟器中的每项公开能力都有版本化 JSON 定义。定义至少包含：

- capability ID；
- LLM 工具名称；
- 可用状态；
- 精确输入 JSON Schema；
- `purpose` 和 `applies_to`；
- `not_for`；
- 前置能力和输入状态；
- 产生的结果和状态；
- `common_next` 常见后续能力；
- 按错误类型组织的恢复建议；
- 对分析上下文的 `context_effect`。

当前仓库包含 30 份模拟器 capability 定义。它们是工具语义和执行契约的共同来源，而不是由 provider 适配器或问题提示词临时拼装。

### 4.2 运行时求交集

启动时，`grid-agent` 执行以下过程：

1. 从模拟器 `environment.describe` 读取当前运行时真正可执行的 capability。
2. 加载仓库中的版本化 capability 定义。
3. 按 capability ID 求交集。
4. 检查被模拟器宣布为可执行的能力是否有对应定义、是否为 `published`，以及 `context_effect` 是否一致。
5. 将通过检查的能力确定性地物化为 `grid-tool-catalog/1.0`。
6. Pi 插件遍历目录，为每一项生成 LLM 工具。
7. 工具调用统一转换成 `grid-capability/1.0` 请求并交给 `gridctl`。

这意味着工具面取决于“版本化契约”和“模拟器实际公布能力”两者的一致性。仅有文档而没有实现的能力不会注册；仅有实现而没有公开契约的能力也不会悄悄暴露给模型。

相关实现：

- [`packages/grid-agent/src/grid_agent/tools/catalog.py`](../../packages/grid-agent/src/grid_agent/tools/catalog.py)：加载、校验、筛选和物化统一工具目录。
- [`packages/pi-grid-tools/src/domain-tools.mjs`](../../packages/pi-grid-tools/src/domain-tools.mjs)：遍历工具目录并注册 Pi 工具，同时提供指南工具。
- [`packages/grid-simulator/src/grid_simulator/operations.py`](../../packages/grid-simulator/src/grid_simulator/operations.py)：校验 capability、输入、调度结果和输出契约。
- [`packages/grid-simulator/src/grid_simulator/analysis_registry.py`](../../packages/grid-simulator/src/grid_simulator/analysis_registry.py)：管理通用分析操作注册表及操作选项 Schema。
- [`packages/grid-simulator/src/grid_simulator/bindings/__init__.py`](../../packages/grid-simulator/src/grid_simulator/bindings/__init__.py)：汇总潮流、OPF、短路、估计、诊断、拓扑和保护等操作绑定。
- [`packages/grid-simulator/src/grid_simulator/creators.py`](../../packages/grid-simulator/src/grid_simulator/creators.py)：发现并约束声明式网络元素创建器。

## 5. 基于注册工具的组合推理

### 5.1 组合器是什么

当前组合器是“**受工具契约约束的 LLM 规划器**”，不是按问题编号编写的工作流，也不是把所有问题都塞进一个万能工具。

每轮模型调用获得：

- 当前问题；
- 系统策略；
- 当前运行可用的工具及精确参数 Schema；
- 每项工具的适用范围、前置条件、产物、常见下一步和恢复说明；
- 有界的连续分析上下文视图；
- 前面步骤已经得到的模型、场景、结果、证据、事实和限制。

LLM 据此选择下一项工具。工具返回以后，框架验证并投影结果，再将新的上下文交给下一次模型推理。工具使用完成后，LLM 返回普通的面向读者最终文本；`grid-agent` 控制器把当前回合已经消费和产生的结果/证据引用绑定到答案并持久化。

### 5.2 连续组合循环

```text
问题与当前上下文
        |
        v
LLM 选择 capability，并生成符合 Schema 的参数
        |
        v
gridctl 校验输入、模型引用和前置状态
        |
        v
pandapower 执行确定性操作
        |
        v
结果/证据持久化，返回内容寻址引用
        |
        v
grid-agent 验证引用并投影语义状态
        |
        +----> 下一轮 LLM 推理与工具选择
        |
        v
模型最终文本
        |
        v
grid-agent 控制器提交答案、result_refs、claim_evidence_refs
```

分析运行器在每道指令之前物化最新上下文并调用 Pi。上下文视图包含活动模型、约束、场景、可复用计算、已验证事实、已完成问题和未解决限制。相关实现位于：

- [`packages/grid-agent/src/grid_agent/analysis/runner.py`](../../packages/grid-agent/src/grid_agent/analysis/runner.py)：逐条指令驱动模型，并注入最新上下文视图。
- [`packages/grid-agent/src/grid_agent/analysis/view.py`](../../packages/grid-agent/src/grid_agent/analysis/view.py)：生成有界的模型可见上下文。
- [`packages/grid-agent/src/grid_agent/analysis/capabilities.py`](../../packages/grid-agent/src/grid_agent/analysis/capabilities.py)：解释 `requires_state`、`consumes_state`、`produces_state`、`invalidates_state` 和 projector。
- [`packages/grid-agent/src/grid_agent/analysis/domain_projection.py`](../../packages/grid-agent/src/grid_agent/analysis/domain_projection.py)：把工具结果投影成模型、约束、场景和计算等领域状态。
- [`packages/grid-agent/src/grid_agent/analysis/projector.py`](../../packages/grid-agent/src/grid_agent/analysis/projector.py)：配对工具开始/结束事件，验证当前运行结果和证据，并更新连续上下文。

### 5.3 一个组合分析示例

假设问题是：

> 断开线路 0，判断是否出现失电区域；如果没有，再执行 DC 潮流，并与基准工况比较。

框架可以由 LLM 动态规划出以下工具链：

1. `context.open`：打开基准电网模型。
2. `model.element.get`：把自然语言中的“线路 0”解析为明确资产引用。
3. `model.revision.derive`：创建线路停运的不可变子修订。
4. `analysis.run(operation=topology.unsupplied)`：计算失电区域。
5. `result.dataset.query`：读取拓扑结果。
6. LLM 根据是否存在失电区域决定是否继续执行后续分支。
7. `analysis.run(operation=powerflow.dc)`：在满足条件时运行 DC 潮流。
8. `result.dataset.query`、`result.aggregate` 或 `result.compare`：读取、汇总或比较基准与故障场景。
9. LLM 返回可读结论；`grid-agent` 控制器分别绑定主结果引用和结论证据引用并提交答案。

这个链条不是硬编码的固定流程。能力目录提供语义和状态关系，LLM 负责根据问题及中间结果进行规划，模拟器负责逐步验证和执行。

## 6. 组合过程中的状态与证据

### 6.1 状态不是聊天摘要

连续分析上下文保存的是有类型的领域状态，而不仅是 LLM 自己写的一段摘要，包括：

- 活动模型及不可变修订；
- 当前运行状态和已执行计算；
- 有来源的电压、负载率等约束；
- 故障和派生场景；
- 可复用结果及其模型修订关系；
- 已验证事实；
- capability 可用性；
- 未解决限制和诊断。

完整表格保存在模拟器结果存储中；模型只获得有界视图，需要更多数据时必须通过注册的结果查询工具读取。

### 6.2 每个数值结论必须跨越模拟器边界

线路端点、电压、损耗、潮流、排序、越限和故障结果等网络特定结论不得由 LLM 猜测。它们必须由 `gridctl` 执行并产生当前运行的结果或证据引用。

结果存储负责：

- 保存完整的 pandapower `res_*` 表；
- 记录操作、参数、模型上下文和修订；
- 校验内容哈希；
- 支持列表、描述、查询、聚合和跨结果比较；
- 记录结果生产与后续消费的血缘关系。

最终提交时，`grid-agent` 控制器将模型面向用户的文字与 `result_refs`、`claim_evidence_refs` 分开绑定。运行时验证这些引用确实来自当前运行；模型正文不得暴露内部 result/evidence/context/asset/constraint/path/nonce 标识。

## 7. 这种架构能保证什么

它能够保证：

- 题目不能直接取得任意 Python、shell、文件系统或原始 pandapower 对象；
- 工具只能来自模拟器和版本化契约共同确认的能力集合；
- 每次工具调用都有明确输入 Schema；
- 模型修订、计算结果和证据可以追溯；
- 网络特定数值来自 pandapower 确定性执行，而不是 LLM 猜测；
- 新问题可以复用已有能力并动态组合，不需要逐题增加专用解题函数；
- 验证和观察意见可以进入轨迹和报告，但不应仅因摘要、投影或格式意见否定已成功的主任务结果。

## 8. 这种架构不能自动保证什么

需要如实区分“能力可用”和“规划必然正确”：

- 当前不是一个在 capability 图上穷举搜索并证明可达性的形式化规划器。
- `requires`、`produces`、`common_next` 和 `context_effect` 用于约束并帮助 LLM 推理，但当前不会自动合成唯一或最短工作流。
- LLM 仍可能选错工具、漏掉必要步骤、使用低效工具链或误解问题。
- Schema 和证据校验可以阻止伪造参数和无依据数值，但不能单独保证问题语义理解 100% 正确。
- 24/24 表示声明的静态分析能力已经发布，不表示任意自然语言问题的端到端正确率天然为 100%。

因此端到端质量需要同时观察三件事：

1. **能力覆盖：** 所需确定性能力是否已经注册并可执行。
2. **组合规划：** LLM 是否选择了正确、充分的工具链。
3. **事实闭环：** 最终结论是否绑定了正确模型修订、结果和当前运行证据。

## 9. 如何判断是否出现逐题硬编码

实现和评审应遵守以下判断标准：

- 不按题号、测试文件名、问题原文或预期答案分支；
- 不为某个网络或某道题增加只返回目标答案的 capability；
- 新能力以分析语义、输入 Schema、结果数据集和证据规则定义；
- 同一能力可以被不同网络、不同题目和不同工具链复用；
- 验证题答案文件只作为 oracle，不进入运行时工具选择和计算路径。

例如，“查询线路端点”应由通用实体解析和拓扑端点能力完成；“计算最严重线路”应由通用潮流、结果查询或排序能力完成。它们不能写成“IEEE-39 第 11 号线路答案”或“测试题第 4 题计算器”。

## 10. 相关架构文档

- [Pandapower 3.4.0 Static-Analysis Full-Capability Design](../superpowers/specs/2026-08-18-pandapower-static-analysis-full-capability-design.md)
- [Analysis Context Architecture](analysis-context.md)
- [Trajectory Event Architecture](trajectory-events.md)
- [`grid-agent` system policy](../../configs/agent/system-policy.md)
