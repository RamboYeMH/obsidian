---
类型: 备份
来源: 本地 MongoDB door 库
集合: gs_meta_data
状态: 已备份
tags:
  - 备份
  - mongodb
  - door
  - gs_meta_data
创建日期: 2026-06-18
---

# door / gs_meta_data 备份

> 本地 MongoDB `mongodb://127.0.0.1:27017` → `door` 库 → `gs_meta_data` 集合
> 备份时间：2026-06-18，共 **1 个文档**，含 4 个区服（s1–s4）的元信息。

## 数据文件

- `gs_meta_data_20260618.json` —— canonical EJSON（每行一条文档，类型信息完整，可还原）。

## 区服概览（infos 字段）

| 区服 | serverid | name | status | group | zvzGroup | kvk_group | maxLoginCount | serverOpenAt(ms) |
|------|----------|------|--------|-------|----------|-----------|---------------|------------------|
| 1 | 1 | s1 | 2 | 1 | 1 | 1 | 333 | 1781669181949 |
| 2 | 2 | s2 | 2 | 1 | 1 | 1 | 333 | 1781677041866 |
| 3 | 3 | s3 | 2 | 1 | 1 | 1 | 333 | 1772093820634 |
| 4 | 4 | s4 | 2 | 1 | 1 | 1 | 333 | 1781162484551 |

文档顶层字段：`_id`、`ids_trusted`(null)、`infos`(4 个区服)、`kadminkey`("")、`import_sync_addr`("")。

## 还原方法

> ⚠️ 还原会按 `_id` 写回。若目标库已存在同 `_id` 文档，请先确认是否需要覆盖。

### 方式一：mongosh（推荐，无需额外工具）

```bash
mongosh --quiet "mongodb://127.0.0.1:27017/door" --eval '
  const fs = require("fs");
  const lines = fs.readFileSync("gs_meta_data_20260618.json","utf8").trim().split("\n");
  lines.forEach(l => db.gs_meta_data.insertOne(EJSON.parse(l)));
  print("restored: " + lines.length);
'
```

如需先清空再还原，在 insert 前执行 `db.gs_meta_data.deleteMany({})`。

### 方式二：mongoimport（需安装 mongodb-database-tools）

```bash
mongoimport --uri="mongodb://127.0.0.1:27017/door" \
  --collection=gs_meta_data --file=gs_meta_data_20260618.json
```
