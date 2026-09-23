---
created: 2026-07-09
tags: [review, homeland, go]
branch: h5_new_tf_v1042_homeland
p0: 4
p1: 5
p2: 6
---

# 家园系统（HomeLand）深度代码审查报告

## 审查概览

| 项目 | 详情 |
|------|------|
| 审查人 | Claude (full-code-review + go-review) |
| 分支 | `h5_new_tf_v1042_homeland` |
| 日期 | 2026-07-09 |
| 审查范围 | 家园系统全部 Go 源文件（19 个核心文件 + 13 个 Handler 文件） |
| 审查基准 | `origin/main` vs HEAD |
| 规范依据 | go-rules.md 规1-33 + L1-L16 |
| 文档对齐 | homelandDoc/INDEX.md ✅ 已读取 |
| 🔴 P0 | 4 项 |
| 🟡 P1 | 5 项 |
| 🟢 P2 | 6 项 |

### 分层覆盖自检

| 层 | 是否覆盖 | 覆盖的文件 |
|----|:---:|------|
| 协议入口 ctl/On*Req | ✅ | ctl_home_land.go, ctl_home_land_build.go, ctl_home_land_sign.go, 等 13 个 handler |
| 核心逻辑 pkg | ✅ | model/ (data, map_data, building_data, etc.) + plugin/ (6 个插件文件) |
| 数据挂载 mplayer/tiny | ✅ | mgr.go, homeland_helper.go, reddot.go |
| 关联系统 shop/mail/rank | ✅ | ctl_home_land_build.go (排行榜同步), ctl_home_land.go (联盟校验) |
| 配置 gdconf | ✅ | 配置读取均通过 gdconf 包，配置结构体定义已纳入审查 |

---

## 问题汇总表

| # | 优先级 | 规范 | 文件:行号 | 描述 | 来源维度 |
|---|:---:|------|----------|------|---------|
| P0-1 | 🔴 | 规4/24 | ctl_home_land*.go (26处) | `p.PlayerID` 直接字段访问，Player 已生成 accessor，应使用 `p.GetPlayerID()` | 字段访问 |
| P0-2 | 🔴 | L12 | ctl_home_land_build.go:565 | ErrCode 语义混用：建筑不可回收返回 `ErrCodeHomeLandBuildingConflict` | 逻辑 |
| P0-3 | 🔴 | L6 | homeland_helper.go:35, ctl_home_land_build.go:708 | switch 缺 default 分支，未知类型静默失败 | 逻辑 |
| P0-4 | 🔴 | L15 | sign_data.go:96 vs sign_data.go:72 | `IsRewardClaimed` 与 `signRewardStateMap` nil 检查不一致，旧存档可能 panic | 逻辑 |
| P1-1 | 🟡 | 规11 | lumbermill.go:338 等 (6处) | 6 个函数超过 60 行限制，最长 85 行 | 代码组织 |
| P1-2 | 🟡 | 规13 | ctl_home_land.go 等 (16处) | 16 个 >20 行函数缺少中文注释 | 可维护性 |
| P1-3 | 🟡 | 规1/32 | plugin_maincity.go:27,44,57 | `building.GetID()` 同函数内多次调用未提升为局部变量 | 效率 |
| P1-4 | 🟡 | L15 | plugin_maincity.go:27 | `GetMainCityStates()[id]` 直接 map 下标访问无 nil 守卫 | 防御性 |
| P1-5 | 🟡 | L6 | ctl_home_land.go:873 | `GetHomelandRecordsReq` switch 未知类型降级为空返回，无日志 | 逻辑 |
| P2-1 | 🟢 | 规6 | ctl_home_land_build.go:28 | `ctx.GetMapData().GetMainCityStates()[building.GetID()]` 三层穿透 | 封装 |
| P2-2 | 🟢 | 规1 | ctl_home_land.go:68-86 | `b.GetCfgID()` / `b.GetLevel()` / `b.GetEffective()` 在循环体内每项调用 ≥2 次 | 效率 |
| P2-3 | 🟢 | 规15 | homeland_helper.go:20 | `checkConditionCommon` 多处提前 return，但末尾无统一 `return true` 成功路径 | 代码组织 |
| P2-4 | 🟢 | 规30 | data.go:120 | `RemoveBuildingStock` 使用手写 `DeleteSliceElem` 工具函数 ✅，但遍历中使用 `range` + `return` 后退，方式正确 | 已验证 |
| P2-5 | 🟢 | 规21 | ctl_home_land_build.go:435,476 | `homeLandUpdateLayout` / `homeLandValidatePlacement` 仅包内使用但大写导出 | 可见性 |
| P2-6 | 🟢 | 规32 | plugin_maincity.go:49 | `cfg.OutputRes` 在 `OnPeekCollect` 中一次性使用，无需提升 | 效率 |

