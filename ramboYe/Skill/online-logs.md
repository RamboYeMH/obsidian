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

# Skill: online-logs

| 项 | 值 |
|---|---|
| 名称 | `online-logs` |
| 源文件 | `/home/cc/slgh5/gs/.claude/skills/online-logs/SKILL.md` |
| 作用域 | 项目 gs |
| 行数 | 206 |
| 用途 | 通过 Kibana/ES HTTP API 查线上 h5prod 游戏服日志排查玩家问题 |

**触发条件（description 字段，决定什么时候自动加载）**

> 查询线上（h5prod）游戏服日志，排查玩家反馈的问题。用户说「查一下玩家 XXX」「线上日志」「玩家说他没收到/收到两份/领不到」「某某服报错」「查 error」等需要看线上运行日志的场景时使用。通过 Kibana(ES) HTTP API 直接查询，不用打开浏览器。

> [!warning] 已脱敏
> 原文件含明文密码，归档时替换为 `«密码见本地 SKILL.md»`。
> 真凭据只存在于本机 `.claude/` 下（已在 `.gitignore`），**不要写回本笔记**。

---

## 原文

# 线上日志查询 skill

线上日志集中在 Kibana + Elasticsearch，**用 curl 走 Kibana 的 console proxy 查询**，不需要开浏览器。

## 连接信息

| 项      | 值                          |
| ------ | -------------------------- |
| Kibana | http://106.53.123.224:5601 |
| 账号     | ``                         |
| 密码     | `«密码见本地 SKILL.md»`         |
| 版本     | Kibana / ES 8.17.4         |
| 环境     | `gameid = h5prod`（线上正式服）   |

浏览器入口：http://106.53.123.224:5601/app/discover

## 查询方式（固定模板）

所有查询都用这个形式，`path=` 后面跟 ES 的路径，body 是标准 ES DSL：

```bash
curl -s -m 90 -u suhongfan:«密码见本地 SKILL.md» \
  -X POST "http://106.53.123.224:5601/api/console/proxy?path=<ES_PATH>&method=POST" \
  -H "kbn-xsrf: true" -H "Content-Type: application/json" \
  -d '<ES_QUERY_DSL>'
```

- `kbn-xsrf: true` 必带，否则 400。
- proxy 的 `path` 里若要带 query string，`&` 要写成 `%26`，否则会吃掉 `method` 参数。
- 结果建议管道给 `python3 -c` 精简输出，原始 JSON 很大会撑爆上下文。

## 索引结构

- 索引是 **每天一个 data stream**：`game-h5prod-YYYY.MM.DD`（如 `game-h5prod-2026.08.10`）。
- **只保留约 20 天**。
- 单日数据量约 150~270 GB，所以：
  - **必须限定索引到具体日期**，如 `game-h5prod-2026.08.09,game-h5prod-2026.08.10`。
  - 用 `game-h5prod-*` 跨全部索引 + 大时间范围**会 502 超时**（`Client request timeout`）。真要跨天就配 `range` 过滤且控制在 2~3 天内。

查有哪些日期可用：

```bash
curl -s -u suhongfan:«密码见本地 SKILL.md» -X POST "http://106.53.123.224:5601/api/console/proxy?path=_data_stream/*/_stats&method=GET" \
  -H "kbn-xsrf: true" | python3 -c "
import sys,json
for x in json.load(sys.stdin)['data_streams']: print(x['data_stream'])
" | sort
```

## 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `@timestamp` | date | **UTC 时间**。北京时间 = UTC + 8。跨天活动结算常在 UTC 16:00（= 次日 00:00 北京时间） |
| `message` | match_only_text | 日志正文。用 `match_phrase` 搜；**不支持高效 wildcard** |
| `serverid` | keyword | 进程名：`game39` `gate7` `cross1010` `actv1` `mail71` `chat2` 等 |
| `log_level` | keyword | `info` / `warning` / `error` / `debug`（debug 也在，量少） |
| `src_location` | keyword | 打日志的代码位置，如 `battlefield_kill/logic.go:371`。**精确过滤神器** |
| `gameid` | keyword | `h5prod` |
| `host.name` | keyword | 物理机，如 `h9` |
| `log.file.path` | keyword | 如 `/data/gslog/h5prod_game754.log` |

