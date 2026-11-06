# 本地通用客户端

入口 `scripts/benchmark_client.py`，仅依赖 Python 标准库。复用现有 MCP 参数和 Block，不含任何玩法专用逻辑。源码/配置查找、用例规划、准备状态核验和业务判定仍由 Agent 完成。

## 连接与证据

设置 `BENCHMARK_MCP_URL` 为已授权实例的 `/mcp` URL；需要认证时通过 `BENCHMARK_MCP_TOKEN` 环境变量提供 Bearer token，不写进参数文件。`--url` 可覆盖 URL。不自动选择环境或机器人。

证据默认保存在 `~/.cache/benchmark-agent/evidence`；受限执行环境应指定可写目录，例如 `--store /tmp/benchmark-evidence`。每份响应独立保存，文件权限 0600。原始响应可能包含玩家数据或令牌，不直接发布整个目录。证据只是本地文件，不保证永久保存。

全局参数放子命令前。以下 `CLIENT` 表示本 skill 下脚本绝对路径。

```bash
python3 "$CLIENT" --store /tmp/benchmark-evidence create-draft --input create.json
python3 "$CLIENT" --store /tmp/benchmark-evidence apply-draft --input edit.json
python3 "$CLIENT" --store /tmp/benchmark-evidence run --input run.json --observe-seconds 100
python3 "$CLIENT" --store /tmp/benchmark-evidence collect --run-id RUN_ID --after CURSOR --observe-seconds 30
python3 "$CLIENT" --store /tmp/benchmark-evidence read-evidence --ref REF.json --pointer /response/result/structuredContent --max-bytes 6000
python3 "$CLIENT" --store /tmp/benchmark-evidence cleanup --older-than-days 30
```

## 输入沿用 MCP 契约

`create-draft`：现有 `create_block_draft` 参数。`apply-draft`：现有 `edit_block_draft` 参数，例如：

```json
{"id":"example","expected_revision":"实际返回的revision","operations":[{"type":"set_start","start_at":"Login"}]}
```

操作字段与当前 `get_flow_spec` 核对。只提交变化的 operations；删除必须显式 `delete_state`。不自动读取最新 revision 覆盖冲突，不隐式替换整个 Block。编辑返回 validation，通常无需另调 validate；不合法也可能已经保存新 revision，修正时用返回 revision。

`run`：现有 `run_block_draft` 参数：`draft_id`、`expected_revision`、`environment_id`、`robot_id`、可选 `variables` 和 `confirm:true`。仅发送一次启动请求。启动成功立即输出并 flush 一行 `phase:started`（含 Run ID 和证据引用），观察结束再输出一行摘要，因此 run 输出为 JSON Lines。**每次重新执行 run 都是新启动，本工具不提供幂等性**。返回未知时不能重跑 run；从已取得的原始响应、运行状态或租约核实。已知 Run ID 一律用 collect 续读。客户端会把启动、状态和 Trace 页写入 `runs/RUN_ID.json` 清单；collect 默认从清单游标续读，若要从头重读显式传 `--after ""`。摘要计数合并清单里去重后的所有页，并列出页数、事件数和 `collection_complete`；后者为 false 时不能把计数称为完整运行统计。

## Block 编写流程

Agent 负责用例与预期，客户端只提交原生 MCP 参数。默认采用“小 Block 提供能力，顶层流程组合”的方式，不要求用户填写流程：

1. **优先组合已有能力**：用 `search_context` 定向查找，`get_block` 读取相关小 Block；核对当前 `get_flow_spec`、输入输出、前置条件、完成核验与副作用。顶层用原生 `Type: Call`、`CallChain` 和 `CallParams` 组合。CallChain 填稳定 Block ID，不能填展示名。不能只按名称推断能力适用。
2. **缺少能力才补小 Block**：一个小 Block 对应可独立核验的能力，例如“确保加入联盟”可包含查询、必要时加入、成员状态核验；不机械地把每条请求都拆成文件。功能特有的一次性步骤可留在顶层，不为复用率强制拆分。参数和预期从当前协议、配置和业务依据取得。
3. **内部逻辑不同才克隆**：相近 Block 无法通过现有参数满足需求时，用 `create-draft` 的 `from_block_id` 克隆，再局部修改，保持原共享 Block 不变；检查固定角色 ID、资源量及旧预期。完全新能力直接生成原生 StateDef。

顶层负责编排准备依赖、被测操作和业务结果核验；小 Block 负责自身能力是否完成。准备不能代做被测操作；测试“加入联盟”时不能先调用准备能力把加入动作完成。已有状态满足时，可跳过准备动作，但必须核验当前条件。共享准备是否可重复或会污染其他用例，需实际判断。

每个小 Block 的契约保留在现有说明或一条资料记录中，不增加协议字段或独立文档要求：输入及参数来源、前置条件、完成核验、输出上下文路径、副作用与失败行为。子流程和父流程共享上下文；CallParams 临时覆盖的路径在返回时恢复，所以输出不得依赖这些输入路径的变更，且避免父子路径重叠。其他结果使用清楚的上下文命名，防止覆盖兄弟流程变量；不要把调用隔离理解成独立玩家状态。

