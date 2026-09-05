---
类型: 模块设计
模块: SSR战魂
版本: v1050
状态: 待策划填数值
创建日期: 2026-09-03
tags:
  - 设计
  - 配表说明
  - 战魂
  - 改版
---

# SSR 战魂系统 改版配表变更说明（新版策划案）

对应单号 **H5-11860**，依据 [[《指尖王国》SSR战魂系统策划案新版]]（2026-09-01）与 [[SSR战魂系统策划案新旧差异清单]]。

服务端代码、协议、配表结构**已按新版改完并跑通生成流程**，分支 `h5_new_tf_v1050_ssr_soul`（gs / gdconfig / protocol 三仓库同名）。

> [!info] 这份文档只讲**改版相较旧版动了哪些表**。表结构基础规则（tsv 行版式、`ext[]` 写法、id 编码规则）见 [[SSR战魂-配表说明]]，那份仍然有效，但其中 **`WarSoulNodeRewardCfg` 和 `skin_reward` 两节已作废**。

---

## 一、一句话总览

| 表 | 本次动作 |
|---|---|
| `WarSoulNodeRewardCfg.tsv` | <span style="color:red">**整表删除**</span> |
| `WarSoulHeroCfg.tsv` | 删 `skin_reward` 列 |
| `WarSoulCampNodeCfg.tsv` | <span style="color:red">**新增 `hero_att` 列**</span>、术语改为「高级节点」 |
| `WarSoulLevelCfg.tsv` | 不变 |
| `WarSoulMaterialCfg.tsv` | 不变 |
| `D2ConfigCfg.tsv` | 数值不变，只给 4 条战魂配置的中文说明加了 `【战魂】` 前缀 |
| `i18n/*.tsv` | **本次不动**，多语言文案按新版策划案单独走 |

---

## 二、删除的内容

### 2.1 `WarSoulNodeRewardCfg.tsv` —— 整表删除

**为什么**：新版策划案删掉了旧版 5.5「阵营加成进度奖励」整章（阵营加成每达到一次指定要求领取一次奖励），新版 5.2.11 明确「战魂详情页底部只保留两个页签：属性详情、战魂升级」。

**连带删除**（策划不用管，已改完）：
- 协议 `WarSoulNodeRewardReq` / `WarSoulNodeRewardAck`
- `WarSoulInfo.takenRewards`、`WarSoulInfoAck.canTakeRewards`
- 错误码 31011~31013（号段留空不复用）
- 存档字段 `WarSoul.TakenReward`
- BI ReasonID 626 `war_soul_node_reward`

> 原来那 28 行（14 个 SSR × 2 档，`need_node_count` 3 和 5）里 `reward` 全是 `[]`，没配过真实奖励，删掉零损失。

### 2.2 `WarSoulHeroCfg.tsv` —— 删 `skin_reward` 列

**为什么**：新版删掉了旧版 4.6.6 / 4.6.7「某个 SSR 的全部阵营节点解锁后获得领主档案皮肤」。

改后表只剩 3 列：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | SSR 英雄真实ID（`D2HeroCfg.mutex_id`），<span style="color:red">**硬要求，代码按它直接查表**</span> |
| `level_group` | int | 指向 `WarSoulLevelCfg` 的等级组 |
| `max_level` | int | 战魂等级上限 |

**连带删除**：`WarSoul.SkinGranted` 存档字段、`WarSoulNodeUnlockAck.skinReward`、BI ReasonID 627。

---

## 三、`WarSoulCampNodeCfg.tsv` —— 唯一需要策划重新填数的表

### 3.1 新增 `hero_att` 列（<span style="color:red">重点</span>）

**依据**：新版 4.1.5「觉醒刻印属性**根据 buff 属性加给对应阵营或当前 SSR 英雄**」。旧版是「节点属性一律加给整个阵营」。

`BuffPropertyCfg` 里没有能区分「加阵营 / 加单体」的字段，所以在节点表上开了一列：

| 列 | 作用域 | 说明 |
|---|---|---|
| `camp_att` | **该 SSR 所在阵营（兵种）的全部英雄** | 原有列，行为不变 |
| `hero_att` | **只加给该 SSR 自己** | <span style="color:red">**新增列**</span> |

**一个节点可以两列都配**，各自生效，互不影响。命名和 `WarSoulLevelCfg.hero_att` 一致。

