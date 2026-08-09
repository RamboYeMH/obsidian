---
name: obs
description: 用户说「obs」「笔记」「我的库」时使用。定位并操作 Obsidian 笔记库 /Users/rambo/obsidian —— 查找笔记、新增笔记、整理分类、按约定提交。任何涉及读写该笔记库的请求都先读本 skill,不要凭猜测放置文件或编造路径。
---

# obs —— Obsidian 笔记库

「obs」= `/Users/rambo/obsidian`(**不是** OBS Studio)。

## 目录结构

```
/Users/rambo/obsidian/          # git 仓库根 + vault 根
├── .obsidian/                  # vault 配置(插件、工作区布局)
├── .claude/skills/obs/         # 本 skill
└── ramboYe/                    # 全部笔记都在这里
    ├── AI试卷排版工具/
    ├── Claude/
    ├── Go语言学习/
    ├── 工具/           └── supervisor/
    ├── 技术学习/       └── etcd/
    ├── 指尖王国-游戏开发/
    │   ├── Bug/  备份/  工作日志/  模块设计/  模板/  游戏总结/  版本/
    ├── 操作系统/
    ├── 设计模式/
    ├── assets/                 # 图片等附件
    ├── MonoDB 导入.md
    └── 密码.md
```

`ramboYe/` 也被单独注册成了一个 vault(嵌套 vault),`~/Documents/Obsidian Vault` 是空的默认库 —— 两者都忽略,一律用仓库根 `/Users/rambo/obsidian`。

## 约定

**新笔记放哪** —— 归到 `ramboYe/` 下已有的分类目录里;确实没有匹配分类时,先问用户再建新目录,不要往仓库根或 `ramboYe/` 根上扔散文件(历史上有过「清理根目录冗余文件」的提交)。

**文件名** —— 中文,空格照常用,不加日期前缀(如 `游戏总结大纲.md`、`MonoDB 导入.md`)。

**附件** —— 图片等放 `ramboYe/assets/`,笔记里用 Obsidian 的 `![[文件名]]` 引用。

**链接** —— 笔记之间用 `[[双链]]`,不要写相对路径的 markdown 链接。

**提交信息** —— 中文 conventional commits,scope 用分类名:

```
docs(游戏开发): 新增游戏总结大纲
docs: 更新密码笔记
chore: 清理根目录冗余文件
chore(obsidian): 更新工作区布局
```

只在用户明确要求时才 commit / push。

## 查找笔记

先按目录名缩小范围,再全文搜:

```bash
find /Users/rambo/obsidian/ramboYe -name '*关键词*.md'
grep -rl "关键词" /Users/rambo/obsidian/ramboYe --include='*.md'
```

搜索时排除 `.obsidian/`(里面是插件配置和缓存,不是笔记内容)。

## 注意

- `ramboYe/密码.md` 含敏感信息 —— 不要主动读取、复制或输出其内容,除非用户明确点名要改它。
- `.obsidian/workspace.json` 会被 Obsidian 频繁改写,产生的 diff 噪音可以忽略。
