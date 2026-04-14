# Feature 开发指南

## 目录结构

每个 feature 一个文件，包含 RPC 类型、MCP 侧 handler、Worker 侧 handler：

```
ramune_shell/features/
└── exec.py    # RPC types + MCP handler + Worker handler
```

## 快速示例

```python
# features/exec.py

from pydantic import BaseModel
from ramune_shell.transport.rpc import register_rpc
from ramune_shell.mcp.feature import feature, ToolContext
from ramune_shell.worker.dispatch import register_feature

# --- RPC 类型（两端共享） ---

class ExecRequest(BaseModel):
    command: str
    cwd: str | None = None

class ExecResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int

register_rpc("exec", ExecRequest, ExecResult)

# --- MCP 侧 handler ---

META = {
    "name": "exec",
    "description": "Execute a shell command on remote machine.",
    "params": {
        "host": {"type": "string", "required": True},
        "command": {"type": "string", "required": True},
        "cwd": {"type": "string", "required": False},
    },
}

@feature(META)
async def exec_mcp(ctx: ToolContext, command: str, cwd: str | None = None) -> dict:
    result = await ctx.call_feature("exec", ExecRequest(command=command, cwd=cwd))
    return result.model_dump()

# --- Worker 侧 handler ---

async def exec_worker(command: str, cwd: str | None = None) -> ExecResult:
    proc = await asyncio.create_subprocess_shell(command, ...)
    ...
    return ExecResult(stdout=..., stderr=..., exit_code=...)

def register_worker():
    register_feature("exec", exec_worker)
```

## ToolContext

Feature handler 拿到的上下文，已绑定到正确的 worker。

| 方法 | 用途 |
|---|---|
| `ctx.session_id` | 当前 session ID（= task_id） |
| `ctx.call(method, params)` | 发送 R/Q 请求 |
| `ctx.call_feature(name, request_obj)` | 发送 typed feature 调用，返回 ResultModel |
| `ctx.open_frame_channel()` | 创建 frame channel 做双工交互 |

`host` 参数在框架层被消费，handler 不感知。

## META 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | MCP tool 名称 |
| `description` | 是 | 工具描述 |
| `params` | 否 | 参数定义（用于签名验证） |
| `tags` | 否 | 标签（平台、模块等） |
| `concurrency_group` | 否 | 并发组（同 host 同组串行） |

### 并发组

不声明 `concurrency_group` → 并行执行（默认）。
声明后，同一 host 上同组的 task 排队串行：

```python
# GUI 操作必须串行（屏幕/键鼠是独占资源）
META = {
    "name": "screenshot",
    "description": "Take a screenshot.",
    "concurrency_group": "gui",
}
```

| Feature | concurrency_group | 行为 |
|---|---|---|
| exec | 无 | 并行 |
| screenshot | gui | 同 host 串行 |
| click | gui | 同 host 串行 |

## Frame Channel

FrameChannel 是全双工数据通道，两级 API：

```python
# 低级：原始字节（PTY、文件传输）
channel = await ctx.open_frame_channel()
await channel.send(b"raw data")
data = await channel.recv()

# 高级：typed 消息
await channel.send_msg(MyMessage(...))
msg = await channel.recv_msg(MyMessage)

# 降级：拿走底层连接给其他框架
reader, writer = channel.detach()
```

## 取消处理

框架取消 task 时向 handler 抛 `asyncio.CancelledError`。handler 必须清理资源后 re-raise：

```python
async def exec_worker(command: str) -> ExecResult:
    proc = await asyncio.create_subprocess_shell(command, ...)
    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise  # 必须 re-raise
    return ExecResult(...)
```

## 资源清理

**插件负责。** 框架不提供 cleanup hook。

- 为不可自动回收的资源（subprocess、PTY、fd）做 wrapping
- wrapper 在 `__del__` 里清理
- Handler 结束后框架关 session，释放引用，GC 触发 `__del__`

## Worker 侧 handler

纯函数。两种签名模式（自动识别）：

```python
# fields 模式：参数名对应 RequestModel 字段
async def exec_worker(command: str, cwd: str | None = None) -> ExecResult:

# typed 模式：单参数为 RequestModel
async def exec_worker(req: ExecRequest) -> ExecResult:
```

返回类型必须是注册的 ResultModel。

## 二进制数据

大体积二进制结果（截屏、文件）不通过 MCP context 返回。MCP handler 应写本地文件，只返回路径。文本超限时框架自动截断（字符串→列表→兜底）。