改后完整表头：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 建议 `英雄真实ID × 100 + 序号`；代码不解析，但<span style="color:red">**必须全表唯一**</span> |
| `hero_id` | int | <span style="color:red">**真正决定归属的是这列**</span>，所属 SSR 英雄真实ID |
| `need_level` | int | 达到这个战魂等级才能解锁 |
| `node_type` | int | **1 = 普通节点**（到级自动生效）；**2 = 高级节点**（到级后还要消耗战魂结晶手动解锁） |
| `cost` | ext[] TypIDVal | 高级节点的解锁消耗。普通节点填 `[]` |
| `camp_att` | ext[] Effect | 阵营属性，加给该 SSR 所在阵营的全部英雄 |
| `hero_att` | ext[] Effect | <span style="color:red">**新增**</span>：英雄属性，只加给该 SSR 自己 |

**当前状态**：70 行（14 SSR × 5 节点）的 `hero_att` 全部填的是 `[]`，即行为与改版前完全一致。**要不要用这列、哪些属性归哪列，需要策划定。**

`hero_att` 写法与 `camp_att` 完全一样：

```json
[{"typ":"buff","id":40111,"val":100}]
```
- `typ` 固定 `buff`
- `id` 是 `BuffPropertyCfg` 里的属性 ID，<span style="color:red">**必须 `Scope=2`（英雄作用域）**</span>
- `val` 万分比属性按万分比填，`100` = 1%

### 3.2 术语改名（只改注释，不改数据）

新版把「阵营加成 / 阶段节点」改叫「觉醒刻印 / 高级节点」。表里 `node_type=2` 的注释已从「阶段」改成「高级」，**取值本身没变**，老数据不用动。

### 3.3 <span style="color:red">⚠ 阻塞项：战魂结晶道具还不存在</span>

新版 4.7.5 / 5.3 明确高级节点消耗「**战魂结晶**」，但：

- <span style="color:red">**`ItemCfg.tsv` 里没有「战魂结晶」这个道具**</span>。全表搜「结晶」只有天赋结晶 `20510002`、神兽结晶 `80300002`、特级神兽结晶 `80300003`，都无关
- `WarSoulCampNodeCfg.cost` 现在 70 行全是 `[]`，等于**高级节点现在是免费解锁的**

**需要策划做的**：
1. 在 `ItemCfg.tsv` 建「战魂结晶」道具（含图标、获取途径 `Access`、i18n 名称/描述）
2. 把道具 ID 填进每个 `node_type=2` 节点的 `cost`，例如 `[{"typ":"item","id":<战魂结晶ID>,"val":2}]`
3. 顺便定一下 4.7 / 5.4 的「获取途径」指向哪些礼包或活动

代码侧的消耗与校验是配置驱动的（`CheckDecAssets` / `DecAssets`），**道具建好后只填表就生效，不用改代码**。

---

## 四、`D2ConfigCfg.tsv` —— 数值已符合新版，无需改

| id | Constant | 值 | 新版依据 |
|---|---|---|---|
| 1808 | `WarSoul_Entry_Show_Star_Num` | **8** | 4.2.1 入口显示所需 15 星英雄数 |
| 1809 | `WarSoul_Unlock_Star_Num` | **10** | 4.2.2 正式解锁所需 15 星英雄数 |
| 1810 | `WarSoul_Symbiont_Star_Limit` | **15** | 4.3.3 共生英雄星级门槛 |
| 1811 | `WarSoul_Risk_Star_Threshold` | **13** | 4.11.5 高价值本体提示门槛 |

本次只给这 4 行的中文说明加了 `【战魂】` 前缀，和邻近的 `【家园】``【群聊】` 保持一致。

> 提醒（沿用旧说明）：`WarSoul_Symbiont_Star_Limit` 同时被「满星英雄数量」的统计复用 —— 统计的是星级 ≥ 这个值的英雄数。如果「满星」和「共生门槛」想用不同数值，说一声，拆成两个配置。

---

## 五、多语言文案（本次不处理）

新版策划案里有一批文案改动（一键选择提示收敛成一条、升级确认弹窗三段合一、新增「暂无可用材料 / 请先选择投放材料 / 材料状态已变化，请重新选择」、「阶段节点」改「高级节点」、进度奖励与共生英雄信息相关文案作废等）。

**本次配表变更不动 `i18n/`**，`cn.tsv` 里的 `WarSoul_*` 保持原样（62 条），多语言按新版策划案单独排期处理。

---

## 六、改完表怎么生效

流程不变：策划改完 tsv 提交到 gdconfig，服务端跑一次 `make conf`。**只改数值不用改代码；加/删列要提前说**。

### 自查清单

id 相关（最容易错，沿用旧说明）：

- [ ] `WarSoulHeroCfg.id` 就是英雄真实ID（`D2HeroCfg.mutex_id`）
- [ ] `WarSoulLevelCfg.id` 逐行等于 `level_group × 1000 + level`
- [ ] `WarSoulMaterialCfg.id` 逐行等于 `material_type × 100 + hero_type`
- [ ] `WarSoulCampNodeCfg.id` 全表唯一，且每个英雄的节点数没超过 99

