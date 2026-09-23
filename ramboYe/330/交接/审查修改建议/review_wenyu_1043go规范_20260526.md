---
created: 2026-05-26
tags: [review, wenyu]
branch: h5_new_tf_v1043
p0: 0
p1: 3
p2: 4
---

## 审查概览

| 字段 | 内容 |
|------|------|
| 审查人 | Claude Sonnet 4.6 |
| 被审查人 | wenyu |
| 日期 | 2026-05-26 |
| 分支 | `h5_new_tf_v1043` |
| 规则来源 | `go-rules.md`（规范 1–24 + L1–L13）|
| 审查范围 | 今日两个提交：`8019dace60`、`9353f9bcf5` |
| 关注维度 | Go 项目规范 · 逻辑风险 |

**问题总数：P0 × 0，P1 × 3，P2 × 4**

---

## 问题汇总表

| 优先级 | 规范 | 问题描述 | 文件位置 |
|--------|------|---------|---------|
| P1 | #12 + L7 | `GetPhaseStartTime` bool 返回值被 `_` 忽略，startTime=0 导致定时器立即触发 | `ctl_battlefield_melting_ice.go:84` |
| P1 | #4 / #6 | `troop.OriginMarchExtra.MeltingIceCnt` 穿透访问嵌套字段 | `ctl_battlefield_melting_ice.go:587` |
| P1 | #10 | `troop.OriginMarchExtra = nil` 直接赋 nil，应封装为 reset 方法 | `ctl_battlefield_melting_ice.go:588` |
| P2 | #7 | `BiLogBfMeltingIceArrived(...)` 6 个参数未换行 | `ctl_battlefield_melting_ice.go:640` |
| P2 | #4 | `pc.Name` 直接访问字段，应通过 getter | `ctl_battlefield_melting_ice.go:637` |
| P2 | #18 | `troop.BatCtx().GetCosts()[troopId]` map 直接下标访问 | `ctl_battlefield_melting_ice.go:645` |
| P2 | 命名 | `TimeFormNow` 拼写错误（应为 `TimeFromNow`）；格式：括号内多余空格、`>0{` 缺空格 | `time.go:98` |

---

## 问题详情

### P1-01 · GetPhaseStartTime bool 返回值忽略（规范 #12 + L7）

**文件：** `game/wmap/internal/ctl_battlefield_melting_ice.go:84`

```diff
- startTime, _ := wmap.BattlefieldMgr.GetPhaseStartTime(cspb.BFPBattleIn)
+ startTime, ok := wmap.BattlefieldMgr.GetPhaseStartTime(cspb.BFPBattleIn)
+ if !ok {
+     tlog.Errorf("getMeltingIceWeekSettleTime: BFPBattleIn phase not found")
+     return 0
+ }
```

> **根因：** `GetPhaseStartTime` 返回 `(int64, bool)`，阶段未开始时 bool=false、startTime=0。此值流入 `NextWeekdayTs(0, ...)` 后计算出历史时刻，传给 `timerMgr.NewTimer` 的 `diffTs` 为负数，定时器立即触发，周榜结算提前执行。

---

### P1-02 · OriginMarchExtra 穿透访问（规范 #4 / #6）

**文件：** `game/wmap/internal/ctl_battlefield_melting_ice.go:587`

```diff
- meltCnt := int64(troop.OriginMarchExtra.MeltingIceCnt)
```

`troop.OriginMarchExtra.MeltingIceCnt` 穿透两层访问嵌套字段，违反规范 #6"不得在外部穿透多层访问"。应在 `PlayerTroop` 上封装方法：

```go
// 推荐：封装到 PlayerTroop 方法
func (t *PlayerTroop) PopMeltingIceCnt() int64 {
    if t.OriginMarchExtra == nil || t.OriginMarchExtra.MeltingIceCnt <= 0 {
        return 0
    }
    cnt := int64(t.OriginMarchExtra.MeltingIceCnt)
    t.OriginMarchExtra = nil
    return cnt
}
```

---

### P1-03 · 直接赋 nil 而非封装 reset（规范 #10）

**文件：** `game/wmap/internal/ctl_battlefield_melting_ice.go:588`

```diff
- troop.OriginMarchExtra = nil
```

