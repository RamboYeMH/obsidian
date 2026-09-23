# 联盟缓存 miss 风暴 — cross 实例 GetUnionCache 大量缺失

- 日期: 2026-08-26
- 来源: 线上日志巡查 (elklog triage --profile online --from 5h, 2026-08-26 10:05 CST)
- 级别: P1 新增高频异常（低功能影响）

## 现象

- `cache/player.go:306/307` `GetUnionCache` "player X unionY cache cannot found"，5h 窗口 12,604 条（占 0.4%），昨日同窗 **0 条** → 新增
- 今日逐小时: 980 → 2,267 → 4,186 → 3,540 → 2,469（峰值 08:05-09:05，当前 2.5k/h 仍高）
- 实例分布 (24h): cross1002 18.8k / cross1010 14.0k / cross1007 9.9k / cross1009 277 / cross1011 138
- 首发: **2026-08-25 03:30:27 CST cross1007**（:306 行号变体，旧二进制）；16:10 滚动发版（行号 :306→:307）后扩散 cross1010(16:10:23)/cross1002(16:12:44)

## 数据佐证

- `playercache_cross_1007` 引用 1,155 个不同联盟（unionid≠0），`unioncache_cross_1007` 仅 **750 条文档** → ~35% 被引用联盟无缓存
- 首发 3 玩家（724563/1382477/1808668，均 origin server 68）的联盟 ID 在 unioncache_cross_1007 中 MongoDB find 均不存在
- 集合活跃（最新 updatetime = 当日），最早文档 08-02（跨实例 08-07 重建后保留的存量）

## 调用点与影响

- `wmap/internal/packproto.go:2574` `packPlayerHeadInfoByCache` → `pCache.GetUnionCache()` → nil 时容错构造空 UnionCache
- 影响: 跨服场景（wmap UI/视野扫描/战斗界面）玩家联盟昵称/联盟名/旗帜显示缺失，**非崩溃**；主要代价为 error 日志污染 + 展示数据缺口
- 关联热点: onset 时段 wmap 视野扫描 (ctl_scout.go:166, NPC 部队召回扫描) 与 LostMine 联盟战 (ctl_lost_mine.go:386 troop arrive lostmine on union war) 活跃

## 排除项

- RemoveByTime 未触发: `source 'cache/union.go:150'` 30h = 0（7d = 373 次，最近一次 08-23 cross11/12/15）
- 进程重启: cross1007 日志量 04:00-05:00 CST 平稳（11k-18k/5min）无中断
- duplicatemgr 12h tick: cross1007 tick 在 10:54/04:10，非 onset 时刻

## 根因方向（待专项确认）

代码缺陷候选: `game/wmap/duplicatemgr/handler.go:387` `cache.U.RemoveByTime(DUPLICATE_TIEMOUT_DEL*util.DayMs)`（7 天）**无 InstId 过滤**，对比同函数 `cache.PCD.DelByTimeOut(7d, v.InstId)` 带 InstId —— 删服/合服清理会全量清除整实例所有 7 天未更新的联盟缓存（内存 + DB bulk remove），且 `U.Get` 无懒加载（union.go:107-117 纯 sync.Map 查找）→ 缓存被清后不自愈，仅靠玩家重新参与跨服活动时 Put 回补。

## 建议

1. 专项排查 cross 实例 U.Put 填充链路（哪些事件会把联盟缓存写入 cross 实例）
2. 评估修复 RemoveByTime 增加 InstId/ServerID 过滤（与 PCD.DelByTimeOut 对齐）
3. 观察是否随活动周期回落；若持续 2.5k/h 需加急
