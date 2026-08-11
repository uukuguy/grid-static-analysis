# CLI 运行进度设计

`grid-agent run` 保持 stdout 只输出最终 JSON。Pi RPC 的每个事件通过可选回调交给 CLI；CLI 在 stderr 输出时间、阶段、输入与输出的 200 字摘要。没有事件超过十秒时输出等待心跳。密钥和完整长内容不显示。
