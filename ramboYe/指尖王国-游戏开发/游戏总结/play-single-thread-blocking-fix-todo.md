# Play 单线程阻塞风险待修复清单

## 1. 文档目标

`gs/game/play` 的普通消息、异步调用回调、后台任务完成回调和定时器回调共享同一个串行执行循环。本文逐项记录当前静态检查发现的阻塞点和长时间独占点，用于后续修复、评审和线上验证。

重点关注的故障表现：

- `iproto.PlayCharacterLoginReq`、`iproto.PlayCharacterCreateReq` 已由 gsgate 成功投递，但十几分钟后 play 才开始处理；
- play 已开始异步加载玩家，但登录回调长时间不能完成；
- play 队列持续增长，普通业务、登录、创角、定时器和异步回调一起滞后；
- 固定周期、零点、活动阶段切换、批量登录或 DB 异常时延迟显著放大。

> 本清单基于当前代码静态检查。标记为“确定”的项目可以直接从代码证明会阻塞或独占 play 主循环；标记为“高风险”的项目需要结合线上数据规模和耗时指标确定实际影响。

## 2. 执行模型与判定标准

### 2.1 play 主循环是严格串行的

证据：

- `gs/vendor/git.tap4fun.com/fw/tse/core/module/skeleton.go`：`Skeleton.Run`；
- `gs/game/play/internal/module.go`：`Play.Run` 调用 `play.skeleton.Run(closeSig)`；
- `gs/game/play` 未调用 `Skeleton.InitWorker` 或 `Skeleton.Dispatch`。

同一循环串行处理：

1. `s.server.ChanCall`：普通消息；
2. `s.client.ChanAsynRet`：异步 RPC/DB 回调；
3. `s.g.ChanCb`：`skeleton.Go` 完成回调；
4. `s.dispatcher.ChanTimer`：定时器回调。

任何一个 handler/callback/timer 在返回前执行同步等待、超大循环、深拷贝或同步事件链，都会暂停其他三类队列的消费。

### 2.2 同步事件会扩大单个 handler 的执行范围

证据：`gs/vendor/git.tap4fun.com/fw/tse/cmlib/event/event.go`。

`Event.Fire` 最终在当前 goroutine 中逐个执行全部 listener，并非异步派发。因此 `PlayerOnline`、`PlayerNextDay`、`ServerNextDay` 等事件的全部监听器，都属于当前 play 消息或定时器的同步执行时间。

### 2.3 本文风险级别

- **P0**：可直接冻结整个 play，或是十几分钟延迟的直接候选；
- **P1**：在大服、DB 异常或批量事件下可显著独占主线程并制造积压；
- **P2**：放大延迟、缺少保护或缺少观测能力，需配合治理。

---

## 3. P0：确定的同步阻塞点

### TODO-P0-01 冷玩家加载回调中同步读取行军装备包

- [ ] 待修复

**位置**

- `gs/game/play/internal/mplayer/player_mgr.go`
- `PlayerMgr.GetPlayerAsyn`
- `PlayerMgr.playerLoadCb`
- `PlayerMgr.loadMarchEquipBag`

**调用链**

```text
OnPlayCharacterLoginReq
  -> PlayerMgr.GetPlayerAsyn              // 主玩家文档异步加载
  -> DB 回调进入 play.ChanAsynRet
  -> decodePlayerFromDB                   // play 主线程
  -> PlayerMgr.playerLoadCb               // play 主线程
  -> PlayerMgr.loadMarchEquipBag
  -> db.LoadCall                          // 同步等待 DB
  -> loadPlayerAfter / callback
```

**问题**

主玩家文档虽然通过 `db.LoadCb` 异步加载，但异步回调中再次调用 `db.LoadCall`。该同步调用运行在 play 主线程，返回前 play 无法处理任何消息、定时器或其他回调。

Mongo 操作默认执行超时为 1 分钟，但超时只在 DB worker 真正开始执行后生效；进入 DB worker 前的排队时间没有上限。多个冷玩家回调依次执行时，等待会累计。

**影响**

- 直接影响 `PlayCharacterLoginReq` 的 step 4 → step 5；
- 当前冷登录可长时间无响应；
- 后续登录、创角和全部 play 消息一起滞后；
- DB 队列积压时可能超过十几分钟。

**建议修复**

1. 将行军装备包改为异步加载；
2. 玩家主文档与装备包可以并行加载，或使用异步串行状态机；
3. 两份数据准备完成后，只将“组装并挂入 PlayerMgr”的短回调投递回 play；
4. 对同一 `playerID` 的并发加载做 singleflight/请求合并，避免重复 DB 请求；
5. 为完整加载增加端到端 deadline，而不是只依赖 Mongo 执行超时。

**验收标准**

- `GetPlayerAsyn` 的 play 回调链中不存在 `db.LoadCall/SaveCall/DeleteCall/CounterCall`；
- DB 故障或 DB 队列积压时，play 主循环仍可处理其他在线玩家消息；
- 冷登录耗时可拆分为主文档 DB、装备包 DB、play queue wait、decode/init；
- 压测并发冷登录时，play `ChanCall` 最老消息年龄不会持续增长。

