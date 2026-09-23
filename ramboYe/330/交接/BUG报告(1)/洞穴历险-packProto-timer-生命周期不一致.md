---
created: 2026-07-02
tags: [bug, lost_mine, 洞穴历险, 数据不一致]
severity: high
server: 716
player: 9337723
---

# 洞穴历险：packProto与timerLostMineTicker生命周期判断不一致

## 问题
716服线上玩家9337723点击探索5星洞穴无反应，返回 `ErrCodeLostMineCanExistOnlyOne` (25755)。

## 根因
**actv 的 packProto 和 wmap 的 timerLostMineTicker 对洞穴生命周期结束的判断标准不对称：**

| 模块   | 函数                                           | 删除/重置条件                          |
| ---- | -------------------------------------------- | -------------------------------- |
| actv | `packProto` (logic.go:74)                    | `now > deadline` （不管部队）          |
| wmap | `timerLostMineTicker` (ctl_lost_mine.go:158) | `now > deadline AND troops == 0` |

### 触发场景
1. 玩家创建4★洞穴 → actv:Exist, wmap:entity存在
2. 部队进入洞穴
3. Deadline 到期
4. `packProto` → resetMine (entityid清零) + state=Crashed
5. 玩家看UI"已坍塌"，尝试创建5★洞穴
6. actv检查通过 ✓ → wmap检查失败 ✗（entity还在，部队未退出）
7. 返回 `ErrCodeLostMineCanExistOnlyOne`，客户端无明确提示

## 验证数据 (MongoDB game716)
```
actvID=7656476708005462076:
  mines[2]: cfgid=4004(4★), state=2(Crashed), entityid=0, deadline=0
  → 与 packProto resetMine+Crashed 路径完全吻合
```

## 代码位置
- `game/actv/internal/activity/template/lost_mine/logic.go:74-78` — packProto deadline reset
- `game/wmap/internal/ctl_lost_mine.go:149-223` — timerLostMineTicker
- `game/actv/internal/activity/template/lost_mine/ctl.go:204-211` — actv create check
- `game/wmap/internal/ctl_lost_mine.go:72-89` — wmap create check

## 附加问题
两个 `ErrCodeLostMineCanExistOnlyOne` 检查点的 tlog.Warnf 均被注释：
- `actv/ctl.go:206` → `//tlog.Warnf(...)`
- `wmap/ctl_lost_mine.go:80,86` → `//tlog.Warnf(...)`

## 修复建议
1. **（推荐）** timerLostMineTicker: deadline 到期时无论是否有部队都强制召回并删除
2. packProto: 如果 entity 在 wmap 仍存在则不 reset
3. 恢复被注释的 tlog.Warnf
