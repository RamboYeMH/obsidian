# BUG — 两个编队同时攻击后同时撤退，防守方有概率收不到战报

## 现象

A 的两个 PlayerTroop 同时攻击 B 的一个 PlayerTroop，A 的两个编队同时拉开撤回，B 有概率收不到 A 其中一队的战报。

## 根因

`battle/battlectx.go:1007` — `otherGiveupTarget` 只清理了 `WhoAttack`，未同步清除 `CurTarget`。

撤退时调用链：
`giveUpTarget` (`ctl_battle.go:674`) → `GiveupTarget` → `otherGiveupTarget` → 回到 `giveUpTarget` 判断 `CurTarget == nil` 分流

`otherGiveupTarget` 的实现：
```go
func (t *BatCtx) otherGiveupTarget(other *BatCtx) {
    removeBattleTroop(&t.WhoAttack, other.GetTroopID())
    // ⛔ 缺失：没有 if t.GetCurTargetTroopID() == other.GetTroopID() { SetCurTargetBatCtx(nil) }
}
```

对比部队**死亡**时 `otherDead` 的正确实现：
```go
func (t *BatCtx) otherDead(other *BatCtx) {
    removeBattleTroop(&t.WhoAttack, troopId)
    if t.GetCurTargetTroopID() == troopId {
        t.SetCurTargetBatCtx(nil)    // ✅ 正确清除
    }
}
```

触发条件：B（防守方）的 `CurTarget` 恰好指向正在撤退的 A1 时：

1. `GiveupTarget(A1)` → 调 `otherGiveupTarget(B)` → B.WhoAttack 移除 A1，B.CurTarget 仍悬空指向 A1
2. 回 `giveUpTarget` 690行 `targetCtx.GetCurTarget()` 不为 nil → 走 else 分支
3. 696行 `targetCtx.GetCurTargetTroopID() != owner.GetID()` 为 false（B.CurTarget == A1）→ 跳过 `settleBattle`
4. `battleEnd` 检查：B.InBattle() 仍为 true（CurTarget 悬空）→ 不触发
5. **结果：A1 vs B 的战报未被发送，且 B 战斗状态残留**

## 修复

`game/wmap/internal/battle/battlectx.go:1007` — 对齐 `otherDead` 的行为：

```go
func (t *BatCtx) otherGiveupTarget(other *BatCtx) {
    removeBattleTroop(&t.WhoAttack, other.GetTroopID())
    if t.GetCurTargetTroopID() == other.GetTroopID() {
        t.SetCurTargetBatCtx(nil)
    }
}
```

B.CurTarget 清除后，`giveUpTarget` 690行的 `nil` 检查通过，进入 `settleBattle(target, owner)` 正常发战报。

## 复盘

- 部队撤退与部队死亡在此上下文中语义相同（对"被攻击方"而言都是攻击方离开），但 `GiveupTarget` 和 `TroopDead` 对目标方的清理不对称。
- 类似的不对称模式可扫描：`GiveupTarget` / `TroopDead` / `TroopDel` 对 `otherGiveupTarget` / `otherDead` / `otherDel` 的调用，看各自是否正确清理了 `CurTarget`。