---

### TODO-P0-02 支付回调同步调用本地 ACTVMOD

- [ ] 待修复

**位置**

- `gs/game/play/internal/handler.go`：注册 `gspb.BuyGiftPaidReq`；
- `gs/game/play/internal/ctl_d2iap.go`：
  - `OnBuyProductPaidReq`；
  - `AuditPlayerOnBuyProduct`；
  - `LoadPlayerOnBuyProduct`；
  - `loadPlayerCallbackSetEndTime`。

**调用链**

```text
BuyGiftPaidReq
  -> OnBuyProductPaidReq
  -> GetPlayerAsyn callback               // play 主线程
  -> LoadPlayerOnBuyProduct/Audit...
  -> loadPlayerCallbackSetEndTime
  -> play.Call(conf.ACTVMOD, req)          // 本地活动时同步等待
```

跨服活动分支使用 `play.ClusterCall`，最终 NATS 默认约 5 秒超时；本地活动分支使用普通 chanrpc `Call`，没有超时。

**问题**

`chanrpc.Client.Call` 在 `<-chanSyncRet` 上无限等待。以下情况均会冻结 play：

- ACTVMOD 队列严重积压；
- ACTVMOD handler 执行慢；
- ACTVMOD handler 漏掉 `ci.Ret`；
- ACTVMOD 在处理过程中同步反调 play，形成循环等待；
- ACTVMOD 异常但模块通道没有关闭。

**建议修复**

1. 将活动信息查询改为 `AsynCall/ClusterACall`；
2. 支付处理拆成显式状态机，在异步回调中继续结算；
3. 设置明确超时，并定义超时后的幂等重试、补单和告警策略；
4. 不要在持有 play 单线程状态执行权时等待其他业务模块；
5. 框架层考虑禁止或告警“模块主循环内本地同步 Call”。

**验收标准**

- `loadPlayerCallbackSetEndTime` 不再调用同步 `play.Call/ClusterCall`；
- ACTVMOD 停止响应时，play 其他消息仍能处理；
- 支付回调超时后可幂等恢复，不重复发货；
- 增加支付各阶段耗时及超时指标。

---

### TODO-P0-03 每分钟 ServerList 回调同步保存 DB

- [ ] 待修复

**位置**

- `gs/game/play/internal/ctl_serverinfo.go`
- `ServerListCheck`
- `ServerListInfoCb`

**问题代码**

```go
db.SaveCall(conf.DBMOD, play.serverInfo.GetSaveOp(false))
```

`ServerListCheck` 的 NATS 请求本身是异步的，但 `ServerListInfoCb` 运行在 play 主线程，并同步等待 DB 保存。该流程成功后约每分钟再次调度。

**影响**

- DB worker 队列拥塞时，任何一次回调都可冻结 play；
- 周期频繁，属于非维护期也会触发的常态风险；
- 容易与定时存盘高峰叠加。

**建议修复**

- 若后续逻辑不依赖持久化完成，改为 `db.SaveCast`；
- 若必须确认落库，改为异步保存回调，不占用 play 主循环；
- 增加保存失败重试和指标，避免用同步等待保证可靠性。

**验收标准**

- `ServerListInfoCb` 中不存在同步 DB API；
- DB 模块不可用时，server list 刷新失败但 play 主循环不暂停。

---

### TODO-P0-04 战场进入阶段连续执行 3 次同步 DB 清理

- [ ] 待修复

**位置**

- `gs/game/play/internal/ctl_battlefield.go`：`TimerTypeBattlefieldPhaseCheck`，`cspb.BFPBattleIn` 分支；
- `gs/game/play/internal/ctl_battlefield_quest.go`：`BattleFieldQuestClose`；
- `gs/game/play/internal/ctl_battle_field_battle_pass.go`：`BattlePassClose`；
- `gs/game/play/internal/ctl_melting_ice_quest.go`：`MeltingIceClose`。

**同步调用清单**

1. `BattleFieldQuestClose`：1 次 `db.SaveCall(BulkRemoveOp)`；
2. `BattlePassClose`：1 次 `db.SaveCall(BulkRemoveOp)`；
3. `MeltingIceClose`：1 次 `db.SaveCall(BulkRemoveOp)`。

**问题**

战场阶段切换是 play 定时器回调。3 个同步 DB 操作串行执行，期间整个 play 停止消费。每个操作都可能额外等待 DB 队列，并各自具有最长约 1 分钟的 Mongo 执行超时。

**建议修复**

- 阶段切换先更新内存状态和持久化状态机；
- DB 清理改为异步任务；
- 3 个删除可合并为后台批次，但必须分别记录结果；
- 清理失败不得回滚或卡住 play 阶段状态，应通过可重试任务补偿。

**验收标准**

