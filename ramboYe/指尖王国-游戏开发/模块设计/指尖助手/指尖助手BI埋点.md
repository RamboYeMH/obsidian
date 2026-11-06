---
类型: 模块设计
模块: 指尖助手
版本: v1054
状态: 已实现待联调
创建日期: 2026-10-23
tags:
  - 设计
  - BI
---

# 指尖助手 BI 埋点（实现 + 评审）

> 需求来源：`Assistant_BI_Tracking.docx`（同目录）。服务端实现见 [[指尖助手服务端设计与实现]]，版本 [[v1054]]。
> 代码分支 `h5_new_tf_v1054_assistant`，改动**未提交**。

## 一、实现位置

| 事件 | 上报点 | 次数保证 |
|---|---|---|
| `Assistant_Settings_Save` | `OnAssistantSaveSettingReq` 写完设置之后（`game/play/internal/ctl_assistant.go`） | 只有解锁校验这一个失败分支，提前 return 时不会上报 |
| `Assistant_Start` | `assistantHost.LogBatch(.., "start")`，由 `Engine.Start` 在预扣成功、建好批次后调用（`assistant/engine.go` Start） | 有批次时再开会被 `ErrCodeAssistantBusy` 拦住；重试和重连都不会再走 Start |
| `Assistant_Start_Fail` | `OnAssistantStartReq` 中 `Engine.Start` 返回非成功时（`ctl_assistant.go`） | 每次开始失败报一次；成功时不报 |
| `Assistant_End` | `assistantHost.LogBatch(.., "end")`，由 `Engine.finish` 调用（engine.go finish） | finish 先 `ArchiveBatch` 清空当前批次，后面的回调都会被 `GetBatch()==nil` 拦掉；正常完成、取消、`abort` 超时都只走这一个出口 |

- BI 组装代码：`game/play/internal/ctl_assistant_bi.go`
- 事件常量和注册表：`game/bi/def/table.go`（`BILogAssistantSettingsSave/Start/StartFail/End`）
- 走 `p.BILogUserAssetNew` → `newBILog`，会自动带上 role_id、server_id、等级、设备这些公共维度，和文档“公共维度不重复定义”一致
- 事件 Key **严格按文档的大小写**（`Assistant_Start`）。项目里其他事件都是小写下划线（如 `radar_level_up`），需要和数据组确认用哪种（见第三章 #1）
- 如果一次请求里全是同步步骤，同一次请求内会先报 Start 再报 End，顺序没问题

## 二、字段

### Assistant_Settings_Save

| 字段 | 类型 | 说明 |
|---|---|---|
| free_card | bool | 免费速办权益（持卡）状态 |
| group_ids | []int | 勾选子事件所属的主事件，按执行顺序去重 |
| cfg_ids | []int | 已保存的子事件 `FingertipAssistantCfg.Id` |
| radar_lineup_ids | []int64 | 情报站讨伐/BOSS 派遣编队 |
| auto_use_stamina | bool | 行动力不足时是否自动用道具 |
| stamina_item_limit | int | 单批次自动用道具上限，0 = 不限 |
| quote_cost | [{type,id,num}] | 保存时按当前状态算出的报价 |

### Assistant_Start

| 字段 | 类型 | 说明 |
|---|---|---|
| batch_id | int64 | 批次 ID |
| charge_type | string | `free_card` 持卡免费 / `item_cost` 道具速办 |
| group_ids / cfg_ids | []int | **实际建了步骤的**主/子事件（勾选里开始时不可执行的已经过滤掉） |
| prepaid_cost | [{type,id,num}] | 预扣消耗，持卡时为空 |

### Assistant_Start_Fail（补充）

| 字段 | 类型 | 说明 |
|---|---|---|
| err_code / err_name | int / string | 失败原因，如 `ErrCodeAssistantPriceChanged`、`NoTask`、`NeedLineup`、`ResultUnconfirmed`、`Busy`、`NotOpen`，或预扣时道具不足 |
| group_ids / cfg_ids | []int | 客户端请求开始的主/子事件 |
| expect_cost | [{type,id,num}] | 客户端预计消耗 |
| need_cost | [{type,id,num}] | 服务端报价（价格变化、预扣失败时有值） |

### Assistant_End

