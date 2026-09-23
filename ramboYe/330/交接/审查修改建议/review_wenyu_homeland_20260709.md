---
created: 2026-07-09
tags: [code-review, homeland, 家园系统]
branch: h5_new_tf_v1042_homeland
p0: 4
p1: 21
p2: 27
---

# Homeland 家园系统 — 完整代码审查报告

## 📍 范围声明

- **审查类型**：系统审查（全量 homeland 代码）
- **审查人**：Claude Code (full-code-review)
- **被审查人**：wenyu
- **分支**：`h5_new_tf_v1042_homeland`
- **日期**：2026-07-09
- **0.5 语义补全**：已执行 / 检索词="homeland building upgrade collect reward worker" + "homeland visitor groom like sign treasure theme" / 新捞入文件 Q\S=无新增

### 分层覆盖自检

| 层 | 覆盖 | 覆盖的文件 |
|----|:---:|------|
| 协议入口 ctl/On*Req | ✅ | ctl_home_land*.go (13 文件) |
| 核心逻辑 pkg | ✅ | home_land/mgr.go, homeland_helper.go, reddot.go |
| 数据挂载 model | ✅ | home_land/model/*.go (9 文件) |
| 插件 plugin | ✅ | home_land/plugin/*.go (6 文件) |
| 关联系统 | N.A. | 本次聚焦 homeland 核心，shop/mail/rank 关联仅通过调用链覆盖 |
| 配置 gdconf | ✅ | 通过调用分析覆盖（GetXxxCfg 调用点） |

- **总文件数**：32 个 Go 源文件（排除 accessor_*/deepcopy_generated）
- **总行数**：~7625 行

---

## 📊 审查概览

| 优先级 | 数量 | 主要领域 |
|:---:|:---:|------|
| 🔴 P0 | 4 | 并发竞争、panic 风险、BI 数据一致性 |
| 🟡 P1 | 21 | 超长函数(10)、重复 getter、缺失条件、nil 不一致、重复代码 |
| 🟢 P2 | 27 | switch 缺 default、注释完善、性能优化、风格统一 |

---

## 🔴 P0 — Critical（必须修复）

### 1. plugin/plugin.go:86 | L4 并发安全 | ticker goroutine 与请求 handler 的数据竞争

`SettleAllBuildings` 被两个 goroutine 调用：
- `tickLumberMillNtf`（全局 ticker goroutine，~30s 间隔）
- `forceRefreshHomelandRedDot`（PlayerOnline 事件 / 登录路径）
- `OnHomelandDataReq`（玩家请求 handler）

两者同时访问同一 `homeData`，无同步机制。`settleMiningStep` 使用 `GetCellsPtr()` 原地修改 Cells 数组，而请求 handler 的 `ApplyDiff` 使用 `GetCells()`（值拷贝）+ `SetCells()`（写回）模式——ticker 的原地修改可能被请求 handler 的 `SetCells()` 静默覆盖。

```go
// lumbermill.go:362 — ticker 路径原地写入
cells := mapData.GetCellsPtr()
cells[ty][tx] = model.CellFree  // 原地修改

// model/util.go:171-184 — 请求路径 copy-then-swap
mapCell := mapData.GetCells()    // 值拷贝
// ... 修改 mapCell ...
mapData.SetCells(mapCell)        // 写回 — 可能覆盖 ticker 的原地修改
```

`model/map_data.go` 注释声称"两种访问模式在同一 goroutine 内串行执行，无并发风险"——此假设不成立。

**修复建议**：确认框架是否保证玩家数据单 goroutine 串行访问。若不保证，需为 Cells 操作加锁，或将 ticker 路径也改为 copy-then-swap 模式。

---

### 2. model/util.go:199 | L3 越界 | `RemoveBuildingFromLayout` 空切片时 panic

```go
func RemoveBuildingFromLayout(layout []*Building, id int64) []*Building {
    result := make([]*Building, 0, len(layout)-1)  // len(layout)==0 → panic
```

当前调用方在调用前检查了建筑存在性，但作为公共工具函数应防御性安全。

