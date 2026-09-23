# game862 内存持续增长 — 战令 BattlePassMgr 全局 map cfg-nil 先入后查致 Player 驻留

日期: 2026-08-20
实例: game862 (h5prod)
性质: 线上内存泄漏（累积型，无重启不释放）

## 现象

- 内存（RSS）自 08-19 14:00 起持续拉升 6.6G → 18:00 峰值 10.35G，随后平台化在 9.2-9.5G，**今天 08-20 活跃大幅下降也不释放**，Go heap 反略升（4.54G→5.43G）。
- Go heap profile（inuse_space）：goal 订阅表（AddSubInfo 423MB）+ tiny_play 任务（makeDragonWindQuest 364MB）等 per-player 数据占主导，订阅者量级（数百万）远超 808 个 activePlayers 能承载。
- 日志：`battlefield/battle_pass_mgr.go:71 InitPlayerBattlePassDataMgr main cfg is nil` 在 game862 **命中 185,507 次**。

## 活跃 vs 内存对照（关键证据）

| 时段 | ccu | activePlayers | 新角色注册 | RSS |
|------|-----|--------------|-----------|-----|
| 08-19 07-09 | 0-200 | 0-900 | 247-950/h | 低 |
| 08-19 10-17 | 280-660 | 1200-2500 | 1039-1305/h | 6.6G→10.35G |
| 08-19 18+ | 275-618 | 1000-2470 | 骤停 ~49 | 平台化 9.2G |
| 08-20 全天 | 60-198 | 400-830 | 1 条 | 9.34G |

**08-19 存在约 1.2 万新号注册潮**（07-18 点，18 点骤停），是异常日；今天是正常低活跃。内存随注册潮拉升、潮停平台化、活跃下降不释放 → 注册潮产生的大量 per-player 数据驻留。

## 根因

`InitPlayerBattlePassDataMgr`（`game/play/internal/battlefield/battle_pass_mgr.go:49`）**先入全局 map，后校验配置**：

```go
func (mgr *BattlePassMgr) InitPlayerBattlePassDataMgr(pid, ...) {
    if _, ok := mgr.Mgr[pid]; !ok {
        mgr.Mgr[pid] = NewBattlePassPlayerData(pid)  // 先加入全局 map
    }
    battlePass.QuestMgr.evalFunc = evalFunc          // evalFunc 闭包捕获 *Player
    battlePass.RandQuestMgr.evalFunc = evalFunc
    ...
    if len(battlePass.QuestMgr.Quests) <= 0 {
        cfg := gdconf.GetMainCfgByStartTs(...)
        if cfg == nil {
            tlog.Errorf("InitPlayerBattlePassDataMgr main cfg is nil ...")  // 远征未开 → cfg 恒 nil
            return                                      // 提前返回，条目已残留
        }
    }
}
```

**远征未开放时 `GetMainCfgByStartTs` 恒返回 nil** → 每次调用都在全局 `BattlePassMgr.Mgr[pid]` 留下一个含捕获 `*Player` 的 evalFunc/ntfAPI 闭包条目后报错返回。被闭包持有的 Player 无法被 GC，其全部 tiny_play 任务（makeDragonWindQuest ~500/号）+ goal 订阅数据全部驻留。

触发路径：`InitBattlePassData`（ctl_battle_field_battle_pass.go:62）在 `OnBattleFieldBattlePassReq` 等战令数据请求处理器中，**位于 `IsExpeditionOpen()` 守卫之前无条件调用**（line 34）。08-19 注册潮期间客户端/机器人请求战令数据即触发。

清理：`BattlePassClose()` 仅在远征赛季结束时调用，远征未开 → **永不触发，条目永久累积**。

## 修复（建议）

1. **主修**：`InitPlayerBattlePassDataMgr` 把入 map 时机移到配置校验之后；cfg nil 时 `delete(mgr.Mgr, pid)` + 清 dispatcher，不残留闭包条目。
2. **补逐玩家下线清理**：`PlayerOffline`/`DelPlayer` 时从 `BattlePassMgr.Mgr` 删除该玩家条目（含 UnRegSubscriber），不依赖赛季 Close。
3. **防御**：`InitBattlePassData` 入口加 `BattleFieldIsOpen()` 守卫，远征未开直接返回不入 map。

## 复盘

- 同类缺陷存在于远征族全部 4 个全局 per-player QuestMgr：`BattlefieldQuestMgr.PlayerQuestMgr`（ctl_battlefield_quest.go:171）、`BattlePassMgr.Mgr`（本报告，当前 game862 触发）、`ExpGamePlayMgr.Mgr`（ctl_battlefield_game_play.go:95）、`MeltingIceQuestMgr.PlayerQuestMgr`（当前无调用方）。均以 evalFunc/ntfAPI 闭包捕获 *Player 存入全局 map、仅赛季 Close 清理。
- 远征"未开放"不等于不触发——战令初始化路径不受 `IsExpeditionOpen()` 守卫，注册/请求战令数据即可喂满全局 map。
- 排查陷阱：`inuse_objects` 对小对象采样严重放大，Player/订阅者计数须用字节（inuse_space）反推。

## 二次验证 (2026-08-21, 本地测试服 weak 探针 A/B)

本地 330gs 用标准库 `weak.Pointer`（Go 1.24+，不参与 GC 可达性）重验，**确认本泄漏真实存在**：

| 测试号 | 战令初始化(`InitPlayerBattlePassDataMgr`) | weak 判定 |
|--------|-------------------------------------------|-----------|
| 29025 | ❌ 未执行 | **COLLECTED**（30s+3次GC 后 weak 失效）|
| 29027 | ✅ 执行(闭包存入 `BattlePassMgr.Mgr[pid]`) | **RETAINED**（weak 仍存活）|

- 登出 → DelPlayer 移除 activePlayers → 30s 排空 + 3 次 `runtime.GC()` → `wp.Value()` 判存活。唯一变量 = 战令初始化，差异即因果。
- **方法更正**：此前 finalizer 探针判的"Player 普遍驻留"多为**探针自造假象**——Player 处于引用循环，finalizer+循环死锁（finalizer 永不触发 + GC 不回收）。最小复现 `/tmp/finalizer_repro`：无 finalizer 循环被回收 / 有 finalizer 循环泄漏 3.6 对象。**凡对象在循环中，禁以 finalizer 判回收**。
- 本泄漏（全局 map 闭包捕获 *Player、登出不清理）经 weak 探针 A/B 实锤，与线上 14,984 条 `battlefield_battle_pass` 一致。
- 验证方法详见 skill: `h5-object-retention`（weak 探针代码、判定流程、陷阱）。
