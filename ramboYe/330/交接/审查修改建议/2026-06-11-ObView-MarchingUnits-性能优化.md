---
created: 2026-06-11
tags: [性能优化, cross服, 行军, ObView, memmove, pprof]
type: 审查修改建议
---

# ObView.MarchingUnits slice 删除性能问题

## 问题发现

来源：cross1005 生产环境 pprof CPU profile（采样 30.2s）

```
flat    flat%   cum     cum%    函数
29.92s  72.87%  29.92s  72.87%  runtime.memmove
0.01s   —       29.91s  72.84%  ObMgr.DelMarchingUnit
0.01s   —       29.90s  72.82%  ObView.DelMarchingUnit
```

**72.87% 的 CPU 时间全部消耗在 `runtime.memmove`，根源是 `ObView.DelMarchingUnit` 的 slice 中间删除操作。**

## 调用链

```
OnMarchTickSplit（每帧驱动）
  └─ marching（逐个行军单位）
       └─ notifyAfterMarching
            └─ BroadcastPositionNtf
                 └─ GetDiffObservers
                      └─ updateMarchingInfo
                           └─ addMarchingUnit
                                └─ DelMarchingUnit（先删旧路径）
                                     └─ ObView.DelMarchingUnit  ← 热点
```

`addMarchingUnit` 先删旧注册、再按新路径遍历所有 ObView 各调一次 `DelMarchingUnit`，每帧 × 每个行军单位 × 路径经过的 ObView 数量。

## 问题代码

`game/wmap/internal/mmap/mplayer/obview.go:42`

```go
func (v *ObView) DelMarchingUnit(unit munit.IUnit) {
    for i, u := range v.MarchingUnits {
        if u.GetID() == unit.GetID() {
            // 中间删除：把 i+1 后所有元素左移，触发 memmove
            v.MarchingUnits = append(v.MarchingUnits[:i], v.MarchingUnits[i+1:]...)
            return
        }
    }
}
```

**为什么 cross 服特别严重：** cross 服聚合多个 game 服的跨服行军，行军单位数量是单 game 服的数倍；每个 ObView 的 `MarchingUnits` 可能存有几十条记录，中间删除时 `memmove` 搬运字节量大。

## 修复方案：swap-with-last（O(1)，无 memmove）

原理：把**最后一个元素填到被删位置**，再截断尾部，两次赋值搞定，无内存搬运。

```go
func (v *ObView) DelMarchingUnit(unit munit.IUnit) {
    for i, u := range v.MarchingUnits {
        if u.GetID() == unit.GetID() {
            last := len(v.MarchingUnits) - 1
            v.MarchingUnits[i] = v.MarchingUnits[last]
            v.MarchingUnits[last] = nil   // 断开 interface 指针，避免 GC 泄漏
            v.MarchingUnits = v.MarchingUnits[:last]
            return
        }
    }
}

func (v *ObView) DelMarchingUnitByID(unitID int64) {
    for i, u := range v.MarchingUnits {
        if u.GetID() == unitID {
            last := len(v.MarchingUnits) - 1
            v.MarchingUnits[i] = v.MarchingUnits[last]
            v.MarchingUnits[last] = nil
            v.MarchingUnits = v.MarchingUnits[:last]
            return
        }
    }
}
```

**顺序变化无影响**：`MarchingUnits` 唯一消费方 `ObMgr.GetMarchingUnits` 只做 range 遍历后放入 map，与顺序无关。

**边界情况均正确：**
- 只有 1 个元素：`last=0`，自赋值后截断为空 ✓
- 删最后一个：`i==last`，自赋值后截断 ✓
- 元素不存在：循环结束，不执行 ✓

## 次级热点（参考）

| 热点 | cum% | 位置 | 说明 |
|------|------|------|------|
| `UnitMgr.RangeUnits` | 23.14% | gather timer | 每帧全量扫描采集单位做修复/删除检查，可改增量 |
| `exitBattleLogic` | 6.92% | battle | 战斗结算遍历死亡判断，正常开销 |

## 文件位置

`game/wmap/internal/mmap/mplayer/obview.go` — `DelMarchingUnit`（line 39）和 `DelMarchingUnitByID`（line 49）
