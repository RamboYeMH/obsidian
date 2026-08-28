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

# Skill: jira

| 项 | 值 |
|---|---|
| 名称 | `jira` |
| 源文件 | `/home/cc/slgh5/gs/.claude/skills/jira/SKILL.md` |
| 作用域 | 项目 gs |
| 行数 | 206 |
| 用途 | 通过 REST API 直接查询/处理 H5 项目组 Jira 单，不开浏览器 |

**触发条件（description 字段，决定什么时候自动加载）**

> 查询和处理 Jira 上的需求/故障单（H5项目组）。用户说「看下我的 jira」「我有哪些单」「H5-11906 是什么问题」「这个单处理完了」「提单」「改完了把单推到上线排期」等场景时使用。通过 REST API 直接读写，不用开浏览器。

> [!warning] 已脱敏
> 原文件含明文密码，归档时替换为 `«密码见本地 SKILL.md»`。
> 真凭据只存在于本机 `.claude/` 下（已在 `.gitignore`），**不要写回本笔记**。

---

## 原文

# Jira 处理 skill

公司自建 Jira，**Server 8.0.2**（2019 版，注意：**不支持 Personal Access Token**，8.14+ 才有，只能用 basic auth）。

## 连接信息

| 项 | 值 |
|---|---|
| 地址 | `https://jira-lyqs26.330stars.com:60003` |
| 账号 | `yemingheng` |
| 密码 | `«密码见本地 SKILL.md»` |（注意首字母大写 T）
| 版本 | Jira Server 8.0.2 |
| 主项目 | `H5`（H5项目组） |
| API 根 | `https://jira-lyqs26.330stars.com:60003/rest/api/2` |

网页入口：https://jira-lyqs26.330stars.com:60003/secure/Dashboard.jspa
单子直达：`https://jira-lyqs26.330stars.com:60003/browse/H5-11906`

> 证书是自签的，curl **必须带 `-k`**，否则报证书错误。

## ⚠️ 认证现状（先读这段）

**读**：匿名就能读全部单（54000+），无需登录 —— 查询/看详情直接发请求，不带 `-u`。

**写**（评论、改状态、建单）：需要 basic auth，而当前账号处于 **CAPTCHA 锁定**状态：

```
x-seraph-loginreason: AUTHENTICATION_DENIED
x-authentication-denied-reason: CAPTCHA_CHALLENGE; login-url=.../login.jsp
```

这是登录失败次数超阈值触发的验证码锁，**API 无法绕过**。解法：
用浏览器打开 https://jira-lyqs26.330stars.com:60003/login.jsp ，手动输账号密码 + 填验证码登录成功一次，锁即解除，之后 basic auth 恢复可用。

解锁后先自检：

```bash
curl -s -k -u 'yemingheng:«密码见本地 SKILL.md»' \
  "https://jira-lyqs26.330stars.com:60003/rest/api/2/myself" | python3 -m json.tool
```

返回 JSON 里有 `name: yemingheng` 就是通了；仍是 403 就再看一眼 `x-authentication-denied-reason`。

> 别反复用错密码重试 —— 每次失败都会加深锁定。403 时先看 header 判因，不要盲目重刷。

## 查询（匿名可用，已验证）

统一形式，JQL 用 `-G --data-urlencode` 传，避免中文和空格转义问题：

```bash
J="https://jira-lyqs26.330stars.com:60003/rest/api/2"
curl -s -m 90 -k -G "$J/search" \
  --data-urlencode 'jql=<JQL>' \
  --data-urlencode 'maxResults=20' \
  --data-urlencode 'fields=key,summary,status,priority,assignee'
```

结果管道给 `python3 -c` 精简，**原始 JSON 极大（单个 issue 上百字段），别直接打印**。

### ⚠️ JQL 状态名的坑（踩过，必看）

界面显示的中文状态名，**有的在 JQL 里不能用**——因为那是翻译，不是真名：

| 界面显示 | JQL 里要写 |
|---|---|
| 开放 | **`Open`** ← 写"开放"报错 |
| 重新打开 | **`Reopened`** ← 写"重新打开"报错 |
| 关闭 | `关闭` ← 写 `Closed` 反而报错 |
| 分配程序 / 上线排期 / 研发合并 / 策划自测 / done | 直接用中文 |

规律：**只有 `Open` 和 `Reopened` 用英文，其余一律用中文。** 报错长这样：
`{"errorMessages":["“status”域中没有“开放”值。"]}`

### 常用查询

**我的待办**（最常用，进来先跑这个）：

```bash
J="https://jira-lyqs26.330stars.com:60003/rest/api/2"
curl -s -m 90 -k -G "$J/search" \
  --data-urlencode 'jql=project = H5 AND assignee = yemingheng AND status not in (关闭, done) ORDER BY updated DESC' \
  --data-urlencode 'maxResults=30' \
  --data-urlencode 'fields=key,summary,status,issuetype,priority,reporter,updated' | python3 -c "
import sys,json
d=json.load(sys.stdin)
if 'errorMessages' in d: print('ERR',d['errorMessages']); sys.exit()
print('total:',d['total'])
for i in d['issues']:
    f=i['fields']
    print(f\"  {i['key']:<10} {f['status']['name']:<6} {f['issuetype']['name']:<4} {(f.get('priority') or {}).get('name','-'):<3} | {(f['summary'] or '')[:60]}\")
"
```

