# 线上巡查 P0 新增：askActvRefreshGfit 类型断言 panic + TrailTower 注册缺失

日期: 2026-08-23
来源: 线上日志巡查 (elklog triage --profile online --from 5h, 窗口 10:01~15:01 CST)
窗口错误总量: 2,177,873

## 背景

triage P0 显示 46 条 panic 挂在 interface conversion 名下，逐条分类后实为 3 类并存：
34 × not register handler (SyncTrailTowerLineupChangeNtf) + 10 × interface conversion (askActvRefreshGfit) + 2 × GetIslandMgr 空指针。

## P0-A: askActvRefreshGfit 类型断言 panic（新增变体，10 条）

- 消息: `interface conversion: interface {} is *natsutil.ClusterCallAck, not *iproto.P2AGetOneActvInfoByActvIDAck`
- 位置: `game/play/internal/ctl_d2iap_merge.go:158` `(*Play).askActvRefreshGfit.func1`，recover 点 chanrpc.go:447（客户端回调 Cb）
- 时间: 2026-08-23 06:00:08 UTC（14:00:08 CST）同步爆发，跨 10 个实例各 1 条（game220/270/275/32/365/526/554/623/763/796）
- 根因: 回调里 `callAck := ri.Ack.(*iproto.P2AGetOneActvInfoByActvIDAck)` 无 comma-ok 保护。cross=true 走 `natsrpc.ACall(actv 集群)`，14:00 整点集群调用失败返回 `*natsutil.ClusterCallAck`（错误 ack，ri.Err==nil 不拦），断言 panic
- 历史: 家族已知（7d 内 "interface conversion" 496 条，但均为其他 ack 类型如 A2MLostMineInfoAck——同类无保护断言的不同调用点）；本变体（P2AGetOneActvInfoByActvIDAck / askActvRefreshGfit 调用点）7d 历史 0，判定新增
- 修复: `callAck, ok := ri.Ack.(*iproto.P2AGetOneActvInfoByActvIDAck); if !ok { tlog.Warnf(...); return }`
- 触发线索: 14:00:08 整点跨服同步 → 疑似 actv nats 集群在 14:00 有重启/leader 切换，待验证

## P0-D: SyncTrailTowerLineupChangeNtf not register handler（新增，34 条）

- 消息: `msg 2953095231 not register handler:&cspb.SyncTrailTowerLineupChangeNtf{...}`
- 位置: cross1007 独有，recover 点 chanrpc.go:246，爆发于 12:05 CST（04:05 UTC）约 2 分钟内 34 条
- 协议: msgid.def:2286 `2953095231 SyncTrailTowerLineupChangeNtf`，1038 版本即存在（git log -S）；本地分支注册齐全（`game/wmap/dupmaps/trialtower/trialtower.go:201 RegisterRPCMsg`，handler.go:156 OnSyncTrailTowerLineupChangeNtf）
- 发送方: `game/play/internal/ctl_trial_tower.go:1215`、`ctl_world_enemy.go:649`
- 判定: `'"not register handler" AND "trail tower"'` 7d 历史 = 0 → 新增
- 根因（疑似）: 协议为老协议但 cross1007 不识别 → cross1007 部署版本落后（game 服已更新、cross1007 未更新），或 cross1007 分支注册被合并丢失。需对照 cross1007 实际部署版本验证
- 修复: 对齐 cross1007 版本 / 补注册（流程见 h5-protocol-registration skill）

## P0-B: GetIslandMgr 空指针（持续，2 条，非新增）

- `expedition.(*Mgr).GetIslandMgr` mgr.go:813 ← `WMap.OnExpFortScoreReq` ctl_island.go:2135，game289，10:13/10:14 CST
- 7d 历史 28 条（game496/414/679 等，间歇出现）→ 已知间歇问题，低频率观察

## 检索技巧备忘（已补入 h5-online-patrol skill）

1. triage P0 详情只显示首个去重样本，同窗多类并存需直连 ES 逐条分类
2. camelCase 函数名单词检索不可靠（askActvRefreshGfit=0 / GetIslandMgr=2），用全小写短语
3. 裸 msg ID 检索被 skeleton stat 周期日志污染，需组合短语

## 附件

- 分类脚本: /tmp/patrol_panic_classify.py、/tmp/patrol_abc.py、/tmp/patrol_d.py、/tmp/patrol_hist.py
