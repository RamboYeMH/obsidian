# BUG - 龙巢防守集结卡死：giveUpTarget IF 分支提前 return 缺 battleEnd

> 最终版根因（2026-08-11，本地 GM 复现 + 双修复对照实验验证）
> 取代第一版根因（`otherGiveupTarget` 缺 CurTarget 清理）——最终日志证明 CurTarget 会被清空，真正缺口在 giveUpTarget IF 分支

## 现象

- **环境**: online / cross1007（远征跨服）
- **玩家**: 6487192(game501), 6444469(game501), 2972815(game218)
- **时间**: 2026-08-10 09:00 起，至排查时（22:00+）仍未恢复
- **表现**: 玩家部队驻防龙巢后，防守集结被攻击者围攻，全部攻击者死亡/召回后集结无法解散，部队永久卡在龙巢，客户端显示永久"采集中"
- **特征**: 被其他玩家攻击一次后状态才解除（新攻击者加入→触发战斗→离开时触发 battleEnd→CCityDefendEnd 看到 InBattle:false→解散）

### 日志特征

- `ctl_union_war.go:2234` 反复打出 `龙巢防守战结束, InBattle:true`，集结永不解散
- 攻击者全部离开后（21:07:43 起），集结进入**静默驻留**状态：无 battleEnd、无 CCityDefendEnd、无 joinpassive

## 根因（最终版）

### 核心缺陷

**解散入口唯一性**：`CCityDefendEnd` 仅 2 个调用点（`rTroopBattleEndAlive` / `rTroopBattleEndDead`），**都在 `battleEnd` 路径内**。任何导致 `battleEnd(防守集结)` 不触发的路径都会让集结永久驻留。

**召回路径断链**（`giveUpTarget`，ctl_battle.go:748-804）：

```go
func (wmap *WMap) giveUpTarget(owner battle.IBattleUnit) bool {
    // ...
    ownerBatCtx.GiveupTarget()          // 清防守集结.WhoAttack + owner.CurTarget
    // ...
    if targetCtx.GetCurTarget() == nil {   // ← 最后一个攻击者被召回时命中
        if targetBatUnit, ok := melem.UnitToIBattleUnit(target); ok {
            wmap.settleBattle(targetBatUnit, owner)
            return true                    // ← 提前返回，battleEnd 缺失！【根因缺口】
        }
    } else {
        // ELSE 分支：有 3 条既有 battleEnd 触发机制（TroopDel attackMe / 182 行兜底 / 目标死亡保底）
    }
    // TAIL: !InBattle() 时 battleEnd（IF 分支提前 return 后永远执行不到）
    if targetBatUnit, ok := ...; ok && !targetBatUnit.BatCtx().InBattle() {
        wmap.battleEnd(targetBatUnit)
    }
    return false
}
```

**时序**（线上 21:07:43，与本地 GM 复现一致）：
1. **C 先召回**：防守集结.CurTarget=C（非 nil）→ **ELSE 分支** → `GiveupTarget` 清 WhoAttack → 正常
2. **D 后召回**：防守集结.CurTarget=nil（C 已清）→ **IF 分支** → `settleBattle + return true` → `battleEnd(防守集结)` 不触发 → `CCityDefendEnd` 失去唯一调用点 → **卡死**

**为什么死亡正常、召回必卡死**（分水岭）：
- 死亡路径 `TroopDead`（battlectx.go:1029-1034）有 **attackMe 保底**：`len(attackMe)==0 && curTarget!=nil` 时把 curTarget 加入列表，强制触发 `battleEnd(被攻击方)`
- 召回路径 `giveUpTarget`/`TroopDel` **无此保底** → IF 分支提前 return → battleEnd 缺失

**D 不被反击的原因**：`JoinBattlePassive`（ctl_battle.go:637 guard `beAtk.CurTarget != nil`）——防守集结 CurTarget 一直被 C 占住，D 无法加入反击，D 也不在防守集结的 WhoAttack 反击链中。

**版本退化**：v1101 有 `checkRallyDisbandy`（commit `51a56ac774` "容错处理非战斗状态集结未解散bug"，2024-06-05），v1048 被 wenyu 在 commit `bb4649930d4` "1039整理代码"（2026-03-17）整体注释掉 → v1048 失去 tick 兜底。

### 关键代码位置

| 文件 | 行号 | 说明 |
|------|------|------|
| `game/wmap/internal/ctl_battle.go` | 766-779 | `giveUpTarget` IF 分支 `settleBattle + return true` 提前返回（**根因缺口**） |
| `game/wmap/internal/ctl_battle.go` | 796-801 | TAIL `!InBattle() → battleEnd` 兜底（被 IF 提前 return 跳过） |
| `game/wmap/internal/battle/battlectx.go` | 1029-1034 | `TroopDead` attackMe 保底（死亡路径正常的原因） |
| `game/wmap/internal/battle/battlectx.go` | 898-909 | `InBattle()` = CurTarget != nil 或 WhoAttack 非空 |
| `game/wmap/internal/ctl_union_war.go` | 2230-2251 | `CCityDefendEnd` InBattle=true 时不解散 |
| `game/wmap/internal/ctl_battle.go` | 635-653 | `JoinBattlePassive` 637 行 guard 导致 D 不被反击 |
| `game/wmap/internal/ctl_rallytroop.go` | 623-636 | `recallRallyTroop` → `DisbandRallyTroop` 召回入口 |

## 修复方案（双保险，均已验证）

