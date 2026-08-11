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

## LLM 配置与 Pi RPC 路径

配置写在仓库根目录的 `.env`：它已被 Git 忽略。先复制模板，再只填写一个实际使用的密钥：

```sh
cp .env.example .env
# 编辑 .env：例如保留 GRID_AGENT_LLM_PROVIDER=openai，填写 OPENAI_API_KEY=...
```

可选的非密钥参数也写在 `.env`：`GRID_AGENT_LLM_MODEL`、`GRID_AGENT_LLM_BASE_URL`、`GRID_AGENT_LLM_TIMEOUT_SECONDS` 与 `GRID_AGENT_LLM_MAX_RETRIES`。命令行参数优先于 `.env`，进程环境变量优先于 `.env`。支持的 provider 与默认密钥变量为：`openai`/`OPENAI_API_KEY`、`openrouter`/`OPENROUTER_API_KEY`、`deepseek`/`DEEPSEEK_API_KEY`、`minimax`/`MINIMAX_API_KEY`。`openai-codex` 使用 Pi OAuth，而不是 API key。

Pi 运行时必须二选一：设置 `.env` 中的 `GRID_AGENT_PI_COMMAND=/绝对路径/pi`，或在仓库根目录执行 `make install-pi` 安装本项目锁定版本的运行时。模型密钥会仅在启动 Pi 子进程时通过环境变量传递，不写入 `var/pi/agent` 的配置文件或命令行。

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

`make run` 始终是本地、非计费的离线 gridctl 路径；`make run-llm` 才会调用配置的 LLM，并把受控的 `gridctl` 放入 Pi 的受限 PATH。

## 验证

```sh
make test
make test-e2e
```

`make test` 运行 agent、pandapower simulator 和 Node 扩展测试；`make test-e2e` 运行离线命令行样例及脚本化 Pi → gridctl 路径。