**修复**：`make([]*Building, 0, max(len(layout)-1, 0))` 或直接用 `len(layout)` 作容量。

---

### 3. home_land/reddot.go:131 | L2/L15 | `IsExploreFull()` 无 nil 守卫

```go
func (hm *HomeLandMgr) IsExploreFull() bool {
    return !model.AnyResourceCell(hm.GetHomeData().GetCellsPtr())
}
```

`IsExploreFull` 是公开方法，直接解引用 `hm.GetHomeData()` 而不检查 nil。`HasTickerRedDot` 在调用前做了 nil 检查，但 `IsExploreFull` 本身不检查——若被独立调用则 panic。违反 L15（nil 检查路径不一致）。

**修复**：在函数开头添加 `if hm.GetHomeData() == nil { return false }`。

---

### 4. ctl_home_land_sign.go:88 | L5 重复操作 | BI 日志在全部校验通过前写入

```go
for _, day := range req.GetDays() {
    // ... 各种校验（重复 day、天数不足、已领取、配置缺失）...
    addAssets = append(addAssets, cfg.Reward...)
    addDays[day] = 1
    p.BILogMarchHomeLandSignReward(day, ...) // ❌ 在校验全部通过前写入
}
addAssets = gdconf.MergeTypIDVal(addAssets)
play.AddAssets(p, addAssets, ...) // 奖励发放才真正完成
```

若循环后续某天校验失败并 return，前几天已写入 BI 日志（记录"已领取"），但奖励并未发放。BI 数据与实际状态不一致。

**修复**：将 `BILogMarchHomeLandSignReward` 移到 `AddAssets` 成功后，与奖励实际发放一致。

---

## 🟡 P1 — High（建议尽快修复）

### 5. ctl_home_land_visitor.go:47-90 | L4 并发 | `play.homelandVisitors` 多路径并发读写

`play.homelandVisitors`（`map[int64]map[int64]struct{}`）的读写来自：
- `addHomelandVisitor`（写，handler 入口）
- `removeFromVisitorSet`（写，handler 入口 + `onHomelandVisitorOffline` 事件）
- `notifyHomelandVisitorsGroomState`（读，handler 入口）

`onHomelandVisitorOffline` 由 `gdevent.PlayerOffline` 事件触发，若事件投递与 handler 不在同一 goroutine，存在数据竞争。

**修复**：确认框架并发模型；若需要，加 `sync.Mutex` 保护。

---

### 6. ctl_home_land_build.go:863-881 | Rule 1+32 | `b.GetCfgID()` 同函数内调用 6 次

```go
func isBuildingRecyclable(b *model.Building) bool {
    bConf := gdconf.GetLandBuildingCfg(b.GetCfgID())   // 1
    // ...
    return gdconf.GetMainCityLevelCfgByBuildingLevel(b.GetCfgID(), nextLv) == nil       // 2
    return gdconf.GetLumberMillLevelCfgByBuildingLevel(b.GetCfgID(), nextLv) == nil     // 3
    return gdconf.GetTimberProcessingLevelCfgByBuildingLevel(b.GetCfgID(), nextLv) == nil // 4
    return gdconf.GetDecorationLevelCfgByBuildingLevel(b.GetCfgID(), nextLv) == nil     // 5
    return gdconf.GetDecorationLevelCfgByBuildingLevel(b.GetCfgID(), nextLv) == nil     // 6
```

**修复**：`cfgID := b.GetCfgID()` 提升为局部变量。

---

### 7. ctl_home_land_build.go:878-879 | L6 | `isBuildingRecyclable` default 分支重复

```go
case model.PluginTypeDecoration:
    return gdconf.GetDecorationLevelCfgByBuildingLevel(b.GetCfgID(), nextLv) == nil
default:
    return gdconf.GetDecorationLevelCfgByBuildingLevel(b.GetCfgID(), nextLv) == nil  // 完全相同
```

**修复**：`default` 应返回已知安全值（如 `true`），而非静默降级为装饰物逻辑。

---

### 8-17. 10 个函数超过 60 行限制 | Rule 11

