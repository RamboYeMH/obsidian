---
tags: [etcd, 架构设计, 源码阅读, 状态机, 学习笔记]
创建日期: 2026-08-04
状态: 进行中
---

# etcd 启动流程与双循环架构

> 从 `main()` 入口一路追到核心运行循环，看作者是怎么把这个框架搭起来的。
> 前置概念见 [[Raft共识算法]]，Raft 内部实现见 [[Raft源码-Leader选举]]。
> **本篇是整个 etcd 架构的骨架，也是自己写类似框架最值得抄的部分。**

## 一、启动调用链

```
main()                                    server/main.go:30
 └─ etcdmain.Main(os.Args)                server/etcdmain/main.go:25
     └─ startEtcdOrProxyV2(args)          server/etcdmain/etcd.go:43   // 解析配置、检查 data-dir
         └─ startEtcd(&cfg.ec)            server/etcdmain/etcd.go:180
             └─ embed.StartEtcd(cfg)      server/embed/etcd.go:110     // ★ 真正的骨架搭建
```

### `embed.StartEtcd` 的搭建顺序（`server/embed/etcd.go`）

| 步骤 | 代码位置 | 做什么 |
|---|---|---|
| 1 | `etcd.go:142` `configurePeerListeners` | 先占住节点间通信端口 |
| 2 | `etcd.go:150` `configureClientListeners` | 先占住客户端端口 |
| 3 | `etcd.go:260` `etcdserver.NewServer(srvcfg)` | 组装内部状态：raft node、WAL、存储 |
| 4 | `etcd.go:280` `e.Server.Start()` | 启动后台运行循环 |
| 5 | `etcd.go:282` `e.servePeers()` | 把 peer 端口接上 raft 通信 |
| 6 | `etcd.go:284` `e.serveClients()` | 把 client 端口接上 gRPC/HTTP API |

**通用套路**：先把网络端口占住（listener）→ 再组装内部状态 → 再启动后台循环 → 最后才把端口"接上"业务逻辑对外服务。很多 Go 服务都是这个结构，写自己的框架可直接照搬。

## 二、`Start()` 的真正心脏

`EtcdServer.Start()`（`server/etcdserver/server.go:529-541`）本身只是挂了一堆后台任务（`purgeFile`、`monitorClusterVersions`、`LinearizableReadLoop` 等）。真正的心脏在 `s.start()` 末尾：

```go
// server/etcdserver/server.go:594
go s.run()
```

## 三、★ 全景：两个循环 + 一个队列

```
              raftNode 循环                        EtcdServer 循环
        (server/etcdserver/raft.go:177)      (server/etcdserver/server.go:841)
                     │                                   │
   ticker ──────────►│                                   │
   raft.Ready() ────►│ ── ap(toApply) ──► applyc ───────►│──► applyAll()
                     │                                   │       │
                     │  持久化 WAL / 发网络消息            │       └─► 写入 MVCC 存储
                     │  r.Advance()                      │
```

## 四、循环一：raftNode 循环（`server/etcdserver/raft.go:177-341`）

```go
for {
    select {
    case <-r.ticker.C:
        r.tick()                // 驱动 raft 内部时钟（选举超时/心跳）
    case rd := <-r.Ready():     // raft 库"吐出"待处理的工作
        ...
    case <-r.stopped:
        return
    }
}
```

### ★★ Ready 模式 —— 最值得偷师的设计

**raft 库本身不做任何 I/O**。它不碰网络、不碰磁盘、不看时钟，是一个纯粹的状态机：

- 调 `Tick()` 推进时间
- 调 `Step(msg)` 喂消息进去
- 通过 `Ready()` 告诉外层"现在该做这几件事"
- 处理完调 `Advance()`（`raft.go:331`）表示"这批处理完了，给我下一批"

| Ready 字段 | 含义 | 谁来执行 |
|---|---|---|
| `rd.Entries` | 新日志，需要持久化 | 外层写 WAL |
| `rd.HardState` | term/vote/commit，需要持久化 | 外层写 WAL |
| `rd.Messages` | 要发给其他节点的消息 | 外层走网络发送 |
| `rd.CommittedEntries` | 已提交、可应用的日志 | 外层应用到状态机 |
| `rd.Snapshot` | 需要保存的快照 | 外层落盘 |

