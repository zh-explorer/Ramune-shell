# Ramune-shell Roadmap

## 项目目标

解决 AI agent（运行在容器中）远程操控其他机器的问题。支持 CLI 和 GUI 两种交互模式，覆盖 Linux 和 Windows。

## 设计原则

- 远程机器为 agent 专用，完全可控
- 安全层在通信最外层包裹（TLS / SSH tunnel），不侵入协议设计
- 能用 shell 命令完成的不单独实现，保持 client 精简
- 能力做厚，降低 agent 调用复杂度
- 复杂脚本走文件传输通道，彻底规避转义问题

## Client 原生能力

### 命令执行
- Shell 执行（bash / powershell / cmd）
- 指定工作目录、环境变量
- 同步 / 异步执行
- 交互式输入支持

### 文件传输
- 上传 / 下载（二进制安全）

### GUI 操控
- 截屏（全屏 / 指定区域）
- 键盘输入 / 组合键
- 鼠标点击、移动、拖拽
- 窗口枚举与管理（前置、最小化、关闭、调整大小）
- 剪贴板读写

### 网络通道
- 端口转发
- SOCKS 代理

## 不单独实现（走命令执行）

文件操作、进程管理、系统信息、服务管理、计划任务、注册表、hash、压缩解压、DNS、网络状态查看等。

## 架构设计

### 整体架构

```text
[本地 - Agent 侧]                  [远端 - 目标机器]

Agent (Claude)                      执行层
  ↕ MCP protocol                      ↕
MCP 服务层                          协议层
  ↕                                   ↕
  └──── TCP / SSH 连接 ──────────────┘
```

### 包依赖

```text
ramune-protocol         ← 消息定义 + 帧编解码 + Request/Response 收发
  ↑
ramune-server / ramune-client
```

### 分层职责

**MCP 服务层**（仅本地）
- 接收 agent 的 tool call，翻译为内部协议消息
- Host 管理与路由（多台远程机器时分发到正确的连接）
- 本地文件读取（file= 参数时读取本地文件内容发送到远端）
- 结果转换为 MCP 响应（文本、image content 等）

**协议层 `ramune-protocol`**（两端对称）
- 消息定义：Request / Response / ErrorCode
- 序列化 / 反序列化（msgpack）
- 帧编解码：长度前缀分帧（`[4B length][msgpack payload]`）
- 协议规则：
  1. 一个 Request 对应一个 Response，通过 id 匹配
  2. Response 必须在传输层超时内返回，超时视为信道故障（非业务错误）
  3. Request 双向发起 — 两端都可以主动发送 Request
  4. 每个 Request 逻辑上是独立通道，不做协议层分片
- 传输层：
  - 每个 Request 独立一条 TCP 连接（loopback），无 HOL blocking，无需分片
  - 远端 daemon 监听 `127.0.0.1:PORT`，accept 连接、处理单个请求、返回响应
  - SSH 模式：每个 request 开一个 SSH channel，转发到 daemon 的 loopback 端口
  - dev 模式：直接 TCP 连接到 daemon（无认证）
  - loopback TCP 开销可忽略（内核内部 buffer 拷贝，微秒级建连）
  - 协议层不感知底层传输方式
- 不在协议层处理：命令执行超时、流式输出、长任务轮询（均为业务层职责）

**执行层**（仅远端）
- Shell 执行器（bash / powershell / cmd）— **并发**，来一个跑一个
- GUI 执行器（截屏、键鼠模拟、窗口管理、剪贴板）— **串行 task 队列**，屏幕/键鼠是独占资源
- 文件操作执行器（接收上传、读取下载）— 并发
- 网络通道执行器（端口转发、SOCKS 代理）— 长生命周期

并发策略由远端 Client 自行管理，MCP Server 不感知，agent 可自由并发调用。

### Agent ↔ MCP Server 交互

- 简单命令：`exec(host, command="...")`
- 复杂脚本：agent 先用 Write tool 写文件到本地，再调用 `exec(host, file="/tmp/script.sh")`
- 截屏等二进制数据通过 MCP 原生 image content 返回
- 认证、传输细节全部封装在 MCP Server 内部，agent 无感知

### Host 管理

- MCP Server 提供 `host_add` / `host_remove` / `host_list` 等 tool
- agent 可通过 MCP 动态添加 host（传入认证信息）
- 也支持静态配置文件 / 外部接口注入 host
- agent 通过 `host_list` 查询可用机器

## 参考架构

整体框架参考 Ramune-ida 的 Worker + Server + 插件化设计。

**直接复用的模式**
- 插件系统：`metadata.py` + handler 函数 + 自动发现
- 动态 MCP tool 注册：从 metadata 生成 Signature，注册到 FastMCP
- 协议结构：`Request(id, method, params)` / `Response(id, result/error)`
- ErrorCode 枚举 + ToolError
- Task 生命周期（GUI 串行队列）

**需要适配**
- Worker 从本地子进程 → 远端网络 daemon
- IPC 从 socketpair JSON-line → 网络管道 msgpack
- Project → Host
- 并发模型：shell 并发 + GUI 串行（ida 全串行）

**需要新增**
- Host 管理层（add / remove / list）
- 通信层（网络连接、重连、加密）
- 文件传输通道

## 技术选型

- **语言**：Python（统一两端，协议层只需实现一份）
- **包管理 / 运行时**：uv（快速 bootstrap，远端自动部署）
- **MCP SDK**：Python 官方 SDK
- **GUI 自动化**：待定（pyautogui / pynput / 平台原生方案）
- **序列化**：msgpack（原生 bytes 支持，适合文件传输和截屏）
- **通信层**：SSH（channel 多路复用，复用 ssh config / 密钥，paramiko）
- **GUI 操作**：不使用 VNC，远端 Client 直接调用平台工具（scrot/xdotool/pyautogui），图片通过 msgpack 协议返回

## 实现计划

- [ ] 协议层完善（Request/Response 收发、超时、重试）
- [ ] MCP tool 接口定义
- [ ] 插件清单（首批实现哪些）
- [ ] Server / Client 骨架搭建
