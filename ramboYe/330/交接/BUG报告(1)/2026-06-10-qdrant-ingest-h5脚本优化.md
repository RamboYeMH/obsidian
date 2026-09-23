---
created: 2026-06-10
tags: [qdrant, embedding, azure-openai, 中文检索, 断点续跑, H5项目]
---

# Qdrant H5项目代码录入脚本优化记录

脚本路径：`/home/wenyu/Documents/330gs/scripts/ingest_qdrant_h5.py`
集合名：`gs_game_h5`（与 `gs_game_v1` 完全隔离，不得混用）

## 问题与修复

### 1. APITimeoutError 未捕获导致崩溃
原来 `embed_batch` 只捕获 `RateLimitError`，Azure OpenAI S0 tier 网络不稳定时会抛 `APITimeoutError`，脚本直接崩溃，8768 条跑到一半报错退出。

**修复**：同时捕获 `APITimeoutError` 和 `APIConnectionError`，指数退避重试（5→10→20…秒，最多8次）；调用加 `timeout=60`。

### 2. asyncio.gather 一个 batch 失败全局中断
改为每个 `process_batch` 内部 try/except，失败记录数量后 return，不影响其他 batch。

### 3. 无续跑能力，重跑会重复嵌入
新增 `fetch_existing_ids()`，启动时用 Qdrant scroll API 滚动拉取所有已有 ID，过滤掉已写入的 chunk。ID 用 `sha256(file::func_name)[:16]` 生成，稳定幂等。

### 4. 中文查询无法匹配英文函数名
Go 代码全是英文，用中文查"英雄升级"找不到 `OnHeroStepsUpgradeReq`。

**修复**：新增 `make_embed_text()` 和 `_infer_chinese_desc()`，在代码前面拼接中文语义摘要：

| 函数名模式 | 中文描述 |
|-----------|---------|
| `On*Req` | 处理XXX请求 |
| `On*Event` | 处理XXX事件 |
| `On*AckBack` | 处理XXX回调确认 |
| `On*Ntf` | 处理XXX通知 |
| `BILog*` | 记录XXXBI埋点日志 |
| `Init*` | 初始化XXX |
| `Get*` | 获取XXX |
| `Set*` | 设置XXX |
| `Check*/Is*/Has*` | 条件检查：XXX |
| `Send*` | 发送XXX |

加上元数据补充：`is_handler=true`→"网络请求处理器"；`kibana_searchable`→"有/无Kibana日志"；`bi_calls`→"BI埋点：XXX"。

### 5. MAX_CONCURRENT=2 在 S0 tier 反而更容易超时
改为 1，串行更稳定。

## 启动方式

```bash
export AZURE_OPENAI_ENDPOINT=https://timeracetech-agent-resource.services.ai.azure.com
export AZURE_OPENAI_API_KEY=<key>
cd /home/wenyu/Documents/330gs
PYTHONUNBUFFERED=1 python3 -u scripts/ingest_qdrant_h5.py 2>&1 | tee /tmp/ingest_h5.log
```

脚本会自动跳过已有记录，只嵌入未录入的部分。
