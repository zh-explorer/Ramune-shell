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
- 认证、传输细节全部封装在 MCP Server 内部，agent 无感知
- 输出策略：
  - 文本结果：直接返回，超限时渐进式截断（字符串→列表→兜底），完整输出写文件
  - 二进制数据（截屏、下载文件等）：MCP server 写本地文件，只返回文件路径，agent 用 Read 读取
  - 不通过 MCP context 返回大体积二进制数据（base64 编码 token 消耗不确定且可能很高）
  - 截断输出只是 fallback，插件应主动处理大结果

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

## 已完成

- [x] 协议层（Request/Response、msgpack 序列化、长度前缀帧）
- [x] Worker daemon（TCP server、dispatch、内建命令）
- [x] MCP server（FastMCP、connector、动态 tool 注册）
- [x] 插件系统（目录扫描、平台过滤、metadata 驱动注册）
- [x] exec 插件（首个插件，端到端验证通过）

## TODO

### MCP 层任务管理（已完成基础框架）

- [x] MCP 层超时机制：tool call 超时后返回 task_id，内部请求继续执行
- [x] result 缓存：worker 响应到达后缓存，等 AI 用 task_id 来取
- [x] get_result(task_id) tool：轮询异步结果
- [x] cancel(task_id)：取消运行中的任务
- [ ] cancel 向 worker 传递：MCP → worker 发送 cancel request，handler 自行取消（不可取消的用子进程 + kill）

### Host 管理（已完成基础框架）

- [x] host_add(name, host, port) — TcpHost，dev 模式直连
- [x] host_remove(name)
- [x] host_list() — 查询可用机器
- [x] 请求路由：tool call 的 host 参数 → 找到对应 connector 转发
- [ ] ssh_host_add — SshHost，生产模式 SSH 连接
- [ ] HostInfo 扩展：机器基础信息（OS、架构等），通过插件获取

### SSH 通信层

#### 设计

两种 Host 类型：
- `TcpHost`：dev 模式，直连 worker TCP 端口，无认证
- `SshHost`：生产模式，通过 SSH 连接远端机器

```text
[asyncio event loop]                    [SSH thread]

async call(req) ──→ Queue ──→ SshSession (paramiko)
                                 ├── connect / auth
                                 ├── open_channel (direct-tcpip → worker)
                                 ├── read / write (msgpack protocol)
                                 ├── keepalive / reconnect
                                 └── sftp / exec (额外 SSH 能力)
result ←── Future ←────────── response (loop.call_soon_threadsafe)
```

核心组件：

**SshSession** — 独立线程，拥有 paramiko 连接
- 生命周期独立于 asyncio 事件循环
- 内部全同步 paramiko 代码，不外泄
- 对外暴露 async 接口：call / sftp_get / sftp_put / exec
- async 侧通过 asyncio.Future 拿结果，SSH 线程用 `loop.call_soon_threadsafe` 回传
- 负责 keepalive、断线检测、自动重连

**认证** — 支持多种方式：
- SSH config（`~/.ssh/config`）别名：`ssh_host_add(name, alias="my-vm")`
- 显式指定：`ssh_host_add(name, host, user, key_file, ...)`
- SSH agent 转发
- paramiko 的 SSHConfig 类解析 ssh config

**MCP tools**：
- `ssh_host_add(name, alias)` — 从 ssh config 读取配置
- `ssh_host_add(name, host, user, ...)` — 显式指定连接参数

**显式 SSH channel 管理**（选择方案 A 而非端口转发）：
- 每个 request 开一个 direct-tcpip channel 到远端 worker 的 loopback 端口
- 可直接使用 SSH 的其他能力：SFTP 文件传输、SSH exec 命令执行
- 插件可按需使用这些能力

#### TODO

- [ ] SshSession 类（独立线程 + paramiko）
- [ ] async 接口（Queue + Future 桥接）
- [ ] SSH config 解析
- [ ] SshHost 类 + ssh_host_add tool
- [ ] SFTP 文件传输接口
- [ ] SSH exec 接口
- [ ] 断线重连 / keepalive

### Worker 部署

- [ ] 由 agent 自行完成，框架不实现自动部署
- [ ] 两种部署方式：
  - 裸机：安装 uv → uv 装 Python → uv sync → uv run 启动
  - 容器：拉 Docker 镜像直接跑
- [ ] 部署完成后 agent 调 host_add / ssh_host_add 注册
- [ ] MCP description 不写部署步骤（污染上下文），放独立文档，description 只引用链接

### 插件

- [ ] 更多插件（文件传输、GUI 操控、网络通道等）
- [ ] 插件依赖安装（requirements.txt + uv）
- [ ] sysinfo 插件：获取机器基础信息，host_add 后自动调用填充 HostInfo