**为什么这样设计**：把 I/O 剥离后，raft 算法变成纯函数式状态机——输入消息、输出决策，无副作用。于是可以**确定性地测试**：喂一串消息进去断言输出，不需要起网络、不需要磁盘、不需要 sleep。这就是 raft 库里能有 `testdata/` 数据驱动测试的原因。

### 执行顺序有讲究：leader 与 follower 相反

```go
// raft.go:240-243  leader 先发消息
if islead {
    r.transport.Send(r.processMessages(rd.Messages))
}
// raft.go:249  快照必须先于其他数据保存
r.storage.SaveSnap(raftSnap)
// raft.go:256  再持久化 HardState + Entries 到 WAL
r.storage.Save(rd.HardState, rd.Entries)
// raft.go:287  写入内存中的 raftStorage
r.raftStorage.Append(rd.Entries)
// raft.go:324  follower 落盘之后才发消息
r.transport.Send(msgs)
```

- **Leader 先发送、后落盘**（`raft.go:237-243`，注释引用 Raft 论文 10.2.1）：发消息与本地写盘并行，一次写入延迟 = `max(本地磁盘, 网络+远端磁盘)` 而非两者相加。实打实的性能优化。
- **Follower 必须先落盘、后回复**（`raft.go:299-324`）：回复 `MsgAppResp` 等于向 leader 承诺"我已安全存下这条日志"，leader 据此推进 commit index。若未落盘就回复，follower 一崩溃数据就丢，而 leader 已认为提交——**一致性直接被破坏**。

## 五、循环二：EtcdServer 主循环（`server/etcdserver/server.go:841-855`）

```go
for {
    select {
    case ap := <-s.r.apply():       // 收 raft 循环丢过来的已提交日志
        f := schedule.NewJob("server_applyAll", func(ctx) { s.applyAll(&ep, &ap) })
        sched.Schedule(f)            // 丢给 FIFO 调度器串行执行
    case leases := <-expiredLeaseC:  // 处理过期 lease
        s.revokeExpiredLeases(leases)
    case err := <-s.errorc:
        return
    case <-s.stop:
        return
    }
}
```

用 `FIFOScheduler`（`server.go:764`）而非直接调用，是为了保证**应用顺序严格串行**——正是"状态机复制"的核心要求：所有节点按相同顺序执行相同操作。同时 `applyAll` 异步执行，不阻塞 raft 循环处理下一批 Ready。

## 六、★ 为什么要拆成两个循环

etcd 架构上最重要的一次解耦：

- **raft 循环**只关心「共识」：日志是否安全持久化、消息是否发出、commit index 推进到哪
- **apply 循环**只关心「业务」：把已达成共识的操作真正写进 KV 存储

中间用 `applyc` channel 解耦。好处：apply 慢（磁盘抖动、大事务）不会拖住共识流程，raft 可继续复制后面的日志。

**关键推论：committed ≠ applied**。一条日志已被多数派确认（committed），但可能还没应用到 KV（applied）。这个区别在理解**线性一致读（linearizable read）**时至关重要。

## 七、自己写框架可直接抄的三点

1. **纯状态机 + Ready 模式**：核心算法不碰 I/O，通过"待办清单"结构体与外层通信 → 可确定性测试
2. **双循环 + channel 解耦**：共识层与业务层分离，慢的一方不拖累快的一方
3. **FIFO 串行调度**：需要严格顺序的地方用调度器，而非依赖调用顺序

## 待学 / 下一步

- [x] 启动流程 `main` → `embed.StartEtcd` → 双循环
- [ ] `etcdserver.NewServer` 内部：raft node、WAL、bbolt backend 如何组装
- [ ] 一次 `Put` 请求的完整生命周期（穿过两个循环）
- [ ] `applyAll` 如何把日志写入 MVCC 存储
- [ ] 线性一致读：ReadIndex 机制与 `committed != applied` 的关系
- [ ] WAL 持久化格式与崩溃恢复
