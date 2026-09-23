---
created: 2026-05-19
tags: [bug报告, TDUnlimited, 无限塔防, 跳关, H5项目]
status: 待验证
severity: P2
---

# BUG 根因分析：TDUnlimited 关卡进度回退

## 问题描述

玩家反馈：5月12日在 `TinyType_TDUnlimited`（无限塔防，玩法类型 6）中已达到第 2200 关，但 5月18日查看时进度显示为第 1872 关，5月19日目标关卡变为 1800。服务器无异常维护，无存档异常。策划确认配置表未做任何修改。

**关键日志：**
- 5月18日 `OnTowerSkipStageReq` tarStage=1900
- 5月19日 `OnTowerSkipStageReq` tarStage=1800

---

## 根因定位

### 核心问题

`addHistoryMaxStage`（更新 `TinyBrief.MaxStage`）**仅在页边界（page boundary）完成时调用**，跳关循环在 boss 关触发天赋选择提前 break 时，`MaxStage` 不会更新。

玩家实际经历 2200 关，但 `MaxStage` 始终停留在最后一次完整走完整页时的边界值，从未记录到 2200。

---

## 调用链分析

### 正常跳关路径（页完成）

```
OnTowerSkipStageReq
  └─ handleUnlimitedSkipStage          (ctl_tiny_tower_single.go:373)
       └─ loop: oldStage == pageTarStage
            └─ crossStage              (ctl_tiny_tower_defense.go:1278)
                 └─ stageFinish        (ctl_tiny_tower_defense.go:1369)
                      └─ addHistoryMaxStage  ← MaxStage 在此更新
```

### 中间关卡路径（页未完成）

```
OnTowerSkipStageReq
  └─ handleUnlimitedSkipStage
       └─ handleTowerSkipAndMonsterAward  (ctl_tiny_tower_single.go:400)
            ├─ tower.IsBossStage(oldStage) → addTalents
            │    └─ handleSkipStageTalent returns true → loop break  ← 提前退出
            ├─ tower.AddPermanentStage(oldStage)
            └─ tower.SetCurStage(oldStage + 1)
            // addHistoryMaxStage 未调用！
```

---

## 关键参数

| 参数 | 值 | 来源 |
|------|-----|------|
| `TinyType_TDUnlimited` | 6 | `pb/cspb/struct.pb.go:115` |
| `unlimitedRound`（D2ConfigCfg） | 10 | `gdconfig/D2ConfigCfg.tsv` |
| `OneKeyMaxPage`（每页步数） | 500 | 代码常量 |
| boss 关间隔 | 每 5 关 | `TDUnlimitedStageCfg.tsv` |
| `chapter_stuck=1` 的关卡 | 仅第 5000 关 | `TDUnlimitedStageCfg.tsv` |

**关键关卡 skip_attack 门槛：**

| 关卡 | skip_attack |
|------|------------|
| 1800 | 486,200 |
| 1872 | 560,400 |
| 1900 | 603,200 |
| 2200 | 1,059,900 |

---

## 完整因果链

1. 玩家多次调用 `OnTowerSkipStageReq` 向 2200 关跳进
2. 每次请求最多处理 500 关（一页），`pageTarStage = min(tarStage, CurStage+500)`
3. 每 5 关出现一个 boss 关，触发 `addTalents` → `handleSkipStageTalent` 返回 `true` → 循环 `break`
4. 循环 break 时 `oldStage != pageTarStage`，`crossStage / stageFinish / addHistoryMaxStage` 均不执行
5. `SetCurStage(oldStage+1)` 使 CurStage 在循环内逐步推进，曾到达 2200，但 `MaxStage` 从未被更新
6. 存档时：`CurStage=1872`（天赋中断点），`MaxStage` 停留在最后一次完整页边界（预期约 1900）
7. 下次登录：`GetMaxSkipStage() = MaxStage / 10 * 10 = 1900`
8. 玩家请求 tarStage > 1900 → `checkTowerSkipStage` 返回 `ErrCodeTowerDefenseSkipStageLimit`
9. 玩家感知：进度从 2200 "回退"到 1900，无法继续

---

## 关键代码位置

**`addHistoryMaxStage` — 唯一更新 MaxStage 的函数：**
```go
// game/play/internal/ctl_tiny_play.go:647
func addHistoryMaxStage(tiny tiny_play.TinyIFace) bool {
    brief := tiny.GetBriefInfo()
    curStage := tiny.GetCurStage()
    if curStage > brief.GetHistoryMaxStage() {
        if tiny.GetTinyType() == cspb.TinyType_TDUnlimited {
            ut := tiny.(*tiny_play.TowerDefense)
            ut.GetDetail().SetBeRashMaxStage(curStage)
        }
        brief.SetHistoryMaxStage(curStage)
        return true
    }
    return false
}
```

**`handleTowerSkipAndMonsterAward` — 缺失调用的位置：**
```go
// game/play/internal/ctl_tiny_tower_single.go:400
} else if oldStage != pageTarStage {
    if tower.IsBossStage(oldStage) {
        play.addTalents(pPlayer, tower, true, false, tiny_play.PassiveRefreshNormal)
    }
    detail.SetIsRefreshPassivePre(tiny_play.PassiveRefreshNormal)
    tower.AddPermanentStage(oldStage)
    // ← addHistoryMaxStage 未在此调用，MaxStage 不更新
    tower.SetCurStage(oldStage + 1)
}
```

---

## 数据验证

查询受影响玩家的 MongoDB 存档，验证根因：

```javascript
// 查关键字段
db.player.find(
  { "_id": NumberLong(<playerID>) },
  {
    "tinyplaysets.6.iface.briefinfo.curstage": 1,
    "tinyplaysets.6.iface.briefinfo.maxstage": 1
  }
)
```

**预期结果（根因成立时）：**

| 字段 | 预期值 |
|------|--------|
| `briefinfo.curstage` | 1872 |
| `briefinfo.maxstage` | ≤ 1900，且为 10 的倍数 |

```javascript
// 查完整 TDUnlimited 存档
db.player.find(
  { "_id": NumberLong(<playerID>) },
  { "tinyplaysets.6": 1 }
)
```

---

## 修复方案

在 `handleTowerSkipAndMonsterAward` 的中间关卡分支中，每阶段推进后同步更新 `MaxStage`：

**文件：** `game/play/internal/ctl_tiny_tower_single.go`

```go
} else if oldStage != pageTarStage {
    if tower.IsBossStage(oldStage) {
        play.addTalents(pPlayer, tower, true, false, tiny_play.PassiveRefreshNormal)
    }
    detail.SetIsRefreshPassivePre(tiny_play.PassiveRefreshNormal)
    tower.AddPermanentStage(oldStage)
    addHistoryMaxStage(tower)  // ← 新增：同步更新 MaxStage
    tower.SetCurStage(oldStage + 1)
}
```

**修复原理：** 每推进一关即更新 `MaxStage`，天赋 break 不再导致 MaxStage 丢失。`addHistoryMaxStage` 内部已有 `curStage > MaxStage` 守卫，不会重复写入，性能影响可忽略。

---

## 影响范围

- 所有在 `TinyType_TDUnlimited` 模式下进行过跳关操作的玩家
- 表现为历史最高关无法被正确记录，导致下次跳关上限受限
- 无数据损坏风险，修复后玩家可重新跳关到实际到达过的关卡

---

## 状态

- [x] 根因分析完成
- [ ] MongoDB 数据验证（需用上述查询确认）
- [ ] 代码修复
- [ ] 测试验证
- [ ] 上线
