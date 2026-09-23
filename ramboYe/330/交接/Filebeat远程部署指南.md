---
created: 2026-07-01
tags: [elk, filebeat, 部署, 日志采集, h5项目]
---

# Filebeat 远程部署指南

架构：远程机器 Filebeat → 本机 ES (192.168.5.250:9200)。

---

## 部署前检查（在远程机器上执行）

```bash
# 1. ES 可达
curl -s http://192.168.5.250:9200/ | python3 -c "import sys,json;print(json.load(sys.stdin)['cluster_name'])"
# 预期: docker-cluster

# 2. Docker 可用
docker --version

# 3. 确认日志路径
ls /path/to/logs/game_logic.log
```

---

## 部署步骤

### 1. 生成 Filebeat 配置

在本机生成目标机器的 filebeat.yml：

```bash
python3 ~/Documents/Obsidian/SecondBrain/Claude_Skills/项目/h5gs/scripts/gen_filebeat_config.py \
    --server <server名> \
    --log-dir <日志目录> \
    --types game,gate,cross
```

**server 命名规范**：使用与游戏服务端一致的标识，如 `game1`、`game2`、`cross1008`、`gate1`。

如果不方便跑脚本，手动改模板（`~/elastic-stack/filebeat-template.yml`）：
1. 改 `game_server: "<标识>"`（所有 input 都要改）
2. 改 `paths` 里的日志路径
3. 按需注释/取消注释各 input（game / cross / gate / actv / mail / …）

### 2. 部署到远程机器

```bash
# 把配置文件传到目标机器
scp filebeat-<server>.yml <user>@<target-host>:/path/to/filebeat.yml

# SSH 到目标机器，启动 Filebeat
ssh <user>@<target-host>

docker run -d --name filebeat --restart unless-stopped \
    -v /path/to/logs:/logs:ro \
    -v /path/to/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro \
    -v /path/to/filebeat-data:/usr/share/filebeat/data \
    docker.elastic.co/beats/filebeat:8.17.0
```

### 3. 验证部署

```bash
# 在本机检查新 server 是否出现在列表中
python3 scripts/elklog.py servers

# 确认最近有日志入库
python3 scripts/elklog.py tail 5 --server <server名>

# Filebeat 自身日志（在远程机器上）
docker logs --tail 20 filebeat
```

---

## 各服务类型对应日志文件

| log_type | 日志文件 | Filebeat input id |
|----------|---------|-------------------|
| game | game_logic.log, game_logic2.log | game-logs |
| cross | cross_logic.log | cross-logs |
| gate | gate_info.log | gate-logs |
| actv | actv.log | actv-logs |
| mail | mail_logic.log | mail-logs |
| global | global_logic.log | global-logs |
| chat | chat_logic.log | chat-logs |
| door | door_logic.log | door-logs |
| web | web.log | web-logs |

---

## 管理命令

```bash
# 查看 Filebeat 状态
docker ps --filter name=filebeat

# 查看采集日志
docker logs --tail 50 filebeat

# 重启 Filebeat（修改配置后）
docker restart filebeat

# 停止并删除
docker stop filebeat && docker rm filebeat

# 清理采集位点重新采集（慎用！ES 里会有重复数据）
docker stop filebeat
rm -rf /path/to/filebeat-data/registry
docker start filebeat
```

---

## 排查 Filebeat 问题

| 症状 | 检查 |
|------|------|
| ES 里看不到新 server | `curl http://192.168.5.250:9200/` 从目标机器可达？ |
| 有 server 但无日志 | 日志路径挂载正确？`docker exec filebeat ls /logs/` |
| 日志行未解析 | 日志格式是否匹配 `YYYY-MM-DD HH:MM:SS\tlevel\tsource\tmsg`？ |
| 大量 `ignore_failure` | dissect tokenizer 可能不匹配，检查日志格式 |

---

## 关联

- `测试环境BUG排查工作流.md` — 多 server 日志使用 `--server` 过滤
- `本地ELK日志采集搭建.md` — 本机 ELK 搭建说明
- `~/elastic-stack/filebeat-template.yml` — 模板配置文件