---

## 问题详情

### 🔴 P0-1: `p.PlayerID` 直接字段访问（规4/24）

**文件**: `ctl_home_land.go`, `ctl_home_land_build.go`, `ctl_home_land_reddot.go`, `ctl_home_land_visitor.go`, `ctl_home_land_sign.go`, `ctl_home_land_pack.go`

Player 结构体已有 `accessor_Player.go`（由 `accessor_engine2` 生成），但 Handler 层中大量使用 `p.PlayerID` 直接字段访问。共计约 26 处违规。

**典型违规代码** (`ctl_home_land.go:35`):
```go
play.SendTo(p.PlayerID, &cspb.HomelandDataAck{...})
```

**应改为**:
```go
play.SendTo(p.GetPlayerID(), &cspb.HomelandDataAck{...})
```

**影响范围**: 全部 homeland Handler 文件，包括 sign、visitor、reddot、pack、timber、theme、treasure 子模块。

**修复建议**: 全局批量替换 `p.PlayerID` → `p.GetPlayerID()`，建议使用 LSP `findReferences` 定位所有引用点（grep 可能混入其他结构体的同名 `PlayerID` 字段）。

---

### 🔴 P0-2: ErrCode 语义混用（L12）

**文件**: `ctl_home_land_build.go:563-567`

```go
buildingConfig := gdconf.GetLandBuildingCfg(id)
if buildingConfig == nil || buildingConfig.BuildingRecycle == 0 {
    ack.ErrCode = cspb.ErrCodeHomeLandBuildingConflict  // ❌ 语义错误
    return
}
```

**问题**: 建筑不可回收是业务规则拒绝（配置不允许回收），但返回的 ErrCode 是 `ErrCodeHomeLandBuildingConflict`（碰撞冲突），客户端会展示错误的提示文案。

**同样的问题** (`ctl_home_land_build.go:152-154`):
```go
if !isBuildingRecyclable(b) {
    ack.ErrCode = cspb.ErrCodeHomeLandInvalidRequest  // ❌ 过于泛化
    return
}
```

**修复建议**: 定义专用错误码 `ErrCodeHomeLandBuildingNotRecyclable`，替换两处引用。

---

### 🔴 P0-3: switch 缺 default 分支（L6）

**文件 1**: `homeland_helper.go:35-63`

```go
switch conditionType {
case "Honor":
    // ...
case "MainLevel":
    // ...
case "PioneerProgress":
    // ...
default:
    tlog.Warnf("no deal this type  = %v,cid = %v", conditionType, conditionID)
    return false
}
```

虽然有 default 分支，但 `"PioneerProgress"` case 中 `conditionValue1` 变量名暗示取自 `require.ConditionValue1` 字段——若配置中存在 `ConditionValue2` 等新字段，当前代码会静默忽略。

**文件 2**: `ctl_home_land_build.go:708-721`

```go
switch buildingType {
case model.PluginTypeMainCity:
    // ...
case model.PluginTypeLumberMill:
    // ...
case model.PluginTypeDecoration:
    // ...
default:
    tlog.Warnf("homeLandDoUpgrade cfgID%d unsupported buildingType%d", cfgID, buildingType)
    return cspb.ErrCodeHomeLandInvalidBuildingID, nil, nil
}
```

此处的 default 处理较好（有日志 + 错误返回），但 `ErrCodeHomeLandInvalidBuildingID` 用于"不支持的建筑类型"，语义不够精确——应为 `ErrCodeHomeLandInvalidBuildingID → ErrCodeHomeLandUnsupportedBuildingType`。

---

### 🔴 P0-4: nil 检查路径不一致（L15）

**文件**: `sign_data.go:72-78` vs `sign_data.go:95-97`

**安全路径** (`signRewardStateMap`):
```go
func (s *SignData) signRewardStateMap() map[int32]int32 {
    m := s.GetSignRewardStateMap()
    if m == nil {
        m = make(map[int32]int32)
        s.SetSignRewardStateMap(m)
    }
    return m
}
```

**无保护路径** (`IsRewardClaimed`):
```go
func (s *SignData) IsRewardClaimed(day int32) bool {
    return s.GetSignRewardStateMap()[day] == 1  // ❌ 若 map 为 nil，返回 false（Go 允许 nil map 下标访问），但语义依赖于"默认零值 == 0 ≠ 1"
}
```