- 战场进入阶段不在 play 主线程同步等待 DB；
- DB 删除超时不会阻塞登录、创角及普通业务；
- 阶段切换和后台清理均有状态与失败重试记录。

---

### TODO-P0-05 战场关闭阶段连续执行 5 次同步 DB 清理

- [ ] 待修复

**位置**

- `gs/game/play/internal/ctl_battlefield.go`：`TimerTypeBattlefieldPhaseCheck`，`cspb.BFPBattleClose` 分支；
- `gs/game/play/internal/ctl_battlefield_quest.go`：`BattleFieldQuestClose`；
- `gs/game/play/internal/ctl_battle_field_battle_pass.go`：`BattlePassClose`；
- `gs/game/play/internal/ctl_battlefield_game_play.go`：`BattleFieldTrainQuestClose`；
- `gs/game/play/internal/ctl_melting_ice_quest.go`：`MeltingIceClose`。

**同步调用清单**

1. `BattleFieldQuestClose`：1 次；
2. `BattlePassClose`：1 次；
3. `BattleFieldTrainQuestClose`：2 次；
4. `MeltingIceClose`：1 次。

合计 5 次同步 `db.SaveCall`，此外还执行在线玩家处理和 `ExpClose` 同步事件链。

**影响**

- 正常 DB 超时累计即可达到数分钟；
- 加上 DB worker 排队，具备超过十几分钟的条件；
- 阶段关闭通常伴随奖励、回服和大量通知，容易与其他重任务叠加。

**建议修复与验收标准**

同 TODO-P0-04，但关闭阶段必须额外验证：奖励、回服、数据清理之间的顺序与幂等性不被异步化破坏。

---

### TODO-P0-06 合服处理在 play 主线程执行大量同步 RPC/DB

- [ ] 待修复或明确隔离策略

**位置**

- `gs/game/play/internal/ctl_merge.go`

**主要同步入口/函数**

- `OnMergeProcessDataReq`：同步 `natsrpc.Call` 获取服务器列表；
- `processLocalData` / `clearUnionMapData` / `closeGlobalActv`：同步调用 WMAP/ACTVMOD；
- `mergeDisbalePfRole`：同步 DB 批量加载，并逐玩家同步调用 PFMOD；
- `mergeRoleInit`、`mergeUnionInit`：同步 `db.CounterCall`；
- `mergeRole`：同步加载玩家/历史数据并循环同步保存；
- `mergeRevertAccount`：同步加载、同步保存；
- `loadSubChatMgr`：同步加载 DB；
- `mergeUnion`：同步加载联盟、科技、红包数据并同步保存多个集合；
- `mergePlayerRank`、`mergeUnionRank`、`mergeUnionMobilizeQuest`：同步 DB；
- `mergeActv`：同步 ACTVMOD；
- `mergeOther`、`mergeMarchEquipBag`、`mergeRecord`：同步 DB；
- `changePlayerMergeDirtyActv`、`changePlayerActv`：同步 ACTVMOD；
- `mergeOneRole`：同步加载并连续同步保存；
- `mergeMailSendInterceptor` 及相关恢复逻辑：同步 DB。

**问题**

合服属于维护场景，但这些操作仍运行在 play 单线程。`MergeMainServerId` 设置后，登录 handler 会返回维护错误；然而登录请求必须先被 play 消费。如果合服 handler 正在执行长同步流程，已经进入队列的登录/创角仍会长时间等待，不能及时收到维护响应。

**建议修复**

优先选择一种明确策略：

1. 合服前在 gate/door 层停止向 play 投递新登录并直接返回维护；
2. 合服数据迁移放入独立模块/进程，不占用在线 play 主循环；
3. play 只维护短状态机，每个 tick 处理有限批次；
4. 所有跨模块和 DB 操作异步化，支持断点、幂等和重试；
5. 合服命令不能把一个完整服务器的数据处理放在单次 handler 内。

**验收标准**

- 合服期间登录能够立即收到维护响应；
- 单次 play 合服回调有明确执行预算；
- 不存在 play 主线程同步 RPC/DB；
- 合服中断后可以从持久化进度恢复。

---

## 4. P1：主线程长时间独占点

### TODO-P1-01 百万级普通消息队列缺少背压、优先级和消息期限

- [ ] 待修复

**位置**

- `gs/game/play/internal/module.go`：`OnInit`；
- `gs/game/conf/game_conf.go`：`ChanRPCLen = 10000`；
- `gs/game/base/skeleton.go`：`NewSkeletonWithChanLen`。

**当前配置**

```go
play.skeleton = base.NewSkeletonWithChanLen(
    conf.PLAYMOD,
    conf.Debug,
    conf.ChanRPCLen*100,
)
```

实际普通消息队列容量为 `10000 * 100 = 1,000,000`。

**问题**

