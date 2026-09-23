# UnionDuel ChangeRoad 空指针（联盟对决换路）— 2026-08-22

## 现象

- 线上 triage P0：`runtime error: invalid memory address or nil pointer dereference`，recover 点 `chanrpc.go:246`
- 首次出现 **2026-08-22 00:08**（联盟对决新一轮 00:00 开启后），至 10:14 共 ~9 次，全部集中在 **actv1** 实例
- 历史窗口（24-12h / 36-30h / 7d）`comp_union.go` 全 0 命中 → 本次巡查判为新增 P0
- 同一 chanrpc exec goroutine（6232）反复 panic 被 recover，进程未挂，影响玩家换路请求失败

## Stack

```
(*UnionDuelPlayerTroops).GetRoad  accessor_UnionDuelPlayerTroops.go:8
(*UnionDuelPlayer).ChangeRoad     comp_union.go:159
(*ActvTmplUnionDuel).onCrossActvUnionDuelChangeRoadReq  ctl.go:412
(*ReqDispatcher).OnReq            handler.go:93
(*ActvMgr).OnActvActionReq        actv_msg.go:226
(*ActvModule).OnActvActionReq     ctl_actv.go:107
```

## 根因

- `UnionDuelPlayer.Troops (*UnionDuelPlayerTroops)` 仅在**布防流程**初始化（`ctl.go:287`）
- 玩家加入参赛名单时（`logic.go:137` / `api.go:121` 两处构造）`Troops` 为 nil，且无判空
- 未布防玩家被管理员（LockTroop 阶段，BattleState=2）或本人（DeployTroop 阶段，BattleState=1）换路：
  `ctl.go:412 oldRoad := playerProgress.ChangeRoad(req.Road)` → `comp_union.go:159 p.GetTroops().GetRoad()` → accessor 对 nil 解引用
- 连带风险点：`ctl.go:423/426` `unionProgress.GetTroops()[targetID]` map 未命中时同样 nil 解引用

## 修复建议

1. `ctl.go:412` 前补 nil 保护：
   ```go
   if playerProgress.GetTroops() == nil {
       ack.ErrCode = cspb.ErrCodeUnionDuelCantChangeTroopRoad
       return
   }
   ```
2. `ctl.go:423/426` 对 `unionProgress.GetTroops()[targetID]` 判 nil

## 备注

- 非新代码：union_duel 模板 1030/1031 版引入（c376b09411 H5-4472 联盟对决基础搭建），1046-1048 有优化提交（a3669f5125）
- 周期活动重开暴露潜伏 bug：判新需结合活动周期（历史窗口 0 命中 ≠ 代码新增，可能是上一轮活动结束 >7d）
