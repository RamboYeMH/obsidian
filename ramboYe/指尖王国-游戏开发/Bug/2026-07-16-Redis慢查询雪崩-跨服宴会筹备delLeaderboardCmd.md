---
created: 2026-07-16
tags: [线上排查, Redis, 性能, 宴会筹备, 排行榜, 雪崩]
severity: P1
---

# Redis 慢查询雪崩 — 跨服宴会筹备 `delLeaderboardCmd`

## 概述

2026-07-15 凌晨 00:00，跨服宴会筹备活动（cfgid=1020311）开启时，Redis 出现大量 evalsha 慢查询，引发雪崩。根因是 `delLeaderboardCmd` Lua 脚本使用 SCAN 全库遍历（无 COUNT 限制），在 175 万 key 的 Redis 实例上单次执行需 35 万次 SCAN 迭代，叠加 Mailserver 凌晨批量发邮件，导致 Redis 阻塞近 2 小时。

## 关键数据

| 指标 | 数值 |
|------|------|
| 活动 ID | `7662414070601317800` |
| 活动类型 | `ActvTypeCrossBanquetPrepare` (120) |
| 活动配置 | cfgid=1020311 |
| 开启时间 | 2026-07-15 00:00:00 CST |
| 慢查询脚本 SHA1 | `997906e48842762a906ee441c07b70166ef2c677` |
| 慢查询脚本 | **`delLeaderboardCmd`** |
| 受影响 zone | 225 个 |
| Redis 实例 | cross1，DBSIZE=1,758,683 |
| rank.go:393 错误 | 32,605 条 |
| Mailserver Redis SetNX 超时 | 93,254 条 |
| Mailserver HTTP 邮件错误 | 460,135 条 |

## 雪崩链路

```
2026-07-15 00:00:00  跨服宴会筹备活动 7662414070601317800 开启

00:00:01  actv1 服务 nil pointer panic（chanrpc.go:244）
            → BanquetPrepareTmpl.OnTick() 崩溃

00:00:03  OnBanquetPrepareOpenNtf 到达各 game server
            → Del() → DeleteRankCorssList() → delLeaderboardCmd
            → SCAN 全库 175万 key → 匹配 0 个 → 白扫全库
            → 一次 evalsha 内 35万次 SCAN 迭代
            → Redis 单线程阻塞几十秒

00:00 同时  Mailserver 凌晨批量发邮件
            → 460K HTTP 邮件请求
            → 93K Redis SetNX deadline exceeded
            → Redis 压力雪上加霜

00:00:15  rank.go:393 开始大面积 TCP 超时
            → updateLeaderboardEntryCmd 失败
            → 32,605 条错误，持续近 2 小时

00:00~02:05  delLeaderboardCmd 超时
            → NATS 回调失败（ri.Err != nil）
            → SentMap 未标记
            → banquet_prepare.OnTick() 重试
            → 再次 delLeaderboardCmd → 再次超时
            → 死循环：225 zone × N 次重试 = 几百万次 evalsha
```

## 根因分析

### `delLeaderboardCmd` 脚本问题

```lua
-- rank/services/rank.go:224
local rank_keys = 'leaderboard_rank_' .. leaderboardId .. '*'
repeat
    local res = redis.call("scan", cursor, "MATCH", rank_keys)
    -- 没有指定 COUNT，默认 10
    -- ...
until cursor <= 0
```

**SCAN 不是索引查找，是全表遍历。** `MATCH` 只是服务端过滤，不减少扫描量。

- Redis cross1 有 **1,758,683** 个 key
- 默认 COUNT=10，每次 SCAN 返回约 10 个 key
- 全库扫描需要 **175,868 次 SCAN 迭代**
- 再对 `leaderboard_extra_*` 重复一遍 = **~350,000 次 SCAN**
- 实际匹配 BanquetCrossUnionRank 的 key：**0 个**

**结论：一次 `delLeaderboardCmd` 做了 35 万次无意义的 SCAN，白白阻塞 Redis。**

### 无限重试机制

`banquet_prepare/api.go` 的 `OnTick()` 重试逻辑：

```go
// 失败回调
if ri.Err != nil {
    return  // SentMap 已删，SentMap 未设 → 下次 OnTick 重试
}
progress.SentMap[sid] = group  // 只有成功才标记
```

`delLeaderboardCmd` 超时 → NATS 回调收到 error → `SentMap` 未标记 → `OnTick` 重试 → 再次超时 → **死循环**。

## 涉及的代码路径

| 文件 | 行号 | 功能 |
|------|------|------|
| `rank/services/rank.go` | 224-282 | `delLeaderboardCmd` — 问题脚本 |
| `rank/rankmgr/handler.go` | 96-105 | `OnDeleteRankListReq` — 调用入口 |
| `game/play/internal/ctl_rank_cross.go` | 345-356 | `DeleteRankCorssList` — play 侧 |
| `game/play/internal/ctl_banquet.go` | 115-146 | `OnBanquetPrepareOpenNtf` — 触发 Del() |
| `game/play/internal/ctl_banquet.go` | 730-736 | `CrossBanquetRank.Del()` — 调用 DeleteRankCorssList |
| `actv/cactv/internal/activity/template/banquet_prepare/api.go` | 50-102 | `OnTick` + 重试逻辑 — 死循环源头 |

## 建议修复

1. **`delLeaderboardCmd` 加 COUNT 参数**：`SCAN cursor MATCH pattern COUNT 10000` 可大幅减少迭代次数

2. **改用精确 key 删除**：如果知道具体的 rank key 格式，直接用 `DEL leaderboard_rank_<精确key>` + `DEL leaderboard_extra_<精确key>`，避免 SCAN

3. **加退避重试**：`OnTick` 失败回调中加指数退避，避免死循环

4. **Redis 实例隔离**：Rank 服务与 Mailserver 使用不同 Redis 实例，避免互相影响

5. **批量邮件限流**：Mailserver 凌晨批量发邮件加限流/QPS 控制

## 相关日志

- 活动数据：`actv1.actv.findOne({_id: 7662414070601317800})`
- 日志搜索：`python3 scripts/elklog.py search "PrepareOpen = true" --profile online --from 40h --to 20h`
- rank 错误：`python3 scripts/elklog.py search "updateLeaderboardEntry" --profile online --from 40h --to 30h`