- 登录、创角、普通玩家请求和模块内部通知共用同一个 `ChanCall`；
- 队列内部只有 FIFO，没有登录优先级；
- 没有 enqueue timestamp、deadline、最老消息年龄限制；
- `Cast` 只在队列完全满时返回错误，百万级容量掩盖过载并允许形成十几分钟历史积压；
- 消息恢复消费后仍会处理大量已经失去业务价值的过期请求。

**建议修复**

1. 显著缩小队列容量，使过载可快速暴露；
2. 登录/创角/登出/维护控制消息使用独立高优先级队列；
3. 为客户端请求携带 deadline 或 enqueue timestamp，过期消息快速失败；
4. 设置队列长度、高水位、最老消息年龄告警；
5. 按消息类型做限流和入口背压，避免内部广播淹没登录。

**验收标准**

- 登录请求在普通业务洪峰下仍能在目标 SLA 内开始处理；
- 队列过载时调用方收到明确快速失败，而不是等待十几分钟；
- 能监控每类消息的 queue wait P50/P95/P99/max。

---

### TODO-P1-02 周期存盘在 play 主线程生成保存对象

- [ ] 待修复

**位置**

- `gs/game/dbop/save.go`：`SaveMgr.timerHandler`；
- `gs/game/play/internal/saver.go`：play 所有保存项注册；
- `gs/game/play/internal/types/def.go`：保存周期与分片参数。

**问题**

`timerHandler` 最终使用 `db.SaveCast`，但调用 `doc.GetSaveOps(false)`、遍历集合、检查 dirty、清 dirty、构建 BSON selector、深拷贝业务对象，都在 play 主线程同步执行。

多个管理器每 10 秒、5 分钟或 10 分钟运行。注册时只按管理器序号错开约 1 秒；数据量大或 GC 压力高时，仍会持续占用 play。

**建议修复**

- 每个保存管理器按“最多 N 条”或“最多 X ms”分片；
- 将可安全快照的数据复制到不可变快照，再由后台 goroutine 编码和投递；
- dirty 清理必须在确认快照成功后进行，防止构造失败导致数据丢失；
- 每个 `GetSaveOps` 单独记录扫描数量、dirty 数量、深拷贝耗时、序列化耗时。

**验收标准**

- 单次保存 timer 的 play 主线程占用不超过约定预算；
- 大服全量缓存规模下不产生秒级停顿；
- 保存期间普通消息 queue wait 无明显尖峰。

---

### TODO-P1-03 玩家缓存每 10 分钟全量扫描

- [ ] 待修复

**位置**

- `gs/game/play/internal/saver.go`：注册 `PlayerCacheCollName`；
- `gs/game/play/internal/types/def.go`：`PlayerCacheSaveDura = 10 * Minute`、`PlayerCacheSaveGrad = 1`；
- `gs/game/cache/player.go`：`PlayerCacheMgr.GetSavePlayerCacheOp`；
- `gs/game/cache/player.go`：`LoadPlayerCacheMgr` 使用全量分页加载。

**问题**

每次保存都对 `PCD.Players` 执行完整 `sync.Map.Range`，即使只有少量 dirty 数据。该缓存启动时从数据库全量加载，规模可能接近全服历史玩家数。

**建议修复**

- 维护独立 dirty player ID 集合/队列，不再扫描全表；
- dirty 队列做去重和分片；
- 保存成功后再清 dirty；
- 监控缓存总量、dirty 数量、扫描条数和耗时。

**验收标准**

- 保存复杂度由 O(全部玩家缓存) 降为 O(dirty 玩家数)；
- 10 分钟周期附近不再出现 play queue wait 周期尖峰。

---

### TODO-P1-04 活跃玩家保存遍历并深拷贝玩家大对象

- [ ] 待修复

**位置**

- `gs/game/play/internal/mplayer/player_mgr.go`
- `PlayerMgr.GetSaveOp`
- `PlayerMgr.GetMarchEquipBagSaveOp`

**问题**

- 遍历全部 active player；
- 对待保存玩家执行 `p.SyncPlayerCache()` 和 `p.DeepCopy()`；
- 玩家对象较大，深拷贝会带来明显 CPU、内存分配和 GC 压力；
- 淘汰离线玩家也在同一次遍历中执行。

虽然 `PlayerSaveGrad=10`，仍需控制每次执行预算，不能只依赖 playerID 取模分片。

**建议修复**

- dirty/淘汰分别维护队列；
- 每 tick 限制处理玩家数和执行时长；
- 对深拷贝和 BSON 编码做性能统计；
- 评估缩小持久化快照，避免复制不落库字段。

**验收标准**

- 任意一次玩家保存准备工作不产生长尾主线程停顿；
- 深拷贝条数与耗时可观测。

---

### TODO-P1-05 联盟及联盟缓存保存全量遍历、深拷贝

- [ ] 待修复

**位置**

- `gs/game/play/internal/munion/mgr.go`：`Mgr.GetSaveOps`；
- `gs/game/cache/union.go`：`UnionCacheMgr.GetSaveOps`；
- `gs/game/play/internal/types/def.go`：
  - `UnionSaveDura = 10 * Minute`、`UnionSaveGrad = 1`；
  - `UnionCacheSaveDura = 10 * Minute`、`UnionCacheSaveGrad = 1`。

