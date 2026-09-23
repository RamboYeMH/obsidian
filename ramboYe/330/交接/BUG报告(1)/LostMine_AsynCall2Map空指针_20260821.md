# LostMine.packProto → chanrpc.Delay 空指针（AsynCall2Map 误判本服）

- 日期: 2026-08-21
- 级别: P0（panic，SafeCall 恢复，无崩溃）
- 状态: 持续性问题（≥2 周），根因已定位，未修复

## 现象

线上 triage（5h 窗口）出现 10 条 panic，其中 4 条为：

```
SendActvExtNtfToPlayer%!(EXTRA runtime.errorString=runtime error: invalid memory address or nil pointer dereference)
actv_com/doc.go:23 SafeCall.func1  ← recover 点
chanrpc.(*Server).Delay  chanrpc.go:251  ← 实际空指针点（s==nil）
module.(*Skeleton).AsynCall  skeleton.go:271  ← server.Delay() 调用
gameServiceImpl.AsyncCall  service.go:106  ← GetChanRPC(modName) 返回 nil
gameServiceImpl.AsynCall2Map  service.go:124  ← IsLocalServer==true 走本地分支
ActvTmplLostMine.packProto  logic.go:51
SendActvExtNtfToPlayer  actv_msg.go:571  ← OnActvListReq 打包活动列表
```

## 频率（非新增）

| 窗口 | 数量 |
|------|------|
| 14d~7d 前 | 36 条 |
| 7d~24h 前 | 116 条 |
| 今日 24h | ~11 条（00:26 / 08:34 / 14:05 三波小爆发，game11/38/385）|

存在 ≥2 周，日均 ~15 条，凌晨聚集，SafeCall 已恢复（影响：个别玩家活动列表请求失败）。

## 根因链路

1. `game/actv/internal/activity/template/lost_mine/logic.go:50-51`：`curMap := p.GetMapInfo()` 可能为 nil（玩家无地图信息）或 `ServerId==0`。
2. `service.go:114-124 AsynCall2Map`：mapInfo nil/零值时用默认 `serverType=Game, serverId=conf.ServerID, modName=WMAPMOD("wmap")`。
3. `service.go:144-149 IsLocalServer`：**`serverID==0 || servertype==""` 直接返回 true（短路误判本服）**。
4. 走本地分支 → `service.go:106 AsyncCall` → `core.DefaultApp().GetChanRPC("wmap")` 在 **actv 独立进程**中未注册 wmap 模块 → 返回 **nil**（core.go:220-236 遍历 app.mods + multiMods 均未命中）。
5. `skeleton.go:271 server.Delay()`（server==nil 的方法调用合法）→ `chanrpc.go:251 if !s.opendelay` → 空指针 panic。

设计假设是 actv 内嵌 game 进程（本服=本进程），实际拓扑 actv 为独立 NATS 服务（natsdef.Actv），wmap 永不注册。

## 修复建议

- `AsynCall2Map`：`mapInfo==nil || ServerId==0` 时不做本地 chanrpc 调用（记 error 跳过或明确走 NATS 到真实 game 服）。
- `AsyncCall`（service.go:106）前判 `GetChanRPC(modName)==nil` 防御。
- 治本：IsLocalServer 的 `serverID==0 || servertype==""` 短路在 actv 独立进程场景应返回 false。

## 关联

- 洞穴历险/失落矿脉 近期提交：H5-10527（07-08）、1037 系列（02-03月）、矿洞 update（07-18/19）。
- AsynCall2Map 引入于 06-17「洞穴探险」提交 9d2b41f466。
