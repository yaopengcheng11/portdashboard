"""Port Dashboard MCP server — 把本地面板的 HTTP API 包装成 MCP tools。

让 coding agent（ZCode / Claude / Cursor…）可以直接查看端口占用、启停托管项目、
读日志、杀进程，而不需要打开浏览器面板。

运行（stdio transport）:
    python portdashboard_mcp.py

配置方法见同目录 README.md。前置条件：Port Dashboard 本体必须在运行
（默认 http://127.0.0.1:9229，可用环境变量 PORT_DASHBOARD_URL 覆盖）。
"""

import json
import os

import requests
from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("PORT_DASHBOARD_URL", "http://127.0.0.1:9229").rstrip("/")
REQUEST_TIMEOUT = 15

mcp = MCPServer("portdashboard")


def _api(method: str, path: str, params: dict | None = None, json_body: dict | None = None) -> str:
    """统一请求入口，返回单个 JSON 文本块。

    2.x 的 MCPServer 会把 list/dict 返回值拆成多个 text content，客户端很难
    完整取回；自己 dumps 成一个字符串就永远是单块。失败时返回带 hint 的错误
    JSON 而不是抛异常——agent 读得懂原因才能自行恢复（比如提示用户先把面板跑起来）。
    """
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.request(method, url, params=params, json=json_body, timeout=REQUEST_TIMEOUT)
    except requests.ConnectionError:
        data: object = {
            "error": f"cannot connect to Port Dashboard at {BASE_URL}",
            "hint": "start the dashboard first: start.bat (Windows) / ./start.sh (Unix)",
        }
    except requests.Timeout:
        data = {"error": f"request to {url} timed out after {REQUEST_TIMEOUT}s"}
    else:
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        if resp.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else data
            data = {"error": f"HTTP {resp.status_code}", "detail": detail}
    return json.dumps(data, ensure_ascii=False, indent=2)


# ── 只读观测 ──────────────────────────────────────────────────────────────


@mcp.tool()
def list_projects() -> str:
    """List all managed projects with runtime status.

    Each project: id, name, port, status (running / stopped / external),
    pid, owner, managed, and port_process (who actually holds the port).
    """
    return _api("GET", "/api/projects")


@mcp.tool()
def scan_ports() -> str:
    """Scan all TCP listening ports on this machine.

    Each entry: port, pid, process name, address, cwd, project_name (inferred),
    and dashboard_project (set when the port is held by a dashboard-managed project).
    """
    return _api("GET", "/api/system/ports")


@mcp.tool()
def system_stats() -> str:
    """Get system stats: CPU / memory usage, LAN IP, dashboard uptime, OS."""
    return _api("GET", "/api/system/stats")


@mcp.tool()
def dashboard_snapshot(force: bool = False) -> dict:
    """Full dashboard snapshot in one call: stats + all ports + grouped
    local ports (by process, with category and HTTP detection) + projects.

    Use force=true to bypass the 3s port cache.
    """
    return _api("GET", "/api/dashboard/snapshot", params={"force": str(force).lower()})


@mcp.tool()
def tail_logs(project_id: str, max_bytes: int = 8192) -> dict:
    """Read the most recent console output of a managed project.

    Returns the tail (last `max_bytes`, clamped 1024..65536) of the project's
    log buffer. `synthetic: true` in the response means the project has no log
    file yet (never started, or running externally).
    """
    max_bytes = max(1024, min(int(max_bytes), 65536))
    return _api("GET", f"/api/projects/{project_id}/logs",
                params={"offset": 0, "limit": max_bytes})


# ── 托管项目生命周期 ──────────────────────────────────────────────────────


@mcp.tool()
def start_project(project_id: str) -> str:
    """Start a managed project.

    Fails with 409 when the target port is held by an external process,
    and with 500 when the startup health check times out (log file has details).
    """
    return _api("POST", f"/api/projects/{project_id}/start")


@mcp.tool()
def stop_project(project_id: str) -> str:
    """Stop a dashboard-managed project (kills its process tree).

    Refuses to kill external processes; the response carries `external: true`
    in that case. `success: false` means the kill did not take effect.
    """
    return _api("POST", f"/api/projects/{project_id}/stop")


@mcp.tool()
def create_project(project_id: str, name: str, cwd: str, command: str, port: int,
                   description: str = "", sync_name: bool = False) -> str:
    """Register a new project under dashboard management.

    `command` is the start command run inside `cwd` (shell pipes/redirections
    are not supported; `ENV=value` prefixes are). `port` is the expected
    listening port used for start-time conflict pre-checks.
    """
    return _api("POST", "/api/projects", json_body={
        "id": project_id, "name": name, "cwd": cwd, "command": command,
        "port": port, "description": description, "sync_name": sync_name,
    })


@mcp.tool()
def update_project(project_id: str, name: str, cwd: str, command: str, port: int,
                   description: str = "", sync_name: bool = False) -> str:
    """Replace a managed project's full configuration (all fields required)."""
    return _api("PUT", f"/api/projects/{project_id}", json_body={
        "id": project_id, "name": name, "cwd": cwd, "command": command,
        "port": port, "description": description, "sync_name": sync_name,
    })


@mcp.tool()
def delete_project(project_id: str) -> str:
    """Remove a managed project. If it is running, it is stopped first."""
    return _api("DELETE", f"/api/projects/{project_id}")


# ── 场景（按依赖顺序批量启停） ────────────────────────────────────────────


@mcp.tool()
def list_scenes() -> str:
    """List scenes (named groups of projects) with per-step runtime state.

    Each scene: id, name, steps [{project_id, name, state}], up_count, total.
    Step order is the start order (dependencies first) and the reverse of the
    stop order.
    """
    return _api("GET", "/api/scenes")


@mcp.tool()
def start_scene(scene_id: str) -> str:
    """Start a scene: bring up its projects in dependency order.

    Steps already running (or served by an external process) are skipped.
    Aborts at the first failed step; the response carries per-step `results`.
    """
    return _api("POST", f"/api/scenes/{scene_id}/start")


@mcp.tool()
def stop_scene(scene_id: str) -> str:
    """Stop a scene: bring its projects down in reverse dependency order."""
    return _api("POST", f"/api/scenes/{scene_id}/stop")


# ── 进程控制（危险） ──────────────────────────────────────────────────────


@mcp.tool()
def kill_process(pid: int) -> dict:
    """Force-kill a process by PID, including its whole child tree.

    DANGEROUS: protected system processes are refused server-side, but
    everything else dies immediately. Prefer stop_project for dashboard-managed
    processes, and double-check `pid` against scan_ports output before calling.
    """
    return _api("POST", f"/api/system/ports/kill/{pid}")


if __name__ == "__main__":
    mcp.run()