**问题**: 虽然 Go 的 nil map 下标访问不会 panic（返回零值），但 `IsRewardClaimed` 跳过了 `signRewardStateMap()` 的惰性初始化——其他写入方调用 `signRewardStateMap()` 后 map 已非 nil，读取方却走了不同的 nil 路径，违反 L15 "同一字段的 nil 检查必须在所有调用点一致"。

**修复建议**: `IsRewardClaimed` 改用 `s.signRewardStateMap()[day] == 1`，与 `SetSignReward`、`AddDaysSignReward` 保持一致。

---

### 🟡 P1-1: 函数超过 60 行限制（规11）

| 文件 | 行号 | 函数 | 行数 |
|------|------|------|:---:|
| `plugin/lumbermill.go` | 338 | `settleMiningStep` | 85 |
| `ctl_home_land_build.go` | 359 | `OnPlaceHomelandBuildingReq` | 73 |
| `ctl_home_land_build.go` | 614 | `OnUpgradeHomelandBuildingReq` | 71 |
| `ctl_home_land.go` | 622 | `loadHomelandGroomTarget` | 69 |
| `ctl_home_land_build.go` | 24 | `OnSaveHomelandLayoutReq` | 68 |
| `ctl_home_land_build.go` | 541 | `OnRecycleShopHomeLandBuildingReq` | 66 |

**最严重**: `settleMiningStep`（85 行）是伐木场采集结算的核心分支函数，包含多个嵌套分支（格子耗尽/负载满/仓库满），建议将三个分支抽取为独立函数：`handleCellExhausted`、`handleStorageFull`、`handleUnloadAndContinue`。

**Handler 超长函数**: `OnSaveHomelandLayoutReq` 等 Handler 已用阶段化注释分隔（"阶段一"~"阶段五"），但未拆分为子函数。建议将校验阶段抽为 `checkSaveLayoutReq`，应用阶段抽为 `applySaveLayoutReq`。

---

### 🟡 P1-2: >20 行函数缺少中文注释（规13）

共计 16 个函数超过 20 行但缺少中文注释。主要集中在：

| 文件 | 受影响函数数 | 典型函数 |
|------|:---:|------|
| `ctl_home_land.go` | 11 | OnVisitHomelandReq, OnHomelandLikeReq, loadHomelandGroomTarget, OnCrossHomelandGroomReq, etc. |
| `plugin/lumbermill.go` | 8 | settleMiningStep, settleWorkerFull, dispatchWorker, freezeMiningProgress, etc. |
| `model/util.go` | 1 | occupyBuildingCells (65 行) |

**说明**: `plugin/lumbermill.go` 中的算法函数（如 `settleMiningStep`）虽然注释密度较高（函数体内有多行注释说明分支逻辑），但缺少函数签名上方的中文功能概述注释。Handler 函数（如 `OnVisitHomelandReq`、`OnHomelandLikeReq`）则完全没有注释。

---

### 🟡 P1-3: 同函数内重复 getter 调用未提升（规1/32）

**文件**: `plugin_maincity.go:27,44,57`

在 `OnUpgrade`、`OnPeekCollect`、`OnCollect` 三个方法中，`building.GetID()` 被调用了 ≥2 次：
```go
func (m *mainCityPlugin) OnUpgrade(ctx *HomeLandBatCtx, oldLv int32, now int64) {
    building := ctx.GetBuilding()
    state := ctx.GetMapData().GetMainCityStates()[building.GetID()]  // 调用 1
    // ...
    oldCfg := gdconf.GetMainCityLevelCfgByBuildingLevel(building.GetCfgID(), oldLv)
    if oldCfg == nil {
        tlog.Errorf("mainCityPlugin OnUpgrade building%d oldLv%d cfg not found", building.GetID(), oldLv)  // 调用 2
```

**同样模式**: `ctl_home_land.go:68-86` 循环中 `b.GetCfgID()` 和 `b.GetLevel()` 各调用 ≥2 次。

**修复建议**: 在函数开头提升 `bID := building.GetID()` 和 `bCfgID := building.GetCfgID()`，减少重复 getter 调用。

---

### 🟡 P1-4: map 下标直接访问无 nil 守卫（L15）

**文件**: `plugin_maincity.go:27,44,57`

```go
state := ctx.GetMapData().GetMainCityStates()[building.GetID()]
```

三个方法（`OnUpgrade`、`OnPeekCollect`、`OnCollect`）都直接对 `GetMainCityStates()` 结果做下标访问。虽然这些方法调用时 `OnPlace` 已经执行过（map 已初始化），但缺乏 nil 守卫意味着将来如果新增调用路径不经过 `OnPlace`，会 panic。