规范 #10：需要重置结构体字段必须封装 `resetXXX` 方法，不得在外部直接赋 nil 或零值。与 P1-02 合并解决：将"取值 + 清空"封装为 `PopMeltingIceCnt()` 后，`consumeOriginMeltCnt` 简化为：

```go
func consumeOriginMeltCnt(troop *mtroop.PlayerTroop) int64 {
    if cnt := troop.PopMeltingIceCnt(); cnt > 0 {
        return cnt
    }
    return 1
}
```

---

### P2-01 · BiLogBfMeltingIceArrived 超 3 参数未换行（规范 #7）

**文件：** `game/wmap/internal/ctl_battlefield_melting_ice.go:640`

```diff
- wmap.BiLogBfMeltingIceArrived(playerID, score, count, int64(gridId), lvlCountMap, createFailMap)
+ wmap.BiLogBfMeltingIceArrived(
+     playerID,
+     score,
+     count,
+     int64(gridId),
+     lvlCountMap,
+     createFailMap,
+ )
```

---

### P2-02 · pc.Name 直接字段访问（规范 #4）

**文件：** `game/wmap/internal/ctl_battlefield_melting_ice.go:637`

```diff
- PlayerName: pc.Name,
+ PlayerName: pc.GetName(),
```

---

### P2-03 · map 直接下标访问（规范 #18）

**文件：** `game/wmap/internal/ctl_battlefield_melting_ice.go:645`

```diff
- costs := troop.BatCtx().GetCosts()[troopId]
```

规范 #18：map 字段按 key 取值必须封装为方法。应在 `BatCtx` 上增加：

```go
func (b *BatCtx) GetCostByTroopID(troopId int64) []*SomeType {
    return b.GetCosts()[troopId]
}
```

调用方改为：

```go
costs := troop.BatCtx().GetCostByTroopID(troopId)
```

---

### P2-04 · TimeFormNow 命名拼写 + 格式问题

**文件：** `vendor/git.tap4fun.com/fw/tse/core/util/time.go:98`

```diff
- //一个时间距离现在多久（）
- func TimeFormNow( startTs int64 ) int64 {
-     if startTs > 0{
+ // TimeFromNow 返回 startTs 距当前的秒数，startTs <= 0 时返回 0。
+ func TimeFromNow(startTs int64) int64 {
+     if startTs > 0 {
```

同步更新所有调用方：`exp_union_center.go`、`ice_contest_crystal_tower.go`。

---

## 正确改动 Praise

1. **新提取的 6 个函数全部有中文注释**：`consumeOriginMeltCnt` / `updateMeltingAreaCount` / `processMeltingIceStamina` / `broadcastMeltingIceArrived` / `calcMagicCarbonCost` / `grantCarbonReward` 均在签名上方添加说明，符合规范 #13 ✅

2. **`broadcastMeltingIceArrived` 签名 7 个参数正确换行**：符合规范 #7 ✅

3. **`processMeltingIceStamina` 的 `CastByPID` 调用正确换行**：5 个参数换行写，符合规范 #7 ✅

4. **`IceMorrowMine` 添加 `//go:generate accessor_engine2` 指令**：符合规范 #16 ✅

5. **`GiveUp` / `OccupyEnd` 全面切换 accessor**：`SetState` / `SetProtectTs` / `SetOccupyUnionID` 等均通过 setter 访问，符合规范 #24 ✅

6. **`getMeltingIceWeekSettleTime` 冗余形参消除**：移除外部传入的 `startTime`，改为内部获取，符合规范 #17 ✅（但需补 bool 校验，见 P1-01）

---

## 修复进度追踪

| 编号 | 问题 | 状态 |
|------|------|------|
| P1-01 | GetPhaseStartTime bool 返回值处理 | 待修复 |
| P1-02/03 | PopMeltingIceCnt 封装（穿透访问 + nil 赋值） | 待修复 |
| P2-01 | BiLogBfMeltingIceArrived 换行 | 待修复 |
| P2-02 | pc.Name → pc.GetName() | 待修复 |
| P2-03 | GetCosts() map 访问封装 | 待修复 |
| P2-04 | TimeFormNow → TimeFromNow + 格式修正 | 待修复 |