| # | 文件 | 函数 | 行数 |
|---|------|------|:---:|
| 8 | ctl_home_land_build.go:23 | `OnSaveHomelandLayoutReq` | 68 |
| 9 | ctl_home_land_build.go:358 | `OnPlaceHomelandBuildingReq` | 73 |
| 10 | ctl_home_land_build.go:541 | `OnRecycleShopHomeLandBuildingReq` | 66 |
| 11 | ctl_home_land_build.go:615 | `OnUpgradeHomelandBuildingReq` | 71 |
| 12 | ctl_home_land.go:622 | `loadHomelandGroomTarget` | 69 |
| 13 | ctl_home_land_sign.go:34 | `OnHomeLandSignRewardReq` | 68 |
| 14 | ctl_home_land_theme.go:104 | `applyMapThemeSwitch` | 65 |
| 15 | model/util.go:88 | `occupyBuildingCells` | 62 |
| 16 | plugin/lumbermill.go:338 | `settleMiningStep` | 86 |
| 17 | plugin/plugin_lumbermill.go:127 | `OnUpgrade`（lumberMillPlugin） | ~54 |

**修复方向**：按职责拆分为子函数（校验 / 执行 / 响应 三段式）。

---

### 18. ctl_home_land_reddot.go:49 | L7 | `SettleAllBuildings` 返回值被丢弃

```go
plugin.SettleAllBuildings(homeData, now)  // (changedIDs, unloadEvents) 均丢弃
```

登录追帧时丢弃了 `unloadEvents`（卸货通知），客户端可能漏掉卸货动画。

**修复**：若确认客户端不需要，添加注释说明原因。

---

### 19. model/data.go:55,71 | L2 | groom record 过滤时 nil 元素可致 panic

```go
for start < len(records) && records[start].GetGroomTime() < cutoff {
```

若 `records` 中存在 nil 元素（DB 损坏），`.GetGroomTime()` panic。

**修复**：添加 `records[start] != nil &&` 守卫。

---

### 20. model/building_data.go:229-234 | L6 | `effectiveRate` 静默吞没负数

```go
func (s *TimberProcessingState) effectiveRate(ratePerWorker int32) int64 {
    n := s.GetActiveWorkers()
    if n < 0 {
        n = 0   // 静默掩盖数据损坏
    }
    return int64(ratePerWorker) * int64(n)
}
```

**修复**：至少打印 warning 日志；或移除 clamp 暴露异常。

---

### 21. model/map_data.go:40-82 | Rule 5 | `GetOrCreate*` 三重复

`GetOrCreateTimberState` / `GetOrCreateMainCityState` / `GetOrCreateLumberMillState` 结构完全相同。

**修复**：提取内部 `ensureMapEntry` + 工厂回调的共享模式。

---

### 22. model/sign_data.go:30-35 | Rule 25 | `CheckInit` 命名误导

方法名暗示"检查并初始化"，实际只做纯查询。应改为 `IsInitialized()`。

---

### 23. model/sign_data.go:95-97 | L15 | nil map 访问风格不一致

`IsRewardClaimed` 直接索引可能 nil 的 map，而 `HasRoadSkin` 显式 guard nil。统一为显式 nil 守卫。

---

### 24. plugin/plugin_decoration.go:47 | L6 | 旧等级配置缺失时静默继续

```go
if oldCfg := gdconf.GetDecorationLevelCfgByBuildingLevel(..., oldLv); oldCfg != nil {
    oldHonor = int64(oldCfg.AddHonor)
}
// oldCfg == nil → oldHonor = 0 → 荣誉度 = newCfg.AddHonor - 0（膨胀）
```

`newCfg == nil` 时提前返回并打 error log，但 `oldCfg == nil` 时只静默当作 0。不一致，可能导致荣誉度膨胀。

**修复**：与 `newCfg == nil` 一致，打印 error log 并提前返回。

---

### 25. plugin/plugin_lumbermill.go:40 | L13 | `OnPlace` 派遣循环 O(n²)

每次派遣都重新扫描全部已派遣工人的目标格（`occupiedMiningCells`），O(n²)。

**修复**：循环外构建一次 occupied map，每轮只追加新派遣工人的目标格。

---

