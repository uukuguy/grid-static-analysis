# 轨迹工作台操作手册

本手册说明如何生成、启动和检查 Grid Agent 的智能体轨迹。工作台仅在本机回环地址提供**只读**浏览，不会修改 `runs/` 中的运行记录。

完整的智能体运行、Provider 配置和验证流程见 [运行操作指南](RUNBOOK.md)。

## 1. 准备环境

在仓库根目录执行：

```sh
make setup
make doctor
```

`make setup` 安装 Python、Simulator、Pi tools 和工作台依赖，并构建工作台静态资源。`make doctor` 只检查本机环境，不会调用模型。

如果只需要重新安装或构建工作台：

```sh
make setup-workbench
make build-workbench
```

## 2. 生成可浏览的轨迹

### 连续分析（推荐）

```sh
make analysis
```

或指定指令文件：

```sh
make analysis INSTRUCTIONS=questions.txt
```

每次分析创建一个 `runs/analysis-<UTC 时间戳>/` 目录。标准输出只给出最终 JSON envelope；进度、工具调用和诊断写入 stderr。完成后，最终报告在该目录的 `report.md`。

### 单题运行

离线确定性检查：

```sh
make run QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
```

需要模型理解和工具编排时，先按 [运行操作指南](RUNBOOK.md#llm-配置与-pi-rpc-路径) 配置 Provider，再运行：

```sh
make run-llm QUESTION="对线路17开展N-1校核"
```

仿真型问题会在 `runs/<question_id>/` 保留证据；纯信息型离线回答不会创建运行目录。

## 3. 启动工作台

```sh
make trajectory PORT=8765
```

打开 <http://127.0.0.1:8765/>。该命令会先构建工作台，再启动本地服务。服务日志只写 stderr；使用 `Ctrl-C` 停止。

也可直接指定运行目录：

```sh
uv run --project packages/grid-agent \
  grid-agent trajectory serve --host 127.0.0.1 --port 8765 --runs-root runs
```

`--host` 仅允许 `127.0.0.1`、`::1` 或 `localhost`。局域网和公网绑定会被拒绝。

### 浏览历史示例

仓库根目录的历史示例为：

```text
runs/analysis-20260814T081822Z
```

它会显示为 `legacy-v0.2`；新版本原生轨迹显示为 `native`。两类运行均可在同一工作台浏览。

## 4. 工作台界面

### 选择运行

左侧 **Runs** 区域列出可识别的运行。可按状态或来源筛选，选择一个运行后，主视图会加载其投影数据。

运行状态含义：

| 状态 | 含义 | 操作建议 |
| --- | --- | --- |
| `completed` | 运行和投影完整。 | 正常浏览。 |
| `partial` | 已持久化的部分可安全显示。 | 浏览已记录事实；结合诊断确认缺失区段。 |
| `corrupt` | 事件或投影完整性不能确认。 | 不据此做业务结论，检查诊断和原始 run。 |
| `unsupported` | 当前工作台不支持该轨迹版本或能力。 | 保留 run，升级工具后重试。 |

网络或服务错误会显示 **Retry**，可在服务恢复后重新请求，不会重跑分析。

### Business：业务解题轨迹

默认视图按问题分组显示决策、工具、主张等业务节点。

- 使用文本、来源和状态筛选缩小范围。
- 选择具体节点，而不是只选择父问题：右侧 Inspector、Context 与 Evidence 会使用该节点的精确序列和引用。
- **Load older history** 会按游标加载更早记录；100k 级别轨迹保持虚拟化窗口，不会一次渲染全部行。
- 顶部概览时间线可点击或用键盘 `Enter` / `Space` 选择回合。

### Agent：智能体执行轨迹

展示扁平分页后的 turn、step、模型请求、重试、工具调用与响应关系。可按 **Turn、Kind、Status、Capability、Query** 筛选；筛选条件会绑定分页游标，改变筛选会开启一组新的结果，不能混用旧游标。树控件支持方向键导航；选中工具、请求或响应时，只跳转到该记录明确保存的业务序列并同步 Inspector。父项在尚未加载的更早页中时会显示截断标记，不会猜测父项。

**Load older agent history** 请求更早的一页并保留已加载行。失败后使用 **Retry older agent history** 会重试失败时保存的同一不透明游标；筛选或切换 run 后，迟到的旧响应不会覆盖当前视图。

### Context：全过程上下文

摘要时间线可按起止序列、起止 revision、是否变化、是否有请求输入筛选，并用 **Load older context history** / **Retry older context history** 分页。选择摘要后才按精确 `at_sequence` 获取权威 frame；Previous/Next 只在已经加载的摘要间移动。

详情以结构化节点展示 Before、Delta、After；**Raw recorded JSON** 是次要折叠视图。可将两个已经获取的权威 frame 分别固定为 A/B，比较 Added、Removed、Changed 键。比较不会生成合成上下文。模型请求输入只有在 frame 保存了已验证引用时才提供下载；工作台不会用最近序列替代缺失输入。

中心 Context 里的请求输入链接表示最终的、provider 无关的语义输入，而不是 provider wire payload。原生 v2 请求预览只暴露 `semantic_request`、相关 turn/request/context 标识和运行时身份；内部提交确认、Provider 私有 reasoning、thinking signature、凭证和 wire payload 不会出现在 API 响应或工作台预览中。已登记工件下载仍返回原始不可变字节，用于完整性复核。

### Evidence：证据与工件

Evidence 是虚拟化的分页调查表，可按 **Kind、Source、Verification、起止序列、Relevant reference、Sort** 筛选。表头状态显示当前已加载记录数和序列范围；**Load older evidence history** 与 **Retry older evidence history** 的游标语义和 Agent 相同。每条记录可以复制引用；Producer 和 Consumer 按钮只导航到记录中明确保存的序列，不按数字巧合或最近节点推断关系。

只有 `verification_status=verified` 的记录会显示 **Preview** 和 **Download**。预览仍通过同源的已登记工件网关请求，发送 `Range: bytes=0-131071`，客户端最多保留 131,072 bytes，并明确标记截断；仅接受 JSON、Markdown 和纯文本响应。预览是显示用途，不执行内容。未验证记录显示持久化的不可用原因，且不会生成预览按钮、下载链接或工件 URL。

原生 `native` run 通常包含可重新校验的登记工件和精确语义请求输入。历史 `grid-model-request-input/1.0` 工件仍可作为只读历史原始输入浏览或下载，但它们不会被改写为 v2，也不等同于当前的 canonical replay。`legacy-v0.2` run 的摘要、分页和已能投影的 lineage 仍可浏览；没有登记文件、摘要或精确请求输入的项目保持 `unavailable` 并说明原因。两类 run 都不会用附近序列、父 turn 或任意文件路径补齐缺失事实。

### Inspector 与移动设备

- 宽屏：左侧运行 rail、中央因果轨迹和右侧 Inspector 同屏显示；Inspector 的 **Overview / Evidence / Context / Execution** 四个页签分别显示节点身份、证据链、上下文 delta 和有界执行切片。
- 800–1199px：Inspector 为可调整宽度的右栏；拖动分隔线或聚焦分隔线后使用方向键调整。
- 小于 800px：点击 **Open inspector** 打开底部 sheet；`Escape` 或 **Close inspector** 关闭，焦点会返回触发按钮。

顶部主题按钮可切换浅色/深色；偏好只保存在浏览器本地，不包含轨迹数据或凭据。

## 5. 只读 API

工作台使用同源 GET API。常用检查：

```sh
curl http://127.0.0.1:8765/api/runs
curl 'http://127.0.0.1:8765/api/runs/<analysis_id>/business'
curl 'http://127.0.0.1:8765/api/runs/<analysis_id>/context?at_sequence=42'
```

可用资源包括运行摘要、Business、Agent、Context、Evidence 和已登记工件。服务没有写入路由、CORS 或 WebSocket；`POST` 等方法应返回 `405`。

非 `/api/` 客户端路由返回工作台入口；未知 `/api/*` 路径保持 JSON 404，不会返回 HTML。

## 6. 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 提示缺少静态资源 | 执行 `make build-workbench` 后重新启动。 |
| 左侧没有运行 | 确认 `--runs-root` 指向包含 `runs/<analysis_id>/manifest.json` 的目录；历史 run 还需保留其 context 与 trace 文件。 |
| 浏览器无法打开 | 确认命令仍在运行，并使用 `http://127.0.0.1:<PORT>/`，不要使用公网地址。 |
| 显示 `corrupt` | 不要依据该 run 输出结论；检查其事件链和诊断，必要时重新执行分析。 |
| Evidence 链接被拒绝 | 这是预期安全行为：路径、未登记引用、符号链接逃逸或摘要不匹配都会被拒绝。 |
| 模型请求提交失败 | 这是分析完整性失败；请求必须先持久化并收到 commit acknowledgement，才允许进入 provider I/O。不要按 provider 故障处理。 |
| 前端开发验证缺少浏览器 | 默认使用 Playwright 固定版本 Chromium：`npm exec --prefix packages/trajectory-workbench -- playwright install chromium`。只有在固定浏览器档案不可用且明确接受本机差异时，才临时设置 `TRAJECTORY_WORKBENCH_BROWSER_CHANNEL=chrome` 使用系统 Chrome。 |
| 需要复用已启动的本地 Vite 服务 | 默认测试会启动独立 loopback 服务以保持验证可重复；仅在本地排障时设置 `TRAJECTORY_WORKBENCH_REUSE_SERVER=1`。 |

## 7. 验证与维护

提交前或排障后可执行：

```sh
make test
make test-e2e
make validate

npm run check --prefix packages/trajectory-workbench
npm test --prefix packages/trajectory-workbench
npm run test:e2e --prefix packages/trajectory-workbench
npm run test:visual --prefix packages/trajectory-workbench
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api packages/grid-agent/tests/trajectory/projections -q
```

浏览视觉基线时额外执行：

```sh
npm exec --prefix packages/trajectory-workbench -- playwright install chromium
npm run test:visual --prefix packages/trajectory-workbench -- --update-snapshots
npm run test:visual --prefix packages/trajectory-workbench
```

更新视觉基线前先确认功能测试通过；更新后检查宽屏深色、宽屏浅色、1024px 可调整 Inspector、768px 底部 sheet、所有异步状态，以及 Inspector 的 Overview / Evidence / Context / Execution 四个面板。正文应保持 13px、元数据保持 11px、普通标题不超过 16px。

`make validate-provider` 会实际调用配置的模型，可能计费；只有在明确需要时才运行。