**问题**

每次遍历所有联盟/联盟缓存；dirty 对象会深拷贝。联盟对象包含成员和多个子管理器时，单次深拷贝成本可能较高。

**建议修复与验收标准**

同 TODO-P1-03/P1-04：改为 dirty 队列、分片处理、记录对象大小与耗时。

---

### TODO-P1-06 其他 SaveMgr 注册项在主线程遍历或深拷贝

- [ ] 逐项评估并修复

**位置与对象**

`gs/game/play/internal/saver.go` 注册的下列 `GetSaveOp/GetSaveOps` 均由 play timer 同步调用，需逐一纳入执行预算：

- TimerMgr；
- NameMgr；
- ChatMgr；
- RankMgr；
- RankHistoryMgr；
- GlobalValue；
- ShopMgr；
- AccuseMgr；
- MessageBoardMgr；
- RallyPrepareMgr；
- UnionTechMgr；
- MobilizeMgr；
- ArenaMgr；
- MarqueeRecordMgr；
- TroopArenaMgr；
- TroopArenaKingMgr；
- KingWar；
- ServerGuiders；
- Banquet；
- GiftTimeMgr；
- VipCustomerServiceMgr；
- UnionShareGift；
- ChangeServerMgr；
- RecommendMgr；
- RecommendedGroupMgr；
- BattlefieldMgr；
- BattlefieldBonusMgr；
- BattlefieldQuestMgr；
- BattlePassMgr；
- MeltingIceQuestMgr；
- ExpGamePlayMgr；
- ActiveGamePlayMgr；
- UnionHongbao；
- RecordMgr；
- UnionVoteMgr。

**要求**

对每一项记录：总对象数、扫描数、dirty 数、复制字节数、主线程耗时、DB 队列投递结果。超过预算的改为 dirty 队列或多 tick 分片。

---

### TODO-P1-07 PlayerOnline 同步执行数十个监听器

- [ ] 待治理

**位置**

- `gs/game/play/internal/ctl_login.go`：`PlayerOnline`；
- `gs/game/play/internal/event.go`：所有 `gdevent.PlayerOnline` listener；
- `gs/vendor/git.tap4fun.com/fw/tse/cmlib/event/event.go`：同步事件执行。

**问题**

`PlayerOnline` 同步执行：

- 玩家在线状态与缓存同步；
- 数十个 `PlayerOnline` listener；
- 跨模块 Cast；
- `NextDayCheck` 及可能的完整 `PlayerNextDay` listener 链；
- 编队、活动、联盟、战场、修复、邮件、任务等初始化与通知。

登录/创角 ACK 虽然在调用 `PlayerOnline` 前发送，但 handler 尚未返回；当前上线逻辑会延迟后续所有 play 消息。

**建议修复**

1. 给每个 listener 增加独立耗时统计；
2. 区分 ACK 前必须完成、ACK 后可延迟、可异步三类逻辑；
3. ACK 后任务拆成有预算的多 tick 队列；
4. 禁止 listener 内同步 RPC/DB；
5. 一次性老数据修复不要永久挂在每次登录事件上。

**验收标准**

- 可输出每个 PlayerOnline listener 的 P95/P99；
- 单个玩家上线后的同步主线程占用满足预算；
- 批量登录时 play 消费能力不会持续低于入队速度。

---

### TODO-P1-08 冷玩家 BSON 解码和完整初始化在 play 主线程执行

- [ ] 待优化

**位置**

- `gs/game/play/internal/mplayer/player_mgr.go`：
  - `decodePlayerFromDB`；
  - `decodingTinySets`；
  - `playerLoadCb`；
- `gs/game/play/internal/ctl_login.go`：`loadPlayerAfter`；
- `mplayer.Player.AfterLoad`；
- `Play.checkPlayerData`、`Play.PlayerInit`、`Play.InitNewAltar`。

**问题**

主玩家文档返回后，BSON marshal/unmarshal、TinyPlay 二次转换、模型 AfterLoad、数据修复和初始化都在 play 回调中同步执行。玩家数据较大、TinyPlay 数据复杂或批量冷登录时，会显著降低主循环吞吐。

**建议修复**

- 将纯数据解码放到 DB worker 或专用后台 worker；
- 只把必须访问 play 状态的短初始化步骤回投主线程；
- 为每个阶段分别计时；
- 初始化拆分后保证玩家在完整 ready 前不会被其他消息访问。

**验收标准**

- 冷玩家加载可分段观测；
- 主线程 decode/init 时间有明确上限；
- 批量冷登录不会造成普通消息长时间饥饿。

---

### TODO-P1-09 服务器零点处理同步遍历全部在线玩家和联盟

- [ ] 待修复

**位置**

- `gs/game/play/internal/ctl_player.go`：
  - `timerNextDayHandler`；
  - `OnPlayerNextDay`；
  - `OnPlayerNextDaySendInfo`；
