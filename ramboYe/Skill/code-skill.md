---
类型: Skill
工具: Claude Code
作用域: 项目 gs
状态: 使用中
创建日期: 2026-08-21
tags:
  - claude-code
  - skill
---

# Skill: code-skill

| 项 | 值 |
|---|---|
| 名称 | `code-skill` |
| 源文件 | `/home/cc/slgh5/gs/.claude/skills/code-skill/SKILL.md` |
| 作用域 | 项目 gs |
| 行数 | 466 |
| 用途 | 本项目 Go 代码规范：结构体访问封装、作用域控制、设计模式、SOLID |

**触发条件（description 字段，决定什么时候自动加载）**

> 本项目 Go 代码规范（结构体访问封装、作用域控制、设计模式、SOLID 原则）。编写、整理、审查本仓库 Go 代码时读取。

---

## 原文

> **格式类约束已下沉到工具层，本文件不再重复。**
> 行长、导入分组、导出注释、重复代码由 `./scripts/check-local.sh` 机械判定。
> 本文件只保留 **需要看上下文做判断、linter 判不了** 的规则。
>
> 改完代码跑：`./scripts/check-local.sh`（只查你本次改动，通常 10~20 条以内）

## 规则详解

### 规则 1：结构体字段访问

- 同一字段链访问**超过 2 次**，必须声明短变量
- 字段访问必须通过 **Get 方法**，不得直接访问字段
- 嵌套字段必须在**原始对象上封装访问方法**，不暴露中间层

```go
func (rt *RallyTroop) GetActionCtx() *ActionCtx {
    return rt.GetRallyCtx().ActionCtx // 封装在 rt 上，不暴露中间层
}

func foo(rt *RallyTroop) {
    state := rt.GetRallyState() // 超过2次访问先取短变量
    if state == StateA {
        doSomething(state)
    }
}
```

---

### 规则 2：变量作用域控制

即获取即判断的变量，必须写在 `if` 初始化子句中。
如果引用只在一处引用则放在最小作用域中

```go
if r := wmap.PackRally(troop, true); r != nil {
    // r 的作用域仅限 if 块
}
```
错误演示
```go
occupyUnionID := mine.GetOccupyUnionID()

if pc.GetUnionID() == occupyUnionID {
tlog.Infof("pTroopArriveIceMorrowMineAttack ownerID:%v unitID:%v occupyUnionID:%v same union", unit.OwnerInfo().GetID(), unit.GetID(), occupyUnionID)
return cspb.ErrCodeNotSameUnion
} 
```
正确演示
```go
if occupyUnionID := mine.GetOccupyUnionID(); pc.GetUnionID() == occupyUnionID {
tlog.Infof("pTroopArriveIceMorrowMineAttack ownerID:%v unitID:%v occupyUnionID:%v same union", unit.OwnerInfo().GetID(), unit.GetID(), occupyUnionID)
return cspb.ErrCodeNotSameUnion
} 
```

---

### 规则 3：case 多值换行格式

多值相同 `case` 每个值独占一行；单值正常书写。

```go
case
    AAA,
    BBB,
    CCC:
    逻辑语句

case DDD:
    逻辑语句
```

---

### 规则 4：封装操作方法

- slice 字段添加元素必须通过封装的 **Add 方法**
- 重置/清空数据必须封装为 **resetXXX 方法**
- 不允许在调用处散落 append / 赋值语句

```go
func (rt *RallyTroop) AddMember(member *Member) {
    rt.Members = append(rt.Members, member)
}

func (rt *RallyTroop) resetState() {
    rt.State = 0
    rt.ActionCtx = nil
}
```

---

### 规则 5：消除重复代码 → 已下沉到工具层

由 `dupl` 判定（阈值 150 token），跑 `./scripts/check-local.sh` 即可。
不必再靠人工记忆——实测存量 `game/wmap/internal` 有 22 处重复未被这条文字规则拦住。

---

### 规则 6：初始化函数直接返回字面量

```go
func NewStubUnit(coord geo.Coord, eType cspb.MapUnitType) IUnit {
    return &Unit{Coord: coord, Type: eType}
}
```

---

### 规则 7：超过 3 个参数必须换行

函数签名与调用均适用。**保留在指令层**：`lll` 只管行长 140，管不到「参数超过 3 个即使不超长也要换行」。

