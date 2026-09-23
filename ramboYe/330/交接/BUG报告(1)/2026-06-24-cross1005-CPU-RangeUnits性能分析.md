---
created: 2026-06-24
tags: [pprof, 性能优化, wmap, RangeUnits, cross服]
---

# cross1005 CPU 性能分析 — RangeUnits 三重间接寻址

## 采集信息

| 项目 | 值 |
|------|----|
| 实例 | cross1005 |
| 采集时间 | 2026-06-24 16:31 |
| 采样时长 | 30s |
| 总采样量 | 16080ms |
| CPU 占用率 | **53.33%** |

## Top20 关键项目函数

| 函数 | flat% | cum% |
|------|-------|------|
| `UnitMgr.RangeUnits` | 4.79% | **53.48%** |
| `WMap.isGatherResourceLow` | 3.61% | 3.61% |
| `WMap.gatherRepair` | 3.54% | 6.03% |
| `EntityMgr.GetGridByGridCoord` | 3.30% | 3.79% |
| `BatCtx.InBattle` | 3.05% | 3.17% |
| `PlayerTroop.OwnerInfo` | 2.74% | — |
| `Unit.OwnerInfo` | 2.67% | 8.27% |
| `WMap.exitBattleLogic` | 2.30% | 16.60% |
| `SumMapValueByCond` | 2.30% | 7.28% |

Go 1.24 runtime map（swiss-table）合计占 **~17%**：`(*Map).Used` 6.65% + `ctrlGroup.matchFull` 5.66% + `(*Iter).Next` 5.41%。

---

## 根因分析：RangeUnits 三重间接寻址

### 数据结构

```
mapUnits[MapUnitType] = map[int64]GridIndex   // unit ID → 格子序号
Grid.Entities         = map[int64]IEntity     // unit ID → interface
```

### 热路径（每个 unit 走一遍）

```
mapUnits[t] range        ← swiss-table 迭代（触发 matchFull/Iter.Next）
  → GridIndex
  → GetGridByIndex
      → maxGridXZ()      ← 每次2次整数除法（80ms）
      → grids[x][z]
  → grid.GetEntity(id)   ← 第2次 map 查找
  → entity.(munit.IUnit) ← interface 断言 660ms flat
  → f(unit)
      → UnitToXxxMust    ← 第2次断言（range.go 封装层）
```

**核心问题**：`mapUnits[t]` 存 GridIndex 是为了空间查询，但"按类型遍历"完全不需要 Grid。每个 unit 做了 2 次 map 查找 + 2 次 interface 断言，实际只需要 0 次。

---

## 优化方案

### P0：增加 unitCache（预期节省 20%+ CPU）

```go
// UnitMgr 新增字段
unitCache map[cspb.MapUnitType]map[int64]munit.IUnit

// AddUnit 同步维护
mu.unitCache[u.GetType()][u.GetID()] = u

// DelUnit 同步维护
delete(mu.unitCache[u.GetType()], u.GetID())

// RangeUnits 简化
func (mu *UnitMgr) RangeUnits(t cspb.MapUnitType, f func(unit munit.IUnit)) {
    for _, unit := range mu.unitCache[t] {
        f(unit)
    }
}
```

关键文件：`game/wmap/internal/mmap/melem/unit_mgr.go:419`

### P2：缓存 maxX/maxZ（10分钟改动）

`EntityMgr` 增加 `maxX, maxZ int32` 字段，Init 时一次性计算，消除 `GetGridByGridCoord` 每次的整数除法。

关键文件：`game/wmap/internal/mmap/melem/munit/mentity/entity_mgr.go:157`

### P3：采集 ticker 改事件驱动

`isGatherResourceLow`（580ms）和 `gatherRepair`（570ms）的根源是每 tick 遍历所有 NpcGather。资源量不变时应跳过，改为"资源变化时标记 dirty，只处理 dirty 节点"。

---

## 其他热点备忘

- `exitBattleLogic:149` → `unit.IsDead()` cum 1.3s，cross 服死亡单位多时特别明显
- `SumMapValueByCond` → map 全量求和 800ms，改为写时增量维护累计值
- `BatCtx.InBattle` → `GetCurTarget()` 490ms flat，高频调用

