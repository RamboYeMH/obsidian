---
tags: [etcd, raft, 源码阅读, 学习笔记]
创建日期: 2026-08-04
状态: 进行中
---

# Raft 源码阅读 —— Leader 选举

> 概念铺垫见 [[Raft共识算法]]。本篇对照 `go.etcd.io/raft/v3` 源码（etcd v3.6+ 把 raft 拆成独立仓库/模块，不在 etcd 主仓库里，需要 `go mod download go.etcd.io/raft/v3` 到本地模块缓存查看）。

## 0. 去哪里找代码

```
go.mod / server/go.mod 里搜到依赖版本：go.etcd.io/raft/v3 v3.7.0
本地缓存路径：~/go/pkg/mod/go.etcd.io/raft/v3@v3.7.0/raft.go
```

核心文件是 `raft.go`（状态机主逻辑）+ `log.go`（日志存储与安全性判断）。

## 1. 四种状态（`raft.go:51-54`）

```go
StateFollower StateType = iota
StateCandidate
StateLeader
StatePreCandidate   // 比基础 Raft 论文多的优化，见第 4 节
```

## 2. 状态转换函数（`raft.go:891-971`）

| 函数 | 关键动作 |
|---|---|
| `becomeFollower(term, lead)` | `tick` 指向 `tickElection`（开始计时选举超时） |
| `becomeCandidate()` | **`r.Term + 1`**（任期自增）、`r.Vote = r.id`（给自己投票） |
| `becomePreCandidate()` | 不自增 term、不改 `r.Vote`，只是试探 |
| `becomeLeader()` | `tick` 换成 `tickHeartbeat`；**立刻追加一条空日志**，尽快推进本任期的 commit index |

## 3. 选举超时触发（`raft.go:850-858`, `2046-2054`）

```go
func (r *raft) tickElection() {
    r.electionElapsed++
    if r.promotable() && r.pastElectionTimeout() {
        r.electionElapsed = 0
        r.Step(&pb.Message{From: r.id, Type: pb.MsgHup})
    }
}

func (r *raft) pastElectionTimeout() bool {
    return r.electionElapsed >= r.randomizedElectionTimeout
}
// randomizedElectionTimeout = electionTimeout + rand(electionTimeout)
```

随机化超时是为了避免多个节点同时发起选举导致选票分裂——每个节点实际等待时间不同，谁先到期谁先发起。

## 4. PreVote 机制（论文之外的重要工程优化）

`campaign()`（`raft.go:1025`）有两种模式：

```go
if t == campaignPreElection {
    r.becomePreCandidate()
    voteMsg = pb.MsgPreVote
    term = r.Term + 1   // 只是"打算用"的 term，不真的自增 r.Term
} else {
    r.becomeCandidate() // 真正自增 r.Term
    voteMsg = pb.MsgVote
}
```

**动机**：一个节点被网络分区隔离后会不断超时重试选举，term 持续自增（因为一直选不出来）。等它重新联网，term 已远高于集群实际值。它一发起真实投票请求，会强行把全集群 term 拉高、触发一次没必要的重新选举，哪怕现有 leader 工作正常。

**解法**：先用 PreVote"试探性"问一圈"如果我发起选举你们会投给我吗"，这一步不改 `r.Term`，不会扰动集群。只有拿到多数预投票，才真正 `becomeCandidate()` 并自增 term 发起正式选举。

## 5. 投票授予逻辑（`raft.go:1212-1262`）—— 安全性的核心实现

```go
canVote := r.Vote == m.From ||                     // 本任期已投过同一人（重复消息）
    (r.Vote == None && r.lead == None) ||           // 还没投票且不认为有 leader
    (m.Type == pb.MsgPreVote && m.Term > r.Term)    // 或这是对未来任期的预投票

if canVote && r.raftLog.isUpToDate(candLastID) {
    // 投票
}
```

`isUpToDate`（`log.go:442-445`）：

```go
func (l *raftLog) isUpToDate(their entryID) bool {
    our := l.lastEntryID()
    return their.term > our.term || their.term == our.term && their.index >= our.index
}
```

翻译：候选人最后一条日志的 term 更大，或者 term 相同但 index 更大/相等，才算"不落后"，才有资格当选。这保证新 leader 一定持有所有已 commit 的日志——防止选出数据落后的节点当 leader，对应 [[Raft共识算法#③ 安全性（Safety）]]。

## 6. Leader 租约保护（`raft.go:1100-1112`）

```go
case m.GetTerm() > r.Term:
    if m.GetType() == pb.MsgVote || m.GetType() == pb.MsgPreVote {
        inLease := r.checkQuorum && r.lead != None && r.electionElapsed < r.electionTimeout
        if !force && inLease {
            // 忽略该投票请求，不更新 term
        }
    }
```

如果当前节点最近收到过 leader 心跳（`electionElapsed < electionTimeout`），即使收到更高 term 的投票请求也拒绝响应——防止网络分区后重连的节点靠一次性拉高 term 抢走健康的 leader。是 PreVote 之外的第二层保险（需开启 `checkQuorum`）。

## 读代码的方法论小结

1. 先找**状态定义**（enum/const），搞清楚系统有哪几种状态
2. 找**状态转换函数**（`become*`），看每次转换改了什么字段、切换了哪个 `tick`/`step` 函数指针——这类"状态机 + 函数指针分发"是 Raft 实现的核心模式
3. 找**驱动状态转换的入口**（`tickElection`、`Step`），跟着消息类型（`MsgHup`/`MsgVote`/`MsgApp`...）分支往下读
4. 遇到条件判断（如 `canVote`），逐条对照 Raft 论文的安全性规则，理解"这行代码在防止什么坏情况"

## 待学 / 下一步

- [x] Leader 选举：状态机、随机超时、PreVote、up-to-date 检查、租约保护
- [ ] 日志复制：`MsgApp` / `AppendEntries`，`raftLog` 的 committed/applied/stable 三个指针
- [ ] 快照（Snapshot）机制
- [ ] etcd 如何用 WAL 持久化 Raft 日志
- [ ] MVCC 存储层如何在 commit 之后应用到实际 KV 数据
