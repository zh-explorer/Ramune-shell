# Feature 开发指南

## 目录结构

```
ramune_shell/
├── mcp/features/
│   └── exec.py          # MCP 侧：tool 注册 + 预处理/后处理
└── worker/features/
    └── exec.py          # Worker 侧：实际执行逻辑
```

## MCP 侧 Feature

```python
from ramune_shell.mcp.feature import feature, ToolContext

META = {
    "name": "exec",
    "description": "Execute a shell command on remote machine.",
    "tags": ["module:exec", "platform:linux", "platform:windows"],
    "params": {
        "host": {"type": "string", "required": True},
        "command": {"type": "string", "required": True},
    },
}

@feature(META)
async def exec(ctx: ToolContext, command: str) -> dict:
    resp = await ctx.call_plugin("exec", {"command": command})
    if resp.error:
        return {"error": resp.error.message}
    return resp.result
```

`@feature(META)` 自动处理：MCP tool 注册、host 参数注入、ToolContext 创建、TaskManager 包装。

### ToolContext

| 方法 | 用途 |
|---|---|
| `ctx.call(method, params)` | 发 R/Q 请求到 worker |
| `ctx.call_plugin(name, params)` | 发插件调用到 worker（自动加 `plugin:` 前缀） |
| `ctx.open_session()` | 创建 Frame session（全双工通道） |
| `ctx.task_id` | 当前任务 ID（= wire request_id） |

## Worker 侧 Feature

```python
from ramune_shell.worker.dispatch import register_module

MODULE = "exec"

async def exec_handler(params):
    ...
    return {"stdout": ..., "exit_code": ...}

def register():
    register_module(MODULE, {"exec": exec_handler})
```

Worker 启动时在 `main.py` 里调 `register()`。

## 通信模型

### R/Q（控制平面）

适用：短请求短响应。所有 `ctx.call()` / `ctx.call_plugin()` 走这条路。

约束：
- **Response 超时 30 秒**。控制命令应快速返回。
- **不传大数据**。大文件走 SFTP 或 Frame session。
- 连接池化复用，空闲 60 秒回收，worker 空闲 5 分钟断开。

### Frame Session（数据平面）

适用：流式/交互场景（PTY、实时日志等）。

```python
@feature(META)
async def pty_start(ctx: ToolContext, command: str) -> dict:
    async with await ctx.open_session() as session:
        await session.send(b"start")
        data = await session.recv()
        ...
```

约束：
- 全双工，send/recv 可并发。
- **无超时**，由 feature 自行管理生命周期。
- **必须用 `async with`** 保证 close。
- TCP 保证可靠有序，不需要 ACK。

### 大文件传输

走 SSH 的 SFTP，不走 R/Q：

```python
ssh_session = host_manager.get_ssh_session(host)
await ssh_session.sftp_put(local_path, remote_path)
await ssh_session.sftp_get(remote_path, local_path)
```

## 取消处理

框架取消任务时向 handler 抛 `asyncio.CancelledError`。
**feature 必须自行清理资源**，框架无法替你释放。

```python
async def exec_handler(params):
    proc = await asyncio.create_subprocess_shell(...)
    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise  # 必须 re-raise
```

不处理 `CancelledError` 时，框架返回 `CANCELLED`，但子进程/临时文件会泄漏。

## 模块注册

Worker feature 用 `register_module(MODULE, handlers)` 注册模块名 + handler 映射。
`list_plugins` 返回已加载的模块名列表。
MCP META 中的 `module:xxx` tag 标注归属，agent 可对照判断 host 是否支持。

## Tags

| Tag | 含义 |
|---|---|
| `module:xxx` | 所属模块 |
| `platform:linux` | 仅 Linux |
| `platform:windows` | 仅 Windows |

## 错误处理

- Handler 异常被框架捕获，返回 `INTERNAL_ERROR`
- Worker 不支持的 feature 返回 `"feature 'xxx' not available on this worker"`
- 不需要在 handler 内部捕获所有异常，让意外错误自然上报

## 二进制数据

截屏、下载文件等二进制结果 **不通过 MCP context 返回**。
MCP feature 应写本地文件，只返回路径让 agent 用 Read 读取。
文本结果超限时框架自动渐进式截断（字符串→列表→兜底），完整输出写文件。
