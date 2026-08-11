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

`make setup` 分别创建 agent 与 simulator 的隔离环境，并安装 Pi Bash 扩展依赖。`make doctor` 不发送模型请求。

## 执行分析问题

```sh
make run QUESTION="IEEE-39节点系统中线路11连接哪两个母线?"
make run QUESTION="对IEEE-39节点系统运行交流潮流，并输出有功网损;"
make run QUESTION="筛选负载率最高的5条线路;"
```

标准输出始终是一个 JSON 对象，仅含 `question_id` 与 `answer_output`。数值计算通过独立的 `gridctl` JSONL 进程完成；运行证据写入当前目录的 `var/runs/`。

## Pi RPC 路径

默认命令使用本地、非计费的 gridctl 证据路径。若明确设置 `GRID_AGENT_PI_COMMAND`，`grid-agent run` 会通过 Pi JSONL RPC 启动该命令；API 密钥只能通过环境变量提供，绝不能写入参数或文件。

## 验证

```sh
make test
make test-e2e
```

`make test` 运行 agent、pandapower simulator 和 Node 扩展测试；`make test-e2e` 运行离线命令行样例及脚本化 Pi → gridctl 路径。
