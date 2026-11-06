# Benchmark 机器人测试工具包

这份目录把本机 Benchmark 部署、Codex Agent Skill、客户端脚本和 MCP 注册步骤放在一起。首次部署命令可以一键串起本地镜像构建、部署、Skill 安装和 MCP 注册；Mongo 副本集、NATS JetStream、etcd、游戏 Gate 及镜像构建权限必须先在目标机器可用。

## 适用范围

- Linux 开发机，Agent 与 Benchmark MCP 在同一台机器上运行。
- 当前目标是本机/测试环境。管理台绑定 `127.0.0.1`，启用免登录仅用于本机，勿改成 `0.0.0.0` 暴露网络。
- 需要一个已配置的 gs 源码仓库，以及可达的本机游戏 Gate。
- 不会创建游戏服、Mongo/NATS/etcd，也不会自动写任意玩家存档。机器人、玩法前置和业务测试由随包 Skill 经现有 MCP 完成。

远程 Agent 无法直接访问另一台机器的 `127.0.0.1`。不要为了让远程 Agent 连通而将免登录管理台公开到网络；应将 Agent 放在同机运行，或另行配置受保护的隧道和认证。

## 一键安装

在有 gs 源码和本机服务的 Linux 主机上：

```bash
cd Benchmark机器人测试工具包
./scripts/setup-local.sh --repo /path/to/gs
```

脚本执行前会检查 Docker/Compose、源码构建输入和 Mongo、NATS、etcd 端口。随后会：

1. 若源码缺少批量机器人 MCP 适配，检查补丁是否能干净应用，再添加只读预览及显式确认创建工具。
2. 从 gs 源码构建本地镜像 `gs-benchmark:local`。
3. 使用本机默认连接启动一套隔离 Benchmark 环境；生成独立业务库、etcd 前缀、NATS 环境 ID 和 Worker 卷。
4. 只在这套本机部署启用 Block 自测试，并将自测试和玩家 GM allowlist 限定到本部署的唯一 environment ID；管理台绑定回环地址。
5. 将 `benchmark-function-test` Skill 安装到 `~/.agents/skills/`，并注册 Codex MCP `benchmark-local` 到 `http://127.0.0.1:28082/mcp`。

Mongo/NATS/etcd/Gate 的默认连接见 `templates/local-services.example.env`。脚本优先读取仓库中本机的 `benchmark/envs/h5-local.env`，也可用 `--env-file` 指向私有配置。部署日志不会打印连接字符串；凭据会写入权限为 600 的用户部署目录，不进入本工具包。

如果默认服务地址不同，先复制模板到本地私有文件并改地址，勿覆盖模板：

```bash
install -m 600 templates/local-services.example.env "$HOME/.config/benchmark-local/local-services.env"
$EDITOR "$HOME/.config/benchmark-local/local-services.env"
./scripts/setup-local.sh --repo /path/to/gs --env-file "$HOME/.config/benchmark-local/local-services.env"
```

只生成部署配置而不启动：

```bash
./scripts/setup-local.sh --repo /path/to/gs --prepare-only
```

只在已手工构建好 `gs-benchmark:local` 后部署：

```bash
./scripts/setup-local.sh --repo /path/to/gs --skip-build
```

部署目录默认位于 `~/.local/share/benchmark/benchmark-local-<主机名>`；已有正式部署时脚本拒绝覆盖。已有环境用 `deploy/deploy-local.py --repo /path/to/gs --check|--start|--stop` 操作，或直接使用该目录的 `benchmark-deploy.py`。整套部署由本机操作者显式启动，不会后台自动运行。

## 环境要求

