# 架构设计

## 项目结构

```
ramune_shell/
├── transport/     — 传输层：连接、帧通道、session、RPC 注册
├── mcp/           — MCP server：交互层 + Task 执行器 + 边缘模块
├── worker/        — Worker daemon：dispatch + handler 注册
└── features/      — Feature 实现：跨两端的业务功能
```

## 三层通信

```
Agent (Claude)
  ↕ MCP protocol
MCP Server
  ↕ transport session (R/Q + Frame channel)
Worker Daemon
```

- **MCP Server**：接收 agent tool call，通过 TaskExecutor 调度执行。
- **Transport**：session 层提供 `request()` / `open_frame_channel()` / `ping()` / `close()`。内部管连接池、帧协议、路由。
- **Worker Daemon**：通过 ServerTransport 接受 session，dispatch 循环处理请求。

## MCP 层架构

### Task 为核心

每个 MCP tool call → 一个 Task → TaskExecutor 调度执行。

```
MCP tool call
  → FeatureRuntime.run()
    → open_session() → 包装 Task(session_id, handler) → executor.submit()
    → task.wait(timeout)
      ├── 成功 → 返回 result
      └── 超时 → pending_results[task_id] = task → 返回 task_id
```

### 并发模型

TaskExecutor 用 asyncio.create_task 调度，per-(host, group) Lock 串行化：

- **无 concurrency_group**（exec 等）→ 并行，每个 task 独立 asyncio.Task
- **有 concurrency_group**（gui 等）→ 同 host 同组串行，asyncio.Lock 排队

META 声明并发组：

```python
# 并行（默认）
META = {"name": "exec", "description": "..."}

# 串行（同 host 同组排队）
META = {"name": "screenshot", "description": "...", "concurrency_group": "gui"}
```

### 三层职责

| 层 | 职责 |
|---|---|
| 交互层（app.py, output.py, main.py） | FastMCP 实例、组装组件、输出截断 |
| 执行器（executor.py） | 调度 task、cancel、并发控制 |
| 边缘模块（feature.py, tools.py, hosts.py） | @feature 注册、ToolContext、内建 tools、host 管理 |

## ID 模型

### 对外：task_id

Agent 看到的唯一标识。task_id == session_id 字符串。MCP tool call 超时未返回时，框架返回 `task_id` 供 `get_result` / `cancel_task` 使用。

### 对内：SessionId + OpId

```
SessionId: "sess-000001"         ← transport 内部 new_session() 分配
OpId:      "sess-000001/req-0001" ← ClientSession 内部 _next_op() 分配
```

- 均为 frozen pydantic model，transport 内部类型，不导出。
- `ClientSession.get_session_id() -> str` 是上层拿 task_id 的唯一途径。

## Session 生命周期

**Session = 一次 handler 调用的作用域。**

```
handler 开始前 → 框架创建 session
handler 执行中 → session 内发 request、开 frame channel
handler 返回后 → 框架关闭 session（关 frame channels + 发 close_session 到 worker）
handler cancel → 同上，finally 清理
```

- Session 不跨 handler，不跨 MCP tool call。
- Worker 侧 TTL reaper + ping 保活兜底。
- ToolContext 是 session 的薄包装。

## 取消

**Cancel 到 handler 为止。**

- `cancel_task(task_id)` → executor cancel asyncio.Task → handler 收到 `CancelledError`。
- Handler 自行清理资源（kill subprocess、关 PTY 等），re-raise。
- finally 中 ctx.close() 发 close_session 到 worker 清理 session。

## 跨 tool call 的持久状态

**框架不管，插件自己设计。**

- 每次 MCP tool call 创建独立 session，互不相干。
- Worker 侧跨 call 状态在插件 registry 中（如 pty_id → PTY 对象）。
- session.state 仅在单次 handler 调用期间使用。

## Feature 并发组

| Feature | concurrency_group | 行为 |
|---|---|---|
| exec | 无 | 并行 |
| screenshot | gui | 同 host 串行 |
| click | gui | 同 host 串行 |
| pty_start | 无 | 并行 |

同组 feature 在同一 host 上排队执行。不同 host 或不同组始终并行。

## 资源清理

**插件负责。**

- 插件必须为不可自动回收的资源做 wrapping，在 `__del__` 中清理。
- Handler 内 `CancelledError` 必须 kill 进程 / 关资源后 re-raise。
- 框架只做：关 MCP 侧 frame channels、发 close_session、释放引用。