## 🟢 P2 — Medium（择机修复）

| # | 文件:行号 | 规则 | 问题 | 建议 |
|---|------|------|------|------|
| 26 | ctl_home_land_build.go:477 | L6 | `homeLandValidatePlacement` switch 缺显式 default | 添加 `default: return cspb.ErrCodeSuccess` |
| 27 | ctl_home_land_pack.go:260 | L6 | `homelandCellToPb` switch 缺 default | 为 CellFree 添加显式 case |
| 28 | home_land/reddot.go:31 | Rule 6 | 穿透 `GetMap()` 3 层访问子字段 | 使用 HomelandSystem 委托方法 |
| 29 | home_land/homeland_helper.go:20 | Rule 13 | `checkConditionCommon` 缺函数注释 | 添加中文注释 |
| 30 | home_land/doc.go:1 | Rule 13 | 包注释错写 `Package mailsender` | 改为 `Package home_land` |
| 31 | model/map_loader.go:23 | L6 | 配置缺失时静默返回空地图 | 至少打印 warning |
| 32 | model/data.go:118 | L13 | `RemoveBuildingStock` 双 pass | 用 in-place filter |
| 33 | model/data.go:149 | L13 | `HasObtainedBuilding` O(n) | 改用 `map[int32]bool` |
| 34 | model/const.go:31 | Rule 13 | WorkerState 文档缺 Processing 阶段 | 更新顶部注释 |
| 35 | model/building_data.go:252 | Rule 13 | 精度注释不准确 | 改为"先乘后除避免截断" |
| 36 | model/building_data.go:203 | Rule 10 | `ResetTodayLikesIfNeeded` 重新分配 map | 迭代清空已有 map key |
| 37 | plugin/plugin_maincity.go:22 | Rule 22 | 未使用的 `ctx` 参数 | 替换为 `_` |
| 38 | plugin/plugin_maincity.go:27 | Rule 18 | 直接 map 下标访问 | 添加 `GetXxxState(id)` 方法 |
| 39 | plugin/plugin_lumbermill.go:208 | Rule 18 | 直接 map 下标访问 | 同上 |
| 40 | plugin/plugin_timberprocessing.go:313 | Rule 18 | 直接 map 下标访问 | 同上 |
| 41 | plugin/lumbermill.go:303 | Rule 32 | `w.GetWorkerID()` 调用 3 次 | 提升局部变量 |
| 42 | plugin/plugin_lumbermill.go:146 | Rule 32 | `newConf.MaxLoad` 多处访问 | 提升局部变量 |
| 43 | plugin/lumbermill.go:164 | L3 | 整数除法死区（deadline=now） | 用 ceil 除法 |
| 44 | plugin/lumbermill.go:161 | L6 | `MineRate==0` 无 else 分支 | 添加兜底 |
| 45 | ctl_home_land.go:976 | Style | defer 写法不一致 | 统一风格 |
| 46-52 | 多处 | Rule 13 | 注释完善建议 | 见详情 |

---

## 🔵 调用链逻辑风险

| 类型 | 位置 | 描述 |
|------|------|------|
| **F1 原子性** | ctl_home_land.go:436-462 | `prepareDawnRewardClaim` 中 `getDawnRewardClaimTiming` 可能修改 `LastReceiveDawnTime`，若后续校验失败则奖励未发放但时间已推进。**有意为之**（注释说明），需强调此行为 |
| **F2 返回值消费** | ctl_home_land_reddot.go:49 | `SettleAllBuildings` 返回值被丢弃，登录追帧漏掉卸货通知 |
| **F4 并发路径** | plugin/plugin.go:86 | `SettleAllBuildings` 被 ticker + PlayerOnline + 请求 handler 三源调用（见 P0 #1） |
| **F5 状态一致性** | ctl_home_land.go:671,840 | `TodayGroomOutCount` 被本服+跨服两处 Ack callback 递增，均用 `+1`，一致 |

---

## ✅ 检查通过

