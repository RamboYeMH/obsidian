---
created: 2026-07-11
tags: [代码审查, 家园, homeland, go-review, H5项目]
branch: h5_new_tf_v1042_homeland
reviewer: Claude (full-code-review)
reviewee: guiwei
scope: game/play/internal/home_land/** + ctl_home_land_*.go (~7600 行)
p0: 0
p1: 3
p2: 11
---

# 家园系统代码审查报告

## 审查概览

| 项 | 内容 |
|----|------|
| 审查人 | Claude(full-code-review pipeline) |
| 被审查人 | guiwei |
| 分支 | `h5_new_tf_v1042_homeland` |
| 日期 | 2026-07-11 |
| 范围 | `game/play/internal/home_land/{,plugin,model}/*.go` + `game/play/internal/ctl_home_land*.go`(约 7600 行) |
| 方法 | go-rules.md 逐条(规1–33 + L1–L16)对照 + `homelandDoc/` 当规格说明书核对 + 调用链验证 |
| 统计 | **P0=0, P1=3, P2=11**(另 2 个疑点需开发确认) |

> 侧重:正确性/并发、代码规范、性能。核心并发风险因框架**单 goroutine actor 模型**(Play/skeleton 串行处理消息/定时器/事件回调)被系统性规避,且代码主动以注释声明了该前提(`ctl_home_land.go:197-199`),质量基线较高。

---

## 问题汇总表

| # | 级别 | 问题 | 位置 | 规则 |
|---|------|------|------|------|
| 1 | 🔴P1 | `deepcopy_generated.go` 漏 `LikeRecords`,深拷贝退化为共享底层切片 | `model/deepcopy_generated.go:80-99` | 规23/16 |
| 2 | 🔴P1 | 工厂计时基准 `RateChangeTime` 在 settle 乱序并入时被回拨 → 木材虚增 | `plugin/plugin_timberprocessing.go:242-243` | L5/时间基准 |
| 3 | 🔴P1 | 主城升满入榜:`syncHomelandHonorRank` 读到自增前的旧等级 → 静默跳过写榜 | `ctl_home_land_build.go:755` + `:264` | L1/执行顺序 |
| 4 | 🟡P2 | 建筑不可回收却返回"碰撞冲突"错误码(go-rules L12 点名反例仍在) | `ctl_home_land_build.go:566` | L12 |
| 5 | 🟡P2 | `GetRoadSkin/SetRoadSkin` 无坐标边界校验,越界 key 串格 | `model/map_data.go:99-123` | L3 |
| 6 | 🟡P2 | 离开家园信任客户端 `targetPid` → 访客集合永久残留 | `ctl_home_land_visitor.go:14-22` | 规7/L7 |
| 7 | 🟡P2 | 装饰物拆解材料计算失败仅记日志不 return → 删物不返材 | `ctl_home_land_decoration.go:123-127` | 规6/L7 |
| 8 | 🟡P2 | 签到到期补发邮件 `p==nil` 直接 return,无重试/无告警 → 奖励永久丢失 | `ctl_home_land_sign.go:166-175` | 规6/L7 |
| 9 | 🟡P2 | 访客异步回调在玩家已下线后写回集合 → 残留+无效推送 | `ctl_home_land.go:112-131` | L4时序 |
| 10 | 🟡P2 | `occupiedMiningCells` 循环内 O(工人²) 全量重扫 | `plugin/lumbermill.go:504`、`plugin_lumbermill.go:92` | 性能 |
| 11 | 🟡P2 | 商店批量回收缺 `number>0` 下限校验 | `ctl_home_land_build.go:561-573` | L7防御 |
| 12 | 🟡P2 | 9 处函数超 60 行 | 见详情 | 规11 |
| 13 | 🟡P2 | 文档≠代码:格子编码 -1/-2 颠倒、方法名过时 | `homelandDoc/home_land_model.md` | 文档一致性 |
| 14 | 🟡P2 | `settleMiningStep` 单函数 85 行、分支密集 | `plugin/lumbermill.go:344-429` | 规11 |
| — | ⚪疑点 | 工厂满仓升级扩容后 Waiting 工人不复工 | `plugin_timberprocessing.go:310-329` | 待确认 |
| — | ⚪疑点 | 主题切换保留工厂未重初始化,可能与重置伐木场失步 | `ctl_home_land_theme.go:159-165` | 待确认 |

---

## 问题详情

### 🔴 P1-1 深拷贝遗漏 `LikeRecords`,快照与实时对象共享底层切片 — 规23/16

- 文件:`game/play/internal/home_land/model/deepcopy_generated.go:80-99`(对照 `data.go:25`)
- 现状:`HomelandSystem.DeepCopyInto` 逐字段深拷贝了 `TodayLikes / GroomRecords / OwnedRoadSkins`,唯独**没有 `LikeRecords`**(结构体定义 `data.go:25` 明确存在 `LikeRecords []*GroomRecord`)。该字段只靠顶部 `*out = *in` 浅拷贝。
- 问题:`*out = *in` 只复制切片头,`out.LikeRecords` 与 `in.LikeRecords` 共享同一底层数组与同一批 `*GroomRecord` 指针,DeepCopy 语义被破坏。根因是新增字段后未跑 `make deepcopy`,生成文件过期。当前崩溃风险被 `AddLikeRecord`→`appendGroomRecord` 的 copy-on-write 追加缓解,但这是隐性依赖,一旦有人原地改元素即数据串写。
- 建议:执行 `make deepcopy` 重新生成;建议把生成物一致性检查纳入 CI,防止再次漏字段。

### 🔴 P1-2 工厂计时基准回拨,settle 追帧乱序并入导致木材虚增 — L5/时间基准

- 文件:`game/play/internal/home_land/plugin/plugin_timberprocessing.go:238-245`(触发链 `lumbermill.go` dispatchWorker 无可采格分支以历史 `transTime` 调入)
- 现状:
```go
curStorage := state.CalcStorage(now, conf.OutputRes, conf.MaxStorage)
if curStorage >= conf.MaxStorage { continue }
state.SetStorage(curStorage)
state.SetRateChangeTime(now)   // now 可能是 settle 内的历史时刻
```
- 问题:全图树木采完那次 settle,多个工人在各自不同的 `transTime` 先后并入同一工厂。函数上方注释(222-223)声称"非满仓工厂本轮 RateChangeTime 不会被改写…必为前向推进",但 `assignIdleWorkerToFactory` 是**按每个 idle 工人调用**的,同一工厂会被写多次。若先处理的工人 A(`transTime=T5`)已把基准推到 T5,后处理的工人 B(`transTime=T2<T5`)再并入:`CalcStorage(T2)` 因 `elapsed=T2-T5<=0` 返回旧 `stored`(见 `building_data.go` CalcStorage 的 `elapsed<=0` 保护),但紧接着 `SetRateChangeTime(T2)` 把基准**回拨**到 T2。此后真实 `now` 的结算用 `(now-T2)×工人数×rate` 重复计入 `[T2,T5]` 区间 → 净虚增 `(T5-T2)×activeWorkers×OutputRes/1000`。注释的安全论证被本函数自身第 243 行推翻。触发窗口窄(利于玩家),若木材可流通则实为资损,可上调 P0。
- 建议:禁止基准回退,写入前取 max:
```go
if now > state.GetRateChangeTime() {
    state.SetStorage(curStorage)
    state.SetRateChangeTime(now)
}
setWorkerProcessing(...)
```
根治方案是 settle 内并入工厂的动作按 `transTime` 排序后再 apply。同时修正 222-223 注释,别继续声称不会回拨。

### 🔴 P1-3 主城升满入榜读到自增前旧等级,静默跳过写榜 — L1/执行顺序

- 文件:`ctl_home_land_build.go:755`(触发)+ `:264-267`(守卫)+ `OnUpgradeHomelandBuildingReq` 中的 `b.SetLevel`
- 现状:调用链 `OnUpgradeHomelandBuildingReq` → `homeLandDoUpgrade`(694)→ `homeLandUpgradeMainCity`(727),在 755 行 `curLv+1 == HomeLandMainCityLimit` 时调 `syncHomelandHonorRank`;但主城建筑 `b.SetLevel(b.GetLevel()+1)` 在 `homeLandDoUpgrade` **返回之后**才执行。
```go
// syncHomelandHonorRank:264
level := homelandMainCityLevel(p.GetHomeData())   // 读建筑当前等级
if level < gdconf.GetD2ConstCfgIntValue(gdconf.HomeLandMainCityLimit) { return }
```
- 问题:触发阈值 `curLv+1==limit`(即 `curLv==limit-1`)成立时,`syncHomelandHonorRank` 重新读到的 `level` 仍是自增前的 `curLv=limit-1 < limit`,守卫判定 false 直接 return,**排行榜写入被静默跳过**。玩家刚把主城升到上限时不进本区服/联盟/全区服荣誉榜,只能等下次荣誉度变化(放置/升级装饰物触发 `sendHonorPointNtfIfChanged`)才补写;若此后荣誉度长期不变则持续缺席榜单。
- 建议:让 `syncHomelandHonorRank` 接收显式 `level` 参数(传 `curLv+1`),或把入榜调用移到 `b.SetLevel` 之后。

### 🟡 P2-4 不可回收建筑返回"碰撞冲突"码 — L12 ErrCode 语义

- 文件:`ctl_home_land_build.go:565-567`
```go
if buildingConfig == nil || buildingConfig.BuildingRecycle == 0 {
    ack.ErrCode = cspb.ErrCodeHomeLandBuildingConflict   // 语义错误
    return
}
```
- 问题:回收 `BuildingRecycle==0` 的建筑时返回"空间碰撞冲突"码,客户端提示文案牛头不对马嘴。这正是 go-rules **L12 章节直接引用的反例**,规则明确要求专用码。`util.go:147` 用同一码是合法真碰撞,不冲突。
- 建议:新增 `ErrCodeHomeLandBuildingNotRecyclable` 并改用;碰撞类码不得用于业务规则拒绝。

### 🟡 P2-5 `GetRoadSkin/SetRoadSkin` 无坐标边界校验 — L3防御

- 文件:`model/map_data.go:99-123`
```go
func roadSkinKey(x, y int32) int32 { return y*MapSize + x }
```
- 问题:无 `[0,MapSize)` 校验。`x=60,y=0` 得 key=60,与合法 `x=0,y=1` 冲突,负坐标同理,会串格覆盖。与同文件 `IsRoadCell`(有边界 check)不一致,当前依赖上游校验。
- 建议:入口加边界校验,与 `IsRoadCell` 同级防御。

### 🟡 P2-6 离开家园信任客户端 `targetPid` → 访客残留 — 规7/L7

- 文件:`ctl_home_land_visitor.go:14-22`
```go
play.removeHomelandVisitor(p, req.GetTargetPlayerId())  // ← 客户端传的 targetPid
```
- 问题:`removeHomelandVisitor` = 从 `targetPid` 集合删 p + `SetVisitingTarget(0)`。若客户端传的 targetPid 与真实 `VisitingTarget` 不一致:从错误集合删(无操作)但仍清 0 → **p 永久残留在真实 target 的 `homelandVisitors` 集合**,持续收到该家园 `HomelandGroomStateNtf`,且 `onHomelandVisitorOffline` 因 VisitingTarget 已清 0 也无法再清理。对比 `onHomelandVisitorOffline`(:31)正确用了 `GetVisitingTarget()`。
- 建议:忽略 req 里的 targetPid,统一用 `GetVisitingTarget()`。

### 🟡 P2-7 装饰物拆解材料失败仍继续 → 删物不返材 — 规6/L7

- 文件:`ctl_home_land_decoration.go:123-127`
```go
mats, ec := homeLandDecorationDisassembleMaterials(playerID, cfgID, level)
if ec != cspb.ErrCodeSuccess {
    tlog.Errorf(...)   // ← 只打日志,没有 return
}
// 继续 ApplyRemove 删建筑,for range mats(nil) → 材料一件不返
```
- 问题:配置在 validate 与 apply 间被 `make conf` 热更改动时,装饰物被删、材料零返还。代码注释已预见该场景却选择继续,属防御缺口(概率极低,同步 handler 内无 yield)。
- 建议:`if ec != Success { return }` 中止(此时建筑尚未移除,安全)。

### 🟡 P2-8 签到到期补发邮件无重试 → 奖励永久丢失 — 规6/L7

- 文件:`ctl_home_land_sign.go:166-175`
```go
play.playerMgr.GetPlayerAsyn(playerID, func(p *mplayer.Player, err error, ctx cbctx.M) {
    if p == nil { return }   // ← 静默返回,err 未记录,一次性定时器已消耗
    play.sendHomeLandSignRewardMail(p)
}, nil)
```
- 问题:一次性定时器回调,`GetPlayerAsyn` 加载失败则未领奖励再无补发机会;`err` 参数完全未使用。
- 建议:至少记录 err;`p==nil` 时按 playerID 直发系统邮件(补发逻辑可脱离在线 Player)。

### 🟡 P2-9 访客异步回调在下线后写回集合 — L4时序

- 文件:`ctl_home_land.go:112-131`(`addHomelandVisitor`)
- 问题:`getPlayerHomelandData` 异步回调里 `addHomelandVisitor(p, targetPid)`;若访客 p 在加载期间断线,`onHomelandVisitorOffline` 已先清理,回调随后又写回 → 残留 + 无效推送。非资损。
- 建议:回调内加 p 在线态/VisitingTarget 一致性校验后再登记。

### 🟡 P2-10 `occupiedMiningCells` 循环内 O(工人²) 重扫 — 性能

- 文件:`plugin/lumbermill.go:504`(`wakeWaitingWorkers`)、`plugin_lumbermill.go:92,96`(`OnMove`)
- 问题:每派一个工人就 `occupiedMiningCells` 全量重扫所有伐木屋工人,与 `settleWorkerFull`(一次构建整段复用)取向不一致。工人数不大时影响有限。
- 建议:仿 `OnPlace`(57-69)增量维护占用集合,派遣成功后 `occupied[pos]=true`。

### 🟡 P2-11 商店批量回收缺 `number>0` 校验 — L7防御

- 文件:`ctl_home_land_build.go:561-573`
- 问题:`int32(len(buildingArr)) < number` 中 `number` 为负时恒真绕过检查,`v.Val*int64(number)` 产生负值资产。`AddAssets` 跳过 `val<=0` 故无实际资损,但缺输入下限校验。
- 建议:循环开头 `if number <= 0 { ErrCodeWrongParam; return }`。

### 🟡 P2-12 / P2-14 函数超 60 行 — 规11

- `plugin/lumbermill.go:344` `settleMiningStep`(**85 行**,分支密集,建议抽 `advanceAfterStep`)
- `ctl_home_land_build.go:359` `OnPlaceHomelandBuildingReq`(73)
- `ctl_home_land_build.go:615` `OnUpgradeHomelandBuildingReq`(71)
- `ctl_home_land_build.go:24` `OnSaveHomelandLayoutReq`(68)
- `ctl_home_land_sign.go:34` `OnHomeLandSignRewardReq`(68)
- `ctl_home_land.go:622` `loadHomelandGroomTarget`(69)
- `ctl_home_land_build.go:542` `OnRecycleShopHomeLandBuildingReq`(66)
- `ctl_home_land_theme.go:104` `applyMapThemeSwitch`(65)
- `model/util.go:88` `occupyBuildingCells`(65)
- 建议:按"检查/执行/通知"职责拆子函数。

### 🟡 P2-13 文档≠代码 — 文档一致性

- `homelandDoc/home_land_model.md:56、194-197`:格子编码写反,文档 `-1=秘宝/-2=占用`,代码实为 `CellOccupied=-1 / CellTreasure=-2`(`const.go:15-17`)。按文档改碰撞/秘宝逻辑会把占用格当秘宝格。
- `home_land_model.md:34、172`:方法名过时——`CheckGetLikeRecords()`→实为 `FilterLikeRecords()`(data.go:67);`CheckInit()`→实为 `IsInitialized()`(sign_data.go:31)。
- 建议:同步文档,与 const.go / 代码对齐。

### 🔎 P1 爆炸半径核验(code_parser 语义检索,Phase 0.5 补做)

- **P1-1 LikeRecords**:唯一读取方 `FilterLikeRecords`(data.go:67),下游经 `GetHomelandRecords` 协议下发,均走 copy-on-write,影响面收敛在 model 包内 → 深拷贝漏字段风险确认为隐性,结论不变。
- **P1-2 木材 RateChangeTime**:`CalcStorage` 被 `timberStorageFull`(reddot.go:71,红点判定)与 `OnPeekCollect`(收取)读取,均在审查范围内 → 回拨虚增会同时污染红点与收取量,结论不变。
- **P1-3 荣誉榜**:语义检索发现一个**审查文件集之外**的调用方 `ctl_rank_cross.go:550 rankHomelandHonorAllMember`(全区服荣誉榜成员回调)。升满主城不写榜的影响不止本区服/联盟榜,**还波及全区服榜** → 佐证 P1 严重度,修复时需确认三处榜(区服/联盟/全区服)都能补上。

### ⚪ 疑点(需开发确认,非缺陷判定)

1. **工厂满仓升级扩容后 Waiting 工人不复工** — `plugin_timberprocessing.go:310-329`。`OnUpgrade` 只 `releaseExcessWorkers`+`assignWorkersToFactory`,不 `wakeFactoryWorkers`。满仓工厂升级把 `MaxStorage` 调大后已不满仓,但 Waiting 工人要等玩家收取才复工,升级期间空转。可能与"收取才唤醒"模型刻意一致,也可能不符玩家预期。
2. **主题切换保留工厂未重初始化** — `ctl_home_land_theme.go:159-165`。只对保留伐木场做 `delete+PlaceBuilding` 重初始化,未对保留的木材加工厂做等价处理,若工厂能原地保留,其在产工人可能与刚重置的伐木场失步。需 plugin 层佐证工厂能否"保留"。

---

## ✅ 检查通过(已逐条验证无问题)

- **并发安全(L4)**:Play/skeleton 单 goroutine actor,handler/定时器/事件/异步加载回调全部串行(`ctl_home_land.go:197-199` 有显式注释)。`cells[y][x]` 原地改写、访客 map 遍历(仅 `SendTo` 入队不改集合)、红点字段(`bson:"-"` 且 setter 无 MakeDirty)均无数据竞争。规33 在此模型下不适用。
- **资源结算原子性(L7)**:收取伐木场/工厂、商店回收、装饰物拆解、主城升级、秘宝领取普遍采用 `check → CheckAndAddItems/CheckAddAssets → commit` 三段式,先校验背包再扣/发,无资损。
- **越界防御(L3)**:`occupyBuildingCells`、`clearBuilding`、`LoadInitCells`、`AnyResourceCell` 所有 `cells[y][x]` 下标前均有 `[0,MapSize)` 校验(仅 RoadSkin 例外,见 P2-5)。
- **签到幂等/秘宝去重**:`IsRewardClaimed`/`AddLoginDay`(IsSameDay 跨天去重 + signDayMax 封顶)/`IsTreasureClaimed` 守卫齐全,check-then-grant-then-mark 顺序正确,无刷奖路径。
- **离线追帧(L1/时间)**:`settleWorkerFull` 时间单调推进,`maxIters=100000` 仅安全网;`gdconf.Second=1000` 全链路 ms↔秒换算一致(无 L10 违规);`CalcStorage/CalcAccumulated` 全程 int64 防溢出并处理截断/负值。
- **accessor 合规(规4/24)**:包级函数一律 Get/Set;`MainCityState/SignData` 内的直接字段访问命中规24"实现层例外";slice 删除用 `utility.DeleteSliceElem`/反向过滤/新建返回,无 L16 range 删元素问题。
- **跨服鉴权**:拜访/点赞/打理跨服回包在目标服二次校验(record 非空、`recPlayerID==fromPlayerID`、本服时间覆盖来源时间防伪造);布局保存 `validateUpsertedBuildings`+`occupyBuildingCells` 双层校验(去重/边界/来源/碰撞/锁定格),伪造请求被拒。
- **幂等**:`RecalcDecorationEffective` 用 `sort.SliceStable`(等级降序+放置时间升序)确定性排序,重复调用稳定。

## 🏆 Praise

- **架构**:整体采用清晰的插件框架(`BuildingPlugin` 接口 + `SettleAllBuildings` 统一入口),伐木/工厂/主城/装饰物各自插件解耦,新增建筑类型成本低。
- **防御性**:主动用注释固化隐含约定——单 goroutine 串行前提(`ctl_home_land.go:197-199`)、副作用顺序不可颠倒(`plugin_lumbermill.go:153`)、int64 防溢出推导(CalcStorage)、"先校验后提交避免资损"(build.go:596),接手者不必读全链路即可理解约束。
- **可维护性**:`homelandDoc/` 18 份文档 + 伐木场完整状态机图,规格级别的文档在游戏项目中少见,极大降低理解成本(本次审查即以其为 checklist)。
- **性能**:ticker 门控(`anyLumberMillDeadlineExpired || AnyTimberCapReached`)有效跳过无效 settle;`occupied` 集合在 `settleWorkerFull` 内一次构建整段复用,已体现性能意识。

---

## 修复进度追踪

| # | 级别 | 问题 | 状态 |
|---|------|------|------|
| 1 | P1 | deepcopy 漏 LikeRecords(跑 `make deepcopy`) | 待修复 |
| 2 | P1 | 工厂 RateChangeTime 回拨 → 木材虚增(max 守卫) | 待修复 |
| 3 | P1 | 主城升满入榜读旧等级 → 不写榜(传显式 level) | 待修复 |
| 4 | P2 | 不可回收返回碰撞码(新增 NotRecyclable 码) | 待修复 |
| 5 | P2 | RoadSkin 无边界校验 | 待修复 |
| 6 | P2 | 离开家园信任客户端 targetPid(改用 VisitingTarget) | 待修复 |
| 7 | P2 | 装饰物拆解失败不 return(删物不返材) | 待修复 |
| 8 | P2 | 签到补发邮件无重试 | 待修复 |
| 9 | P2 | 访客异步回调下线后残留 | 待修复 |
| 10 | P2 | occupiedMiningCells O(n²) | 待修复 |
| 11 | P2 | 商店回收缺 number>0 校验 | 待修复 |
| 12 | P2 | 9 处函数超 60 行 | 待修复 |
| 13 | P2 | 文档 -1/-2 编码颠倒 + 方法名过时 | 待修复 |
| 14 | P2 | settleMiningStep 85 行 | 待修复 |
| — | 疑点 | 工厂满仓升级不复工 | 待确认 |
| — | 疑点 | 主题切换保留工厂未重初始化 | 待确认 |
</content>
</invoke>