| 组件 | 必须满足 | 默认连接 |
|---|---|---|
| Python | 3.8+ | 部署机本地 |
| Docker | Engine、Buildx、Compose v2 | 部署机本地 |
| Agent | Codex CLI 可选（存在时脚本自动安装 MCP 与 Skill） | 部署机本地；其他 Agent 读取随包 Skill 并注册同一 HTTP MCP URL |
| 镜像构建依赖 | Harbor 镜像构建阶段所需 Node/Go/Debian 基础镜像可拉取 | `benchmark/Dockerfile` |
| Mongo | 可写副本集，配置库可从镜像导入；容器可达。副本集通告的成员地址也必须可达 | `host.docker.internal:27017`, `rs0` |
| NATS | JetStream 已开启，容器可达 | `nats://host.docker.internal:4222` |
| etcd | v3 HTTP gateway，无认证，容器可达 | `http://host.docker.internal:2379` |
| Gate | 正确区服的游戏 Gate，容器可达 | `host.docker.internal:21001` |

Docker Compose 为容器添加 `host.docker.internal:host-gateway`。Linux 服务若只监听 `127.0.0.1`，容器仍无法连接；部署脚本会在配置初始化前探测依赖并停止。不要通过本工具自动修改共享 Mongo、NATS 或 etcd 的系统配置。Mongo 副本集成员地址错误、NATS 未启 JetStream、etcd 认证/证书和镜像私有仓库访问都需先由该机器的运维配置解决。

### 安装并检查依赖

已有 Docker/Compose 时只需检查版本与 daemon：

```bash
python3 --version
docker version
docker buildx version
docker compose version
docker info >/dev/null
```

Ubuntu 新机器按 [Docker 官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/) 安装 Docker Engine、Buildx 和 Compose plugin；不要在已有服务的机器上先卸载/重装 Docker。将当前用户加入 `docker` 组后重新登录，保证 `docker info` 可运行。

本机依赖先确认进程和监听端口，再在 `local-services.env` 填入容器可达地址：

```bash
ss -lnt | rg ':(27017|4222|2379|21001)\b'
```

Mongo 必须是可写副本集（URI 中 `replicaSet` 与实际一致），容器通过副本集通告的 member 地址回连也必须可达；只启动一个 standalone mongod 不够。NATS 必须开启 JetStream 且帐号有独立测试 stream 所需权限。etcd 要提供可达的 v3 HTTP gateway；本部署脚本不支持 etcd auth 或客户端证书。Gate 使用正在运行的本机测试服，不要误填 Benchmark 管理台端口。第一次运行 `deploy-local.py --preflight` 会再测 TCP，并由 Benchmark 内置部署 helper 验证 Mongo、NATS/JetStream、etcd、Gate 和数据状态。

容器不能使用宿主机的 loopback。默认 `host.docker.internal` 会由 Compose 映射到 Docker host gateway；若本机服务仅绑定物理网卡 IP，在私有 env 文件里逐项填那个可达 IP。不要为了本工具把 Mongo/NATS/etcd 改成全网卡监听；先由运维评估本机网络访问策略。

脚本从 gs 父目录构建，因为 Dockerfile 使用 `gs/` 路径：

```bash
./scripts/build-local-image.sh /path/to/gs
```

需要已登录可读 `harbor-dev.330stars.com`，且本地 `gs` 仓库目录名为 `gs`。Dockerfile 会编译 Benchmark、Worker 和处理服务；构建前要求两个内嵌目录文件存在：

- `benchmark/backend/internal/aiblockassistant/protocol_catalog.json.gz`
- `benchmark/backend/internal/robotaction/catalog.json`

这些文件缺失时不要从别的分支随便复制；应按当前项目构建步骤生成。

## 如何验证部署

部署完成后确认：

```bash
curl -fsS http://127.0.0.1:28082/ping
codex mcp list
```