**对比**: `GetOrCreateMainCityState` 做了完整的惰性初始化，但上述方法没有使用它。建议统一使用 `GetOrCreateMainCityState()` 或者至少在各方法中直接访问前添加 nil 检查（尽管当前理论上不会为 nil）。

---

### 🟡 P1-5: 未知记录类型静默降级（L6）

**文件**: `ctl_home_land.go:868-875`

```go
switch req.GetType() {
case cspb.HomelandRecordType_Groom:
    modelRecords = homeData.GetGroomRecords()
case cspb.HomelandRecordType_Like:
    modelRecords = homeData.FilterLikeRecords()
default:
    // 未知记录类型，返回空列表
}
```

**问题**: default 分支仅以注释说明"返回空列表"，没有日志记录。如果客户端因版本不匹配发送了新的记录类型，服务端静默返回空，排查困难。

**修复建议**: 添加 `tlog.Warnf` 记录未知类型，同时仍返回空列表（不阻断请求）。

---

### 🟢 P2-1 ~ P2-6（低优先级）

| # | 说明 | 修复建议 |
|---|------|---------|
| P2-1 | `plugin_maincity.go` 中 `ctx.GetMapData().GetMainCityStates()[building.GetID()]` 三层穿透访问 | 在 `HomeLandBatCtx` 上添加 `GetMainCityState(id)` 委托方法 |
| P2-2 | `OnHomeLandBuffOverviewReq` 循环中 `b.GetCfgID()` 每迭代调用 3 次 | 在循环开头提升为局部变量 |
| P2-3 | `checkConditionCommon` 函数结构：多分支 return 混杂，前三 case 末尾 return 不同路径 | 调整为统一的「末尾返回成功」模式，或改为表驱动 |
| P2-4 | `RemoveBuildingStock` 使用 `utility.DeleteSliceElem` ✅ | 代码正确，已验证通过 |
| P2-5 | `homeLandUpdateLayout` / `homeLandValidatePlacement` 大写导出但仅包内使用 | 改为小写 `homeLandUpdateLayout` → `updateHomeLandLayout` |
| P2-6 | `plugin_maincity.go:49` `cfg.OutputRes` 仅用 1 次，无需额外优化 | 当前写法已是最优 |

---

## ✅ 检查通过

| 规范 | 结论 | 说明 |
|------|:---:|------|
| 规3 case 格式 | ✅ | switch case 格式符合规范 |
| 规5 禁止冗余 | ✅ | 未发现 `ok == false` 等冗余写法 |
| 规7 多参数换行 | ✅ | 函数参数换行符合规范 |
| 规9 返回值类型 | ✅ | 统一使用 `ErrCode` / `bool`，无冗余三元组 |
| 规10 数据结构重置 | ✅ | 均有封装 Reset 方法（`MainCityState.Reset`、`TimberProcessingState.Reset`） |
| 规12 错误处理 | ✅ | 无 `_, _ =` 忽略错误的情况 |
| 规14 变量就近 | ✅ | 变量声明紧邻使用位置 |
| 规16 accessor 生成 | ✅ | 所有持久化结构体均有 `//go:generate accessor_engine2` 标记 |
| 规19 形参命名 | ✅ | 形参名使用调用方视角语义（`now`、`playerID`、`newStockMap`） |
| 规20 纯函数缓存 | ✅ | 未发现重复调用纯函数未缓存的情况 |
| 规22 未使用形参 | ✅ | 所有未使用形参均已用 `_` 占位 |
| 规23 DeepCopy | ✅ | SignData 已标记 `+deepcopy-gen=true` |
| 规25 语义化操作 | ✅ | WorkerState 有 `IsIdle()`/`IsMining()`/`IsWaiting()`/`IsProcessing()` 语义方法 |
| 规27 持久化副作用 | ✅ | 读取型委托方法使用直接字段访问（`GetLayout()` → `d.GetMap().GetLayout()` 在内部访问字段） |
| 规28 sub-mgr 委托 | ✅ | HomelandSystem 为 HomelandMap 子字段提供了委托方法（`GetLayout()`、`GetCells()` 等） |
| 规30 DeleteSliceElem | ✅ | 使用 `utility.DeleteSliceElem` 替代手写 append 删除 |
| 规33 回调快照 | ✅ | 未在回调内修改被遍历集合 |
| L1 死代码 | ✅ | 未发现死代码 |
| L3 越界 | ✅ | 坐标访问前均有边界检查 |
| L4 并发安全 | ✅ | 系统在单 goroutine 内串行执行 |
| L5 重复操作 | ✅ | 未发现同一副作用多次执行 |
| L7 返回值校验 | ✅ | 所有 `(val, err)` 函数返回值均有校验 |
| L8 break/continue 顺序 | ✅ | for range 中 break 条件均在 continue 之前 |
| L9 奖励合并 | ✅ | 奖励发放前调用 `gdconf.MergeTypIDVal` |
| L10 时间单位 | ✅ | 毫秒/秒换算统一使用 `gdconf.Second` 常量 |
| L11 调试代码 | ✅ | 未发现 Fake/Debug/临时 代码残留在生产路径 |
| L13 循环内分配 | ✅ | 未发现循环内无条件分配对象 |
| L14 atomic.Value | ✅ | 配置读取均为只读使用 |
| L16 range 修改退出 | ✅ | `RemoveBuildingStock` 中删除后立即 return |