### 修复 1：事件层治本（giveUpTarget IF 分支补 battleEnd）

`ctl_battle.go:775-778`，在 IF 分支 settleBattle 后补 battleEnd，与 `TroopDead` attackMe 保底对齐：

```go
if targetCtx.GetCurTarget() == nil {
    if targetBatUnit, ok := melem.UnitToIBattleUnit(target); ok {
        wmap.settleBattle(targetBatUnit, owner)
        if _, isRt := melem.UnitToRallyTroop(target); isRt &&
            !targetBatUnit.BatCtx().InBattle() {
            wmap.battleEnd(targetBatUnit)   // ← 新增兜底
        }
        return true
    }
}
```

限定 RallyTroop + `!InBattle()`：仅集结、仅无战斗状态时触发，避免影响普通部队结算语义。
触发时机：D 的 `GiveupTarget` 已清空防守集结 WhoAttack/CurTarget → `InBattle()=false` → battleEnd 走 `CCityDefendEnd` → 立即解散（同回调栈，零延迟）。

### 修复 2：tick 层兜底（恢复 v1101 的 checkRallyDisbandy）

`ctl_battle.go:117-137` + `battlePrepare` 调用点（169 行）恢复：

```go
func (wmap *WMap) checkRallyDisbandy(owner battle.IBattleUnit) {
    if rt, ok := melem.UnitToRallyTroop(owner); ok {
        if _, ok := rt.GetMarch(); ok { return }   // 行军中不解散
        if !cspb.IsMapUnitPlayerCity(rt.GetDefendType()) {
            wmap.DefenderForceExitBattle(owner)      // 非城防部队强制解散
        } else {
            wmap.RecallSelfTroopFromIdleCityDefenceTroop(rt)
        }
    }
}
```

`battlePrepare` 每 tick 检查 idle 集结（`exitBattleLogic` 返回 true 时），事件层漏网时下个 tick（约 2s）补上。
**不影响正常驻防**：防守集结只在攻击者到达时创建（`getOrCreateDefender`），无战斗时无集结，checkRallyDisbandy 只处理战斗形态的 InBattle=false 集结。

## 复现步骤（本地 GM）

1. **环境**: 本机测试服（世界地图也可复现），龙巢 CentralCity 存在
2. **防守方**: 部队驻防龙巢形成防守集结
3. **进攻方**: 玩家 28528 派 **2 个集结**（A/B）攻击龙巢，B 晚到（被 JoinBattlePassive guard 拦截不反击）
4. **GM 召回**: `recallRallys`（临时 GM 命令，recallRallys <pid>，召回该玩家所有集结）
5. **BUG 触发**: 先召回被反击者 A（ELSE 分支）→ 后召回单向攻击者 B（IF 分支）→ 卡死
6. **验证**: ES 日志 `giveUpTarget IF owner:B (targetCurTarget==nil)` 后无解散日志 → 卡死

> ⚠️ 卡死仅当"先召回被反击者、后召回单向攻击者"；若顺序相反（后召回的是 CurTarget 持有者），后者的 TroopDel attackMe 保底会正常解散。

## 对照实验（本地，GM recallRallys）

| 测试 | 事件层修复 | tick 兜底 | 结果 |
|------|-----------|----------|------|
| 17:01 | ❌ 注释 | ✅ 开启 | ✅ 解散（延迟1 tick，checkRallyDisbandy 日志出现） |
| 17:05 | ✅ 开启 | ❌ 未触发 | ✅ 立即解散（FIX battleEnd 日志出现） |
| 17:09 | ❌ 注释 | ❌ 注释 | ❌ 卡死复现（无任何解散日志） |
| 17:31 | 两处均在（召回顺序安全） | — | ✅ ELSE 分支既有保底解散 |

**结论**：双修复全关必然卡死；任一修复开启均可解散；事件层立即、tick 层延迟一个周期。两处修复独立有效、互为备份。

## GM 链路一致性

GM `recallRallys` 与线上同链路，仅触发源不同：

```
RecallTroop → GetRecallController(MapUnitRallyTroop) → recallRallyTroop
  → DisbandRallyTroop → GiveUpTroopAction → giveUpTroopBattle → giveUpTarget 【汇合点】
```

- 线上触发源：`RecallAttacks`（owner change）/ 玩家手动召回 → 同一个 `RecallTroop`
- GM 把线上小概率事件（恰好在该时序召回全部攻击者）确定性放大，用于复现验证

## 玩家恢复方案

1. **首选**：玩家重新登录 → `OnEventValidateTroopsOnline` → `P2MTroopValidateRepair` → `ForceDelect`
2. GM `deltroop` 不适用（`ForceRecall` 拒绝 CentralCity）

## 复盘

- `giveUpTarget` IF 分支与 ELSE 分支的 battleEnd 触发机制不对称：ELSE 有 TroopDel attackMe / 182 行兜底 / 目标死亡 3 条路径，IF 分支只有 settleBattle
- 死亡路径（TroopDead）有 attackMe 保底、召回路径（giveUpTarget）没有，这是"死亡正常、召回卡死"的分水岭
- v1048 在"1039整理代码"中注释掉 v1101 的 checkRallyDisbandy 兜底，属于无意识的功能丢失（疑似误当死代码清理）
- 防守集结的解散完全依赖攻击侧事件触发 battleEnd，缺少独立的超时/状态巡检兜底机制（checkRallyDisbandy 正是为此设计）