> ⚠️ `src_location` 的行号来自**线上运行的版本**，可能与本地分支不一致（如线上 `utils/mail_util.go:59`，本地同一行是 `:113`）。按文件名+函数语义对齐，别死磕行号。

## 常用查询

### 1. 定位玩家在哪个服（第一步永远先做这个）

```bash
curl -s -m 90 -u suhongfan:«密码见本地 SKILL.md» -X POST "http://106.53.123.224:5601/api/console/proxy?path=game-h5prod-2026.08.09,game-h5prod-2026.08.10/_search&method=POST" \
  -H "kbn-xsrf: true" -H "Content-Type: application/json" -d '{
  "size":0,
  "query":{"bool":{"filter":[{"match_phrase":{"message":"1562232"}}]}},
  "aggs":{"srv":{"terms":{"field":"serverid","size":10}}}
}' | python3 -c "
import sys,json
d=json.load(sys.stdin)
print([(b['key'],b['doc_count']) for b in d['aggregations']['srv']['buckets']])
"
```

玩家 ID 直接 `match_phrase` 就能命中（日志里普遍是 `pid:123` `player:123` `PlayerID:123` 这类写法，分词后能匹配上）。

### 2. 看某玩家某时间段的全部日志

```bash
-d '{
  "size":50,
  "query":{"bool":{"filter":[
    {"term":{"serverid":"game39"}},
    {"range":{"@timestamp":{"gte":"2026-08-09T15:59:50Z","lte":"2026-08-09T16:01:30Z"}}},
    {"match_phrase":{"message":"1562232"}}
  ]}},
  "sort":[{"@timestamp":"asc"}],
  "_source":["@timestamp","serverid","log_level","message","src_location"]
}'
```

日志噪音很大（礼包/活动检查刷屏），配 `must_not` 排除高频位置：

```json
"must_not":[{"prefix":{"src_location":"custome_gift/"}},{"term":{"src_location":"internal/ctl_actv.go:759"}}]
```

### 3. 先聚合 `src_location`，再看细节（排查利器）

不知道该看什么日志时，先看这个时间窗里哪些代码位置在活动：

```bash
-d '{
  "size":0,
  "query":{"bool":{"filter":[
    {"term":{"serverid":"game39"}},
    {"range":{"@timestamp":{"gte":"2026-08-09T16:00:00Z","lte":"2026-08-09T16:00:25Z"}}},
    {"bool":{"should":[
      {"prefix":{"src_location":"battlefield_kill/"}},
      {"prefix":{"src_location":"utils/mail_util"}}
    ],"minimum_should_match":1}}
  ]}},
  "aggs":{"loc":{"terms":{"field":"src_location","size":30}}}
}'
```

### 4. 查报错

```bash
-d '{
  "size":20,
  "query":{"bool":{"filter":[
    {"range":{"@timestamp":{"gte":"now-2d"}}},
    {"term":{"log_level":"error"}},
    {"term":{"serverid":"game39"}}
  ]}},
  "sort":[{"@timestamp":"desc"}],
  "_source":["@timestamp","serverid","message","src_location"]
}'
```

## 排查玩家「奖励/邮件」问题的固定套路

这类反馈（没收到 / 收到两份 / 数量不对）按这个顺序查，几步就能定性：

1. **定位服务器**：按上面第 1 步拿到 `serverid`。
2. **查玩家收到的所有活动邮件**——这条日志一封邮件一行，直接给出邮件模板 ID：
   ```json
   {"bool":{"filter":[
     {"term":{"serverid":"game39"}},
     {"match_phrase":{"message":"PlayerID:1562232"}},
     {"term":{"src_location":"internal/ctl_actv.go:156"}}
   ]}}
   ```
   输出形如 `OnA2PPendPlayerMails mailinfo, PlayerID:1562232,MailType:3,MailCfgID:17116063`。