| 规范 | 结论 |
|------|------|
| L1 死代码 | ✅ 未发现 |
| L8 break/continue 顺序 | ✅ 逻辑正确 |
| L9 奖励合并 | ✅ `MergeTypIDVal` 在所有需要处正确调用 |
| L10 时间单位 | ✅ 全部 ms 时间戳 + /1000 秒转换，未发现单位混淆 |
| L11 调试代码 | ✅ 未发现生产路径中的调试逻辑 |
| L12 ErrCode 语义 | ✅ 与拒绝原因匹配 |
| L14 atomic.Value | ✅ 不适用 |
| L16 range 修改退出 | ✅ 手写删除均有 break/return |
| Rule 4/24 Accessor | ✅ 外部调用均使用 Get/Set |
| Rule 7 多参数换行 | ✅ ≥4 参数均换行 |
| Rule 8 Slice Add | ✅ 使用封装方法 |
| Rule 9 返回值 | ✅ ErrCode 或 bool |
| Rule 12 错误处理 | ✅ 未发现 _ 吞没 |
| Rule 14 变量就近 | ✅ 基本合规 |
| Rule 15 check 结构 | ✅ 末尾唯一成功返回 |
| Rule 16/23 代码生成 | ✅ 所有持久化结构体有标记 |
| Rule 21 方法可见性 | ✅ 内部方法小写 |
| Rule 25 语义化操作 | ✅ IsIdle/IsMining/IsWaiting/IsProcessing 齐全 |
| Rule 26 二层 map | ✅ GetOrCreate 惰性初始化 |
| Rule 27/28 读写分离 | ✅ 读写分路 |
| Rule 29 等价函数 | ✅ 除 GetOrCreate* 三重复外无重复 |
| Rule 30 DeleteSliceElem | ✅ 正确使用 |
| Rule 31 pb enum 范围 | ✅ 范围比较保留 GetState() |
| Rule 33 回调快照 | ✅ 循环不修改被遍历集合 |
| BFS 边界检查 | ✅ findNearestLockedCell bounds guard |
| 工人状态机 | ✅ 9 种转换正确实现 |
| 工厂管理顺序 | ✅ freeze→modify→refill→recount |
| maxIters 安全上限 | ✅ settleWorkerFull 100000 次上限 |

---

## 🏆 Praise

| 维度 | 表扬点 |
|------|--------|
| **架构设计** | 插件系统分层清晰——`BuildingPlugin` 接口将四类建筑行为收敛到统一接口，ctl 层不感知具体插件逻辑，开闭原则贯彻得好 |
| **防御性编程** | `OnSetRoadSkinReq` 先全量校验后批量提交的两阶段模式，避免部分成功导致状态不一致 |
| **防御性编程** | `getDawnRewardClaimTiming` 对旧数据"时间未初始化"的兜底处理配合注释清晰说明行为选择 |
| **防御性编程** | `autoCollectTimberOnRecycle` 回收工厂前先结算产出入背包，失败则中止回收——防止资源丢失 |
| **可维护性** | `OnSaveHomelandLayoutReq` 用"阶段一至阶段五"注释清晰划分流程 |
| **性能意识** | `sendLumberMillWaitingNtf` 门控检查避免无效 settle 扫描 |
| **性能意识** | `occupiedMiningCells` 在 settle 主循环中构建一次、全程复用 |
| **性能意识** | `Cells` 访问协议区分值拷贝 vs 原地读写，高频内循环使用后者 |

---

## 📋 修复进度追踪

