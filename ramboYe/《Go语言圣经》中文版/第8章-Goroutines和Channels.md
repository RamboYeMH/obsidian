---
类型: 学习笔记
版本: gopl-zh
状态: 草稿
tags:
  - Go
  - Golang
  - 并发
  - Channel
  - Go语言圣经
创建日期: 2026-06-27
---

# 第8章-Goroutines和Channels

关联：[[00-Go语言学习索引]]、[[第8章-Goroutines和Channels-面试题]]

## 本章定位

第八章讲 Go 的 CSP 风格并发：goroutine 表示并发执行单元，channel 表示 goroutine 之间的通信和同步。原文入口：`ch8/ch8.md:1`。

## 内容总结

| 小节 | 主题 | 核心问题 | 来源 |
|---|---|---|---|
| 8.1 | Goroutines | 轻量并发执行 | `ch8/ch8-01.md:1` |
| 8.2-8.3 | Clock/Echo | 网络服务中的并发 | `ch8/ch8-02.md:1` |
| 8.4 | Channels | 收发、关闭、缓冲、单向 channel | `ch8/ch8-04.md:1` |
| 8.5-8.6 | 并发循环/爬虫 | fan-out、限制并发 | `ch8/ch8-05.md:1` |
| 8.7 | select | 多路复用、超时 | `ch8/ch8-07.md:1` |
| 8.8-8.10 | 目录遍历/退出/聊天 | 取消、广播、服务端模式 | `ch8/ch8-08.md:1` |

## 知识点

### 1. goroutine

`go f()` 会启动一个新的 goroutine 并发执行函数调用。main goroutine 退出时，整个进程结束，其他 goroutine 不会被等待。

### 2. channel 基本语义

channel 是带类型的通信管道：

```go
ch := make(chan int)
ch <- 1
x := <-ch
close(ch)
```

无缓冲 channel 的发送和接收必须同时准备好，因此自带同步语义。

### 3. close 和 range

关闭 channel 表示不会再发送新值。接收方可以用第二个返回值判断 channel 是否关闭：

```go
v, ok := <-ch
```

也可以用 `for v := range ch` 持续接收直到关闭。

### 4. 单向 channel

函数参数中可以声明方向，表达只发送或只接收：

```go
func producer(out chan<- int)
func consumer(in <-chan int)
```

这能让编译器帮忙检查并发协议。

### 5. 并发模式

- pipeline：多个阶段用 channel 串联。
- fan-out：多个 goroutine 从同一个输入中取任务。
- fan-in：多个 goroutine 把结果汇总到一个输出。
- semaphore：用有缓冲 channel 限制并发量。

### 6. select

`select` 等待多个 channel 操作中任意一个就绪。常用于超时、取消和多路复用。

```go
select {
case v := <-ch:
case <-time.After(time.Second):
}
```

### 7. 并发退出

长期运行的 goroutine 必须有退出路径。常见做法是传入 done channel 或 `context.Context`，所有阻塞点都监听取消信号。

## 重点关注点

- goroutine 很轻量，但不是免费资源。
- channel 既传值也表达同步。
- 发送方负责 close，接收方不要随便 close。
- nil channel 永远阻塞，可用于 select 中动态禁用分支。
- 必须考虑 goroutine 泄漏。

## 建议练习

| 练习 | 目标 |
|---|---|
| 8.4 | 实现 pipeline，理解关闭传播 |
| 8.6 | Web 爬虫限制并发 |
| 8.9 | 给并发任务加取消 |

## 学习检查表

- [ ] 能解释 goroutine 和线程的区别。
- [ ] 能解释无缓冲 channel 的同步语义。
- [ ] 能写出 `close`、`range`、`ok` 的用法。
- [ ] 能用 select 实现超时。
- [ ] 能识别 goroutine 泄漏。
- [ ] 能用 channel 限制并发量。
