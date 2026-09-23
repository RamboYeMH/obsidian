# 代码审查 — 烹饪活动 Go 编码规范

> 审查人：wenyu  
> 日期：2026-06-24  
> 提交范围：`2743474aee^..fc4d9f15d6`（H5-10029 【1046】烹饪活动 共10次提交）  
> 审查维度：Go 编码规范 1–32

---

## 问题汇总

| 编号 | 等级 | 规范 | 文件 | 行号 | 简述 |
|------|------|------|------|------|------|
| C-01 | **P1** | 规范 11 | `cooking/handler.go` | 45–136 | `onCookReq` ~92 行，超 60 行限制 |
| C-02 | **P1** | 规范 11 | `cooking/handler.go` | 203–281 | `onRequestIngredientReq` ~78 行，超 60 行限制 |
| C-03 | **P2** | 规范 11 | `cooking/handler.go` | 358–432 | `onDonateReq` ~74 行，超 60 行限制 |
| C-04 | **P2** | 规范 11 | `cooking/handler.go` | 137–202 | `onSubmitReq` ~65 行，轻微超限 |
| C-05 | **P2** | 规范 24 | `cooking/api.go` | 216 | `req.Name` 直接字段访问，应改 `req.GetName()` |
| C-06 | **P2** | 规范 24 | `ap_sync_union_player/sync_union_player.go` | 129 | `progress.Sid` 直接字段访问，应改 `progress.GetSid()` |
| C-07 | **P2** | 规范 21 | `cooking/api.go` | 112、133 | `TryResetByNextDays`、`RecycleItemOnEnd` 包内使用，应小写 |
| C-08 | **P2** | 规范 25 | `cooking/handler.go` | 多处 | 积分累加未封装语义方法，直接 `SetPersonalScore(GetPersonalScore() + delta)` |

---

## 详细说明

### C-01 P1 — onCookReq 超 60 行（~92 行）

`onCookReq`（handler.go:45–136）包含：参数校验 + 批量校验 + 失败短路 + 异步扣道具 + 回调发奖励 + 熟练度解锁，共92行。  
应将检查逻辑和核心操作拆分：

```go
func (a *ActvTmplCooking) onCookReq(playerID int64, req0 interface{}) {
    req := req0.(*cspb.ActvCookingCookReq)
    ack := &cspb.ActvCookingCookAck{ActvID: a.ActvID}
    pp, _ := a.CompPlayer.GocProgress(playerID)
    a.tryBindUnion(playerID, pp)
    a.TryResetByNextDays(pp, util.NowTs(), false)

    if errCode := a.checkCookReq(pp, req); errCode != cspb.ErrCodeSuccess {
        ack.ErrCode = errCode
        msg_cast.ActvSendMsg(playerID, ack)
        return
    }
    if req.Result == cookResultFail {
        ack.ErrCode = cspb.ErrCodeSuccess
        msg_cast.ActvSendMsg(playerID, ack)
        return
    }
    a.doCookReq(playerID, pp, req, ack)
}

// checkCookReq 检查烹饪请求合法性，返回失败原因
func (a *ActvTmplCooking) checkCookReq(pp *CookingPlayerProgress, req *cspb.ActvCookingCookReq) cspb.ErrCode { ... }
```

---

### C-02 P1 — onRequestIngredientReq 超 60 行（~78 行）

handler.go:203–281，包含：参数校验 + 联盟检查 + 次数限制 + 重复请求检查 + 创建请求 + 广播，应至少抽出 `checkIngredientReq` 函数：

```go
func (a *ActvTmplCooking) onRequestIngredientReq(playerID int64, req0 interface{}) {
    req := req0.(*cspb.ActvCookingRequestIngredientReq)
    ack := &cspb.ActvCookingRequestIngredientAck{ActvID: a.ActvID}
    defer msg_cast.ActvSendMsg(playerID, ack)

    pp, _ := a.CompPlayer.GocProgress(playerID)
    a.tryBindUnion(playerID, pp)
    a.TryResetByNextDays(pp, util.NowTs(), false)

    gp, errCode := a.checkIngredientReq(playerID, pp, req)
    if errCode != cspb.ErrCodeSuccess {
        ack.ErrCode = errCode
        return
    }
    a.doCreateIngredientRequest(playerID, pp, gp, req)
    // pack ack ...
}
```

