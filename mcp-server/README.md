# Port Dashboard MCP Server

把本机 [Port Dashboard](../README.md) 的 HTTP API 包装成 MCP tools，让 coding agent
（ZCode / Claude Code / Cursor…）能直接查看端口占用、启停托管项目、读日志、杀进程，
不需要打开浏览器面板。

## 前置条件

- Port Dashboard 本体必须在运行：`start.bat`（Windows）/ `./start.sh`（Unix），
  默认 `http://127.0.0.1:9229`
- Python 3.10+

## 安装（独立 venv，不污染全局）

```bash
cd mcp-server
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # Linux/macOS
```

## 注册到 MCP 客户端

**ZCode / Claude Code（`mcpServers` JSON）：**

```json
{
  "mcpServers": {
    "portdashboard": {
      "command": "G:/AITOOLS/portdashboard/mcp-server/.venv/Scripts/python.exe",
      "args": ["G:/AITOOLS/portdashboard/mcp-server/portdashboard_mcp.py"]
    }
  }
}
```

Linux/macOS 把 `command` 换成 `.venv/bin/python` 即可。面板不在默认端口时加：

```json
"env": { "PORT_DASHBOARD_URL": "http://127.0.0.1:PORT" }
```

## Tools（11 个）

| Tool | 说明 |
|---|---|
| `list_projects` | 托管项目列表 + 运行状态（running / stopped / external） |
| `scan_ports` | 全系统 TCP LISTENING 端口（含 `dashboard_project` 反向标记） |
| `system_stats` | CPU / 内存 / IP / 运行时长 |
| `dashboard_snapshot` | 一次拿全：stats + 端口 + 按进程分组的本地端口 + 项目 |
| `tail_logs` | 读某项目最近的控制台输出（尾部 max_bytes） |
| `start_project` | 启动托管项目（409 = 端口被外部占用；500 = 健康检查超时） |
| `stop_project` | 停止托管项目（杀整棵进程树；拒绝杀外部进程） |
| `create_project` / `update_project` / `delete_project` | 托管项目 CRUD |
| `kill_process` | 按 PID 强杀进程树 ⚠️ 系统关键进程服务端有硬保护，其余请先 `scan_ports` 核对 PID |

所有 tool 返回单个 JSON 文本块；面板未启动时返回带 `hint` 的错误 JSON，
agent 可以读懂原因并提示用户，而不是收到一条异常栈。

## 典型 agent 用法

```
"看看 3000 端口被谁占了"        → scan_ports
"帮我把 api 项目重启一下"       → stop_project + start_project
"nexart 的控制台输出是什么"     → tail_logs
"把 G:/AITOOLS/foo 注册进面板"  → create_project
```
