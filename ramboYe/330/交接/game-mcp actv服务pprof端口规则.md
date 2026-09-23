---
created: 2026-09-16
tags: [运维工具, pprof, game-mcp, 330gs]
---

# game-mcp：actv 服务 pprof 端口规则

## 规则

`actv{N}` 实例的 pprof 端口 = **29000 + N**（N 为服务器 ID）。

例如 `actv1` → `29001`，`actv12` → `29012`。

## 说明

game-mcp 的 pprof 端口是按「服务类型基准端口 + 服务器 ID」推导的，内置默认基准端口表（`internal/config/validate.go:12-17`）：

```go
var builtinPprofPortBases = map[string]int{
	"game":  27000,
	"cross": 28000,
	"gate":  24000,
	"actv":  29000,
}
```

`actv` 原本不在内置默认值里（`config.example.yaml:142` 之前给的示例值是 `26000`，仅为占位示例），已按本环境的实际规则改成内置默认 `29000`，同步改了 `config.example.yaml` 和 `internal/config/validate_test.go`，`go test ./internal/config/...` 已跑过。

同类推导可参考 [[2026-06-26-内存监控自动pprof采集工作流]] 里 cross 的公式：`cross{N} → 28000 + N`（如 `cross1012 → 29012`），actv 是同样的模式，只是基准端口不同。
