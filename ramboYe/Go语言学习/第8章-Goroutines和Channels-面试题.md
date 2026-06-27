---
类型: 面试题
版本: gopl-zh
状态: 草稿
tags:
  - Go
  - Golang
  - 并发
  - 面试
  - Go语言圣经
创建日期: 2026-06-27
---

# 第8章-Goroutines和Channels 面试题

关联：[[第8章-Goroutines和Channels]]、[[00-Go语言学习索引]]

## Q1：goroutine 是什么？

**答：** goroutine 是 Go 运行时调度的轻量级并发执行单元，通过 `go f()` 启动。

## Q2：main goroutine 退出后其他 goroutine 会怎样？

**答：** 进程直接结束，其他 goroutine 不会被自动等待。

## Q3：无缓冲 channel 的特点是什么？

**答：** 发送和接收必须同时就绪，通信本身就是同步点。

## Q4：有缓冲 channel 的特点是什么？

**答：** 缓冲未满时发送不阻塞，缓冲非空时接收不阻塞。它可以解耦发送方和接收方，也可作为信号量限制并发。

## Q5：谁应该关闭 channel？

**答：** 通常由发送方关闭，用来表示不再发送新值。接收方不应该随意关闭自己没有所有权的 channel。

## Q6：从关闭的 channel 接收会怎样？

**答：** 先接收完缓冲中的值，然后持续返回元素零值，第二个返回值 `ok` 为 false。

## Q7：向关闭的 channel 发送会怎样？

**答：** panic。

## Q8：nil channel 有什么特点？

**答：** 对 nil channel 的发送和接收会永久阻塞。在 select 中可用 nil channel 动态禁用某个 case。

## Q9：select 的用途是什么？

**答：** 同时等待多个 channel 操作，用于超时、取消、多路复用和非阻塞尝试。

## Q10：什么是 goroutine 泄漏？

**答：** goroutine 因为阻塞在发送、接收、锁、IO 等位置，永远无法退出。泄漏会持续占用内存和调度资源。
