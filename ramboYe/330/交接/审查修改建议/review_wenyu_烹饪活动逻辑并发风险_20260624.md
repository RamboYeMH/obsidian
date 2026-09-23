# 代码审查 — 烹饪活动 逻辑与并发风险

> 审查人：wenyu  
> 日期：2026-06-24  
> 提交范围：`2743474aee^..fc4d9f15d6`（H5-10029 【1046】烹饪活动 共10次提交）  
> 审查维度：逻辑风险 L1–L15

---

## 问题汇总

| 编号 | 等级 | 风险类型 | 文件 | 行号 | 简述 |
|------|------|----------|------|------|------|
| R-01 | **P0** | L2 空指针 | `cooking_server_quest/api.go` | 62–63 | `GetActvOnlineCfg` 返回值无 nil 检查直接访问 `.AcrossServerGroup` |
| R-02 | **P1** | L2 空指针 | `cooking/handler.go` | 234–235 | `GetD2ActvCookingThemeCfg` 返回值无 nil 检查直接访问 `RequestIngredientsDayMax` |
| R-03 | **P1** | L2 空指针 | `cooking/handler.go` | 450–451 | `doDonateCallback` 中 `themeCfg` 无 nil 检查直接访问积分字段 |
| R-04 | **P1** | L2 空指针 | `cooking/handler_inner.go` | 89 | `GetD2ConfigCfg("Cookin_Compensation_Mail")` 结果无 nil 检查直接 `.Val` |
| R-05 | **P1** | 行为变更 | `actv/cactv/mgr/trigger.go` | 72（被删）| 删除跨服活动 trigger 中全部 `CheckServerOpenTime` 检查，影响所有已有活动 |
| R-06 | **P2** | L5 冗余写 | `cooking/api.go` | 143–144 | `OnTick` 每次调用都执行 `SetUpdateTs + MakeDirty`，无状态变化时产生无效 DB 写入 |
| R-07 | **P2** | L15 nil 一致性 | `cooking/handler.go` | 多处 | 同一函数 `GetD2ActvCookingThemeCfg` 在部分路径有 nil 检查（`packAllyRequests`），部分路径无检查 |

---

## 详细说明

### R-01 P0 — cooking_server_quest: 双 nil 指针

```go
// cooking_server_quest/api.go:59-63
originCfg := gdconf.GetActvOnlineCfg(cfgId)
selfCfg := gdconf.GetActvOnlineCfg(a.CfgID)
// 判断是否属于同一个跨服组
if originCfg.AcrossServerGroup != selfCfg.AcrossServerGroup {
```

`GetActvOnlineCfg` 当配置不存在时返回 nil。若 `cfgId`（来自事件 `e.Ext.(int32)`）无效，或活动配置热更期间不完整，两个指针均可能为 nil，**直接 panic**。

**修复：**
```go
originCfg := gdconf.GetActvOnlineCfg(cfgId)
selfCfg := gdconf.GetActvOnlineCfg(a.CfgID)
if originCfg == nil || selfCfg == nil {
    tlog.Warnf("ActvCookingServerQuest OnCookingScoreUpd cfg nil cfgId:%v selfCfgId:%v", cfgId, a.CfgID)
    return
}
if originCfg.AcrossServerGroup != selfCfg.AcrossServerGroup {
```

---

### R-02 P1 — onRequestIngredientReq: themeCfg 无 nil 检查

```go
// handler.go:234-235
themeCfg := gdconf.GetD2ActvCookingThemeCfg(a.GetContentID())
if pp.GetDailyReqCount() >= themeCfg.RequestIngredientsDayMax {  // ← panic if nil
```

对比 `packAllyRequests`（同文件）已有 nil 检查：
```go
themeCfg := gdconf.GetD2ActvCookingThemeCfg(a.GetContentID())
if themeCfg == nil { return nil }
```

**修复：** 在 `onRequestIngredientReq` 中，获取 `themeCfg` 后立即加 nil 检查并返回合适 errCode。

---

### R-03 P1 — doDonateCallback: themeCfg 无 nil 检查

```go
// handler.go:450-455
themeCfg := gdconf.GetD2ActvCookingThemeCfg(a.GetContentID())
personalDelta := int64(themeCfg.PersonalPointsSend)   // ← panic if nil
...
a.addUnionScoreIfBound(..., int64(themeCfg.LeaguePointsSend))
```