- `gs/game/play/internal/event.go`：`ServerNextDay`、`PlayerNextDay` listeners；
- 联盟跨天相关实现。

**问题**

单次 timer callback 中依次执行：

1. 全部 `ServerNextDay` listener；
2. 雷达跨天逻辑；
3. 遍历全部在线玩家；
4. 对每个跨天玩家执行 `PlayerNextDayAction`；
5. 对每人同步触发全部 `PlayerNextDay` listener；
6. 给每人发送多条通知和跨模块消息；
7. 联盟跨天逻辑。

在线人数高时，该 timer 会长时间独占 play；如果大量 Cast 使下游队列满，还会产生错误和业务消息丢失。

**建议修复**

- 在线玩家和联盟按批次分多个 tick；
- 每 tick 设置最大玩家数/最大耗时；
- 记录跨天总进度并支持重启恢复；
- 跨天业务保证幂等；
- 登录触发的个人补跨天与服务器全量跨天避免重复重活。

**验收标准**

- 零点期间登录和普通请求仍满足延迟 SLA；
- 可观测跨天待处理数、处理速率和最老任务年龄。

---

### TODO-P1-10 战场阶段切换同步遍历全部在线玩家

- [ ] 待修复

**位置**

- `gs/game/play/internal/ctl_battlefield.go`：
  - `TimerTypeBattlefieldPhaseCheck`；
  - `sendOnlineEntryInfo`；
  - `popShowBattlefieldOnlins`；
  - `AllOnlineEnterBattlefield`；
  - `PlayerBattlefield`。

**问题**

阶段切换中可能多次遍历在线玩家。`AllOnlineEnterBattlefield` 对每个满足条件的玩家执行完整 `PlayerBattlefield`，包含状态检查、缓存同步、通知、跨模块投递和可能的回服/传送逻辑。

**建议修复**

- 阶段切换只更新全局状态；
- 玩家迁移与通知进入分片任务队列；
- 对单个玩家处理设置耗时监控；
- 与 TODO-P0-04/P0-05 的异步 DB 清理分离。

**验收标准**

- 战场切阶段单次 timer callback 保持短小；
- 在线人数增加时切阶段不会线性阻塞 play 主循环。

---

### TODO-P1-11 联盟动员结算存在全联盟、全排行、全成员嵌套遍历

- [ ] 待修复

**位置**

- `gs/game/play/internal/ctl_quest_mobilize.go`：
  - `MobilizeSettlement`；
  - `timerMobilizeSettlement`；
  - `timerMobilizeTick`；
  - `resetMobilize`；
  - `clearMobilizeRank`。

**问题**

结算过程同步执行：

- 遍历全部联盟；
- 每联盟遍历个人排行；
- 发放奖励邮件；
- 再遍历全部联盟和全部成员重置数据；
- 清理全部相关排行榜；
- 遍历在线玩家重新初始化并通知。

在联盟和成员规模较大时，该定时任务可能长时间独占 play。

**建议修复**

使用可恢复的结算状态机，按联盟/成员/排行条目分片；每 tick 有工作预算，邮件发放必须幂等。

**验收标准**

- 结算期间 play queue wait 不产生明显尖峰；
- 重启后可从结算游标继续；
- 不重复发奖。

---

### TODO-P1-12 多个消息处理器直接全量遍历在线玩家或联盟

- [ ] 逐项治理

**已发现位置**

- `ctl_mail.go`：全服邮件筛选、系统通知遍历在线玩家；
- `ctl_tech.go`：远征关闭/进入等事件遍历在线玩家；
- `ctl_recommend.go`：遍历在线玩家；
- `ctl_quest_mobilize.go`：结算后遍历在线玩家；
- `ctl_vip_customer_service.go`：遍历在线玩家；
- `ctl_ark.go`：广播内容按玩家组装并遍历发送；
- `ctl_battlefield_game_play.go`：遍历在线玩家；
- `ctl_battlefield_blessing.go`：遍历在线玩家；
- `ctl_play_server_histroy.go`：遍历在线玩家；
- `ctl_gitf_time_limit.go`：在线玩家与活动记录组合遍历；
- `ctl_marqueerecord.go`：遍历在线玩家；
- `ctl_union_altar.go`：遍历全部联盟；
- `ctl_league_war.go`：活动状态切换遍历全部联盟；
- `ctl_gvg_ladder.go`：遍历全部联盟；
- `ctl_union_chat_msg.go`：泰坦刷新时遍历全部联盟并发送聊天消息；
- `ctl_union_duel.go`：全联盟排序、活跃成员检查和匹配数据组装；
- `ctl_altar_rank.go`：遍历全部 rank；
- `ctl_cmd.go`：多个全服 GM 命令遍历玩家缓存、在线玩家、联盟或排行榜。

**治理原则**