本次改版新增的：

- [ ] <span style="color:red">`WarSoulCampNodeCfg.hero_att` 每行都是合法 JSON，没内容写 `[]` 不要留空字符串</span>
- [ ] <span style="color:red">`hero_att` 里的属性 ID 在 `BuffPropertyCfg` 里存在且 `Scope=2`</span>
- [ ] <span style="color:red">`node_type=2`（高级节点）的 `cost` 填了战魂结晶，不是空的</span>
- [ ] 确认每条刻印属性该进 `camp_att`（加全阵营）还是 `hero_att`（只加自己）
- [ ] 表里已经没有 `skin_reward` 列，没有人再引用 `WarSoulNodeRewardCfg`

> [!warning] 一个踩过的坑
> `ext[]` 类型的列，**tsv 第 6 行（param 行）必须填**（消耗类填 `TypIDVal_P_cspb`，属性类填 `Effect_P`），留空的话 `make conf` 会直接 `sys.exit(1)`，报 `ERROR:parse param`。改版前 `WarSoulHeroCfg.skin_reward` 和 `WarSoulNodeRewardCfg.reward` 就是漏填这一行，导致 `make conf` 一直跑不过；这两列本次已随功能一起删掉，问题消失。新加的 `hero_att` 第 6 行已经填了 `Effect_P`。

---

## 七、和上一版配表说明的差异

[[SSR战魂-配表说明]] 里下面这些内容**已作废**：

- 3.1 `WarSoulHeroCfg` 的 `skin_reward` 字段说明
- 3.4 `WarSoulCampNodeCfg` 里「阶段节点」的措辞、以及「全部节点解锁发 `skin_reward`」的行为描述
- 3.5 `WarSoulNodeRewardCfg.tsv` 整节
- 五、条款对照表里的「4.6 阵营加成规则 → `WarSoulHeroCfg.skin_reward`」「5.5 阵营加成进度奖励 → `WarSoulNodeRewardCfg`」两行
- 六、自查清单里的「`WarSoulNodeRewardCfg.hero_id`」「`WarSoulCampNodeCfg.id / WarSoulNodeRewardCfg.id` 唯一」两条中关于 NodeReward 的部分

其余（等级表、材料表、id 编码规则、材料池过滤逻辑写死在代码里）**仍然有效**。

---

## 八、顺手修掉的一个逻辑 Bug（不涉及配表）

`IsWarSoulActive`（`game/play/internal/mplayer/mhero/war_soul_prop.go`）取共生对象取反了，导致**战魂属性永远不生效**、升级和刻印解锁全部被挡（返回「共生英雄星级不足」）。

**根因**：共生关系里 **SSR 是 follow 一侧，不是 master**。
- `D2HeroCfg` 里非 SSR 英雄 `soldiers_symbiosis` 全是 `0`，SSR 全是 `1`（146 行里 144 行）
- 建立共生时要求 master 不可共生、follow 必须可共生（`ctl_altar.go:108`）
- 所以 SSR 用 `SymbiontMajor` 指向被共生的非 SSR 英雄，自身 `SymbiontMinor` **恒为 0**

线上（h5prod game1）实测印证：玩家 6971 的共生对是 `cfgid=1007037`（mutex 37，非 SSR，持有 `symbiontminor`）← `cfgid=1007053`（mutex 53，**SSR**，持有 `symbiontmajor`）。玩家 7097 同构。

原代码取 `SymbiontMinor` → 对 SSR 恒取到 0 → 恒判为未共生。已改成取 `SymbiontMajor` 指向的被共生英雄，判它的星级。

> [!question] 顺带一个需要策划确认的口径
> 共生建立后，SSR（follow）的 CfgID 会按 master 星级重映射、Awake 也跟随 master，**所以一对共生英雄的星级是一样的**。
> 而 4.2「拥有 N 个 15 星英雄」现在的实现是遍历全部英雄数星级，**一对 15 星共生会被算成 2 个**。也就是说「拥有 10 个 15 星英雄」实际 5 对共生就达成了。
> 这是不是预期？如果要按「不重复计数」算，需要在统计时排除 follow（或排除 master），跟我说一声改。

---

## 关联

- [[《指尖王国》SSR战魂系统策划案新版]]
- [[SSR战魂系统策划案新旧差异清单]]
- [[SSR战魂-配表说明]]（基础规则，部分章节已作废，见第七节）
- 单号：H5-11860
- 分支：`h5_new_tf_v1050_ssr_soul`（gs / gdconfig / protocol）