| # | 优先级 | 文件:行号 | 问题摘要 | 状态 |
|---|:---:|------|------|:---:|
| 1 | 🔴 | plugin/plugin.go:86 | ticker 与 handler 的 Cells 并发竞争 | 待修复 |
| 2 | 🔴 | model/util.go:199 | RemoveBuildingFromLayout 空切片 panic | 待修复 |
| 3 | 🔴 | home_land/reddot.go:131 | IsExploreFull 无 nil 守卫 | 待修复 |
| 4 | 🔴 | ctl_home_land_sign.go:88 | BI 日志在奖励发放前写入 | 待修复 |
| 5 | 🟡 | ctl_home_land_visitor.go:47 | homelandVisitors 并发读写 | 待确认 |
| 6 | 🟡 | ctl_home_land_build.go:863 | b.GetCfgID() 调用 6 次 | 待修复 |
| 7 | 🟡 | ctl_home_land_build.go:878 | default 分支重复装饰物逻辑 | 待修复 |
| 8 | 🟡 | ctl_home_land_build.go:23 | OnSaveHomelandLayoutReq 68行 | 待修复 |
| 9 | 🟡 | ctl_home_land_build.go:358 | OnPlaceHomelandBuildingReq 73行 | 待修复 |
| 10 | 🟡 | ctl_home_land_build.go:541 | OnRecycleShopHomeLandBuildingReq 66行 | 待修复 |
| 11 | 🟡 | ctl_home_land_build.go:615 | OnUpgradeHomelandBuildingReq 71行 | 待修复 |
| 12 | 🟡 | ctl_home_land.go:622 | loadHomelandGroomTarget 69行 | 待修复 |
| 13 | 🟡 | ctl_home_land_sign.go:34 | OnHomeLandSignRewardReq 68行 | 待修复 |
| 14 | 🟡 | ctl_home_land_theme.go:104 | applyMapThemeSwitch 65行 | 待修复 |
| 15 | 🟡 | model/util.go:88 | occupyBuildingCells 62行 | 待修复 |
| 16 | 🟡 | plugin/lumbermill.go:338 | settleMiningStep 86行 | 待修复 |
| 17 | 🟡 | plugin/plugin_lumbermill.go:127 | OnUpgrade ~54行 | 待修复 |
| 18 | 🟡 | ctl_home_land_reddot.go:49 | SettleAllBuildings 返回值丢弃 | 待确认 |
| 19 | 🟡 | model/data.go:55 | groom record nil 元素风险 | 待修复 |
| 20 | 🟡 | model/building_data.go:229 | effectiveRate 静默 clamp 负数 | 待修复 |
| 21 | 🟡 | model/map_data.go:40 | GetOrCreate* 三重复 | 待优化 |
| 22 | 🟡 | model/sign_data.go:30 | CheckInit 命名误导 | 待修复 |
| 23 | 🟡 | model/sign_data.go:95 | nil map 访问风格不一致 | 待修复 |
| 24 | 🟡 | plugin/plugin_decoration.go:47 | oldCfg nil 时静默继续 | 待修复 |
| 25 | 🟡 | plugin/plugin_lumbermill.go:40 | OnPlace 派遣 O(n²) | 待优化 |
| 26 | 🟢 | ctl_home_land_build.go:477 | switch 缺显式 default | 待修复 |
| 27 | 🟢 | ctl_home_land_pack.go:260 | switch 缺 default | 待修复 |
| 28 | 🟢 | home_land/reddot.go:31 | 3 层穿透访问 | 待优化 |
| 29 | 🟢 | home_land/homeland_helper.go:20 | 缺函数注释 | 待修复 |
| 30 | 🟢 | home_land/doc.go:1 | 错误包注释 | 待修复 |
| 31 | 🟢 | model/map_loader.go:23 | 配置缺失静默 | 待修复 |
| 32 | 🟢 | model/data.go:118 | RemoveBuildingStock 双 pass | 待优化 |
| 33 | 🟢 | model/data.go:149 | HasObtainedBuilding O(n) | 待优化 |
| 34 | 🟢 | model/const.go:31 | WorkerState 文档缺 Processing | 待修复 |
| 35 | 🟢 | model/building_data.go:252 | 精度注释不准确 | 待修复 |
| 36 | 🟢 | model/building_data.go:203 | ResetTodayLikes 重新分配 map | 待优化 |
| 37 | 🟢 | plugin/plugin_maincity.go:22 | 未使用 ctx 参数 | 待修复 |
| 38-40 | 🟢 | plugin/多处 | 直接 map 下标访问 | 待优化 |
| 41-42 | 🟢 | plugin/lumbermill.go | 重复 getter 调用 | 待优化 |
| 43-44 | 🟢 | plugin/lumbermill.go | 整数除法/缺 else | 待修复 |
| 45 | 🟢 | ctl_home_land.go:976 | defer 风格不一致 | 待修复 |
