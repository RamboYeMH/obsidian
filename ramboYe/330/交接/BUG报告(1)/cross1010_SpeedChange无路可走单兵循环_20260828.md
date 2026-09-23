# cross1010 SpeedChange 无路可走单兵循环

**日期**: 2026-08-28
**来源**: 线上日志巡查（cron，5h 窗口 05:02–10:02 CST）
**状态**: 新增异常，已自愈（非代码变更，未定位触发源）

## 现象

- `melem/marching.go:195` `SpeedChange unit <ID> no route from {X Z} to {X Z}`，2026-08-28 **02:08 ~ 07:47 CST** 集中爆发 ~18,000 条，**100% 集中在 cross1010** 单实例。
- 昨日同窗（08-27 05:08–10:08）仅 66 条（同为 cross1010）→ ~170x 突增，判**新增**。
- 09 点后回落至 62 条/小时残留。

## 单兵循环签名（关键判据）

- 5h 窗口 200 样本去重仅 **3 个 unit**（7678787040168518308 ×138 / 7678885171594900459 ×40 / 7678884681968626724 ×22）。
- 峰值小时（03:08–04:08）3,485 条 ≈ 1 秒 1 条 × 单兵 → 单个行军单位每秒重复失败。
- 同一 unit 每秒 from 坐标在变（{2830834 4619768}→{2830877 4619669}→{2830854 4619721}）——**单位仍在移动**，仅寻路重算失败。

## 机制（代码确认）

- 调用链：`ctl_march_ticker.go:250` 每 tick（MarchTick=1s）检查 `march.MarchChange` 标志 → `mgr.SpeedChange(unit, march)`（`game/wmap/internal/mmap/melem/marching.go:176`）→ `mu.GetPaths(e, target)` 失败 → `marching.go:195` 记 error，`return false` **保留原行军**。
- MarchChange 置位源：ctl_lineup.go:68（编队调速）、ctl_march.go:1223（战斗变速）、ctl_map.go:3126（FixPlayerTroopSpeedRatio）、ticker 内 Chasing（:242）/CheckRelicArea 回滚（:257）。
- 寻路失败 = 目标坐标在 navmesh 中不可达（目标 {2361000 4289000} / {2580000 318329} 固定，from 持续变化）。

## 结论

- 3 个行军单位陷入 SpeedChange→GetPaths 失败循环，每秒 1 条 error；功能仅降级（保留原行军），无崩溃、无玩家数据影响。
- 事件随行军结束/到达/清理自愈，无需紧急处理。
- 触发源未定位：疑 cross1010 上某活动/集结/护卫追击在 02:00–08:00 时段持续触发 MarchChange，且对应目标区域寻路不可达。

## 建议

1. 观察 cross1010 是否复发（同签名：单实例+单兵 1/sec+凌晨时段）。
2. 复发时抓单位详情：查该 unit 的 march 目标类型（集结/护卫/采集/远征目标）、当时 navmesh 状态。
3. 可考虑对 `SpeedChange` 失败加退避（如连续失败 N 次后停 1s 重试间隔），消除 1/sec 刷屏。