```go
func doSomething(
    a int,
    b string,
    c bool,
    d float64,
) {}

doSomething(
    1,
    "hello",
    true,
    3.14,
)
```

---

### 规则 8：返回值规范

能用 errorCode 表达的用 errorCode，否则用 bool，不用 `error` 包装简单成功/失败。

```go
func joinRally(rt *RallyTroop) ErrCode {
    if !valid { return ErrInvalid }
    return ErrOK
}
```

---

### 规则 9：RallyTroop 统一缩写为 rt

```go
func (rt *RallyTroop) DoSomething() {}
```

---

### 规则 10：客户端消息必须使用新建对象

map、slice 字段必须重新初始化，禁止直接引用内部数据结构。

```go
func (rt *RallyTroop) PackMsg() *pb.RallyInfo {
    members := make([]*pb.Member, len(rt.Members))
    for i, m := range rt.Members {
        members[i] = m.Clone()
    }
    extra := make(map[string]string, len(rt.Extra))
    for k, v := range rt.Extra {
        extra[k] = v
    }
    return &pb.RallyInfo{Members: members, Extra: extra}
}
```

---

### 规则 11：用工厂函数统一创建对象（创建型）

同一接口有多种实现时，必须通过**工厂函数**创建，禁止在业务层直接 new 具体类型。

```go
type IHandler interface {
    Handle()
}

func NewHandler(t HandlerType) IHandler {
    switch t {
    case TypeA:
        return &HandlerA{}
    case TypeB:
        return &HandlerB{}
    default:
        return &DefaultHandler{}
    }
}
```

---

### 规则 12：用策略模式替代 if/switch 业务分支（行为型）

同一操作有多套逻辑时，必须抽象为**策略接口**注入执行，禁止在函数体内用大段 if/switch 堆砌业务分支。

```go
type IStrategy interface {
    Execute(ctx *Context)
}

type Executor struct {
    strategy IStrategy
}

func (e *Executor) SetStrategy(s IStrategy) {
    e.strategy = s
}

func (e *Executor) Run(ctx *Context) {
    e.strategy.Execute(ctx)
}
```

---

### 规则 13：用观察者模式解耦状态变更通知（行为型）

对象状态变更需通知多个模块时，必须通过**观察者/事件订阅**广播，禁止在变更处直接调用其他模块函数。

```go
type IEventHandler interface {
    OnEvent(event Event)
}

type EventEmitter struct {
    handlers []IEventHandler
}

func (e *EventEmitter) AddHandler(h IEventHandler) {
    e.handlers = append(e.handlers, h)
}

func (e *EventEmitter) emit(event Event) {
    for _, h := range e.handlers {
        h.OnEvent(event)
    }
}

func (e *EventEmitter) complete() {
    e.setState(StateComplete)
    e.emit(EventComplete) // 只调用 emit，不直接耦合其他模块
}
```

---

### 规则 14：用状态机管理对象生命周期（行为型）

有明确生命周期的对象，状态流转必须通过**状态机**管理，每个状态封装为独立对象，禁止在业务函数中散落 `if state == X` 的跳转逻辑。

```go
type IState interface {
    OnEnter(ctx *Context)
    OnExit(ctx *Context)
    CanTransitTo(next StateType) bool
}

type StateMachine struct {
    current IState
}

func (sm *StateMachine) TransitTo(next StateType) bool {
    if !sm.current.CanTransitTo(next) {
        return false
    }
    sm.current.OnExit(sm.ctx)
    sm.current = NewState(next) // 结合规则 11，工厂创建
    sm.current.OnEnter(sm.ctx)
    return true
}
```
### 15.新增结构体属性值调用
# Golang Struct Access Rule

在 Go 代码中：

- 所有结构体字段禁止直接访问
- 必须统一通过 Getter / Setter 方法进行读写
- 即使字段是导出的(public)也优先使用方法访问
- 新增字段时自动生成对应的 GetXXX / SetXXX 方法
- 业务逻辑中禁止：
  user.Name
- 必须改为：
  user.GetName()

赋值时禁止：
  user.Name = "test"

必须改为：
  user.SetName("test")

#### Get 方法内必须做 nil 初始化

map / slice / 指针字段的 Get 方法，字段为 nil 时要**先初始化再返回**，不能只返回 nil。

