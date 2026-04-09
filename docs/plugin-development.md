# 插件开发指南

## 目录结构

```
plugins/<plugin_name>/
├── __init__.py
├── metadata.py       # 工具定义
├── handler.py        # 处理函数
└── requirements.txt  # 依赖（可选）
```

## metadata.py

```python
TOOLS = [
    {
        "name": "tool_name",
        "description": "Tool description for AI.",
        "tags": ["platform:linux", "platform:windows"],
        "params": {
            "param_name": {
                "type": "string",    # string / integer / number / boolean
                "required": True,
                "description": "Param description for AI.",
            },
        },
    },
]
```

## handler.py

Handler 函数签名：`async def tool_name(params: dict) -> dict`

```python
async def tool_name(params: dict[str, Any]) -> dict[str, Any]:
    value = params["param_name"]
    # ... 执行逻辑 ...
    return {"result": "..."}
```

## 取消处理

框架在取消任务时会向 handler 抛出 `asyncio.CancelledError`。
**插件必须自行处理资源清理**，框架无法替插件释放资源。

常见场景：

### 子进程

```python
async def exec(params):
    proc = await asyncio.create_subprocess_shell(...)
    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise  # 必须 re-raise
```

### 临时文件

```python
async def download(params):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        # ... 写入 ...
        return {"path": tmp.name}
    except asyncio.CancelledError:
        os.unlink(tmp.name)
        raise
```

### 不可中断的操作

如果 handler 内部是纯同步阻塞调用（没有 await 点），`CancelledError` 无法中断。
这种情况下 cancel 只会在下一个 await 点生效。如果需要支持取消，考虑：

- 将长操作拆分为多步，每步之间 `await asyncio.sleep(0)` 给 cancel 机会
- 使用 `asyncio.to_thread` + 可关闭的资源（参考 SSH session 的 `_Op` 模式）

### 不处理取消

如果插件不处理 `CancelledError`，框架会捕获并返回 `CANCELLED` 响应。
但未清理的资源（子进程、临时文件、网络连接）会泄漏。

## 平台 tags

- `platform:linux` — 仅 Linux
- `platform:windows` — 仅 Windows
- 不加 platform tag — 所有平台

Worker 启动时按当前平台过滤，不匹配的插件不加载。
MCP 侧注册全部插件（不过滤），不支持的 host 调用时由 worker 返回错误。

## 错误处理

Handler 抛出的异常会被框架捕获，返回 `INTERNAL_ERROR` 响应。
不需要在 handler 内部捕获所有异常，让意外错误自然上报。