**看单详情 + 状态流水**：

```bash
curl -s -m 60 -k "$J/issue/H5-11906?expand=changelog" | python3 -c "
import sys,json
d=json.load(sys.stdin); f=d['fields']
print(d['key'],'|',f['summary'])
print('类型',f['issuetype']['name'],'状态',f['status']['name'],'优先级',(f.get('priority') or {}).get('name'))
print('报告人',(f.get('reporter') or {}).get('name'),'经办人',(f.get('assignee') or {}).get('name'))
print('--- 描述 ---'); print((f.get('description') or '')[:3000])
print('--- 状态流 ---')
for h in d['changelog']['histories']:
    for it in h['items']:
        if it['field']=='status':
            print(' ',h['created'][:16],(h['author'] or {}).get('name'),':',it['fromString'],'->',it['toString'])
"
```

**看评论**（常有策划/测试补充的复现步骤）：

```bash
curl -s -m 60 -k "$J/issue/H5-11906/comment" | python3 -c "
import sys,json
for c in json.load(sys.stdin).get('comments',[]):
    print('---',(c['author'] or {}).get('name'),c['created'][:16])
    print((c['body'] or '')[:1500])
"
```

**按版本捞单**（版本号写在标题里，如【1049】，不是 fixVersion 字段 —— fixVersions 基本没人填）：

```bash
--data-urlencode 'jql=project = H5 AND summary ~ "1050" AND status = Open ORDER BY created DESC'
```

## 处理单（写操作，需先解 CAPTCHA）

### 本项目的实际约定（从 H5-11895 实测还原）

修完一个故障单，标准动作是**两步**：

1. **加评论写分支名**，格式就一行：
   ```
   分支： h5_new_tf_v1049_slg_drop_bug
   ```
2. **推状态**：`Open` → `分配程序` → `上线排期`（两跳连着做，中间不停）

H5-11895 的真实时间线：`14:38` 评论分支名 → `14:40` Open→分配程序 → `14:40` 分配程序→上线排期。
近期抽样的故障单 3/3 都是这个路径，是稳定套路。

### 故障单完整工作流

```
Open(开放) ─→ 分配程序 ─→ 上线排期 ─→ 关闭
                                ↑
                          重新打开(Reopened)
```
（另有 研发合并 / 合并主干 两个态，用得少）

### 具体调用

**第一步永远是查可用 transition**（transition ID 是按工作流走的，**不要硬编码猜**，不同单/不同状态 ID 不一样）：

```bash
curl -s -k -u 'yemingheng:«密码见本地 SKILL.md»' "$J/issue/H5-11906/transitions" | python3 -c "
import sys,json
for t in json.load(sys.stdin)['transitions']:
    print(' id=',t['id'],t['name'],'->',t['to']['name'])
"
```

> 匿名请求这个接口会返回 `{\"transitions\":[]}`（空数组，不报错），别误以为没有可用流转——那是没登录。

**加评论**：

```bash
curl -s -k -u 'yemingheng:«密码见本地 SKILL.md»' -X POST "$J/issue/H5-11906/comment" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json;print(json.dumps({'body':'分支： h5_new_tf_v1049_slg_drop_bug'}))")"
```

> 中文用 `python3 -c` 生成 JSON，别手写 `-d '{...}'`，避免编码/转义踩坑。

**推状态**（`<ID>` 用上一步查到的）：

```bash
curl -s -k -u 'yemingheng:«密码见本地 SKILL.md»' -X POST "$J/issue/H5-11906/transitions" \
  -H "Content-Type: application/json" -d '{"transition":{"id":"<ID>"}}'
```

成功返回 **HTTP 204 空响应**（没有 body 是正常的，别当失败）。推完重新查一次 `fields=status` 确认。

> ⚠️ 上面三个写接口**目前都没能实测**（CAPTCHA 挡着）。调用形式是 Jira 8 REST 标准，但 transition ID、必填字段（某些流转会要求填解决结果等）要等解锁后第一次跑时确认。

## 使用约定

- **写操作前必须先给我确认**：Jira 是全组共享的，改状态/发评论组里所有人都看得到，还会触发邮件通知。列出「要对哪个单做什么」，我点头再执行。查询随便跑，不用问。
- **别批量刷状态**。一次处理一个单，推完确认再下一个。
- 单号从 commit message 里就能抓：格式是 `1049 - H5-11895【1049】【xxx】描述`。
- 改完代码要写分支名时，分支名用 `git rev-parse --abbrev-ref HEAD` 取当前分支，别手敲。

## 备查

- **项目 key**：H5(H5项目组，主用) / APP(H5APP版本) / MID(中台) / K3 / C5 / V1 / PC / M1 / S1 / T1 / BC / K8 / KCN / KZ2 / TD / TC / K3C5 / K3C6 / C6ICE
- **H5 问题类型**：任务(10002) / 子任务(10003) / 故障(10004) / 配置1(10101)
- **优先级**：P0~P4（实际在用）+ highest/high/medium/low/lowest（基本没人用）
- **版本**：V1036 ~ V1050（`$J/project/H5/versions`）
- **密码是明文写在本文件里的**；`.claude` 已在仓库 `.gitignore`（第 72 行），不会提交。**不要把本文件内容复制到仓库内其他位置**。

---

## 相关

- [[00-Skill 索引]]
- [[Hook]]