在 Codex 新会话中确认可看到 `benchmark-local` MCP 和 `benchmark-function-test` Skill。首次使用若 readiness 显示 `environment_not_configured`，还要在本地管理台 `基础资源 → 环境管理` 创建一个 environment 记录，ID 必须等于部署目录 `deploy-settings.json` 的 `environment` 值；填写环境名称、本机 Webserver URL、AK/SK 并启用。AK/SK 由本机 GMT 的“机器人调用管理”创建；密钥只在本机管理台提交，不放工具包。保存后触发环境拓扑同步，确认实际 Gate 地址和区服列表指向本机测试服。当前 MCP 没有创建管理台 environment 记录的工具，因此这一步不能自动完成；`environment_not_configured` 表示环境记录/同步还未完成，不是容器启动失败。代码已将 Block 自测试和直接 GM allowlist 限定在该唯一 ID。需要 GM 准备玩法状态时才使用本机 Webserver 凭据；不要配置生产或管理员范围的凭据。

注册后让 Agent 调 `list_test_targets`。`preview_robot_batch` 不写数据；`create_robot_batch` 要求确认且只创建机器人主档，角色创建和功能前置仍由登录/业务 Block 完成。

可选 UI：`http://127.0.0.1:28082/ui/`。默认免登录但只监听 loopback。

## Agent 安装与更新

`setup-local.sh` 已自动安装 Skill 与 MCP。如只需手动安装/刷新：

```bash
./scripts/install-agent.sh
```

脚本先备份已有 Skill，再复制随包目录；MCP 地址从 `BENCHMARK_MCP_URL` 读取，默认本机 URL。Codex CLI 和 IDE 共用 MCP 用户配置；注册后开新会话即可加载，详见 [Codex MCP 官方说明](https://developers.openai.com/learn/docs-mcp)。客户端有本地 URL 默认，也可设置 `BENCHMARK_MCP_URL` 覆盖。

其他 Agent 将 `agent-skill/benchmark-function-test/` 安装为其支持的本地 Skill，并按自身配置格式注册 HTTP MCP。例如常见 JSON 配置形态如下，具体键名依 Agent 而异：

```json
{"mcpServers":{"benchmark-local":{"type":"http","url":"http://127.0.0.1:28082/mcp"}}}
```

仅在源码尚无 `preview_robot_batch`/`create_robot_batch` 时才用随包最小补丁；`setup-local.sh` 会先 `git apply --check`，有冲突就停止并要求 Agent 审核。补丁只新增管理 MCP 工具和说明，不动 RobotFlow、Block Engine、业务状态或原执行调度。

## 安全与边界

- 不要把 `benchmark/envs/*.env`、Mongo URI、API Key、环境加密密钥、`answers.json`、`deployment.env` 或 `deploy-settings.json` 加入 Obsidian、Git 或公开归档。
- `BENCHMARK_DEV_AUTH_BYPASS=true` 只用于这套 loopback 本地实例。未经认证的免登录服务不得绑定公网或可信范围之外的网卡。
- Block 自测试仅在本机环境启用；不要把此 Compose 默认直接用于共享或生产 Benchmark。
- `--deploy` 会创建独立 Mongo 库、etcd 前缀、NATS Stream/环境和 Docker Volume。若已有相同环境 ID、库或资源，按现有脚本检查结果处理，不能换号绕过冲突/限额。
- 一键部署的边界是“把已准备好的本机服务组成可运行 Benchmark 并接入 Agent”。它不自动安装/重启共享依赖，不生成游戏配置，不开通 Gate，不创建/启动业务测试，也不验证游戏玩法结果。

## 随包文件

- `deploy/benchmark-deploy.py`：独立部署脚本的本地工具包副本；默认保持 Block 自测关闭，本地封装仅对本机唯一环境开启并设置 allowlist。
- `deploy/deploy-local.py`：本地默认值、预检、私有答案文件及首次部署入口。
- `scripts/setup-local.sh`：一键编排入口。
- `scripts/build-local-image.sh`：从 gs 源码构建部署镜像。
- `scripts/install-mcp-adapter.sh`、`source/robot-batch-mcp.patch`：只补预览/创建机器人 MCP 的最小适配。
- `scripts/install-agent.sh`、`agent-skill/benchmark-function-test/`：安装 Agent 指令、客户端和参考说明。
- `templates/local-services.example.env`：无凭据本机端点示例。
