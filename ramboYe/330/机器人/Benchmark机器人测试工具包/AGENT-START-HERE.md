# 发给 Agent 的部署任务

请按同目录 `README.md` 部署本机 Benchmark 机器人测试环境，并安装随包的 `benchmark-function-test` Skill 与 Benchmark MCP；Codex 使用 install-agent 脚本，其他 Agent 参照 README 的 HTTP MCP 配置。

先检查目标是 Linux 开发机，读取 README 与 `templates/local-services.example.env`，定位 gs 仓库、本机 Mongo 副本集、NATS JetStream、etcd v3 gateway、游戏 Gate、Docker 和可构建镜像。不要读取或复制 `.env` 密钥到对话、Obsidian 或工具包。优先从目标机器私有 `benchmark/envs/h5-local.env` 读取连接设置；凭据缺失时让操作者放入私有文件。

执行 `scripts/setup-local.sh --repo <gs根目录>` 前，先说明：会构建本机镜像，若缺少机器人批量 MCP 工具会向 gs 源码应用最小补丁，部署到独立本地 Mongo 库/etcd 前缀/NATS environment/volume，管理台仅监听 loopback，且仅本地测试 environment 的 Block 自测与 GM allowlist 开启。预检失败就停下报告缺项；不要改共享依赖监听配置、覆盖已有部署或开放免登录端口。操作者发出该任务即授权此本机开发环境部署。

部署后检查 `/ping`、Codex MCP 注册和 Skill 安装。在新 Codex 会话检查 MCP/Skill，然后调用 `list_test_targets`。首次如出现 `environment_not_configured`，按 README 在本机管理台创建 Webserver environment 记录并同步拓扑；当前 MCP 没有创建该记录的工具，需操作者在 UI 完成。确认 Gate/区服指向本机后再运行游戏测试。不要自动做城堡升级或其他业务测试。

最终报告环境 ID、管理台 loopback 地址、镜像 tag、MCP 名称、Skill 路径、预检/验收结果及任何 UI 步骤。绝不打印 Mongo URI、secret、AK/SK 或原始 env 文件。
