# BUG — 哈罗德集结报 ErrCodeServerData：RallyedID 占用残留 + 错误码被吞

- **日期**: 2026-09-11
- **区服**: game414
- **玩家**: 5326595（熊熊熊）
- **现象**: 召唤哈罗德后点击集结，客户端收到 `NewTroopAck errCode=ErrCodeServerData, action=MarchActRally`，无法集结攻击
- **状态**: 根因已定位，待修复

## 现象

- 18:18:27:841 客户端 `↓[cspb.NewTroopAck-0]:errCode=ErrCodeServerData, action=MarchActRally`
- 18:18:29 服务端 `internal/ctl_lineup.go:1799 5326595 march fail lineupId tp:0 id:7572830050878032538 code:2 [game414]`
- 18:13:56 / 18:14:03 / 18:14:13 / 18:18:29 五次失败，全是同一编队 7572826378680696993 打同一哈罗德
- 目标：动态召唤怪（哈罗德）7684205875790720511（newTroopData 18:05:12 `getAvailableHarold ... status:available` 时分配给该玩家）

## 根因（因果链，代码+日志双向印证）

### 1. 占用残留的来源（17:23–17:24 第一次集结）

- 17:23:23 玩家创建集结，`OnPlayToMapMarchSuccess` → `delNpc` 把自己选中的哈罗德 `SetRallyedID(marchID)`（ctl_lineup.go:1153）。
- 17:24:35 行军碰撞召回 `unit:7684205888675622467 stopMarch MarchAct:6 marchtarget:7684205875790720511`（ctl_march_ticker.go:222-230）。`isStop` 分支先 `stopMarch(unit)`（内部 `troop.StopMarch()` 清 march），再 `RecallTroop` → `recallRallyTroop`（ctl_rallytroop.go:621）→ `DisbandRallyTroop`（ctl_rallytroop.go:437）→ `GiveUpTroopAction` → `giveUpTroopMarch`（ctl_march.go:1388）。
- **缺口**：`giveUpTroopMarch` 第一步 `GetMarch()` 失败直接 return（1391-1392），此时 march 已被 `stopMarch` 清掉 → 1411-1426 的 `npc.SetRallyedID(0)`（1420）**永远走不到**。
- 哈罗德 `RallyedID` 残留为已解散集结的 ID。

### 2. 残留为何挡住后续集结（18:13–18:18 五次失败）

- `delNpc` 再次检查 `npc.GetRallyedID() != 0 && != marchID` → 返回 `ErrCodeNpcSummonMonsterIsRallyed`（ctl_lineup.go:1157），**该分支无任何 tlog**。
- `OnPlayToMapMarchSuccess` 的 defer 统一兜底 `errCode = ErrCodeServerData`（ctl_lineup.go:906）→ 客户端只见 ServerData。
- 侧证：18:14:13 `getAvailableHarold: rally not found: 7683129638582587834` 36+ 条（另一玩家 5315203 的 `RallyTroopIDs` 脏数据）说明该玩法状态字段普遍易残留。

### 3. 为何 18:20:20 自愈

- 残留值是**旧集结 ID**。任何部队只要对该哈罗德开战（哪怕被打），`npcTroopjoinBattlePassive` → `SetRallyedID(0)`（ctl_battle.go:742）即解除占用。
- 18:20:20 失败编队成功出兵、18:21:11 集结战开打（此时 `RallyedID` 被清零）。期间哈罗德 Deadline 到期消失/重建也可能重置该字段，两者都解释自愈。

## RallyedID 生命周期全量触点（grep 全仓实锤）

| 动作 | 位置 | 说明 |
|------|------|------|
| 置位 | ctl_lineup.go:1153 `SetRallyedID(marchID)` | delNpc 集结出发时 |
| 清零(战斗) | ctl_battle.go:742 `SetRallyedID(0)` | 被动开战即清，任何人打它一下就解 |
| 清零(放弃) | ctl_march.go:1420 `SetRallyedID(0)` | **giveUpTroopMarch 尾部，GetMarch 早退则跳过** |

## 修复建议（按优先级）

1. **stopMarch 路径单独清占用**：`RecallTroop`/`DisbandRallyTroop` 前置或 `stopMarch0` 内，按 `unit.GetOriginTargetID()/GetTargetID` 清目标 NPC 的 `RallyedID/RallyedTitanID`，不依赖 `GetMarch()` 存活。参考 ctl_march.go:1416-1426 同款判断。
2. **delNpc 占用分支补日志**：`NpcSummonMonsterIsRallyed`/`TiTanIsRallyed` 分支加 tlog（含 npcID/rallyedID/marchID），下次 5 分钟定位。
3. **OnPlayToMapMarchSuccess:906 收窄兜底**：保留兜底但把原始 errCode 打进日志，避免吞码。
4. **可选**：`delNpc` 占用检查校验 RallyedID 指向的集结是否仍存在/仍指向本 NPC，死引用直接视为未占用（自愈）。

## 复盘

- 状态清理逻辑写在 `giveUpTroopMarch` 尾部且依赖 `GetMarch()` 存活，而调用方（ticker isStop）在调用前已把 march 清掉——**“先清状态再善后”的调用顺序让善后代码变死代码**。同类清理建议前置到 stopMarch 路径本身。
- 吞码兜底（906）+ 无日志错误分支（1157）叠加，导致现象为无上下文 ServerData。排查成本主要花在还原这两层掩盖。
- 关联：`getAvailableHarold` 的 RallyTroopIDs 死引用（36+ 条 warn）是同一玩法状态管理薄弱的另一表现，可一并治理。

## 关键文件

- `game/wmap/internal/ctl_lineup.go:1153,1157,906,1799`
- `game/wmap/internal/ctl_march.go:1388-1427,1508-1517`
- `game/wmap/internal/ctl_march_ticker.go:222-230`
- `game/wmap/internal/ctl_rallytroop.go:621,437,484`
- `game/wmap/internal/ctl_battle.go:738-743`
- `game/wmap/internal/ctl_map.go:2905-2933`