3. **查邮件实际投递**（含全服/联盟邮件，这类不走上面那条日志）：
   ```json
   {"match_phrase":{"message":"configID:17116064"}}
   ```
   `mail/send.go` 的 `sendmail debug log` 会打印 `configID` / `boxID` / `receivers` / 收件人列表。
   > 全服邮件（`MailAddrSyc`）的 `list:` 是**服务器 ID** 而不是玩家 ID，如 `receivers:3 list:39` 表示发给 39 服全体。
4. **把 MailCfgID 翻译成人话**：在 `gdconfig` 仓库查
   ```bash
   awk -F'\t' '$1==17116063' /home/cc/slgh5/gdconfig/tsv/MailCfg.tsv
   grep -o '.\{80\}<LC_key 里的中文>.\{20\}' /home/cc/slgh5/gdconfig/tsv/I18nCfg.json
   ```
   标题相近但 ID 不同 = 两封不同的奖励邮件，不是重复发放。
5. **确认是否真重复**：同一个 `MailCfgID` 对同一玩家出现两次才算重复。批量排行邮件还可以看
   `[Actv]send rank rewards mails, count=N`（`utils/mail_util.go`）出现几次、每次 count 多少。
   ⚠️ 不同活动模板都会打这条 count 日志，**别把别的活动的批次算到当前活动头上**——用它前后紧邻的模板自有日志（如 `battlefield_kill/logic.go` 的 `sendRankMail sendId:`）来区分调用方。

### 已查证案例：密藏之王「收到两份奖励」（玩家 1562232，2026-08-09）—— 真 bug

**教训：只查玩家所在服会得出错误结论。** 一开始只查了 game39，看到 17116063 只有一封，误判为「个人榜+阵营榜两封不同邮件」的误报；
**去掉 `serverid` 过滤后才发现 game33 也发了同一封 17116063**。跨服玩法的问题，必须全服查。

根因：远征跨服榜单 `RankTypeBattlefieldKill_20667_1100121_3003_1_0` 被同组的 game39 和 game33 **各自拉取并各自发奖**，
每服靠 `cache.GetPlayerCache(id).GetOriginServerID() == conf.ServerID` 过滤"只发本服玩家"，
而少数玩家（疑似转服/跨服同步残留）在两个服的 PlayerCache 里都被判定为本服 → 各收到一封**完全相同**的邮件。

| 服 | 时间(UTC) | 收件人数 |
|---|---|---|
| game39 | 16:00:19.623 | 65 |
| game33 | 16:00:19.083 | 62 |
| **重叠（收到两封）** | | **4 人**：1561694 / 1562232 / 1567984 / 8425501 |

排查这类问题的关键查询——**算两服收件人交集**：

```bash
-d '{"size":300,"query":{"bool":{"filter":[
  {"terms":{"serverid":["game33","game39"]}},
  {"range":{"@timestamp":{"gte":"2026-08-09T16:00:15Z","lte":"2026-08-09T16:00:30Z"}}},
  {"match_phrase":{"message":"configID:17116063"}}]}},"_source":["serverid","message"]}'
```
再用 `re.search(r'list:(\d+)')` 提取收件人求交集。

顺带排除的干扰项：16:00:02 的 `send rank rewards mails count=63` 属于**最强指挥官**活动（邮件 17116051），与密藏之王无关；
阵营奖励 17116064 是各服发给自己服的全服邮件（`receivers:3 list:39`），不重复。

## 注意

- 密码是明文写在本文件里的；`.claude` 已在仓库 `.gitignore`（第 72 行），不会提交到 git。**不要把本文件内容复制到仓库内其他位置**。
- 这是**只读排查**用途。不要用这套凭据去写 ES（`_bulk`/`_delete_by_query` 等）。
- 时间一律先换算：北京时间 = 日志时间 + 8 小时。玩家说「今天零点」通常对应日志里的**前一天 16:00 UTC**。

---

## 相关

- [[00-Skill 索引]]
- [[Hook]]