- 入口来自普通消息或 timer 时，禁止单回调处理无上限集合；
- 广播优先使用下游模块提供的批量接口，避免 play 按玩家逐条组装/发送；
- 所有全量任务分片并设置游标；
- GM 命令也不能绕过主线程执行预算；
- 每个入口记录遍历数量和耗时，按线上规模排序治理。

---

## 5. P2：框架与可观测性缺口

### TODO-P2-01 `chanrpc.Call` 没有超时

- [ ] 待修复

**位置**

- `gs/vendor/git.tap4fun.com/fw/tse/core/chanrpc/chanrpc.go`
- `Client.Call`
- `Client.Call0`

**问题**

同步调用发出后直接等待返回 channel，没有 timeout/context。只要被调用方不返回，调用 goroutine永久等待；如果调用 goroutine 是模块主循环，就永久冻结模块。

**建议修复**

- 增加 `CallWithTimeout`/context；
- 模块主循环默认禁止无限同步 Call；
- 超时日志包含调用方、目标模块、消息名、等待时长和双方队列长度；
- 增加同步调用环路检测或开发期 fail-fast。

---

### TODO-P2-02 DB 同步调用的端到端等待无上限

- [ ] 待修复

**位置**

- `gs/vendor/git.tap4fun.com/fw/tse/cmmod/db/dbapi.go`；
- `gs/vendor/git.tap4fun.com/fw/tse/cmmod/db/internal`；
- `gs/vendor/git.tap4fun.com/fw/tse/cmmod/db/op_*.go`。

**问题**

Mongo context timeout只覆盖实际数据库操作，不覆盖：

- 向 DB chanrpc 队列投递的阻塞等待；
- 请求在 DB worker 队列中的等待；
- DB handler 尚未开始执行的时间；
- 返回结果投递异常。

DB 队列容量很大，可能形成长时间历史积压。

**建议修复**

- DB 请求创建时携带 deadline/enqueueAt；
- worker 出队时若已过期则快速失败；
- 同步 API 使用端到端 timeout；
- 暴露 DB queue wait、exec time、总耗时和最老请求年龄。

---

### TODO-P2-03 play 缺少消息入队等待时间统计

- [ ] 待修复

**位置**

- `gs/vendor/git.tap4fun.com/fw/tse/core/module/skeleton.go`；
- `gs/vendor/git.tap4fun.com/fw/tse/core/chanrpc/chanrpc.go`；
- `gs/vendor/git.tap4fun.com/fw/tse/core/util/stat/tpstat.go`。

**问题**

现有 `TPStats` 从事件出队、开始执行 handler 后计时，只能看到执行耗时，无法看到消息在 `ChanCall` 中已经等待了多久。因此可能出现“handler TP99 正常，但客户端延迟十几分钟”。

**建议指标**

- `queue_wait_ms`：按消息类型统计 P50/P95/P99/max；
- `handler_exec_ms`；
- `end_to_end_ms`；
- 四类队列当前长度、容量、高水位；
- 四类队列最老事件年龄；
- 过期丢弃数、队列满拒绝数；
- 按来源模块和消息类型聚合。

**验收标准**

仅通过监控即可区分：入队慢、排队慢、handler 慢、DB/RPC 慢、gsgate 返回慢。

---

### TODO-P2-04 play 缺少主循环卡死 watchdog 和 goroutine dump

- [ ] 待修复

**问题**

发生同步 Call、DB 等待或超大循环时，现有日志通常只能看到最后一条开始日志，不能立即知道主循环卡在哪个栈帧。

**建议修复**

- play 主循环每次完成事件后更新 heartbeat；
- 独立 watchdog goroutine 检查 heartbeat；
- 超过 3~5 秒未推进时输出当前事件信息和全 goroutine stack；
- 分级告警，例如 1 秒 warning、5 秒 error、30 秒 critical；
- 限频，避免卡死期间日志风暴。

---

### TODO-P2-05 play 普通消息、回调和定时器没有执行预算与公平性保证

- [ ] 待设计

**问题**

`select` 只在四类 channel 之间随机选择 ready case：

- 同一类内部 FIFO；
- 没有登录优先级；
- 没有每类消费配额；
- 一个事件内部可以无限工作；
- 大量异步 DB 回调、timer 或普通消息可能长期降低其他类型的处理机会。

**建议修复**

- 先解决所有单事件无限阻塞，再设计优先级/配额；
- 登录、创角、登出和控制消息走高优先级队列；
- 批量任务只能投递小批次 continuation；
- 避免只通过新增 goroutine 破坏玩家状态单线程一致性。

---

### TODO-P2-06 登录与创角缺少统一端到端阶段耗时

- [ ] 待修复

**现有日志**

- step 1~3、7：`gs/game/gsgate/internal/agenthook.go`；
- step 4~6：`gs/game/play/internal/ctl_login.go`。

**阶段判读**