| 字段 | 类型 | 说明 |
|---|---|---|
| batch_id | int64 | 批次 ID |
| charge_type | string | 同上 |
| end_state | string | `finished` 正常完成 / `cancelled` 玩家取消 / `aborted` 异常结束（批次总超时） |
| duration_sec | int64 | 结束时间减开始时间（秒） |
| task_result | [step] | 每个步骤一条：`group_id`、`cfg_ids`、`effective_ids`（已生效、要收费的子事件）、`state`(done/failed/skipped/cancelled)、`reason`(ErrCode)、`done_cnt`、`fail_cnt` |
| done_steps / failed_steps / skipped_steps / cancel_steps | int | 各状态的步骤数 |
| actual_cost / refund_cost | [{type,id,num}] | 实际消耗 / 退还 |
| refund_state | string | `no_refund` / `refunded` |
| awards | [{type,id,num}] | （补充）所有步骤获得的奖励，合并后 |
| costs | [{type,id,num}] | （补充）所有步骤的玩法消耗，合并后：征兵材料、扫荡体力、行动力、自动用掉的道具等，**不含**速办消耗 |
| auto_use_items | [{type,id,num}] | （补充）按授权自动使用的补行动力道具（已经包含在 costs 里，单独列出方便统计） |

## 三、文档设计问题（需要和策划/数据确认）

| # | 问题 | 代码事实 | 处理 / 建议 |
|---|---|---|---|
| 1 | 事件 Key 大小写和项目惯例不一致 | 其他事件都是小写下划线 | 暂时按文档写；如果数数后台要统一，改 `table.go` 里的四个常量就行 |
| 2 | **“预扣钻石 / 实际消耗钻石 / 应退钻石”口径过时** | 2026-10-15 起消耗改成策划配置的道具/资源（`DiamondCost []TypIDVal`，字段名没改） | 改成道具列表 `[{type,id,num}]`；计费方式“钻石速办”改叫“道具速办” |
| 3 | **退款状态“退款中/退款失败”不会出现** | `Engine.finish` 里 `Refund` → `AddAssets` 是**同步**发放，没有异步也没有失败状态；`Charge.Settled` 保证只退一次 | 只有 `no_refund` / `refunded` 两种值；文档里“后续退款异步完成，靠流水核对”的规则不需要。流水可以用道具变更日志 reason `assistant_refund` 核对 |
| 4 | “各事件执行设置（如次数、消耗方式等）”找不到对应字段 | `Settings` 只有：勾选列表、情报站编队、是否自动用道具、道具上限；**没有按事件配置的次数或消耗方式**（次数由玩法自己决定，比如一次领完、打完今日剩余） | 按实际设置上报。策划如果以为有按事件的次数设置，需要对一下需求 |
| 5 | “按主/子事件记录成功/失败/**跳过数量**”做不到按子事件 | 情报站 401~404 会**合并成一个步骤**，`DoneCnt/FailCnt` 是整个步骤的；“跳过”是步骤状态，不是计数 | 按步骤上报，再用 `effective_ids` 标出哪些子事件生效（也就是收费）；跳过数 = 状态为 skipped 的步骤数 |
| 6 | “异常结束”的范围 | 只有**批次总超时**会进入 Aborted。主事件超时只算该步骤 Failed(`ErrCodeAssistantTimeout`)，批次继续跑，最后仍是 `finished` | 分析“超时”要看 `task_result[].reason`，不能只看 end_state |
| 7 | Start 的“主/子事件列表”指勾选的还是实际执行的 | 开始时不可执行的勾选项不会建步骤，也不收费 | 上报实际执行的（和预扣对得上）；勾选全集在最近一次 Settings_Save 里 |
| 8 | Start 失败没有埋点 | 价格变化、没有可执行任务、没选编队、上一轮结果没确认等失败都不上报 | **已补** `Assistant_Start_Fail` |
| 9 | 结果里没有收益 | 批次里有每个步骤的 `Awards`，还有自动用掉的道具 `ConsumeUsed` | **已补** End 的 `awards` / `costs` / `auto_use_items` |
| 10 | GM 命令也会上报 | `assistantRunAll` 走的也是 `Engine.Start` | 测试服的数据要过滤掉 |

## 四、顺手发现

- `def.ReasonIDAssistantUseItem`（assistant_use_item）**定义了但没用**：`assistantTopUp` 调 `UseItem(..., nil)`，自动用道具的流水 reason 是普通的使用道具，没法和手动使用区分。是否要补上待定（这次没改）。
- `ReasonIDAssistantCharge/Refund` 注释里的“钻石”已改成“消耗”（`game/bi/def/const.go`）。