新子 Block 的草稿不能直接被 CallChain 调用。确需可复用产物时，使用现有 `commit_block_draft` 保存新 ID，并确认当前短测试执行路径能够加载该定义及其依赖；保存成功和静态引用校验通过都不等于运行实例必然已加载。遵守本次环境和写入授权，沿用 revision 校验，不覆盖已有共享 Block。客户端没有 commit 子命令时直接调用现有 MCP，不为此新增后端能力。顶层流程可继续使用草稿。

先校验依赖，再校验顶层组合，检查循环引用、参数/输出冲突及累计请求、耗时和调用深度预算。用已有运行证据或本次有必要的验证确认子能力，不为每个小 Block 无条件新增一次游戏运行；尚未实际核验的能力标为未验证。依赖无法解析时定位具体缺口，不能把“保存了子 Block”写成“组合测试已通过”。引用版本或内容改变后复核受影响组合。

将同一逻辑修改涉及的状态、跳转和 StartAt 合成一批 operations 提交，避免逐状态调用造成暂时缺少跳转目标和额外往返。大型流程可按完整逻辑段分批，但未完成草稿不得执行；不为了分批保留无意义的通过分支。

`apply-draft` 直接使用返回的 validation：定位到具体状态和字段，只改受影响操作，保留其他步骤。revision 冲突先读取并分析差异，不自动覆盖。静态校验通过后才启动；它只能证明已检查的结构约束，不能证明前置状态、预期或服务端行为正确。业务失败回到证据分析，不通过删除断言或修改预期来求通过。

当前不增加 JSON 构造器或新模板系统。只有实测确认重复填写结构成为明显成本时，再考虑生成原生 StateDef/operations 的小型辅助；不得自动猜业务参数或预期。

## 输出与失败

- 默认只回短摘要、诊断前 5 项和证据引用，不回整份 Block/Trace。超出 12KB 的摘要存入证据，返回 `result_ref`。运行清单将各响应证据与 Run ID、游标关联；保存的是脱敏响应。
- 工具错误直接返回脱敏后的 message；新实例限额错误还返回 error_code、retry_after_seconds、next_allowed_at。retry_allowed=false 表示本次调用不能盲目重发，不表示额度永不恢复。
- 摘要优先保留失败和近期业务步骤，登录折叠；execution_status 表示流程是否执行完，旧实例缺失时为 null，不能从原始 status 猜测。assertion_results 仅统计实际 assertion 事件，available=false 表示没有观察到该类事件（旧实例或未执行断言），不得当作零失败。protocol_errors 与断言、进程 status 分开展示，最终业务结论仍由 Agent 给出。断言计数由 Run 清单里已保存的去重页汇总；未完成时仅代表这些已索引页面，不能当整次运行统计。
- 新保存的请求与响应自动脱敏；历史证据读取时也脱敏。输入参数文件仍由调用方保护，不要把认证字段、原始配置或登录响应直接输出到终端。
- 草稿错误通过 `evidence_ref` 读取原始 MCP 诊断，不自动重试或修预期。`mutation_outcome_unknown` 表示请求可能生效，禁止自动重发。
- `observe-seconds` 只限制轮询等待，单次 HTTP 超时和随后分页耗时可能额外增加；不改变服务端预算。`terminal:false` 不表示测试失败。
- `collect` 最多读 `max-pages` 页，保留 `next_after`、`has_more`、`truncated`。每个 Run 在 `runs/RUN_ID.json` 保存启动、状态、Trace 页及游标索引；相同 store 下再次 collect 默认从已记游标续读，并自动合并去重页的摘要。显式 `--after` 用于从指定位置重读；只读取中间页不能证明整条 Trace 完整。
- `collection_complete` 表示 Run 清单从空游标起连续覆盖到末页，且状态终结、无已知截断或采集错误；显式从中间游标开始读取不能单独标记完整。不代表全流程业务证据充分或用例通过。服务端 Summary/Detail 还有未标记的长度裁剪，因此不能保证原始文本完整。续读需合并先前证据；`truncated`、`embedded_evidence_truncated` 或任何错误都需要披露。
- 当前 Trace 主要在子进程结束后回放。框架 failed 可能来自预期的负向 ErrCode；Agent 对照事前预期判断，不能直接把 status 当测试结论。
- `read-evidence` 用 JSON Pointer 定位字段；数组支持 `--offset`、`--limit`，保留 `has_more`。过大值返回标记 `truncated:true` 的 `json_fragment`，应缩小字段范围，不能当成完整 JSON。原始响应可能在 `structuredContent` 或 `content[].text`，按实际格式读取。
- 清理命令默认只预览。检查候选后，只有明确需要删除时再加 `--confirm`；仅清理超过保留天数的普通证据文件，未完成或未完整采集 Run 引用的文件会受保护，Run 清单本身保留。
- 定位到 events 数组后可用 `--state STATE`、`--event-type assertion` 筛选，再以 `--fields cursor,state,status,summary,observations` 投影；筛选先于分页。不要为重复提取事件临时编写解析脚本。
- 退出码只用于客户端错误提示，不用于游戏测试判定。没有实际模型计量就不声称节省了多少 token。

不提供任意 MCP 代理、通用造号/造状态 DSL、自动取消或自动重新运行。目标发现、机器人供给继续调用现有 MCP；缺什么补什么，不扩大机器人框架。