```go
func (ab *AreaBattle) GetUnionCenterBuilds() map[int32]int32 {
    if ab.UnionCenterBuilds == nil {
        ab.UnionCenterBuilds = make(map[int32]int32)
    }
    return ab.UnionCenterBuilds
}

// 调用方直接用，不做 nil 判断
areaBattle.GetUnionCenterBuilds()[key] = val
```

**防的是什么**：构造函数 `NewXxx()` 里初始化过不代表安全——从 DB 反序列化出来的**旧数据**该字段可能为空，调用方直接写会 panic。这条不能靠 linter，必须靠人写。

#### Accessor 文件规范

Get/Set 方法统一放到对应的 `accessor_<StructName>.go`，没有就新建。
路径形如 `game/wmap/internal/maritime_trade/accessor_MaritimeFleet.go`。由 `go generate` 生成，也可手写。

---

## 设计原则（SOLID）

> 规则 11~14 是具体「设计模式」，规则 16~20 是其背后的「设计原则」。整理/审查代码时，判断一处扇出分支该不该重构，以本组原则为准绳。

### 规则 16：开闭原则 OCP —— 对扩展开放，对修改关闭

新增一种类型/分支时**不应回去改动已有主流程**。用「注册表 + 统一入口」取代散落的 `switch`：新增类型只在登记处加一条，主流程查表分发保持不变。参数签名不匹配时用**适配器/闭包转接**，不改已有实现（防腐层）。

```go
// ❌ 对修改开放：每加一种类型都要改这个 switch
switch t {
case TypeA: doA()
case TypeB: doB()
}

// ✅ 对扩展开放：主流程不动，新增类型只在别处 register 一条
var reg = map[Type]func(*Ctx){}
func register(t Type, fn func(*Ctx)) { reg[t] = fn }
func dispatch(t Type, c *Ctx) {
    if fn, ok := reg[t]; ok { fn(c) } // 主流程恒定
}
// 老函数签名不一致时用适配器转接，不改老函数：
func adapt(fn func(X)) func(*Ctx) { return func(c *Ctx) { fn(c.X) } }
```

本仓库范式：`game/wmap/internal/mapunit_registry.go`（`registerMapUnit` + 启动自检 + `defendHook` 适配器）、`ctl_march_help.go:83` `registerMarchActionChecker`、`ctl_march_help.go:137` `registerMarchCheckStage`。
配套：回调入参用**参数对象**（如 `GiveUpDefendArgs`），后续加数据只往结构体加字段，签名不变、登记点零改动。

---

### 规则 17：里氏替换 LSP —— 接口的任一实现可无差别替换

同一接口的所有实现必须遵守接口契约，能在不改调用方的前提下互换：

- 不得削弱前置条件、加强后置条件；
- 不得在个别实现里做接口未约定的 `panic` / 返回哨兵值 / 额外副作用；
- `GetXXX()` 即使字段为 nil 也应返回可用零值（呼应规则 1/15），不能某些实现会 panic、某些不会。

```go
// ❌ 某实现违反契约，替换后调用方意外崩溃
func (x *SpecialUnit) GetMembers() []Member { panic("not supported") }

// ✅ 所有实现行为一致、可安全替换
func (x *SpecialUnit) GetMembers() []Member {
    if x.Members == nil { return nil }
    return x.Members
}
```

---

### 规则 18：单一职责 SRP —— 一个类型/函数只有一个变更原因

职责混杂的大 struct / 大函数按职责拆分（校验、打包、分发各归各处）。一个函数只做一件事；一个 `resetXXX` 只负责清理。判断标准：若「因为 A 变」和「因为 B 变」都要改同一处，说明该拆。

```go
// ✅ 校验、组装、分发分离（参考 OnNewMarchReq 拆分）
code := wmap.runMarchChecks(startUnit, targetUnit, req) // 校验
msg  := wmap.buildM2PNewMarchReq(req, targetUnit)       // 组装
wmap.CastByPID(..., msg)                                // 分发
```

---

### 规则 19：接口隔离 ISP —— 小接口，按能力拆

定义面向使用场景的**小接口**，不要逼实现者实现用不到的方法。Go 惯例：按「能力」拆细分接口，调用方按需断言到最小能力接口，而非塞一个大而全的接口。