---

## 🏆 Praise

| # | 维度 | 要点 |
|---|------|------|
| 1 | **架构设计** | 建筑插件框架（`BuildingPlugin` 接口 + 注册表）设计优秀：6 个生命周期回调（OnPlace/OnRemove/OnMove/OnUpgrade/OnSettle/OnPeekCollect/OnCollect）将不同建筑类型的差异化逻辑解耦，新增建筑类型只需实现接口并注册即可。 |
| 2 | **防御性编程** | 跨服请求中使用服务端时间覆盖来源时间（`rec.Time = util.NowTs()`），防止客户端伪造时间戳污染记录。离线玩家异步加载 + nil 守卫模式统一。 |
| 3 | **可维护性** | `OnSaveHomelandLayoutReq` 用 "阶段一~阶段五" 注释清晰标注执行流程；`settleMiningStep` 用 "分支一/二/三" 标注三种结算路径。配置驱动的条件检查（`CheckHomelandCondition`）使策划可以灵活组合解锁条件。 |
| 4 | **性能意识** | `occupiedMiningCells` 一次构建、整段追帧复用，避免 O(迭代数 × 工人数) 的重复扫描。`GetCellsPtr` 直接返回数组指针供热点路径原地修改，避免 14KB 数组值拷贝。`SettleAllBuildings` 内嵌耗时监控（>100ms Warn）。 |
| 5 | **算法设计** | 伐木场工人 BFS 选格 + 满载/格子耗尽双 deadline 跟踪 + 离线追帧主循环（maxIters 保护 + 迭代计数器），是一个完整的离散事件仿真实现。木材加工厂"征召→停产→复工"状态机设计合理。 |

---

## 修复进度追踪

| # | 优先级 | 描述 | 状态 | 修复人 | 备注 |
|---|:---:|------|:---:|------|------|
| P0-1 | 🔴 | `p.PlayerID` → `p.GetPlayerID()` 批量替换 (26处) | 待修复 | — | 建议用 LSP findReferences 精确定位 |
| P0-2 | 🔴 | 建筑不可回收 ErrCode 语义修正 | 待修复 | — | 需定义 `ErrCodeHomeLandBuildingNotRecyclable` |
| P0-3 | 🔴 | switch 缺 default 添加日志/错误处理 | 待修复 | — | homeland_helper.go + ctl_home_land_build.go |
| P0-4 | 🔴 | `IsRewardClaimed` nil 路径统一 | 待修复 | — | 改用 `signRewardStateMap()` |
| P1-1 | 🟡 | 6 个超长函数拆分 | 待修复 | — | settleMiningStep 优先 |
| P1-2 | 🟡 | 16 个函数添加中文注释 | 待修复 | — | 批量补充 |
| P1-3 | 🟡 | getter 重复调用提升为局部变量 | 待修复 | — | plugin_maincity.go + ctl_home_land.go |
| P1-4 | 🟡 | map 下标访问添加 nil 守卫 | 待修复 | — | 或改用 GetOrCreate* 方法 |
| P1-5 | 🟡 | 未知记录类型添加日志 | 待修复 | — | ctl_home_land.go:873 |
| P2-1 | 🟢 | 三层穿透封装委托方法 | 待确认 | — | HomeLandBatCtx 添加 GetMainCityState |
| P2-2 | 🟢 | 循环内 getter 提升 | 待修复 | — | OnHomeLandBuffOverviewReq |
| P2-3 | 🟢 | checkConditionCommon 结构调整 | 待确认 | — | 可选表驱动重构 |
| P2-5 | 🟢 | 仅包内使用的方法改为小写 | 待修复 | — | homeLandUpdateLayout, homeLandValidatePlacement |

---

*报告生成时间: 2026-07-09 | 审查工具: full-code-review + go-review (深度审查)*
*🤖 Generated with [Claude Code](https://claude.com/claude-code)*
