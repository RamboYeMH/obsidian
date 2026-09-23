---
created: 2026-06-17
tags: [bug-report, 城防, OneLineupNtf, 性能, setLineupDataFailCb, h5_new_tf_v1044]
status: 待修复
related: "[[2026-06-17-冰髓争夺城防并发丢兵BUG修改报告]]"
---

# BUG 分析：城防战期间反复拉出/回城编队导致 OneLineupNtf 洪流

## 一、问题描述

**测试反馈**：A 攻击 B 城堡时，B 反复将编队拉出再回城，操作几次后服务器变卡，客户端收到大量 `OneLineupNtf` 消息。

**是否与冰髓丢兵修改相关**：**否**。冰髓丢兵修复只改了 `setLineupDataFailCb` 的版本不匹配路径（不触发 OneLineupNtf）。洪流是已有逻辑问题，测试时间接发现。

---

## 二、根本原因

### 触发链

```
B 拉出/回城编队
  → AssignSoldier / setLineupDataCb
    → toDefenderInfo(update=true) → Cast2Map(P2MChangeTroop)

wmap.OnP2MChangeTroop:
  defTroop.RemoveSelfTroop(playerId)        // 删除 B 的旧 N 个 PlayerTroop
  updatePlayerCityDefender
    → newPlayerCityDefender
      → for i := range ids {
            NewPlayerTroop(idgen.NewID(), ..., ids[i], ...)
        }                ↑ 每次全新对象，LastSyncStatus = 0
  BroadcastUnitNtfImpl(oldDefender)
    → CheckTroopStatus(rally)
      → for _, v := range rally.GetTroops() { SyncTroopStatus(v) }
        → new troop: LastSyncStatus(0) ≠ 实际状态 → M2PTroopSyncStatusNtf × N

play.OnM2PTroopSyncStatus (ctl_lineup.go L1748):
  lineup.CurrentState = req.Status
  play.SendTo(p.PlayerID, play.PackOneLineupNtf(...))   // 无条件发送 L1768
```

**每次 P2MChangeTroop 成功 = wmap 重建 N 个 PlayerTroop = 发出 N 条 OneLineupNtf**

### 根本原因说明

`wmap/internal/ctl_playertroop.go` 的 `newPlayerCityDefender` 每次都通过 `idgen.NewID()` 创建**全新** `PlayerTroop` 对象。新对象字段 `LastSyncStatus = 0`（零值），与实际状态（`Combat`/`Defender`）不同，导致后续 `BroadcastUnitNtfImpl` 时 `SyncTroopStatus` 判断为"状态变更"并发送 `M2PTroopSyncStatusNtf`。

`play` 侧 `OnM2PTroopSyncStatus` 在 L1768 **无条件**发送 `OneLineupNtf`，未判断状态是否真正变化。

### 消息数量估算

| 场景 | 每次操作 OneLineupNtf 数量 |
|------|--------------------------|
| B 拉出 1 支编队（N=5 守城编队） | N-1=4（sync status） + 1（calcSoldier） = 5 |
| B 回城 1 支编队（N=5 守城编队） | N=5（sync status） + 1（adjustSoldiers） = 6 |
| 10 次完整拉出+回城 | ≈ 110 条 |

---

## 三、`adjustSoldiers` 的问题（次要）

`game/play/internal/ctl_lineup.go` L2662：

```go
func (play *Play) adjustSoldiers(p *mplayer.Player, lineup *mlineup.Lineup, lineupType int32) {
    var overflow int64
    for tp, cnt := range lineup.GetSoldiers() {
        // 计算溢出...
    }
    if overflow > 0 { ... }
    play.SendTo(p.PlayerID, play.PackOneLineupNtf(p, lineup, lineupType))  // ← 无论是否有溢出
}
```

每次回城（L3036）必然触发 1 条 `OneLineupNtf`，即使兵力完全没有变化。这是预期行为（同步编队状态），单独不算洪流，但叠加上主路径后放大总量。

---

## 四、修复方案

### 方案一：play 侧守卫（推荐）

**文件**：`game/play/internal/ctl_lineup.go`  
**函数**：`OnM2PTroopSyncStatus`（L1755）

```go
// 修改前
lineup.CurrentState = req.Status
...
lineup.RunTimeOut = req.RunTimeOut
lineup.SetIsRally(req.IsRally)
play.SendTo(p.PlayerID, play.PackOneLineupNtf(p, lineup, req.LineupType))  // 无条件

// 修改后
unchanged := lineup.CurrentState == req.Status &&
    lineup.RunTimeOut == req.RunTimeOut &&
    lineup.GetIsRally() == req.IsRally
lineup.CurrentState = req.Status
...
lineup.RunTimeOut = req.RunTimeOut
lineup.SetIsRally(req.IsRally)
if !unchanged {
    play.SendTo(p.PlayerID, play.PackOneLineupNtf(p, lineup, req.LineupType))
}
```

**安全性**：
- wmap 因重建 PlayerTroop 触发的"假变化"（play 侧已是正确状态）→ `unchanged=true` → 跳过，消除洪流
- 真实状态变更（Defender→Combat 等）→ `unchanged=false` → 照常推送

### 方案二：wmap 侧根治（后续优化）

在 `newPlayerCityDefender`（`wmap/internal/ctl_playertroop.go` L1449）创建新 `PlayerTroop` 后，将 `LastSyncStatus` 初始化为实际状态，避免 `SyncTroopStatus` 误判。改动在 wmap，影响面较广，建议作后续优化。

---

## 五、与冰髓丢兵修改的关系

| 修改 | 文件 | 影响 | OneLineupNtf |
|------|------|------|--------------|
| 冰髓丢兵修复 | ctl_lineup.go `setLineupDataFailCb` | 版本过期路径，补回 HurtCount | **无** |
| OneLineupNtf 洪流修复 | ctl_lineup.go `OnM2PTroopSyncStatus` | 城防 P2MChangeTroop 重建 troop 导致的假变化通知 | **消除** |

两个修改完全独立，可分开上线。

---

## 六、测试要点

1. A 攻 B 城堡，B 反复拉出/回城 10+ 次
2. 修复前：客户端 OneLineupNtf 消息数 ≈ 编队数 × 操作次数 × 2
3. 修复后：状态真正变化时发 1 条，重复 sync 不再发
4. 验证：编队状态（Defender→Combat→Defender）仍然正确同步到客户端
