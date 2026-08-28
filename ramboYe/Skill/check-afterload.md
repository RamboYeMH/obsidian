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

# Skill: check-afterload

| 项 | 值 |
|---|---|
| 名称 | `check-afterload` |
| 源文件 | `/home/cc/slgh5/gs/.claude/skills/check-afterload/SKILL.md` |
| 作用域 | 项目 gs |
| 行数 | 71 |
| 用途 | 检测 gdconf 配置表 afterLoad 回调漏注册（漏注册不报编译错，运行时 panic） |

**触发条件（description 字段，决定什么时候自动加载）**

> 检测 gdconf 配置表加载回调（afterLoad 系列）漏注册的问题。用户说「检测 afterload」「查一下 afterload 有没有漏注册」「afterLoad 检查」「配置表回调有没有漏挂」等场景时触发；也适合在新增/修改 gdconf/*_ext.go 的加载回调、或改动 def.go 注册表之后主动跑一次。

---

## 原文

# afterLoad 漏注册检测 skill

gdconf 里每张配置表可以挂一个加载回调（签名 `func(*CsvConf) error`），在表加载后做预处理。回调必须注册到注册表里才会被执行 —— **忘了注册不会报编译错误**（Go 不检查未使用的包级函数），只会在运行时表现为"预处理没生效"，严重时直接 panic。

这个 skill 跑脚本把这类漏网之鱼找出来。

## 执行

```bash
cd /home/cc/slgh5/gs && python3 scripts/check_afterload.py -v
```

- 不带 `-v`：只报高危
- 带 `-v`：连同降噪项（辅助函数、死代码）一起列出，**默认用 `-v`**，这样能一眼看全分类
- `-d <目录>`：指定 gdconf 路径，默认 `gdconf`

退出码：有高危返回 1，干净返回 0。所以直接跑会看到 `Exit code 1`，**这是预期的，不是脚本出错**。

## 输出怎么读

脚本把候选函数分四档，只有最后一档需要处理：

| 分类 | 含义 | 要不要管 |
|------|------|----------|
| 已注册到任一注册表 | 正常挂上了 | 不用管 |
| 未注册但被包内其它函数调用 | 如 `loadReactionSolider`，是被某个 `afterLoadXxx` 内部调的辅助函数 | 不用管 |
| 未注册，且写入的变量无人使用 | 整块死代码，Getter 全仓库没人调 | 不用管，可提示用户考虑删除 |
| **未注册，且变量/Getter 确有调用方** | **真问题** | **要处理** |

### 高危这档为什么危险

afterLoad 回调基本都是往包级 `atomic.Value` 里 `Store` 预处理结果，再由 `GetXxx()` 读出来。回调没注册 → 变量从没写过 → `Load()` 返回 nil → 而这些 Getter 普遍写成非 comma-ok 的类型断言：

```go
arenaMap := ServerEventArenaMap.Load().(map[int32]*EventCfg)  // nil 断言 → panic
```

所以不是"读到空数据"，是**直接 panic**。脚本只在"该变量或读它的函数确实有调用方"时才报高危，就是为了区分真隐患和死代码。

脚本会打印出应写入的变量、读取函数、以及外部调用方的具体文件行号，直接给用户看即可。

## 报出高危后怎么做

1. 打开脚本指出的回调函数，确认它写入了哪个变量
2. 在 `gdconf/def.go` 的 `afterLoadFuncMap` 里补一行 `XxxCfgKey: afterLoadXxx,`
   - 若该回调依赖服务器初始化后的状态，改挂 `afterLoadAfterServerInitFuncMap`
3. 或者反过来：确认调用方已废弃，把回调和 Getter 一起删掉

**不要擅自替用户补注册或删代码** —— 先把结论和风险讲清楚，问用户要怎么处理。补注册会改变配置加载时的行为，属于需要确认的改动。

## 判定口径（供解释结果时参考）

- 候选 = `gdconf/*_ext.go` 里签名为 `func(*CsvConf) error` 的顶层函数。**不靠函数名匹配** —— 仓库里命名不统一（`afterLoad*`、`afterload*`、`after*`、`loadXxxCb` 都有），只认签名
- 注册表 = 所有 `map[string]func(*CsvConf) error` 类型的包级 map，**自动发现不写死表名**。目前有三张：`loadFuncMap`、`afterLoadFuncMap`、`afterLoadAfterServerInitFuncMap`；另外还认 `regAfterLoadFunc()` 这条运行时注册途径
- 取写入变量时会跟 3 层包内调用链，因为 `Store` 常发生在辅助函数里（如 `afterLoadEventCfg → checkEventArena → ServerEventArenaMap.Store()`）

> 曾踩过的坑：早期版本只认 `loadFuncMap` / `afterLoadFuncMap` 两张表，把注册在 `afterLoadAfterServerInitFuncMap` 里的 `afterLoadNpcBandCfg` 误报成高危。如果以后 gdconf 又加了新的注册途径（不是 map 字面量、也不走 `regAfterLoadFunc`），脚本会漏认，需要相应扩展 `collect_registrations()`。**报高危前值得 `git grep` 一下函数名复核**。

## 已知的存量问题（2026-08 基线）

跑出来若和下面一致，说明没有新增问题：

- 高危 1 处：`conf_event_ext.go:11` `afterLoadEventCfg`，`ServerEventArenaMap` 未写入，调用方 `game/wmap/internal/chronicle/chronicleMgr.go:111`。用户已决定**暂时留着**，不用反复提议修
- 死代码 2 处：`afterLoadD2HeroEquipmentCfg`、`afterLoadD2HeroLvCfg`，Getter 无人调用，同样留着

所以重点看**是否冒出这三条之外的新条目**。

---

## 相关

- [[00-Skill 索引]]
- [[Hook]]
