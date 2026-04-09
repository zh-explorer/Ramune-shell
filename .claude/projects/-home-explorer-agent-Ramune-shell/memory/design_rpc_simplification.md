---
name: RPC 层简化决策
description: 经过深入设计讨论后，决定不需要独立的 RPC/mux 包，protocol 层的 codec + messages 已经够用
type: project
---

经过完整的 RPC 层设计讨论（mux 多路复用、pipe 可靠管道、Stream 抽象等），最终结论是不需要独立的 ramune-rpc 包。

**Why:** TCP/SSH 已经提供了可靠有序传输和多路复用。在此之上再建 mux + ACK + seq + 连接管理本质是重写 TCP，过度设计。

**How to apply:** 核心模型是 send(Request) → recv(Response)，同步阻塞，有限时间返回。protocol 包已有的 codec.py（长度前缀分帧）+ messages.py（Request/Response/ErrorCode）已经够用。SSH channel 提供天然的多路复用，多条 TCP 也行。