---

### C-03 P2 — onDonateReq 超 60 行（~74 行）

handler.go:358–432，虽已将回调提取为 `doDonateCallback`，主函数仍有 74 行。建议将联盟一致性校验抽取为 `checkDonateReq` 函数。

---

### C-04 P2 — onSubmitReq 轻微超限（~65 行）

handler.go:137–202，可将异步回调中的积分计算逻辑抽成 `calcSubmitScore(pp, dishCfg, count) (personalDelta, unionDelta int64)` 进一步精简。

---

### C-05 P2 — 规范 24：req.Name 直接字段访问

```go
// cooking/api.go:216
PlayerName: req.Name,
```

`IngredientRequest` 已生成 `accessor_IngredientRequest.go`，所有字段必须通过 accessor 访问：

```go
// 修复
PlayerName: req.GetName(),
```

---

### C-06 P2 — 规范 24：progress.Sid 直接字段访问

```go
// ap_sync_union_player/sync_union_player.go:129
a.changeFunc(e.Typ, playerId, unionId, progress.Sid)
```

`SyncUnionPlayer` 已生成 `accessor_SyncUnionPlayer.go`（含 `GetSid()`/`SetSid()`），不得直接访问 `.Sid`：

```go
// 修复
a.changeFunc(e.Typ, playerId, unionId, progress.GetSid())
```

---

### C-07 P2 — 规范 21：包内专用方法大写导出

**`TryResetByNextDays`（api.go:133）**：仅在 `cooking` 包内（`handler_inner.go`、`api.go`）被调用，未被跨包引用，应改为 `tryResetByNextDays`。

**`RecycleItemOnEnd`（api.go:112）**：同上，仅被 `OnEnd` 内部调用，应改为 `recycleItemOnEnd`。

规范 21：receiver 方法仅在本 package 内使用，必须声明为小写（unexported）；Getter/Setter 方法不受此规则约束。

---

### C-08 P2 — 规范 25：积分累加未封装语义方法

以下模式在代码中重复出现（`onSubmitReq`、`doDonateCallback`、`onA2PActvRankFakeUpNtf`）：

```go
pp.SetPersonalScore(pp.GetPersonalScore() + personalDelta)
```

规范 25 要求：数值累加应封装为语义方法 `IncrScore` / `AddPersonalScore`，调用层不得自行拼接 Get/Set：

```go
// 建议在 CookingPlayerProgress accessor 中添加：
func (pp *CookingPlayerProgress) AddPersonalScore(delta int64) {
    pp.SetPersonalScore(pp.GetPersonalScore() + delta)
}

// 调用层改为：
pp.AddPersonalScore(personalDelta)
```

---

## 亮点（值得保留）

- `packMyRequest`、`packAllyRequests`、`broadcastAllyRequestDelta` 职责清晰，函数长度合理。
- 异步回调（`TryDecAssets`）提取为 `doDonateCallback` 的模式正确，避免了过深的匿名函数嵌套。
- `AddReceived` 方法封装了 slice append，符合规范 8。
- 时间单位处理一致（`now/1000`、`StartTs/1000` 均转为秒再传 `DiffDay`）。
- `GM Command` 集中在一处，便于测试和维护。

---

## 修复进度追踪

| 编号 | 问题 | 状态 |
|------|------|------|
| C-01 | onCookReq 超行 | 待修复 |
| C-02 | onRequestIngredientReq 超行 | 待修复 |
| C-03 | onDonateReq 超行 | 待修复 |
| C-04 | onSubmitReq 轻微超限 | 待确认 |
| C-05 | req.Name 直接访问 | 待修复 |
| C-06 | progress.Sid 直接访问 | 待修复 |
| C-07 | TryResetByNextDays/RecycleItemOnEnd 大写 | 待修复 |
| C-08 | 积分累加语义封装 | 待修复 |