此处是异步回调（`TryDecAssets` 的 callback），panic 会导致整个 goroutine 崩溃。

**修复：** 加 nil 检查，或将 `themeCfg` 在进入回调前预取并透传。

---

### R-04 P1 — sendIngredientCompensationMail: GetD2ConfigCfg 无 nil 检查

```go
// handler_inner.go:89
mailCfgID := int32(gdconf.GetD2ConfigCfg("Cookin_Compensation_Mail").Val)
```

若配置表缺少 `"Cookin_Compensation_Mail"` 键（热更期间 / 新环境首次部署），`.Val` panic。

**修复：**
```go
cfg := gdconf.GetD2ConfigCfg("Cookin_Compensation_Mail")
if cfg == nil {
    tlog.Errorf("sendIngredientCompensationMail: config Cookin_Compensation_Mail not found")
    return
}
mailCfgID := int32(cfg.Val)
```

---

### R-05 P1 — trigger.go: 整段 CheckServerOpenTime 删除影响面超出烹饪活动

被删代码：
```go
if cfg.GetType() != gdactv.ActvTypeCrossWishPool &&
    cfg.GetType() != gdactv.ActvTypeCrossBanquetPrepare &&
    ... {
    if !cfg.CheckServerOpenTime() {
        return false
    }
}
```

该逻辑本意：跨服活动中，**不在例外列表**的活动类型需通过 `CheckServerOpenTime`（基于 `SpecialType/SpecialVal` 的日历限制）才能触发。烹饪活动未在例外列表中，若直接删除，则烹饪活动绕过日历检查的同时，所有**其他不在例外列表的跨服活动**也一起绕过了检查。

**风险：** 依赖 `SpecialType` 控制开放时间的历史活动，可能在不应该开的时间段被触发。

**建议：** 若意图是"烹饪活动不需要该检查"，应将 `ActvTypeCrossCooking` 加入例外列表而非删除整段逻辑；或确认所有跨服活动均已通过 `checkState` 内的其他时间门控，不再需要此检查。

---

### R-06 P2 — OnTick: 每 tick 无谓 DB 写入

```go
// api.go:133-150
func (a *ActvTmplCooking) OnTick(now int64) {
    globalProgress := a.CompGlobal.GetProgress()
    if !util.IsSameDay(globalProgress.GetUpdateTs(), now) {
        actv_com.SafeCall("ActvTmplCookingNextDay", func() { ... })
    }
    globalProgress.SetUpdateTs(now)  // ← 不管有无跨天，每 tick 都写
    globalProgress.MakeDirty()       // ← 每 tick 触发一次 DB 写
}
```

跨天时才需要更新 UpdateTs，当天内每次 tick 都写是多余的。

**修复：** 将 `SetUpdateTs` 和 `MakeDirty` 移入 if 块内，仅跨天时持久化。

---

### R-07 P2 — L15: nil 检查路径不一致

| 调用位置 | nil 检查 |
|---------|---------|
| `packAllyRequests` | ✅ 有 nil 检查，return nil |
| `broadcastAllyRequestDelta` | ✅ 使用 `GetD2ActvCookingThemeCfgNoErr` + nil 检查 |
| `refreshRecommendIfNeeded` | ✅ `if themeCfg != nil && ...` |
| `onRequestIngredientReq` | ❌ 无 nil 检查 |
| `doDonateCallback` | ❌ 无 nil 检查 |

L15 要求：对同一字段的 nil 检查在所有调用点保持一致。应统一为"调用点全部检查"策略。

---

## 修复进度追踪

| 编号 | 问题 | 状态 |
|------|------|------|
| R-01 | cooking_server_quest nil 指针 | 待修复 |
| R-02 | onRequestIngredientReq themeCfg nil | 待修复 |
| R-03 | doDonateCallback themeCfg nil | 待修复 |
| R-04 | sendIngredientCompensationMail GetD2ConfigCfg nil | 待修复 |
| R-05 | trigger.go CheckServerOpenTime 删除影响面 | 待确认 |
| R-06 | OnTick 无谓 DB 写 | 待修复 |
| R-07 | themeCfg nil 检查不一致 | 待修复（与 R-02/R-03 合并） |