```go
// ✅ 能力细分接口（参考 munit）：ITroopUnit / IUnitBuildTroop / IScoutableUnit ...
type IScoutableUnit interface { GetScoutInfo() *ScoutInfo }
// 调用方只依赖它需要的最小能力
if s, ok := melem.UnitToIScoutableUnit(u); ok { use(s) }
```

---

### 规则 20：依赖倒置 DIP —— 依赖抽象，不依赖具体

高层逻辑依赖**接口/回调**，不依赖具体实现；具体实现通过工厂（规则 11）/注册表（规则 16）/注入提供。主流程里不直接 `new` 或点名调用某个具体玩法函数。

```go
// ❌ 高层直接依赖具体实现
func (w *WMap) giveUpDefend(u ITroopUnit) { w.giveUpDefendOnUnionGvg(u) /* ...一堆具体调用 */ }

// ✅ 高层只依赖抽象（注册表里的 hook），具体实现在别处注入
func (w *WMap) giveUpDefend(u ITroopUnit) {
    if spec, ok := getMapUnitSpec(u.GetDefendCtx().Type); ok && spec.GiveUpDefend != nil {
        spec.GiveUpDefend(w, GiveUpDefendArgs{Unit: u, Defend: u.GetDefendCtx()})
    }
}
```

---

### 规则 21：新增结构体必须加注释（仅剩 linter 管不到的部分）

- 导出类型/方法的注释 → **已下沉**，`revive` 判定
- **非导出 struct 的类型注释** → linter 不管，靠这条
- **字段行内注释** → linter 不管，靠这条：字段含义不是从字段名一眼能看出的（单位、特殊值含义、可为空的条件），必须在字段后加行内注释

下面这个例子正是 linter 覆盖不到的情形——`beAttackPreparedArgs` 是非导出类型，`revive` 不会管它。

```go
// beAttackPreparedArgs 被攻击预警回调的入参（参数对象）
type beAttackPreparedArgs struct {
    Start       munit.IUnit
    SelfUnionID int64 // Start 所属玩家的联盟 ID，非玩家或无联盟时为 -1
    CampID      int32 // Start 所属玩家的阵营 ID，无阵营时为 0
}
```

---

## 审查清单

**先跑 `./scripts/check-local.sh`**，通过后再逐条看下面这些 linter 判不了的。

1. [ ] 字段访问 > 2 次已声明短变量，通过 Get 方法，嵌套字段已封装
2. [ ] 即获取即判断的变量已写入 if 初始化子句
3. [ ] 多值相同 case 已换行合并
4. [ ] slice Add / resetXXX 已封装，无散落操作
5. ~~无重复代码~~ → 工具层 `dupl` 判定
6. [ ] 初始化函数直接 return 字面量
7. [ ] 超过 3 参数已换行
8. [ ] 返回值使用 errorCode 或 bool，而非 error
9. [ ] RallyTroop 变量统一命名为 rt
10. [ ] 客户端消息 map/slice 均已重新初始化
11. [ ] 多实现对象通过工厂函数创建，业务层无直接 new 具体类型
12. [ ] 多分支业务逻辑抽象为策略接口，无大段 if/switch 堆砌
13. [ ] 状态变更通知通过观察者广播，不直接耦合其他模块
14. [ ] 有生命周期的对象使用状态机管理，状态跳转不散落在业务函数中
15. [ ] 结构体字段访问用Get,Set方法
16. [ ] 开闭原则：按类型/分支扇出用注册表+统一入口，新增类型不改主流程；签名不匹配用适配器转接、入参用参数对象
17. [ ] 里氏替换：接口各实现遵守同一契约、可无差别替换，无个别实现 panic/返回哨兵值
18. [ ] 单一职责：类型/函数只有一个变更原因，职责混杂的大 struct/函数已拆分
19. [ ] 接口隔离：定义按能力拆的小接口，调用方按需断言最小能力接口
20. [ ] 依赖倒置：高层依赖接口/回调，具体实现经工厂/注册表/注入提供，主流程不点名 new/调具体实现
21. [ ] **非导出** struct 已加类型注释，含义不明显的字段已加行内注释（导出的由 `revive` 判定）

---

## 相关

- [[00-Skill 索引]]
- [[Hook]]
