# 轨迹工作台审计台升级设计

**状态：** 待用户审阅

**基线：** `main`，统一轨迹平台已合并
**目标：** 将当前可验证的工作台升级为日常可用的专业审计界面，而非演示型投影浏览器。

## 1. 问题与目标

当前工作台具备安全的只读 API、分页、虚拟列表、四类投影和基础无障碍，但仍有三个产品缺口：

1. 字号、行距和卡片留白偏大，桌面信息密度不足；
2. 业务节点与 Context、Evidence、Agent 执行详情之间虽有数据关系，界面却未形成连续调查操作；
3. 若干投影以摘要或空白详情呈现，操作员需要在多个视图之间猜测下一步。

升级后的默认体验是**大屏审计台**：操作员从一个 run 的问题/turn 进入，沿因果时间线选择具体节点，并在不中断时间线位置的情况下核对结论、证据、上下文和执行细节。

不引入写入、人工批注、实时控制、跨 run 聚合、隐藏推理内容或任意文件浏览。

## 2. 信息架构

采用“任务驱动审计台”而非独立详情页面或全屏弹窗。

```text
Run / Turn rail        Causal trajectory                         Investigation inspector
├─ run status          ├─ problem group                           ├─ Overview
├─ source/status       ├─ request → tool → result → claim         ├─ Evidence
└─ turn/problem        ├─ compact node rows                        ├─ Context
                       └─ filters / page controls                  └─ Execution
```

### 2.1 左侧 Run / Turn rail

- 保留 run 搜索、状态和来源筛选。
- 选中 run 后显示其可用的 turn/problem 索引，而不是只显示 run 卡片。
- 每个 turn 显示编号、标题、节点数量、终态、最后序列；点击后定位中间区到该组。
- `partial` 仍可进入并显示已持久化部分；`corrupt` 显示诊断而不假装完整；`unsupported` 不构造投影。

### 2.2 中间因果轨迹

- Business 是默认视图；每个问题组可展开/折叠。
- 每个节点行必须显示：序列、类别、简短结论、来源、状态、上下文 revision、关联 result/evidence 数量。
- 用因果缩进和连线/编号表达 request、tool、result、claim 的关系；不得仅靠颜色表达状态。
- 节点行可展开一段受限摘要：输入摘要、输出摘要、阻塞或失败原因、可用证据标签。
- 过滤器只过滤可见投影，不改变 run 事实；过滤结果显示总数与已隐藏数。
- 更早页面采用明确的 `Load older`/加载中/失败重试状态；加载失败必须重试同一 cursor。
- 100k 轨迹仍使用虚拟化，问题组标题也必须位于虚拟窗口中。

### 2.3 右侧 Investigation inspector

选择**具体业务节点**后，Inspector 固定为四页签；没有选择时显示如何开始调查，而非空白卡。

| 页签 | 内容 | 操作 |
| --- | --- | --- |
| Overview | 标题、状态、来源、序列、所属 turn、父/子因果关系、限制说明 | 跳转父/子节点、复制稳定 node id |
| Evidence | 已登记 result/evidence，摘要校验、生产/消费序列、类别和安全链接 | 选中、预览允许类型工件、回跳生产节点 |
| Context | 精确 source sequence 的 context revision、before/after、结构化 delta、请求输入可用性 | 跳到前/后 revision、在主线高亮对应节点 |
| Execution | 模型请求公共元数据、工具参数和公共结果、重试、耗时、失败原因 | 跳转 request/tool/result 节点；不显示隐藏推理或密钥 |

不能证明的数据必须显示 `Unavailable` 加明确原因，不能填充占位 JSON、推断时间或把 compatibility 文件当作原生事实。

## 3. 视觉与排版契约

### 3.1 桌面优先密度

- 正文基线 13px，辅助元数据 11px 等宽字体，节点标题 14px；不使用 18px 以上的常规内容标题。
- 主轨迹行紧凑但可点击：正常高度 44–56px，展开后展示摘要而不是放大整张卡片。
- 卡片仅用于问题边界、Inspector 面板和工件预览；节点本身使用分隔线、轻量 hover/selection 与状态标记。
- 深色为默认，浅色必须是真实 token 切换；两套颜色满足文本与边界的可读性要求。
- run rail 220–240px；桌面 Inspector 360px；中等宽度 42vw 可调；小于 800px 使用已存在的可访问 bottom sheet。

### 3.2 状态与可访问性

- 所有状态同时使用文字、图标/形状和颜色。
- 节点、页签、分页、工件预览和跳转均支持键盘；焦点位置在主线与 Inspector 之间可预测。
- Inspector 在窄屏保留焦点 trap、Escape、关闭后焦点返回。
- SVG 只承担视觉，不包含嵌套交互元素。

## 4. 数据与 API 边界

- 继续只消费现有同源 GET API、投影和 artifact gateway；不放宽工件访问或新增任意路径 API。
- 当节点需要的执行关系无法由 Business 投影表达时，前端从现有 Agent/Context/Evidence projection 查询并按稳定 id 关联；不得解析 prose 来补关系。
- 如 API 不能提供已存在的投影事实，可新增**有界、只读、类型化**端点；响应必须来自 `ProjectedRun`，遵守安全头、无 CORS、无写入方法。
- 页面请求以 `AbortSignal` 管理；切换 run、节点或 sequence 后旧响应不得覆盖新选择。

## 5. 交互流程

1. 操作员选择 run；rail 展开其问题/turn 索引。
2. 选择 turn/problem；主线定位并显示该因果组。
3. 选择节点；Overview 即刻显示节点身份和关系，Context 使用节点精确 sequence，Evidence 高亮节点 refs。
4. 选择 Evidence、Context 或 Execution 页签；查看投影事实或已登记安全工件，并可回跳产生该事实的节点。
5. 若数据缺失、部分、损坏、不支持或网络失败，界面说明边界与下一步，不伪造完成态。

## 6. 验收标准

- 用真实 native fixture 和 `analysis-20260814T081822Z` legacy run，能从一个 claim/tool 节点连续查看其证据、精确 context 与可用执行记录。
- 大屏 1440px 视口至少同时呈现 run/turn rail、超过 10 条紧凑节点和 Inspector，不出现大面积无意义留白。
- 1024px Inspector 可真实调整宽度；768px 以下 bottom sheet 的打开、Tab、Escape 和焦点返回通过浏览器测试。
- 100k fixture 的 DOM 节点数保持有界；旧页加载、失败和重试保留 cursor 语义。
- Agent、Context、Evidence、Business 的空、partial、corrupt、unsupported、网络失败状态均有真实 API 驱动的文字与操作。
- 前端单测、类型检查、Playwright 功能/Axe、视觉基线通过；后端变更额外通过轨迹 API 与全仓库离线门禁。

## 7. 实施切分

1. **审计数据模型与主线**：补齐节点关系、turn 索引、紧凑虚拟行和分页状态。
2. **Inspector 闭环**：实现 Overview/Evidence/Context/Execution 四页签、关联跳转和不可用语义。
3. **视觉系统与响应式**：重建桌面密度、层级、状态标记和小屏 sheet；更新视觉基线。
4. **真实运行验收**：native/legacy、100k、无障碍、只读边界和服务会话。

每一项都以真实投影数据和可重复浏览器测试验收；任何仍为 placeholder 的区域不能作为完成项。
