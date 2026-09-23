---
created: 2026-06-22
tags: [bug, wmap, 远征图, 采集, MarchPreparedAck]
status: fixed
branch: h5_new_tf_v1045
---

# 远征图采集 MarchPreparedAck gatherTime=0 / maxLoad 系数错误

## 现象

测试服玩家 491352，城堡受到攻击时派兵去采集，编队列表显示**采集时间=0、带回数量=0**。  
涉及协议：`MarchPreparedAck`，字段 `gatherTime` 和 `maxLoad`。

## 根因

远征图（MAP_EXPEDITION，cross1005）的资源节点类型是 **`*BfGather`（MapUnitBfGather）**，而 `OnPlayToMapMarchPrepared` 中对采集点的类型转换用的是 `UnitToNpcGatherable`，该函数只做 `unit.(*NpcGather)` 类型断言，对 BfGather 返回 false，导致所有远征图采集准备请求都走进 `marchPerparedNotGather`。

`marchPerparedNotGather` 的 switch 里只有 `MapUnitCentralCity` 分支会计算 `GatherTime`，BfGather 无处理，`GatherTime` 始终为 0。

Play 侧同理：`getAssetTypeByCfgID` 和 `calcMaxLoad` 遇到 `MapUnitBfGather` 时 `index = -1`，`GetAssetTypeByIndex(-1) = 0`，导致负重系数用金币默认值（`arr[0]`）而非实际资源分组系数。

### 城堡受到攻击时 maxLoad 也为 0 的原因

当编队处于非 `LineupStateDefender` 状态（如城堡被攻击时编队在防守/行军），play 侧走 `else` 分支发送 `MapCanFoundTroop=true`，wmap 侧 `marchPerparedNotGather` 尝试在地图上找该编队，防守编队不作为普通 PlayerTroop map unit 存在，`pt == nil` → 返回 `ErrCodeNotFoundTroop`，前端渲染为 0/0。

## 调用链

```
MarchPreparedReq
  └─ play/ctl_troop.go:746  OnMarchPreparedReq
       ├─ getAssetTypeByCfgID(MapUnitBfGather) → index=-1 → assetType=0  ❌
       ├─ calcMaxLoad(MapUnitBfGather)          → 用金币系数，值偏差     ❌
       └─ Cast2Map → PlayToMapMarchPrepared
            └─ wmap/ctl_march.go:2507  OnPlayToMapMarchPrepared
                 ├─ UnitToNpcGatherable(BfGather) → false                ❌
                 └─ marchPerparedNotGather
                      ├─ switch MapUnitBfGather → 无分支 → GatherTime=0  ❌
                      └─ MapCanFoundTroop=true → pt=nil → ErrCode        ❌
```

## 修复

BfGather 与 NpcGather 使用**同一张 D2GatherCfg 配置表**，BaseSpeed/Remains 接口相同（均通过 `IGatherAble` 暴露），只需在 4 处加入 BfGather 识别即可。

| 文件 | 函数 | 改动 |
|------|------|------|
| `play/internal/ctl_troop.go` | `getAssetTypeByCfgID` | `IsMapUnitNpcGatherable \|\| IsMapUnitBfGather`，读同一张 D2GatherCfg |
| `play/internal/ctl_troop.go` | `calcMaxLoad` | 同上，BfGather 使用正确资源分组系数 |
| `wmap/internal/ctl_march.go` | `OnPlayToMapMarchPrepared` | `UnitToNpcGatherable` → `UnitToIGatherAbleUnit`；`gp.Coord` → `gp.GetCoord()` |
| `wmap/internal/ctl_march.go` | `marchPerparedNotGather` | 新增 `case MapUnitBfGather`：计算 speedup + GatherTime |

关键点：`UnitToIGatherAbleUnit` 做 `unit.(munit.IGatherAbleUnit)` 接口断言，NpcGather 和 BfGather 都实现了该接口，一改通吃。

## 涉及文件

- `game/play/internal/ctl_troop.go`（play 服）
- `game/wmap/internal/ctl_march.go`（wmap/cross 服）

## 相关类型

- `game/wmap/internal/mmap/melem/mcity/bf_gather.go` — BfGather 定义（type=38）
- `game/wmap/internal/mmap/melem/mcity/npc_gather.go` — NpcGather 定义（type=NpcGatherable）
- `game/wmap/internal/mmap/melem/convert.go:101` — `UnitToNpcGatherable`（有问题的函数）
- `game/wmap/internal/mmap/melem/convert.go:238` — `UnitToIGatherAbleUnit`（修复用）