| 时间差 | 含义 | 首要检查 |
|---|---|---|
| step 3 → step 4 | gsgate 已投递，play 尚未开始 handler | play `ChanCall` queue wait、当前卡住的事件 |
| step 4 → step 5 | 异步加载开始，到完整加载和初始化完成 | DB 主文档、DB queue、`ChanAsynRet`、同步装备包 DB、decode/init |
| step 5 → step 6 | 加载完成到 ACK 投递 | 打包耗时、CPU/GC |
| step 6 → step 7 | ACK 已由 play 投递，到 gsgate 收到 | gsgate 队列和发送链路 |

**建议修复**

为每次登录/创角生成 trace ID，统一记录上述阶段、消息入队时间、playerID、sessionID、队列长度和结果码。

---

## 6. 已检查但当前不直接阻塞 play 主线程的设计

以下内容暂不列为阻塞修复项，但应保留失败监控：

1. `gs/game/play` 中发现的 `time.Sleep` 均位于 `play.skeleton.Go` 的后台函数内，未直接睡眠 play 主循环；
2. 普通 `play.Cast`/`chanrpc.Server.Cast` 使用非阻塞投递，目标队列满时返回错误，不会等待；
3. BI 日志通道使用 `select/default`，满时丢弃并记录错误，不阻塞 play；
4. 战报邮件 `Save`、`ClearTimeout`、`FindByTag` 已由 `skeleton.Go` 包裹，DB 同步等待发生在后台 worker；
5. `ctl_scai.go` 中同步模块调用位于独立 `go func`，不会直接堵塞 play，但直接读取 play/player 可变数据存在并发安全风险，应另行审查；
6. GM 主入口通过 `skeleton.Go` 执行命令，命令中的同步 Call/大循环一般不直接占用 play 主循环，但完成回调仍回到 play，且后台并发访问 play 状态存在安全风险；
7. 启服 `load()` 和 `Play.Run` 进入 `skeleton.Run` 前的同步 DB/RPC 会延迟服务就绪，但不会造成运行期消息队列处理中途停顿；
8. `OnDestroy` 的同步 `SaveAll` 属于停服路径，不属于运行期登录排队根因。

---

## 7. 推荐修复顺序

### 第一阶段：先消除可无限/分钟级阻塞

1. TODO-P0-01：冷玩家装备包异步加载；
2. TODO-P0-02：支付回调取消本地同步 ACTVMOD Call；
3. TODO-P0-03：ServerList 回调取消同步保存；
4. TODO-P0-04/P0-05：战场阶段同步清库异步化；
5. TODO-P2-01/P2-02：同步 Call 与 DB 增加端到端超时。

### 第二阶段：补齐证据链和过载保护

1. TODO-P2-03：queue wait 与最老消息年龄；
2. TODO-P2-04：watchdog + goroutine dump；
3. TODO-P2-06：登录/创角 trace；
4. TODO-P1-01：缩小队列并增加登录优先级、deadline、背压。

### 第三阶段：治理周期性和批量 CPU 峰值

1. TODO-P1-03：玩家缓存 dirty 队列；
2. TODO-P1-04/P1-05/P1-06：所有 SaveMgr 项分片；
3. TODO-P1-07/P1-08：上线与冷加载 CPU 链拆分；
4. TODO-P1-09/P1-10/P1-11/P1-12：跨天、战场、结算、广播任务分帧。

### 第四阶段：隔离维护任务

1. TODO-P0-06：合服从在线 play 主循环剥离或状态机化。

---

## 8. 总体验收场景

修复不能只验证功能正确，需要至少覆盖以下故障与压力场景：

1. **DB 不可用**：Mongo 操作超时、DB worker 队列积压时，在线玩家普通消息仍可处理；
2. **ACTVMOD 不响应**：活动查询失败不能冻结 play；
3. **并发冷登录**：大量不同玩家同时首次加载，登录与普通请求 queue wait 受控；
4. **普通消息洪峰**：登录/创角拥有明确优先级和 SLA；
5. **10 分钟存盘周期**：无固定 queue wait、CPU、GC 尖峰；
6. **零点跨天**：在线人数较高时，跨天任务分批完成且普通消息不中断；
7. **战场切阶段**：DB 清理慢、奖励量大、在线人数高时 play 不停顿；
8. **联盟动员结算**：大联盟数、大排行数据下可分批、可恢复、不重复发奖；
9. **合服维护**：登录在入口层快速返回维护，不进入长队列；
10. **可观测性**：仅凭指标和 trace 能定位延迟发生在 gsgate、play queue、handler、DB、RPC 或返回链路。

## 9. 完成定义

全部修复完成需同时满足：

- play 运行期主循环路径不存在同步 DB API；
- play 运行期主循环路径不存在无超时同步跨模块 Call；
- 所有全量任务均有分片、执行预算和可恢复游标；
- 登录/创角具备优先级、deadline 和端到端阶段耗时；
- play 四类队列均具备长度、高水位、queue wait 和最老事件年龄指标；
- watchdog 能在主循环卡住时给出当前消息和 goroutine stack；
- 压测及故障注入中不再出现分钟级登录/创角排队。
