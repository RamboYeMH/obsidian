# TroopArenaKing updateGuessToGlobal nil map 赋值 panic

- 日期: 2026-08-24
- 来源: 线上日志巡查 (cron, 2026-08-24 15:00, 窗口 10:03~15:03)
- 级别: P0（panic，已被 chanrpc execCb recover 捕获，未崩溃进程）

## 现象

- 2026-08-24 13:09 CST，game529，`assignment to entry in nil map: goroutine 4044 [running, locked to thread]`
- panic 栈：`chanrpc.execCb.func1 (chanrpc.go:446)` → `(*Play).updateGuessToGlobal.func1 (ctl_troop_arena_king.go:3584)` → `(*Play).Run (module.go:585)`
- 当前 5h 窗口 1 条；历史 168h 窗口 0 条 → **新增**（首次出现）

## 根因

`game/play/internal/ctl_troop_arena_king.go:3584`：

```go
for pid, betOld := range oldPre.Betting {
    betnew := newPre.Betting[pid]   // nil map 读取 → 0
    if betOld > betnew {
        newPre.Betting[pid] = betnew // ← 3584: 对 nil map 赋值 → panic
    }
}
```

`newPre` 来自 global 端 ack（`iack.Guess` 中同组所有 GuessArenaData 的 `DeepCopy()`，见 `global/internal/ctl_troop_arena.go:1709-1715`）。Global 端仅在 `pre.PrepareInfo.PlayerId == v.TargetPid` 时初始化 `pre.Betting`（1688-1701），**其余选手的 Prepare.Betting 保持 nil**（从未被下注时）。

触发条件：本地 `oldPre.Betting` 有投注记录（betOld > 0），且 global 返回的对应 `newPre.Betting` 为 nil（betnew=0）→ betOld > 0 成立 → 写入 nil map。

## 修复建议

3584 行前补 nil 保护：

```go
if newPre.Betting == nil {
    newPre.Betting = map[int64]int64{}
}
```

或跳过 `newPre.Betting == nil` 的 Prepare（等价于无需合并，因为 betnew 恒为 0 时本地有更高投注才写入，但目标端无该投注记录，直接丢弃即可——需确认业务语义：global 端 DeepCopy 后此 map 仅内存使用，不落库）。

## 关联

- 本地下注路径有同类保护（ctl_troop_arena_king.go:3480-3481 `if prepare.Betting == nil { prepare.Betting = map[int64]int64{} }`），Global 端 OnP2GTroopArenaKingGuessInfoReq 也有（ctl_troop_arena.go:1690-1692），唯独 play 端 ack 回调合并处缺失。
- 同函数 3560-3569 另有 ack 类型断言失败 warning（`updateGuessToGlobal showStr:`，昨日 18:59 game759 1 条），为独立小问题，仅打 warning 不影响。
